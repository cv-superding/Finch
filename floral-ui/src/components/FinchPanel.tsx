import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import "../font-scale.css";
import "../motion.css";

const API = "http://127.0.0.1:8766";
const TYPE_SCALE: Record<number, number> = { 10: 10, 11: 10, 12: 12.5, 13: 12.5, 14: 16, 15: 16, 16: 20 };
const FONT_SIZES = Object.keys(TYPE_SCALE).map(Number);
const DEFAULT_FONT_SCALE = 1.2;

const AGENTS: [string, string, string][] = [
  ["claude", "Claude Code", "claudecode-color.svg"],
  ["codebuddy", "CodeBuddy CLI", "codebuddy.svg"],
  ["codex", "Codex CLI", "codex-color.svg"],
  ["zcode", "ZCode", "zcode.png"],
  ["opencode", "OpenCode", "opencode.svg"],
  ["cursor", "Cursor Agent", "cursor.svg"],
  ["mock", "示例 Agent", ""],
];

type DragSnapshot = {
  id: string;
  y: number;
  rects: Map<string, { top: number; height: number }>;
  ids: string[];
};

// 拖动开始时记下每行的原始位置：跟手、让位、落下归位都基于这份快照，
// 避免读取已被 transform 改动的 rect 造成跳动。
function captureRows(id: string, y: number): DragSnapshot {
  const rows = Array.from(document.querySelectorAll<HTMLElement>("[data-row]"));
  const rects = new Map<string, { top: number; height: number }>();
  rows.forEach((row) => {
    const box = row.getBoundingClientRect();
    rects.set(row.dataset.row || "", { top: box.top, height: box.height });
  });
  return { id, y, rects, ids: rows.map((r) => r.dataset.row || "").filter(Boolean) };
}

function clearRowStyles() {
  document.querySelectorAll<HTMLElement>("[data-row]").forEach((row) => {
    row.style.transition = "";
    row.style.transform = "";
    row.style.zIndex = "";
    row.style.boxShadow = "";
    row.style.cursor = "";
    row.removeAttribute("data-dragging");
  });
}

const STATUS: Record<string, string> = {
  queued: "待执行",
  running: "执行中",
  tool: "工具执行中",
  resuming: "续传中",
  patching: "补做中",
  validating: "校验中",
  done: "已完成",
  attention: "待人工",
  failed: "失败",
  interrupted: "已中断",
  awaiting: "待确认",
};
const ACTIVE = ["running", "tool", "resuming", "patching", "validating"];
const BOARD_COLS: [string, string[]][] = [
  ["待执行", ["queued"]],
  ["进行中", ACTIVE],
  ["待处理", ["attention", "failed", "interrupted", "awaiting"]],
  ["已完成", ["done"]],
];

type Task = {
  id: string;
  title: string;
  prompt?: string;
  status: string;
  agent: string;
  cwd?: string;
  seconds?: number;
  tools?: number;
  resume?: number;
  followup?: number;
  summary?: string;
  progress?: string;
  completed?: string[];
  pending?: string[];
  issues?: string[];
  attention_reason?: string;
  followup_prompt?: string;
  pending_action?: string;
};
type Run = {
  id: string;
  title?: string;
  agent?: string;
  round?: number;
  tools?: number;
  started?: number;
  ended?: number;
  duration?: number;
  status?: string;
  kind?: string;
};
type Autopilot = {
  active?: boolean;
  resumable?: boolean;
  goal?: string;
  max_rounds?: number;
  rounds_used?: number;
  minutes?: number;
  auto_accept?: boolean;
  stop_reason?: string;
};
type Snapshot = {
  tasks: Task[];
  engine: { state: string; active?: string };
  autopilot?: Autopilot;
};

async function call<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 12000);
  try {
    const res = await fetch(API + path, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await res.text();
    let data: any = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        throw new Error(`服务端返回了非 JSON 内容（HTTP ${res.status}）`);
      }
    }
    if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
    return data as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时，服务可能无响应");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

const fmt = (s?: number) =>
  s ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "—";
const clock = (ts?: number) =>
  ts ? new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : "—";
const agentName = (key: string) => AGENTS.find((a) => a[0] === key)?.[1] || key || "—";

type Dialog =
  | null
  | { mode: "new" }
  | { mode: "edit"; task: Task };

export function FinchPanel() {
  const [snapshot, setSnapshot] = useState<Snapshot>({ tasks: [], engine: { state: "idle" }, autopilot: {} });
  const [history, setHistory] = useState<Run[]>([]);
  const [config, setConfig] = useState<Record<string, any> | null>(null);
  const [agentsInfo, setAgentsInfo] = useState<Record<string, any>>({});
  const [page, setPage] = useState<"queue" | "history" | "settings">("queue");
  const [tab, setTab] = useState<"result" | "runs" | "logs" | "chat">("result");
  const [view, setView] = useState<"list" | "board">(() => (localStorage.getItem("finch-view") === "board" ? "board" : "list"));
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get("open") || "");
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [quick, setQuick] = useState("");
  const [historyFilter, setHistoryFilter] = useState("all");
  const [historyQuery, setHistoryQuery] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  const [conversation, setConversation] = useState<{ messages: { role: string; text: string; ts: number }[]; session_id: string; source: string; count: number }>({ messages: [], session_id: "", source: "", count: 0 });
  const [toast, setToast] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [draft, setDraft] = useState({ title: "", prompt: "", agent: "mock" });
  const [decisionPrompt, setDecisionPrompt] = useState<Record<string, string>>({});
  const [goal, setGoal] = useState("");
  const [rounds, setRounds] = useState("3");
  const [minutes, setMinutes] = useState("30");
  const [autoAccept, setAutoAccept] = useState(false);
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "light");
  const [menuFor, setMenuFor] = useState("");
  const [showAutopilot, setShowAutopilot] = useState(false);
  const [showMore, setShowMore] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [online, setOnline] = useState(true);
  const [draggingId, setDraggingId] = useState("");
  const [isNarrow, setIsNarrow] = useState(() => window.matchMedia("(max-width: 600px)").matches);
  const [showMobileMore, setShowMobileMore] = useState(false);
  const [fontScale, setFontScale] = useState(() => {
    const raw = Number(new URLSearchParams(location.search).get("scale"));
    return Number.isFinite(raw) && raw >= 0.9 && raw <= 2 ? raw : DEFAULT_FONT_SCALE;
  });
  const dragRef = useRef<DragSnapshot | null>(null);
  const flipRef = useRef<Map<string, number> | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  // 选中项写进 URL，复制/刷新能回到同一条任务（master-detail 的可寻址准则）。
  const selectTask = useCallback((id: string) => {
    setSelected(id);
    if (window.matchMedia("(max-width: 900px)").matches) setDetailOpen(true);
    const url = new URL(location.href);
    if (id) url.searchParams.set("open", id);
    else url.searchParams.delete("open");
    window.history.replaceState(null, "", url);
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 600px)");
    const onChange = () => setIsNarrow(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // 默认 Agent 在挂载时就取回，不能等进了设置页才有值，
  // 否则快速添加会错误地落到 "mock" 而不是用户设置的默认 Agent。
  useEffect(() => {
    call<Record<string, any>>("/api/config").then(setConfig).catch(() => {});
  }, []);

  const notify = useCallback((message: string) => setToast(message), []);
  useEffect(() => {
    localStorage.setItem("finch-view", view);
  }, [view]);

  // 字号配置持久化在后端，挂载时读取；所有字号走 CSS 变量，改一处全局生效。
  useEffect(() => {
    // ?scale=1.5 用于首帧就按指定字号预览，便于对比，不让后端配置覆盖。
    if (new URLSearchParams(location.search).has("scale")) return;
    call<Record<string, any>>("/api/config")
      .then((c) => {
        const value = Number(c.ui_font_scale);
        if (Number.isFinite(value) && value >= 0.9 && value <= 2) setFontScale(value);
      })
      .catch(() => {});
  }, []);

  const fontVars = useMemo(
    () => Object.fromEntries(
      FONT_SIZES.map((size) => [`--fs-${size}`, `${(TYPE_SCALE[size] * fontScale).toFixed(2)}px`]),
    ) as unknown as CSSProperties,
    [fontScale],
  );

  const changeFontScale = async (value: number) => {
    setFontScale(value);
    setCfg("ui_font_scale", value);
    try {
      await call("/api/config", { ui_font_scale: value });
      notify(`字号已设为 ${Math.round(value * 100)}%`);
    } catch (error) {
      notify(`失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const refresh = useCallback(async () => {
    try {
      setSnapshot(await call<Snapshot>("/api/state"));
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const data = await call<Snapshot>("/api/state");
        if (alive) {
          setSnapshot(data);
          setOnline(true);
        }
      } catch {
        if (alive) setOnline(false);
      }
      try {
        const h = await call<{ rows: Run[] }>("/api/history?limit=200");
        if (alive) setHistory(h.rows || []);
      } catch { /* ignore */ }
    };
    tick();
    const timer = window.setInterval(tick, 2500);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (page !== "settings") return;
    call<Record<string, any>>("/api/config").then((c) => {
      setConfig(c);
      setGoal(c.autopilot_goal || "");
      setRounds(String(c.autopilot_rounds ?? 3));
      setMinutes(String(c.autopilot_minutes ?? 30));
      setAutoAccept(!!c.autopilot_auto_accept);
    }).catch(() => {});
    call<Record<string, any>>("/api/agents").then(setAgentsInfo).catch(() => {});
  }, [page]);


  // 长任务执行中持续拉日志：以前只在切换标签时拉一次，界面看起来像卡死。
  useEffect(() => {
    const row = (snapshot.tasks || []).find((t) => t.id === selected);
    const executing = !!row && (ACTIVE.includes(row.status) || snapshot.engine?.active === row.id);
    if (!row || !executing) {
      setLiveLogs([]);
      return;
    }
    let alive = true;
    const id = row.id;
    const tick = async () => {
      try {
        const d = await call<{ lines: string[] }>(`/api/tasks/${id}/log`);
        if (alive) setLiveLogs(d.lines || []);
      } catch { /* 轮询失败下次再试 */ }
    };
    tick();
    const timer = window.setInterval(tick, 1200);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [selected, snapshot.tasks, snapshot.engine?.active]);

  // 拖动排序：卡片跟手、相邻行让位、松手后按新顺序 FLIP 归位。
  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const dy = event.clientY - drag.y;
      const src = drag.rects.get(drag.id);
      if (!src) return;
      document.querySelectorAll<HTMLElement>("[data-row]").forEach((row) => {
        const key = row.dataset.row || "";
        const base = drag.rects.get(key);
        if (!base) return;
        if (key === drag.id) {
          row.style.transition = "none";
          row.style.transform = `translateY(${dy}px)`;
          row.style.zIndex = "30";
          row.style.boxShadow = "var(--shadow-e4)";
          row.style.cursor = "grabbing";
          row.setAttribute("data-dragging", "true");
          return;
        }
        const movingCenter = src.top + src.height / 2 + dy;
        const middle = base.top + base.height / 2;
        const step = src.height + 10;
        let shift = 0;
        if (base.top > src.top && movingCenter > middle) shift = -step;
        if (base.top < src.top && movingCenter < middle) shift = step;
        row.style.transition = "transform 220ms var(--ease-out)";
        row.style.transform = shift ? `translateY(${shift}px)` : "";
      });
    };
    const onUp = async (event: PointerEvent) => {
      const drag = dragRef.current;
      dragRef.current = null;
      setDraggingId("");
      if (!drag) return;
      if (Math.abs(event.clientY - drag.y) < 8) {
        clearRowStyles();
        return;
      }
      const src = drag.rects.get(drag.id);
      const others = drag.ids.filter((id) => id !== drag.id);
      let at = others.length;
      if (src) {
        const movingCenter = src.top + src.height / 2 + (event.clientY - drag.y);
        for (let i = 0; i < others.length; i += 1) {
          const box = drag.rects.get(others[i]);
          if (box && movingCenter < box.top + box.height / 2) {
            at = i;
            break;
          }
        }
      }
      const ids = [...others];
      ids.splice(at, 0, drag.id);
      const first = new Map<string, number>();
      drag.rects.forEach((box, key) => first.set(key, box.top));
      flipRef.current = first;
      clearRowStyles();
      try {
        await call("/api/order", { ids });
        await refresh();
        notify("顺序已保存");
      } catch (error) {
        flipRef.current = null;
        notify(String(error));
      }
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    return () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
    };
  }, [refresh, notify]);

  // FLIP：列表顺序写回后，每行从旧位置滑到新位置，而不是瞬间跳变。
  useLayoutEffect(() => {
    const first = flipRef.current;
    if (!first) return;
    flipRef.current = null;
    document.querySelectorAll<HTMLElement>("[data-row]").forEach((row) => {
      const before = first.get(row.dataset.row || "");
      if (before == null) return;
      const dy = before - row.getBoundingClientRect().top;
      if (Math.abs(dy) < 1) return;
      row.style.transition = "none";
      row.style.transform = `translateY(${dy}px)`;
      requestAnimationFrame(() => {
        row.style.transition = "transform 240ms var(--ease-out)";
        row.style.transform = "";
      });
    });
  }, [snapshot.tasks]);

  const tasks = snapshot.tasks || [];
  const ap = snapshot.autopilot || {};
  const engineState = snapshot.engine?.state || "idle";
  const running = ["running", "stopping"].includes(engineState);
  const done = tasks.filter((t) => t.status === "done").length;
  const blocked = tasks.filter(
    (t) => ["attention", "failed", "interrupted", "awaiting"].includes(t.status) || t.pending_action === "followup",
  );
  const visible = useMemo(
    () => tasks.filter((t) => (!filter || t.agent === filter) && (!query.trim() || `${t.title} ${t.id}`.toLowerCase().includes(query.trim().toLowerCase()))),
    [tasks, filter, query],
  );
  const current = tasks.find((t) => t.id === selected) || visible[0] || tasks[0];
  const isExecuting = !!current && (ACTIVE.includes(current.status) || snapshot.engine?.active === current.id);

  // 详情请求一律以「当前显示的任务」为准：没点过任务卡时 selected 为空，
  // 但 current 会用 visible[0] 兜底，否则对话/日志/轮次会全部显示为空。
  useEffect(() => {
    if (detailRef.current) detailRef.current.scrollTop = 0;
    const id = current?.id || "";
    if (!id) return;
    call<{ rows: Run[] }>(`/api/tasks/${id}/runs`).then((d) => setRuns(d.rows || [])).catch(() => setRuns([]));
    call<{ lines: string[] }>(`/api/tasks/${id}/log`).then((d) => setLogs(d.lines || [])).catch(() => setLogs([]));
    if (tab === "chat") {
      call<{ messages: { role: string; text: string; ts: number }[]; session_id: string; source: string; count: number }>(
        `/api/tasks/${id}/conversation`
      ).then((d) => setConversation({ messages: d.messages || [], session_id: d.session_id || "", source: d.source || "", count: d.count || 0 }))
        .catch(() => setConversation({ messages: [], session_id: "", source: "", count: 0 }));
    }
  }, [current?.id, tab]);

  const inFlight = useRef<Set<string>>(new Set());
  const act = async (path: string, body: unknown, message: string, method?: string) => {
    const key = `${method || (body === undefined ? "GET" : "POST")} ${path}`;
    // 双击/回车连发会产生重复任务或重复启动，同路径请求完成前直接忽略。
    if (inFlight.current.has(key)) return;
    inFlight.current.add(key);
    try {
      await call(path, body, method);
      await refresh();
      notify(message);
    } catch (error) {
      notify(`失败：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      inFlight.current.delete(key);
    }
  };

  // 当前选中的 Agent 筛选就是「在这个 Agent 下新建」的上下文；
  // 没筛选时才回落到设置里的默认 Agent。
  const activeAgent = filter || config?.agent;
  const createQuick = () => {
    const title = quick.trim();
    if (!title) return;
    const payload = activeAgent ? { title, agent: activeAgent } : { title };
    const message = activeAgent ? `任务已创建 · ${agentName(activeAgent)}` : "任务已创建";
    act("/api/tasks", payload, message).then(() => setQuick(""));
  };

  const openDialog = (next: Dialog) => {
    if (!next) {
      setDialog(null);
      return;
    }
    if (next.mode === "new") {
      setDraft({ title: quick.trim(), prompt: "", agent: filter || config?.agent || "mock" });
    } else {
      setDraft({ title: next.task.title, prompt: next.task.prompt || "", agent: next.task.agent || "mock" });
    }
    setDialog(next);
  };

  const submitDialog = async () => {
    if (!draft.title.trim()) {
      notify("标题不能为空");
      return;
    }
    if (dialog?.mode === "edit") {
      await act(`/api/tasks/${dialog.task.id}/edit`, { ...draft, title: draft.title.trim() }, "任务已更新");
    } else {
      await act("/api/tasks", { ...draft, title: draft.title.trim() }, `任务已创建 · ${agentName(draft.agent)}`);
      setQuick("");
    }
    setDialog(null);
  };

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("theme-option", next);
    setTheme(next);
    notify(next === "dark" ? "已切换深色" : "已切换浅色");
  };

  const exportCsv = () => {
    const rows = history.filter((r) => {
      const ok = historyFilter === "all" || (historyFilter === "done" ? ["done", "ok", "completed"].includes(r.status || "") : !["done", "ok", "completed"].includes(r.status || ""));
      return ok && (!historyQuery.trim() || (r.title || "").toLowerCase().includes(historyQuery.trim().toLowerCase()));
    });
    const esc = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const lines = [
      ["时间", "任务", "Agent", "轮次", "工具", "状态"].map(esc).join(","),
      ...rows.map((r) => [clock(r.ended || r.started), r.title || "", agentName(r.agent || ""), r.round ?? 0, r.tools ?? 0, r.status || ""].map(esc).join(",")),
    ];
    const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "finch-history.csv";
    link.click();
    URL.revokeObjectURL(url);
    notify(`已导出 ${rows.length} 条记录`);
  };

  // ---------- 设置页辅助 ----------
  const setCfg = (key: string, value: unknown) => setConfig((c) => ({ ...c, [key]: value }));
  const setNested = (group: string, key: string, value: unknown) =>
    setConfig((c) => ({ ...c, [group]: { ...(c?.[group] || {}), [key]: value } }));
  const setAgentPath = (key: string, value: string) =>
    setConfig((c) => ({ ...c, agent_paths: { ...(c?.agent_paths || {}), [key]: value } }));

  const field = (label: string, key: string, numeric = false) => (
    <label className="block">
      <span className="fs-11 text-ink-faint">{label}</span>
      <input
        className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 text-ink outline-none focus:border-bamboo"
        value={config?.[key] ?? ""}
        onChange={(e) => setCfg(key, numeric ? e.target.value.replace(/[^\d]/g, "") : e.target.value)}
      />
    </label>
  );
  const nestedField = (label: string, group: string, key: string, numeric = false) => (
    <label className="block">
      <span className="fs-11 text-ink-faint">{label}</span>
      <input
        className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 text-ink outline-none focus:border-bamboo"
        value={config?.[group]?.[key] ?? ""}
        onChange={(e) => {
          const raw = e.target.value.replace(/[^\d.]/g, "");
          setNested(group, key, numeric ? (raw === "" ? 0 : Number(raw)) : e.target.value);
        }}
      />
    </label>
  );
  const checkbox = (label: string, key: string) => (
    <label className="flex items-center gap-2 fs-12 text-ink-soft">
      <input type="checkbox" className="accent-bamboo" checked={!!config?.[key]} onChange={(e) => setCfg(key, e.target.checked)} />
      {label}
    </label>
  );
  const nestedCheckbox = (label: string, group: string, key: string) => (
    <label className="flex items-center gap-2 fs-12 text-ink-soft">
      <input type="checkbox" className="accent-bamboo" checked={!!config?.[group]?.[key]} onChange={(e) => setNested(group, key, e.target.checked)} />
      {label}
    </label>
  );

  const changeDefaultAgent = async (value: string) => {
    setCfg("agent", value);
    try {
      await call("/api/config", { agent: value });
      notify(`默认 Agent 已设为 ${agentName(value)}`);
    } catch (error) {
      notify(`失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  const saveConfig = async () => {
    if (!config) return;
    await act("/api/config", config, "设置已保存");
  };

  const pickDir = async () => {
    try {
      const data = await call<{ path?: string }>("/api/pick-dir", { start: config?.cwd || "" });
      if (data?.path) {
        setCfg("cwd", data.path);
        await call("/api/config", { cwd: data.path });
        notify("已选择目录并保存");
      }
    } catch (error) {
      notify(String(error));
    }
  };
  const openDir = async () => {
    try {
      await call("/api/open-dir", { path: config?.cwd || "" });
    } catch (error) {
      notify(String(error));
    }
  };
  const testAnalyzer = async () => {
    try {
      const data = await call<Record<string, any>>("/api/test-analyzer", config?.analyzer || {});
      notify(data?.ok ? "解析服务连接成功" : `连接失败：${data?.detail || data?.error || "未知错误"}`);
    } catch (error) {
      notify(`连接失败：${String(error)}`);
    }
  };
  const testMcp = async () => {
    try {
      const data = await call<Record<string, any>>("/api/test-mcp", config?.optimizer || {});
      notify(data?.ok ? "MCP 连接成功" : `MCP 失败：${data?.detail || data?.error || "未知错误"}`);
    } catch (error) {
      notify(`MCP 失败：${String(error)}`);
    }
  };

  // ---------- 通用小组件 ----------
  const badge = (status: string) => {
    const dot = status === "done" || ACTIVE.includes(status)
      ? "bg-bamboo"
      : ["attention", "failed", "interrupted", "awaiting"].includes(status)
        ? "bg-amber-500"
        : "bg-ink-ghost/60";
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap fs-10 text-ink-faint">
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        {STATUS[status] || status}
      </span>
    );
  };

  return (
    <div style={fontVars} className="flex h-full w-full min-w-0 max-w-[100vw] flex-col overflow-x-hidden overflow-y-hidden bg-cloud text-ink">
      <div className="mica-topbar flex h-11 min-w-0 shrink-0 items-center gap-2 bg-paper px-4 max-[600px]:px-3">
        <div className="flex shrink-0 items-center gap-1">
          {([["queue", "工作台"], ["history", "执行记录"], ["settings", "设置"]] as const).map(([key, label]) => (
            <button key={key} onClick={() => setPage(key)} className={`shrink-0 whitespace-nowrap rounded-lg px-3 py-1 fs-12 cursor-pointer transition-colors max-[600px]:px-2 ${page === key ? "bg-bamboo-mist text-bamboo font-semibold" : "text-ink-faint hover:bg-bamboo-mist hover:text-bamboo"}`}>{label}</button>
          ))}
        </div>
        <div className="min-w-0 flex-1" />
        {!isNarrow && page === "queue" && (
          <div className="flex items-center gap-2">
            <button onClick={() => act(running ? "/api/queue/pause" : "/api/queue/start", {}, running ? "队列已暂停" : "队列已开始")} className="rounded-lg bg-bamboo px-3 min-h-[30px] py-1.5 fs-11 text-white hover:bg-bamboo-light cursor-pointer">
              {running ? "暂停队列" : "开始队列"}
            </button>
            <button onClick={() => setShowAutopilot(true)} className="rounded-lg border border-paper-deep px-3 min-h-[30px] py-1.5 fs-11 text-ink-soft hover:bg-bamboo-mist cursor-pointer">
              自动驾驶{ap.active ? " · 运行中" : ""}
            </button>
            <div className="relative">
              <button onClick={() => setShowMore(!showMore)} className="rounded-lg border border-paper-deep px-2 min-h-[30px] py-1.5 fs-11 text-ink-soft cursor-pointer">更多</button>
              {showMore && (
                <div className="pop-in absolute right-0 top-9 z-30 w-32 rounded-lg border border-paper-deep bg-cloud py-1 shadow-e3">
                  <button onClick={() => { setShowMore(false); act("/api/queue/stop", {}, "队列已终止"); }} className="block w-full px-3 py-1.5 text-left fs-11 text-ink-soft hover:bg-bamboo-mist cursor-pointer">终止</button>
                  <button onClick={() => { setShowMore(false); act("/api/queue/skip-retry", {}, "已跳过续传"); }} className="block w-full px-3 py-1.5 text-left fs-11 text-ink-soft hover:bg-bamboo-mist cursor-pointer">跳过续传</button>
                  <button onClick={() => { setShowMore(false); act("/api/queue/force-next", {}, "已强制下一条"); }} className="block w-full px-3 py-1.5 text-left fs-11 text-ink-soft hover:bg-bamboo-mist cursor-pointer">强制下一条</button>
                </div>
              )}
            </div>
          </div>
        )}
        {!isNarrow && (
          <span className={`shrink-0 whitespace-nowrap rounded-full border px-2 py-0.5 fs-10 ${running ? "border-bamboo-glow bg-bamboo-mist text-bamboo" : "border-paper-deep text-ink-faint"}`}>
            {running ? "执行中" : "空闲"} · {tasks.length} 条 · {done} 完成
          </span>
        )}
        <button onClick={toggleTheme} className="shrink-0 whitespace-nowrap rounded-lg px-2 py-1 fs-12 text-ink-faint hover:bg-paper-warm hover:text-bamboo cursor-pointer max-[600px]:px-1" title="切换深浅主题">
          {theme === "dark" ? "浅色" : "深色"}
        </button>
      </div>

      {!online && (
        <div className="shrink-0 border-b border-amber-300 bg-amber-50 px-4 py-2 fs-12 text-amber-800">
          Finch 服务未连接（127.0.0.1:8766），队列与设置暂不可用。请重启应用；日志在 <code>.oil-ui/finch-oil-desktop/backend.log</code>。
          <button onClick={() => void refresh()} className="ml-2 rounded-lg border border-amber-400 px-2 py-0.5 fs-11 cursor-pointer">重试</button>
        </div>
      )}

      {page === "queue" && (
        <div className="page-in flex min-h-0 min-w-0 w-full flex-1 overflow-hidden">
          {/* 1：任务列表 */}
          <div role="region" aria-label="任务列表" className="flex min-w-0 flex-1 flex-col border-r border-paper-deep/30 p-4">
            <div className="flex items-center gap-2">
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索任务…" className="h-8 min-w-0 flex-1 rounded-lg border border-paper-deep bg-paper px-3 fs-12 outline-none placeholder:text-ink-faint focus:border-bamboo" />
              <button onClick={() => setView(view === "list" ? "board" : "list")} className="h-8 shrink-0 rounded-lg border border-paper-deep px-2 fs-11 text-ink-soft hover:bg-bamboo-mist cursor-pointer">{view === "list" ? "看板" : "清单"}</button>
            </div>
            <div className="chips-scroll mt-2 flex flex-nowrap items-center gap-1.5 overflow-x-auto pb-1">
              <span className="mr-1 fs-10 text-ink-faint">Agent</span>
              {AGENTS.map(([key, label, asset]) => (
                <button key={key} aria-pressed={filter === key} onClick={() => setFilter(filter === key ? "" : key)} className={`flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2 py-1 fs-11 cursor-pointer ${filter === key ? "border-bamboo bg-bamboo text-white" : "border-paper-deep text-ink-soft hover:bg-bamboo-mist"}`}>
                  {asset ? <img src={`${API}/assets/agents/${asset}`} alt="" className="h-3.5 w-3.5" /> : <span className="h-3.5 w-3.5 text-center">✳</span>}
                  <span>{label}</span>
                  <span className="font-mono fs-10 opacity-70">{tasks.filter((t) => t.agent === key).length}</span>
                </button>
              ))}
              {filter ? <button onClick={() => setFilter("")} className="rounded-full px-2 py-1 fs-11 text-bamboo cursor-pointer">清除 ✕</button> : null}
            </div>

            {blocked.length ? (
              <div className="mt-3 space-y-2">
                {blocked.map((task) => (
                  <div key={task.id} className="rounded-lg border border-amber-200/80 bg-amber-50/60 p-3">
                    <div className="fs-12 font-medium text-amber-800">需要决定 · {task.title}</div>
                    <p className="mt-1 fs-11 leading-relaxed text-ink-faint">{task.attention_reason || task.followup_prompt || "验收发现遗留项，需要确认是否继续补做。"}</p>
                    <input
                      value={decisionPrompt[task.id] ?? task.followup_prompt ?? ""}
                      onChange={(e) => setDecisionPrompt((d) => ({ ...d, [task.id]: e.target.value }))}
                      placeholder="补做指令（可修改）"
                      className="mt-2 w-full rounded-lg border border-amber-200 bg-cloud px-2 min-h-[28px] py-1 fs-11 outline-none focus:border-bamboo"
                    />
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <button onClick={() => act(`/api/tasks/${task.id}/followup`, { decision: "approve", prompt: decisionPrompt[task.id] ?? task.followup_prompt ?? "" }, "已下发补做")} className="rounded-lg bg-bamboo px-2 py-1 fs-10 text-white cursor-pointer">下发补做</button>
                      <button onClick={() => act(`/api/tasks/${task.id}/followup`, { decision: "skip" }, "已跳过补做")} className="rounded-lg border border-amber-300 px-2 py-1 fs-10 text-amber-700 cursor-pointer">跳过补做</button>
                      <button onClick={() => act(`/api/tasks/${task.id}/retry`, { autostart: true }, "已重新开始该任务")} className="rounded-lg border border-paper-deep px-2 py-1 fs-10 text-ink-soft cursor-pointer">重试本轮</button>
                      <button onClick={() => act("/api/queue/force-next", {}, "已强制下一条")} className="rounded-lg border border-paper-deep px-2 py-1 fs-10 text-ink-soft cursor-pointer">强制下一条</button>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="gutter-stable mt-3 min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto pr-1">
              {view === "list" ? (
                <div className="space-y-2.5">
                  {visible.length ? visible.map((task) => (
                    <div
                      key={task.id}
                      data-row={task.id}
                      role="button"
                      tabIndex={0}
                      aria-current={current?.id === task.id ? "true" : undefined}
                      onClick={() => selectTask(task.id)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectTask(task.id); } }}
                      onDragStart={(e) => e.preventDefault()}
                      draggable={false}
                      onPointerDown={(e) => {
                        const target = e.target as HTMLElement;
                        // 按钮、输入框等交互元素不启动拖动；把手自己处理 pointerdown。
                        if (target.closest("button, a, input, textarea, select, summary, [title='拖动排序']")) return;
                        dragRef.current = captureRows(task.id, e.clientY);
                        setDraggingId(task.id);
                      }}
                      className={`task-row rounded-lg border p-3 select-none cursor-pointer transition-colors focus:outline-none focus:border-bamboo ${draggingId === task.id ? "border-bamboo bg-bamboo-mist/60 shadow-e3" : current?.id === task.id ? "border-bamboo bg-bamboo-mist/40" : "border-paper-deep/40 bg-cloud hover:border-bamboo/60"}`}
                    >
                      <div className="flex items-center gap-2">
                        <span onPointerDown={(e) => { e.stopPropagation(); e.preventDefault(); dragRef.current = captureRows(task.id, e.clientY); setDraggingId(task.id); }} className="-ml-1 cursor-grab px-1 fs-12 text-ink-faint select-none active:cursor-grabbing" title="拖动排序">⠿</span>
                        <button onClick={(e) => { e.stopPropagation(); act(`/api/tasks/${task.id}/toggle`, {}, task.status === "done" ? "已取消完成" : "已标记完成"); }} className={`flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-lg border fs-10 cursor-pointer ${task.status === "done" ? "border-bamboo bg-bamboo text-white" : "border-ink-ghost/60 text-transparent"}`} title="标记完成">✓</button>
                        <span className={`min-w-0 flex-1 truncate fs-13 ${task.status === "done" ? "text-ink-faint line-through" : "text-ink"}`}>{task.title}</span>
                        <span className="font-mono fs-10 text-ink-faint">{fmt(task.seconds)}</span>
                      </div>
                      {ACTIVE.includes(task.status) || snapshot.engine?.active === task.id ? (
                        <div className="mt-1.5 flex items-center gap-2 fs-11 text-ink-faint">
                          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-bamboo animate-pulse" />
                          <span className="min-w-0 flex-1 truncate text-ink-soft">{task.progress || "正在执行…"}</span>
                          <span className="shrink-0">{fmt(task.seconds)}</span>
                          <span className="shrink-0">工具 {task.tools || 0}</span>
                        </div>
                      ) : task.progress || task.summary ? (
                        <div className="mt-1.5 truncate fs-11 leading-relaxed text-ink-faint">
                          {task.progress || task.summary}
                        </div>
                      ) : null}
                      <div className="mt-2 flex flex-wrap items-center gap-2 fs-11">
                        {badge(task.status)}
                        <span className="text-ink-faint">{agentName(task.agent)}</span>
                        {task.resume ? <span className="text-ink-faint">续传 {task.resume}</span> : null}
                        {task.followup ? <span className="text-ink-faint">补做 {task.followup}</span> : null}
                        <div className="flex-1" />
                        <div className="relative">
                          <button
                            onClick={(e) => { e.stopPropagation(); setMenuFor(menuFor === task.id ? "" : task.id); }}
                            className="rounded-lg px-1.5 py-0.5 fs-12 leading-none text-ink-faint hover:bg-paper-warm cursor-pointer"
                            title="更多操作"
                          >⋯</button>
                          {menuFor === task.id ? (
                            <div onClick={(e) => e.stopPropagation()} className="pop-in absolute right-0 top-6 z-20 w-28 rounded-lg border border-paper-deep bg-cloud py-1 shadow-e3">
                              {([
                                ["执行", () => act("/api/queue/start", { task_id: task.id }, "已开始执行")],
                                ["重新排队", () => act(`/api/tasks/${task.id}/status`, { status: "queued" }, "已重新排队")],
                                ["编辑", () => openDialog({ mode: "edit", task })],
                                ["重试", () => act(`/api/tasks/${task.id}/retry`, { autostart: true }, "已重试")],
                                ["删除", () => { if (window.confirm(`删除「${task.title}」？`)) act(`/api/tasks/${task.id}`, undefined, "任务已删除", "DELETE"); }],
                              ] as [string, () => void][]).map(([label, fn]) => (
                                <button key={label} onClick={() => { setMenuFor(""); fn(); }} className="block w-full px-3 py-1.5 text-left fs-11 text-ink-soft hover:bg-bamboo-mist hover:text-bamboo cursor-pointer">{label}</button>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  )) : <div className="pt-10 text-center fs-12 text-ink-faint">没有匹配的任务</div>}
                  {visible.length ? (
                    <div className="pt-4 text-center fs-11 text-ink-faint">
                      已显示全部 {visible.length} 条任务 · 在下方输入框添加新任务
                    </div>
                  ) : null}
                  {history.length ? (
                    <div className="mt-6 border-t border-paper-deep/20 pt-3 max-[600px]:hidden">
                      <div className="fs-11 font-semibold text-ink-soft">最近执行</div>
                      <div className="mt-2 space-y-1.5">
                        {history.slice(0, 4).map((run) => (
                          <div key={run.id} className="flex items-baseline gap-2 fs-11">
                            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-bamboo-light/70" />
                            <span className="min-w-0 flex-1 truncate text-ink-soft">{run.title || "执行轮次"}</span>
                            <span className="shrink-0 text-ink-faint">{clock(run.started)}</span>
                            <span className="shrink-0 text-ink-faint">{fmt(run.duration)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="space-y-3">
                  {BOARD_COLS.map(([name, statuses]) => {
                    const items = visible.filter((t) => statuses.includes(t.status));
                    return (
                      <div key={name} onDragOver={(e) => e.preventDefault()} onDrop={async (e) => {
                        e.preventDefault();
                        const id = e.dataTransfer.getData("text/plain");
                        if (!id) return;
                        if (name === "进行中") {
                          notify("运行中由引擎控制，不能直接拖入");
                          return;
                        }
                        const status = name === "已完成" ? "done" : name === "待处理" ? "attention" : "queued";
                        await act(`/api/tasks/${id}/status`, { status }, "状态已更新");
                      }} className="rounded-lg border border-paper-deep/40 bg-paper/60 p-2">
                        <div className="fs-11 text-ink-faint">{name} · {items.length}</div>
                        <div className="mt-2 space-y-1.5">
                          {items.map((t) => (
                            <div key={t.id} draggable role="button" tabIndex={0} aria-current={current?.id === t.id ? "true" : undefined} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectTask(t.id); } }} onDragStart={(e) => e.dataTransfer.setData("text/plain", t.id)} onClick={() => selectTask(t.id)} className={`task-row rounded-lg border bg-cloud px-2 min-h-[30px] py-1.5 fs-11 cursor-grab select-none ${current?.id === t.id ? "border-bamboo" : "border-paper-deep/40"}`}>
                              <div className="truncate text-ink">{t.title}</div>
                              <div className="mt-1 fs-10 text-ink-faint">{agentName(t.agent)}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {isNarrow && (
              <div className="mt-3 flex shrink-0 flex-wrap items-center gap-2 border-t border-paper-deep/20 pt-3">
                <button onClick={() => act(running ? "/api/queue/pause" : "/api/queue/start", {}, running ? "队列已暂停" : "队列已开始")} className="rounded-lg bg-bamboo px-3 py-1.5 fs-11 text-white cursor-pointer">
                  {running ? "暂停队列" : "开始队列"}
                </button>
                <button onClick={() => setShowAutopilot(true)} className="rounded-lg border border-paper-deep px-3 py-1.5 fs-11 text-ink-soft cursor-pointer">自动驾驶</button>
                <div className="relative">
                  <button onClick={() => setShowMobileMore(!showMobileMore)} className="rounded-lg border border-paper-deep px-2 py-1.5 fs-11 text-ink-soft cursor-pointer">更多</button>
                  {showMobileMore && (
                    <div className="pop-in absolute left-0 top-9 z-30 w-32 rounded-lg border border-paper-deep bg-cloud py-1 shadow-e3">
                      <button onClick={() => { setShowMobileMore(false); act("/api/queue/stop", {}, "队列已终止"); }} className="block w-full px-3 py-1.5 text-left fs-11 text-ink-soft cursor-pointer">终止</button>
                      <button onClick={() => { setShowMobileMore(false); act("/api/queue/skip-retry", {}, "已跳过续传"); }} className="block w-full px-3 py-1.5 text-left fs-11 text-ink-soft cursor-pointer">跳过续传</button>
                      <button onClick={() => { setShowMobileMore(false); act("/api/queue/force-next", {}, "已强制下一条"); }} className="block w-full px-3 py-1.5 text-left fs-11 text-ink-soft cursor-pointer">强制下一条</button>
                    </div>
                  )}
                </div>
              </div>
            )}
            <div className="mt-3 flex min-w-0 gap-2">
              <input value={quick} onChange={(e) => setQuick(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") createQuick(); }} placeholder="添加任务，回车创建" className="h-8 min-w-0 flex-1 rounded-lg border border-paper-deep bg-paper px-3 fs-12 outline-none placeholder:text-ink-faint focus:border-bamboo" />
              <button onClick={createQuick} className="shrink-0 rounded-lg border border-bamboo px-3 fs-11 text-bamboo hover:bg-bamboo-mist cursor-pointer">添加</button>
              <button onClick={() => openDialog({ mode: "new" })} className="shrink-0 rounded-lg border border-paper-deep px-2 fs-11 text-ink-soft cursor-pointer">详细</button>
            </div>
          </div>

          {/* 2：详情 */}
          <div role="region" aria-label="任务详情" className={`flex w-[420px] shrink-0 flex-col overflow-hidden max-[900px]:fixed max-[900px]:inset-y-0 max-[900px]:right-0 max-[900px]:z-30 max-[900px]:w-full max-[900px]:bg-cloud max-[900px]:shadow-e5 ${detailOpen ? "" : "max-[900px]:hidden"}`}>
            {current ? (
              <>
                <div className="shrink-0 border-b border-paper-deep/30 px-4 py-4">
                  <div className="flex items-center gap-2 fs-10">
                    {badge(current.status)}
                    <span className="text-ink-faint">{agentName(current.agent)}</span>
                    <span className="text-ink-faint">· {fmt(current.seconds)}</span>
                    <div className="flex-1" />
                    <button onClick={() => openDialog({ mode: "edit", task: current })} className="rounded-lg px-2 py-0.5 fs-10 text-ink-soft hover:bg-paper-warm cursor-pointer">编辑</button>
                    <button onClick={() => act(`/api/tasks/${current.id}/retry`, { autostart: true }, "已重试")} className="rounded-lg px-2 py-0.5 fs-10 text-ink-soft hover:bg-paper-warm cursor-pointer">重试</button>
                    <button onClick={() => setDetailOpen(false)} className="hidden rounded-lg px-2 py-0.5 fs-10 text-ink-soft max-[900px]:inline cursor-pointer">关闭</button>
                  </div>
                  <div className="mt-1.5 truncate font-serif fs-16 font-semibold text-ink">{current.title}</div>
                  <div className="mt-0.5 truncate fs-11 text-ink-faint">{current.progress || current.summary || "等待执行"}</div>
                </div>
                <div className="flex shrink-0 gap-4 px-4">
                  {([["result", "结果"], ["process", "过程"]] as const).map(([key, label]) => (
                    <button key={key} onClick={() => setTab(key === "result" ? "result" : "logs")} className={`py-2 fs-12 cursor-pointer ${(key === "result" ? tab === "result" : tab !== "result") ? "border-b-2 border-bamboo text-bamboo" : "text-ink-faint hover:text-ink-soft"}`}>{label}</button>
                  ))}
                </div>
                {tab !== "result" ? (
                  <div className="flex shrink-0 gap-3 border-b border-paper-deep/20 px-4 pb-1.5 pt-1">
                    {([["runs", "执行轮次"], ["logs", "完整日志"], ["chat", "对话记录"]] as const).map(([key, label]) => (
                      <button key={key} onClick={() => setTab(key)} className={`rounded-lg px-2 py-1 fs-11 cursor-pointer ${tab === key ? "border-b-2 border-bamboo bg-bamboo-mist/40 text-bamboo" : "text-ink-faint hover:text-ink-soft"}`}>{label}</button>
                    ))}
                  </div>
                ) : null}
                <div key={tab} ref={detailRef} className="gutter-stable page-in min-h-0 min-w-0 flex-1 overflow-auto px-4 py-4 break-words">
                  {tab === "result" && (
                    <>
                      {isExecuting ? (
                        <div className="rounded-r-lg border-l-2 border-bamboo bg-bamboo-mist/40 px-3 py-3">
                          <div className="flex items-center gap-2 fs-13 font-semibold text-bamboo">
                            <span className="h-2 w-2 shrink-0 rounded-full bg-bamboo animate-pulse" />
                            正在执行 · {agentName(current.agent)}
                          </div>
                          <div className="mt-1.5 fs-11 text-ink-soft">{current.progress || "Agent 正在启动…"}</div>
                          <div className="mt-2 flex flex-wrap gap-4 fs-11 text-ink-faint">
                            <span>耗时 <b className="fs-13 font-semibold text-ink">{fmt(current.seconds)}</b></span>
                            <span>工具调用 <b className="fs-13 font-semibold text-ink">{current.tools || 0}</b></span>
                          </div>
                          <button onClick={() => setTab("logs")} className="mt-3 fs-11 text-bamboo cursor-pointer">查看过程 →</button>
                        </div>
                      ) : (
                        <div className="rounded-r-lg border-l-2 border-bamboo/60 bg-paper/70 px-3 py-3">
                          <div className="mb-1 fs-10 text-ink-faint">最终结果</div>
                          <div className="font-serif fs-13 leading-relaxed text-ink">{current.summary || "该任务还没有结果摘要。"}</div>
                        </div>
                      )}
                      <div className="mt-3 flex items-center gap-2 rounded-lg border border-paper-deep/40 bg-cloud px-3 py-2">
                        <div className="min-w-0 flex-1">
                          <div className="fs-10 text-ink-faint">产物目录</div>
                          <div className="mt-0.5 truncate font-mono fs-10 text-ink-soft">{current.cwd || "独立沙箱目录"}</div>
                        </div>
                        <button onClick={() => act("/api/open-dir", { task_id: current.id, path: current.cwd || "" }, "已打开目录")} className="shrink-0 rounded-lg border border-paper-deep px-2 py-1 fs-10 text-ink-soft cursor-pointer">打开</button>
                      </div>
                      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-paper-deep/20 pt-3 fs-11">
                        {([["状态", STATUS[current.status] || current.status], ["Agent", agentName(current.agent)], ["耗时", fmt(current.seconds)], ["工具调用", current.tools || 0]] as const).map(([label, value]) => (
                          <div key={label} className="flex items-baseline justify-between gap-2">
                            <span className="text-ink-faint">{label}</span>
                            <span className="truncate font-semibold text-ink-soft">{value}</span>
                          </div>
                        ))}
                        <div className="col-span-2 border-t border-paper-deep/20 pt-2">
                          <div className="fs-10 text-ink-faint">执行目录</div>
                          <div className="mt-0.5 break-all font-mono fs-10 text-ink-soft">{current.cwd || "独立沙箱（未设置项目目录）"}</div>
                        </div>
                      </div>
                      {((current.completed || []).length || (current.pending || []).length || (current.issues || []).length) ? (
                        <details className="mt-3 fs-11 text-ink-faint">
                          <summary className="cursor-pointer">结果明细（完成 / 缺漏 / 风险）</summary>
                          <div className="mt-1 fs-11 leading-relaxed text-ink-soft">
                            {(current.completed || []).map((item, i) => <div key={`c${i}`}>· {item}</div>)}
                            {(current.pending || []).map((item, i) => <div key={`p${i}`}>· 缺漏：{item}</div>)}
                            {(current.issues || []).map((item, i) => <div key={`i${i}`}>· 风险：{item}</div>)}
                          </div>
                        </details>
                      ) : null}
                    </>
                  )}
                  {tab === "runs" && (
                    <div className="space-y-1">
                      {runs.length ? runs.map((run, i) => (
                        <div key={i} className="flex items-center gap-3 border-b border-paper-deep/20 py-2 fs-11">
                          <span className="w-10 font-mono text-ink-faint">#{String(run.round || 0).padStart(2, "0")}</span>
                          <span className="min-w-0 flex-1 truncate text-ink-soft">{run.kind || "main"} · {clock(run.started)} · {fmt(run.duration)} · 工具 {run.tools || 0}</span>
                          <span className="rounded-full border border-paper-deep px-2 py-0.5 fs-10 text-ink-faint">{run.status}</span>
                        </div>
                      )) : <div className="fs-12 text-ink-faint">还没有执行记录。</div>}
                    </div>
                  )}
                  {tab === "chat" && (
                    <div className="space-y-2.5">
                      <div className="rounded-lg border border-paper-deep/40 bg-paper/70 px-3 py-2 fs-10 leading-relaxed text-ink-faint">
                        <div className="font-semibold text-ink-soft">Agent CLI 原始会话 · {conversation.count} 条消息</div>
                        <div className="mt-0.5 break-all">{conversation.source || "未找到会话文件（该任务可能未由 CLI 执行）"}</div>
                        {conversation.session_id ? (
                          <div className="mt-1 flex items-center gap-2">
                            <span className="font-mono">会话 {conversation.session_id}</span>
                            <button onClick={() => { try { void navigator.clipboard?.writeText(`codebuddy --resume ${conversation.session_id}`); notify("已复制续聊命令"); } catch { notify("复制失败"); } }} className="rounded-lg border border-paper-deep px-2 py-0.5 fs-10 text-ink-soft cursor-pointer">复制续聊命令</button>
                          </div>
                        ) : null}
                      </div>
                      {conversation.messages.length ? conversation.messages.map((m, i) => (
                        m.role === "user" ? (
                          <div key={i} className="ml-8 rounded-lg bg-bamboo-mist/60 px-3 py-2 fs-11 leading-relaxed text-ink">
                            <div className="mb-0.5 fs-10 font-semibold text-bamboo">任务指令</div>{m.text}
                          </div>
                        ) : m.role === "assistant" ? (
                          <div key={i} className="mr-8 rounded-lg border border-paper-deep/40 bg-cloud px-3 py-2 fs-11 leading-relaxed text-ink">
                            <div className="mb-0.5 fs-10 font-semibold text-ink-soft">Agent 回复</div>{m.text}
                          </div>
                        ) : m.role === "thinking" ? (
                          <details key={i} className="rounded-lg bg-paper/60 px-3 py-1.5 fs-10 text-ink-faint">
                            <summary className="cursor-pointer">思考过程</summary>
                            <div className="mt-1 whitespace-pre-wrap leading-relaxed">{m.text}</div>
                          </details>
                        ) : (
                          <div key={i} className="rounded-lg border-l-2 border-paper-deep/40 px-2 py-1 font-mono fs-10 leading-relaxed text-ink-faint">
                            <span className="mr-1 font-semibold">{m.role === "tool" ? "调用" : "结果"}</span>{m.text || "（无输出）"}
                          </div>
                        )
                      )) : <div className="py-6 text-center fs-11 text-ink-faint">暂无对话记录</div>}
                    </div>
                  )}
                  {tab === "logs" && (
                    <pre className="whitespace-pre-wrap break-words rounded-lg bg-paper-warm p-3 font-mono fs-11 leading-relaxed text-ink-soft">
                      {(liveLogs.length ? liveLogs : logs).length ? (liveLogs.length ? liveLogs : logs).join("\n") : "暂无日志\n任务开始执行后会实时输出 Agent 的原始日志。"}
                    </pre>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2 border-t border-paper-deep/20 px-4 py-3 fs-10 leading-relaxed text-ink-faint">
                  <span className="min-w-0 flex-1 truncate">{current.id} · {agentName(current.agent)} · {fmt(current.seconds)}</span>
                  
                </div>
              </>
            ) : <div className="flex flex-1 items-center justify-center fs-12 text-ink-faint">选择一条任务查看详情</div>}
          </div>
        </div>
      )}

      {page === "history" && (
        <div className="page-in min-h-0 flex-1 overflow-auto p-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-serif fs-15 text-ink-soft">执行记录</span>
            <span className="fs-11 text-ink-faint">{history.length} 轮真实执行</span>
            <div className="flex-1" />
            <input value={historyQuery} onChange={(e) => setHistoryQuery(e.target.value)} placeholder="搜索任务" className="h-8 w-44 rounded-lg border border-paper-deep bg-paper px-3 fs-12 outline-none focus:border-bamboo" />
            <button onClick={() => setHistoryFilter("all")} className={`rounded-lg px-2 min-h-[30px] py-1.5 fs-11 cursor-pointer ${historyFilter === "all" ? "bg-bamboo text-white" : "border border-paper-deep text-ink-soft"}`}>全部</button>
            <button onClick={() => setHistoryFilter("done")} className={`rounded-lg px-2 min-h-[30px] py-1.5 fs-11 cursor-pointer ${historyFilter === "done" ? "bg-bamboo text-white" : "border border-paper-deep text-ink-soft"}`}>已完成</button>
            <button onClick={() => setHistoryFilter("failed")} className={`rounded-lg px-2 min-h-[30px] py-1.5 fs-11 cursor-pointer ${historyFilter === "failed" ? "bg-bamboo text-white" : "border border-paper-deep text-ink-soft"}`}>其他</button>
            <button onClick={exportCsv} className="rounded-lg border border-paper-deep px-2 min-h-[30px] py-1.5 fs-11 text-ink-soft hover:bg-bamboo-mist cursor-pointer">导出 CSV</button>
          </div>
          <div className="mt-4 space-y-1">
            {history.filter((r) => {
              const ok = ["done", "ok", "completed"].includes(r.status || "");
              const pass = historyFilter === "all" || (historyFilter === "done" ? ok : !ok);
              return pass && (!historyQuery.trim() || (r.title || "").toLowerCase().includes(historyQuery.trim().toLowerCase()));
            }).length ? history.filter((r) => {
              const ok = ["done", "ok", "completed"].includes(r.status || "");
              const pass = historyFilter === "all" || (historyFilter === "done" ? ok : !ok);
              return pass && (!historyQuery.trim() || (r.title || "").toLowerCase().includes(historyQuery.trim().toLowerCase()));
            }).map((run) => (
              <div key={run.id} className="flex items-center gap-3 border-b border-paper-deep/20 py-2 fs-12">
                <span className="w-14 font-mono fs-10 text-ink-faint">{clock(run.ended || run.started)}</span>
                <span className="min-w-0 flex-1 truncate text-ink-soft">{run.title || "—"}</span>
                <span className="fs-10 text-ink-faint">{agentName(run.agent || "")}</span>
                <span className="fs-10 text-ink-faint">第 {run.round || 0} 轮</span>
                <span className="fs-10 text-ink-faint">{run.tools || 0} 次工具</span>
                <span className="rounded-full border border-paper-deep px-2 py-0.5 fs-10 text-ink-faint">{run.status}</span>
              </div>
            )) : <div className="fs-12 text-ink-faint">暂无匹配记录</div>}
          </div>
        </div>
      )}

      {page === "settings" && (
        <div className="page-in min-h-0 flex-1 overflow-auto p-6">
          <div className="flex items-center gap-3">
            <span className="font-serif fs-15 text-ink-soft">设置</span>
            <div className="flex-1" />
            <button onClick={saveConfig} className="rounded-lg bg-bamboo px-3 min-h-[30px] py-1.5 fs-11 text-white hover:bg-bamboo-light cursor-pointer">保存设置</button>
          </div>
          {config ? (
            <div className="mt-4 grid grid-cols-2 gap-6">
              <div className="space-y-3">
                <div className="font-serif fs-14 font-normal text-ink-soft">界面</div>
                <label className="block">
                  <span className="fs-11 text-ink-faint">字号（即时生效并保存）</span>
                  <select
                    value={fontScale}
                    onChange={(e) => void changeFontScale(Number(e.target.value))}
                    className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 outline-none focus:border-bamboo"
                  >
                    <option value={1}>小 · 100%</option>
                    <option value={1.2}>标准 · 120%（默认）</option>
                    <option value={1.35}>大 · 135%</option>
                    <option value={1.5}>特大 · 150%</option>
                  </select>
                </label>
                <div className="font-serif fs-14 font-normal text-ink-soft">运行环境</div>
                <label className="block">
                  <span className="fs-11 text-ink-faint">默认 Agent</span>
                  <select className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 outline-none focus:border-bamboo" value={config.agent || "mock"} onChange={(e) => void changeDefaultAgent(e.target.value)}>
                    {AGENTS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                  </select>
                </label>
                <label className="block">
                  <span className="fs-11 text-ink-faint">默认工作目录</span>
                  <div className="mt-0.5 fs-10 leading-relaxed text-ink-faint">
                    留空 = 每个任务在 %APPDATA%/Finch/workspaces/&lt;任务ID&gt; 独立沙箱执行；填项目路径才会直接在你的项目里读写文件。<br />
                    Finch 调用 CodeBuddy CLI 无头模式，完整对话落在 ~/.codebuddy/projects/&lt;工作目录&gt;/&lt;会话ID&gt;.jsonl，可在任务详情「对话记录」里查看并复制 --resume 命令。<br />
                    CodeBuddy IDE 侧边栏用的是另一套历史（genie-history），无头会话不会自动出现在那里。
                  </div>
                  <div className="mt-1 flex gap-2">
                    <input className="min-w-0 flex-1 rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 outline-none focus:border-bamboo" value={config.cwd || ""} onChange={(e) => setCfg("cwd", e.target.value)} />
                    <button onClick={pickDir} className="shrink-0 rounded-lg border border-paper-deep px-2 fs-11 text-ink-soft cursor-pointer">选择</button>
                    <button onClick={openDir} className="shrink-0 rounded-lg border border-paper-deep px-2 fs-11 text-ink-soft cursor-pointer">打开</button>
                  </div>
                </label>
                <label className="block">
                  <span className="fs-11 text-ink-faint">Claude 权限模式</span>
                  <select className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 outline-none focus:border-bamboo" value={config.permission_mode || "acceptEdits"} onChange={(e) => setCfg("permission_mode", e.target.value)}>
                    {[["acceptEdits", "自动接受文件编辑"], ["default", "默认权限询问"], ["dontAsk", "拒绝危险动作"], ["bypassPermissions", "跳过权限检查"], ["plan", "计划模式"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </label>
                {checkbox("跳过 MCP / 插件启动", "isolate_mcp")}
                <div className="font-serif fs-14 font-normal text-ink-soft">中断检测（秒 / 次）</div>
                {field("文本空闲超时", "text_idle_timeout", true)}
                {field("首包宽限", "first_output_grace", true)}
                {field("工具执行超时", "tool_timeout", true)}
                {field("最大续传次数", "max_resumes", true)}
                {field("最大补做轮次", "max_followups", true)}
                <div className="font-serif fs-14 font-normal text-ink-soft">Agent 路径覆盖</div>
                {AGENTS.map(([key, label]) => (
                  <label key={key} className="block">
                    <span className="fs-11 text-ink-faint">{label}{agentsInfo[key]?.found ? " · 已找到" : ""}</span>
                    <input className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 min-h-[30px] py-1.5 fs-11 outline-none focus:border-bamboo" value={config.agent_paths?.[key] || agentsInfo[key]?.path || ""} placeholder="留空则自动检测" onChange={(e) => setAgentPath(key, e.target.value)} />
                  </label>
                ))}
                <label className="block">
                  <span className="fs-11 text-ink-faint">额外启动参数（JSON，按 Agent 键）</span>
                  <input
                    className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 min-h-[30px] py-1.5 fs-11 outline-none focus:border-bamboo"
                    defaultValue={JSON.stringify(config.agent_extra_args || {})}
                    onBlur={(e) => { try { setCfg("agent_extra_args", JSON.parse(e.target.value)); } catch { notify("额外参数不是合法 JSON"); } }}
                  />
                </label>
              </div>

              <div className="space-y-3">
                <div className="font-serif fs-14 font-normal text-ink-soft">自动续做</div>
                {checkbox("自动补做", "auto_followup")}
                {checkbox("补做前人工确认", "confirm_followup")}
                {checkbox("补做提示词先优化", "optimize_followup")}
                {checkbox("续传指令先优化", "optimize_continue")}
                {field("续传指令模板", "continue_prompt")}
                {field("补做指令模板", "followup_template")}
                {field("结果识别偏好", "analyzer_hints")}
                <div className="font-serif fs-14 font-normal text-ink-soft">自动驾驶默认值</div>
                {field("目标", "autopilot_goal")}
                {field("轮次", "autopilot_rounds", true)}
                {field("时长（分钟）", "autopilot_minutes", true)}
                {checkbox("自动接受补做", "autopilot_auto_accept")}
                <div className="font-serif fs-14 font-normal text-ink-soft">结果解析（OpenAI 兼容）</div>
                {nestedCheckbox("启用语义解析", "analyzer", "enabled")}
                {nestedField("Base URL", "analyzer", "base_url")}
                {nestedField("API Key", "analyzer", "api_key")}
                {nestedField("模型", "analyzer", "model")}
                {nestedField("温度", "analyzer", "temperature")}
                {nestedField("超时（秒）", "analyzer", "timeout", true)}
                <button onClick={testAnalyzer} className="rounded-lg border border-paper-deep px-2 min-h-[28px] py-1 fs-11 text-ink-soft hover:bg-bamboo-mist cursor-pointer">测试连接</button>
                <div className="font-serif fs-14 font-normal text-ink-soft">提示词优化</div>
                <label className="block">
                  <span className="fs-11 text-ink-faint">优化方式</span>
                  <select className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 outline-none focus:border-bamboo" value={config.optimizer?.mode || "auto"} onChange={(e) => setNested("optimizer", "mode", e.target.value)}>
                    {[["auto", "自动"], ["mcp", "仅 MCP"], ["builtin", "仅内置"], ["off", "关闭"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </label>
                {nestedField("MCP 地址", "optimizer", "mcp_url")}
                {nestedField("模板", "optimizer", "template")}
                {nestedField("优化模型 Base URL", "optimizer", "base_url")}
                {nestedField("优化模型 Key", "optimizer", "api_key")}
                {nestedField("优化模型", "optimizer", "model")}
                {nestedCheckbox("使用独立优化模型", "optimizer", "use_optimizer_model")}
                <button onClick={testMcp} className="rounded-lg border border-paper-deep px-2 min-h-[28px] py-1 fs-11 text-ink-soft hover:bg-bamboo-mist cursor-pointer">测试 MCP</button>
              </div>
            </div>
          ) : <div className="mt-4 fs-12 text-ink-faint">正在读取配置…</div>}
        </div>
      )}


      {showAutopilot && (
        <div className="backdrop-in fixed inset-0 z-40 flex justify-end bg-ink/20" onClick={() => setShowAutopilot(false)}>
          <div className="drawer-in flex h-full w-[340px] flex-col overflow-auto border-l border-paper-deep bg-cloud p-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="font-serif fs-15 text-ink-soft">自动驾驶</div>
              <button onClick={() => setShowAutopilot(false)} className="rounded-lg px-2 py-0.5 fs-12 text-ink-faint cursor-pointer">✕</button>
            </div>
            <div className="rounded-lg border border-paper-deep/40 bg-paper p-3">
              <div className="font-serif fs-14 font-normal text-ink-soft">自动驾驶</div>
              <div className="mt-1 fs-11 text-ink-faint">
                {ap.active ? `运行中 · 第 ${ap.rounds_used || 0}/${ap.max_rounds || 0} 轮` : ap.resumable ? `可继续 · ${ap.stop_reason || "已中断"}` : ap.stop_reason ? `已停止 · ${ap.stop_reason}` : "未启动"}
              </div>
              <input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="自动驾驶目标" className="mt-2 w-full rounded-lg border border-paper-deep bg-cloud px-2 min-h-[30px] py-1.5 fs-11 outline-none placeholder:text-ink-faint focus:border-bamboo" />
              <div className="mt-2 flex items-end gap-2">
                <label className="block">
                  <span className="fs-10 text-ink-faint">轮次</span>
                  <input value={rounds} onChange={(e) => setRounds(e.target.value.replace(/[^\d]/g, ""))} className="mt-0.5 w-12 rounded-lg border border-paper-deep bg-cloud px-2 min-h-[28px] py-1 fs-11 outline-none focus:border-bamboo" />
                </label>
                <label className="block">
                  <span className="fs-10 text-ink-faint">分钟</span>
                  <input value={minutes} onChange={(e) => setMinutes(e.target.value.replace(/[^\d]/g, ""))} className="mt-0.5 w-12 rounded-lg border border-paper-deep bg-cloud px-2 min-h-[28px] py-1 fs-11 outline-none focus:border-bamboo" />
                </label>
                <label className="flex items-center gap-1 whitespace-nowrap pb-1 fs-10 text-ink-faint">
                  <input type="checkbox" className="accent-bamboo" checked={autoAccept} onChange={(e) => setAutoAccept(e.target.checked)} />自动
                </label>
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {ap.active ? (
                  <button onClick={() => act("/api/autopilot/stop", { reason: "用户手动停止" }, "自动驾驶已停止")} className="rounded-lg border border-red-300 px-2 min-h-[28px] py-1 fs-11 text-red-400 cursor-pointer">停止</button>
                ) : ap.resumable ? (
                  <button onClick={() => act("/api/autopilot/resume", {}, "自动驾驶已继续")} className="rounded-lg bg-bamboo px-2 min-h-[28px] py-1 fs-11 text-white cursor-pointer">继续</button>
                ) : null}
                <button onClick={() => act("/api/autopilot/start", { goal, rounds: Number(rounds) || 3, minutes: Number(minutes) || 30, auto_accept: autoAccept }, "自动驾驶已启动")} className="rounded-lg bg-bamboo px-2 min-h-[28px] py-1 fs-11 text-white cursor-pointer">启动</button>
                <button onClick={() => act("/api/config", { ...(config || {}), autopilot_goal: goal, autopilot_rounds: Number(rounds) || 3, autopilot_minutes: Number(minutes) || 30, autopilot_auto_accept: autoAccept }, "自动驾驶参数已保存")} className="rounded-lg border border-paper-deep px-2 min-h-[28px] py-1 fs-11 text-ink-soft cursor-pointer">保存参数</button>
              </div>
            </div>

          </div>
        </div>
      )}

      {dialog ? (
        <div className="backdrop-in fixed inset-0 z-50 flex items-center justify-center bg-ink/30" onClick={() => setDialog(null)}>
          <div data-dialog="task" className="modal-in w-[420px] rounded-lg border border-paper-deep bg-cloud p-5 shadow-e5" onClick={(e) => e.stopPropagation()}>
            <div className="font-serif fs-16 text-ink-soft">{dialog.mode === "new" ? "新建任务" : "编辑任务"}</div>
            <div className="mt-3 space-y-2">
              <label className="block">
                <span className="fs-11 text-ink-faint">标题</span>
                <input type="text" autoFocus className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 outline-none focus:border-bamboo" value={draft.title} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} />
              </label>
              <label className="block">
                <span className="fs-11 text-ink-faint">提示词（留空则用标题）</span>
                <textarea rows={4} className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 outline-none focus:border-bamboo" value={draft.prompt} onChange={(e) => setDraft((d) => ({ ...d, prompt: e.target.value }))} />
              </label>
              <label className="block">
                <span className="fs-11 text-ink-faint">Agent</span>
                <select className="mt-1 w-full rounded-lg border border-paper-deep bg-paper px-2 py-1.5 fs-12 outline-none focus:border-bamboo" value={draft.agent} onChange={(e) => setDraft((d) => ({ ...d, agent: e.target.value }))}>
                  {AGENTS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
                </select>
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setDialog(null)} className="rounded-lg border border-paper-deep px-3 py-1.5 fs-12 text-ink-soft cursor-pointer">取消</button>
              <button onClick={submitDialog} className="rounded-lg bg-bamboo px-3 py-1.5 fs-12 text-white cursor-pointer">保存</button>
            </div>
          </div>
        </div>
      ) : null}

      <div data-visible={toast ? "true" : "false"} className="toast pointer-events-none fixed bottom-6 left-1/2 rounded-lg bg-ink px-4 py-2 fs-12 text-paper shadow-e3">{toast}</div>
    </div>
  );
}

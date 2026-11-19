import { createRoot } from "react-dom/client";
import "./App.css";
import "./webui3.css";
import { FinchPanel } from "./components/FinchPanel";

const params = new URLSearchParams(location.search);
// 云母材质只在显式开启时生效，默认界面保持花笺纸张质感。
if (params.get("mica") === "1") {
  document.documentElement.setAttribute("data-mica", "on");
}

const API = "http://127.0.0.1:8766";
const isE2E = params.get("e2e") === "1";
const rawFetch = window.fetch.bind(window);
type Call = { url: string; method: string; body?: any };
const calls: Call[] = [];

// 正式界面不拦截 fetch，避免无谓地累积请求记录；只有 ?e2e=1 才注入探针。
if (isE2E) {
  window.fetch = (async (input: any, init?: any) => {
    const url = typeof input === "string" ? input : String(input?.url ?? "");
    const method = String(init?.method || "GET").toUpperCase();
    if (url.includes("/api/")) {
      let body: any;
      try {
        body = init?.body ? JSON.parse(String(init.body)) : undefined;
      } catch {
        body = undefined;
      }
      calls.push({ url, method, body });
    }
    return rawFetch(input, init);
  }) as typeof window.fetch;
}

createRoot(document.getElementById("root")!).render(<FinchPanel />);

const out = document.getElementById("results")!;
const results: { name: string; ok: boolean; detail: string }[] = [];
const runtimeErrors: string[] = [];
window.addEventListener("error", (event) => runtimeErrors.push(String(event.message)));
window.addEventListener("unhandledrejection", (event) => runtimeErrors.push(String(event.reason)));
const record = (name: string, ok: boolean, detail = "") => {
  results.push({ name, ok, detail });
  out.textContent = "RESULT_JSON:" + JSON.stringify(results);
};
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const qa = (sel: string) => Array.from(document.querySelectorAll(sel)) as HTMLElement[];
const byText = (text: string, sel = "button") =>
  qa(sel).find((e) => (e.textContent || "").trim().includes(text));
const byPlaceholder = (text: string) =>
  qa("input,textarea").find((e) => (e as HTMLInputElement).placeholder?.includes(text)) as
    | HTMLInputElement
    | undefined;
const setValue = (el: HTMLInputElement | HTMLTextAreaElement, value: string) => {
  const proto =
    el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")!.set!;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
};
const click = async (el: HTMLElement | undefined, ms = 600) => {
  if (!el) return false;
  el.click();
  await wait(ms);
  return true;
};
const last = (fragment: string, method?: string) =>
  calls.slice().reverse().find((c) => c.url.includes(fragment) && (!method || c.method === method));
const hadSince = (mark: number, fragment: string, method?: string) =>
  calls.slice(mark).some((c) => c.url.includes(fragment) && (!method || c.method === method));
const api = async (path: string, method = "GET", body?: any) => {
  const r = await rawFetch(API + path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return r.json();
};

async function run() {
  // 让 React 挂载并完成第一次轮询
  await wait(1800);
  (window as any).confirm = () => true;
  let blobCount = 0;
  const origCreate = URL.createObjectURL;
  URL.createObjectURL = ((...args: any[]) => {
    blobCount += 1;
    return (origCreate as any).apply(URL, args);
  }) as any;
  const origAnchorClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () { /* 不真的下载 */ };

  let state: any;
  try {
    state = await api("/api/state");
    record("服务连通 /api/state", Array.isArray(state.tasks), `tasks=${state.tasks?.length}`);
  } catch (e) {
    record("服务连通 /api/state", false, String(e));
    return;
  }
  const originalIds: string[] = state.tasks.map((t: any) => t.id);
  const createdIds: string[] = [];
  const originalConfig = await api("/api/config");

  record("组件挂载（导航可见）", !!byText("工作台", "button"), "");
  record("列表与详情区域已命名", !!document.querySelector('[aria-label="任务列表"]') && !!document.querySelector('[aria-label="任务详情"]'), "");
  const chipRow = document.querySelector('[aria-label="任务列表"] .overflow-x-auto');
  record("筛选 chips 单行横向滚动", !!chipRow && (chipRow.className || "").includes("flex-nowrap"), chipRow?.className || "");
  const firstRow = qa("[data-row]")[0];
  await click(firstRow, 200);
  record("选中项有 aria-current 且写入 URL", firstRow?.getAttribute("aria-current") === "true" && location.search.includes("open="), location.search.slice(0, 90));

  // --- 任务创建 ---
  let mark = calls.length;
  const quick = byPlaceholder("添加任务，回车创建");
  if (quick) {
    setValue(quick, "E2E 快速添加");
    quick.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await wait(800);
  }
  record("快速添加：点击回车发出 POST /api/tasks", hadSince(mark, "/api/tasks", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
  let s = await api("/api/state");
  const quickTask = s.tasks.find((t: any) => t.title === "E2E 快速添加");
  record("快速添加：任务真的入库", !!quickTask, quickTask ? quickTask.id : "未找到");
  if (quickTask) createdIds.push(quickTask.id);

  // --- 选中某个 Agent 时，快速添加必须归属它，而不是掉回默认 claude ---
  const cbChip = qa("button").find((b) => (b.textContent || "").includes("CodeBuddy CLI"));
  if (cbChip && cbChip.getAttribute("aria-pressed") !== "true") await click(cbChip);
  await wait(300);
  mark = calls.length;
  const quickAgain = byPlaceholder("添加任务，回车创建");
  if (quickAgain) {
    setValue(quickAgain, "E2E CodeBuddy 归属");
    quickAgain.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await wait(800);
  }
  const createCall = calls.slice(mark).find((c) => c.url.includes("/api/tasks") && c.method === "POST");
  record("筛选 CodeBuddy 后快速添加带 agent=codebuddy", createCall?.body?.agent === "codebuddy", JSON.stringify(createCall?.body || {}));
  s = await api("/api/state");
  const owned = s.tasks.find((t: any) => t.title === "E2E CodeBuddy 归属");
  record("新建任务真的归属 CodeBuddy", owned?.agent === "codebuddy", owned?.agent || "missing");
  if (owned) createdIds.push(owned.id);
  const cbAgain = qa("button").find((b) => (b.textContent || "").includes("CodeBuddy CLI"));
  if (cbAgain?.getAttribute("aria-pressed") === "true") await click(cbAgain);

  mark = calls.length;
  await click(byText("详细"));
  const dialog = qa("[data-dialog]")[0];
  record("详细新建：对话框可打开", !!dialog, "");
  const titleInput = qa("[data-dialog] input")[0] as HTMLInputElement | undefined;
  const textarea = qa("[data-dialog] textarea")[0] as HTMLTextAreaElement | undefined;
  if (titleInput) setValue(titleInput, "E2E 详细新建");
  if (textarea) setValue(textarea, "验证提示词");
  await wait(250);
  const dialogSave = qa("[data-dialog] button").find((b) => (b.textContent || "").trim() === "保存");
  await click(dialogSave);
  record("详细新建：对话框提交 POST /api/tasks", hadSince(mark, "/api/tasks", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
  s = await api("/api/state");
  const detailed = s.tasks.find((t: any) => t.title === "E2E 详细新建");
  record("详细新建：标题与提示词入库", !!detailed && detailed.prompt === "验证提示词", detailed ? `${detailed.title}/${detailed.prompt}` : "未找到");
  if (detailed) createdIds.push(detailed.id);

  // --- 勾选完成 ---
  mark = calls.length;
  const check = qa('button[title="标记完成"]')[0];
  const checkRowId = check?.closest("[data-row]")?.getAttribute("data-row") || "";
  const beforeToggle = (await api("/api/state")).tasks.find((t: any) => t.id === checkRowId)?.status || "";
  await click(check);
  record("勾选完成：发出 toggle", hadSince(mark, "/toggle", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
  s = await api("/api/state");
  const toggled = s.tasks.find((t: any) => t.id === checkRowId);
  record("勾选完成：状态真的变化", !!toggled && toggled.status !== beforeToggle, `${beforeToggle} → ${toggled?.status}`);

  // --- ⋯ 菜单：重新排队 ---
  mark = calls.length;
  await click(qa('button[title="更多操作"]')[0], 300);
  const menu = byText("重新排队");
  record("⋯ 菜单可展开", !!menu, "");
  await click(menu);
  record("重新排队：发出 status 请求", hadSince(mark, "/status", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));

  // --- 搜索 ---
  const search = byPlaceholder("搜索任务");
  if (search) {
    setValue(search, "清单");
    await wait(400);
    const rows = qa("[data-row]");
    record("搜索：列表被过滤", rows.length > 0 && rows.every((r) => (r.textContent || "").includes("清单")), `rows=${rows.length}`);
    setValue(search, "");
    await wait(300);
  } else {
    record("搜索：列表被过滤", false, "搜索框不存在");
  }

  // --- 看板 / 清单切换 ---
  await click(byText("看板"));
  record("看板：出现列", !!byText("待执行", "div") && !!byText("已完成", "div"), "");
  const boardCard = qa('[draggable="true"]')[0];
  record("看板：任务卡可拖拽", !!boardCard, "");
  await click(byText("清单"));
  record("清单：任务卡回来", qa("[data-row]").length > 0, `rows=${qa("[data-row]").length}`);

  // --- Agent 筛选 ---
  const agentBtn = qa("button").find((b) => (b.textContent || "").includes("Claude Code"));
  await click(agentBtn);
  record("Agent 筛选：按钮进入选中态", !!agentBtn?.className.includes("bg-bamboo"), agentBtn?.className.slice(0, 80) || "");
  await click(agentBtn);

  // --- 详情标签 ---
  const detailBox = document.querySelector('[aria-label="任务详情"]');
  const detailPres = detailBox?.querySelectorAll("pre").length || 0;
  record("详情：默认只显示结果", (document.body.textContent || "").includes("最终结果") && detailPres === 0, `pre=${detailPres}`);
  mark = calls.length;
  await click(byText("过程"));
  await click(byText("对话记录"));
  record("详情：过程里可切到对话记录", qa("button").some((b) => b.className.includes("border-b-2") && (b.textContent || "").includes("对话记录")), "");
  record("对话记录：发出 /conversation", hadSince(mark, "/conversation", "GET"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
  record("对话记录：显示 CLI 会话来源", (document.body.textContent || "").includes("Agent CLI 原始会话"), "");
  await click(byText("结果"));

  await click(byText("过程"));
  await click(byText("执行轮次"));
  record("详情：执行轮次标签可切", qa("button").some((b) => b.className.includes("border-b-2") && (b.textContent || "").includes("执行轮次")), "");
  await click(byText("完整日志"));
  record("详情：完整日志显示 pre", qa("pre").length > 0, `pre=${qa("pre").length}`);
  await click(byText("结果"));

  // --- 队列控制四个按钮 ---
  for (const [label, fragment] of [
    ["开始队列", "/api/queue/start"], ["终止", "/api/queue/stop"],
    ["跳过续传", "/api/queue/skip-retry"], ["强制下一条", "/api/queue/force-next"],
  ] as [string, string][]) {
    mark = calls.length;
    if (label !== "开始队列") {
      await click(byText("更多"), 200);
    }
    await click(byText(label));
    record(`队列控制「${label}」发出请求`, hadSince(mark, fragment, "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
  }

  // --- 暂停队列按钮真的调用 pause（临时让状态轮询返回 running） ---
  const outerFetch = window.fetch;
  window.fetch = (async (input: any, init?: any) => {
    const url = typeof input === "string" ? input : String(input?.url ?? "");
    const response = await outerFetch(input, init);
    if (url.includes("/api/state") && (!init || String(init.method || "GET").toUpperCase() === "GET")) {
      try {
        const data = await response.clone().json();
        return new Response(
          JSON.stringify({ ...data, engine: { state: "running", active: "" } }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      } catch {
        return response;
      }
    }
    return response;
  }) as typeof window.fetch;
  await wait(3000);
  const pauseBtn = byText("暂停队列");
  record("引擎运行中显示「暂停队列」", !!pauseBtn, "");
  mark = calls.length;
  await click(pauseBtn);
  record("暂停队列真的发出 /api/queue/pause", hadSince(mark, "/api/queue/pause", "POST"),
    JSON.stringify(calls.slice(mark).map((c) => c.url)));
  window.fetch = outerFetch;
  await wait(2800);

  // --- 自动驾驶（参数已收进抽屉） ---
  await click(byText("自动驾驶"), 300);
  record("自动驾驶抽屉可打开", !!byPlaceholder("自动驾驶目标"), "");
  const goalInput = byPlaceholder("自动驾驶目标");
  if (goalInput) setValue(goalInput, "E2E 自动驾驶");
  mark = calls.length;
  await click(byText("启动"));
  record("自动驾驶启动：发出请求", hadSince(mark, "/api/autopilot/start", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
  let ap = await api("/api/autopilot");
  record("自动驾驶启动：引擎真的 active", ap.active === true, JSON.stringify(ap).slice(0, 160));
  mark = calls.length;
  await click(byText("停止"));
  ap = await api("/api/autopilot");
  record("自动驾驶停止：引擎真的停下", hadSince(mark, "/api/autopilot/stop", "POST") && ap.active === false, JSON.stringify(ap).slice(0, 160));

  // --- 保存参数 ---
  mark = calls.length;
  await click(byText("保存参数"));
  record("保存参数：发出 /api/config", hadSince(mark, "/api/config", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
  await click(byText("✕"), 200);
  record("自动驾驶抽屉可关闭", !byPlaceholder("自动驾驶目标"), "");

  // --- 主题切换 ---
  const before = document.documentElement.dataset.theme;
  await click(byText("深色"));
  const after = document.documentElement.dataset.theme;
  record("主题切换：data-theme 改变", before !== after, `${before} → ${after}`);
  await click(byText("浅色"));

  // --- 决策卡（造一个 attention 任务） ---
  const targetId = createdIds[0] || "";
  if (targetId) {
    await api(`/api/tasks/${targetId}/status`, "POST", { status: "attention" });
    await wait(3100);
    const decision = byText("需要决定", "div");
    record("决策卡：待人工任务出现在流水线", !!decision, "");
    mark = calls.length;
    await click(byText("跳过补做"));
    record("决策卡：跳过补做发出 followup", hadSince(mark, "/followup", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
    const afterSkip = await api("/api/state");
    const skippedRow = afterSkip.tasks.find((t: any) => t.id === targetId);
    record("决策卡：跳过补做真的置为完成", skippedRow?.status === "done", skippedRow?.status);
    // 决策生效后卡片会消失，重新造一个待决定任务再验证重试
    await api(`/api/tasks/${targetId}/status`, "POST", { status: "attention" });
    await wait(3100);
    mark = calls.length;
    await click(byText("重试本轮"));
    record("决策卡：重试本轮发出 retry", hadSince(mark, "/retry", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
    await api("/api/queue/stop", "POST", {});
    await api(`/api/tasks/${targetId}/status`, "POST", { status: "done" });
  }

  // --- 详情头部重试：先选中测试自己创建的任务，避免清空原有任务的摘要 ---
  await click(byText("工作台", "button"));
  await wait(400);
  const testRow = qa("[data-row]").find((r) => (r.textContent || "").includes("E2E 详细新建"));
  await click(testRow, 300);
  mark = calls.length;
  const exactRetry = qa("button").find((b) => (b.textContent || "").trim() === "重试");
  await click(exactRetry);
  record("详情头部「重试」发出请求", hadSince(mark, "/retry", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));

  // --- 执行记录页 ---
  await click(byText("执行记录", "button"));
  record("执行记录页：渲染标题", !!byText("轮真实执行", "span"), "");
  const histSearch = byPlaceholder("搜索任务");
  if (histSearch) setValue(histSearch, "不存在的任务名XYZ");
  await wait(300);
  await click(byText("已完成", "button"));
  record("执行记录：筛选按钮可点", !!byText("全部", "button"), "");
  mark = blobCount;
  await click(byText("导出 CSV"));
  record("执行记录：导出 CSV 真的生成文件", blobCount > mark, `blobs=${blobCount}`);

  // --- 设置页 ---
  await click(byText("设置", "button"));
  await wait(800);
  const cfgInputs = qa("input,textarea,select");
  record("设置页：渲染真实配置表单", cfgInputs.length > 10, `fields=${cfgInputs.length}`);
  mark = calls.length;
  await click(byText("保存设置"));
  record("设置页：保存发出 /api/config", hadSince(mark, "/api/config", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
  await click(byText("测试连接"));
  await click(byText("测试 MCP"));
  record("设置页：测试连接/MCP 发出请求", !!last("/api/test-analyzer") && !!last("/api/test-mcp"), "");

  // --- 字号配置：切换即时落库并改变实际字号 ---
  const fontLabel = qa("label").find((l) => (l.textContent || "").includes("字号（即时生效并保存）"));
  const fontSelect = fontLabel?.querySelector("select") as HTMLSelectElement | undefined;
  record("设置页有字号配置", !!fontSelect, "");
  if (fontSelect) {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!;
    const apply = async (value: string) => {
      setter.call(fontSelect, value);
      fontSelect.dispatchEvent(new Event("change", { bubbles: true }));
      await wait(500);
    };
    mark = calls.length;
    await apply("1.35");
    record("切换字号即时保存", hadSince(mark, "/api/config", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));
    const cfgNow = await api("/api/config");
    record("字号配置真的落库", Math.abs(Number(cfgNow.ui_font_scale) - 1.35) < 1e-6, cfgNow.ui_font_scale);
    const sample = qa("span").find((e) => (e.className || "").includes("fs-10"));
    const computed = sample ? getComputedStyle(sample).fontSize : "";
    record("界面字号随配置变化", Math.abs(parseFloat(computed) - 13.5) < 0.8, computed);
    await apply("1.2");
  }

  // --- 删除任务：只删测试自己创建的专用任务 ---
  await click(byText("工作台", "button"));
  await wait(500);
  const disposable = await api("/api/tasks", "POST", { title: "E2E 删除专用", prompt: "临时", agent: "mock" });
  createdIds.push(disposable.id);
  await wait(2900);
  const targetRow = qa("[data-row]").find((r) => (r.textContent || "").includes("E2E 删除专用"));
  mark = calls.length;
  const menuBtn = targetRow?.querySelector('button[title="更多操作"]') as HTMLElement | undefined;
  await click(menuBtn, 300);
  await click(byText("删除"));
  record("删除：发出 DELETE", hadSince(mark, "/api/tasks/", "DELETE"), JSON.stringify(calls.slice(mark).map((c) => `${c.method} ${c.url}`)));
  await wait(400);
  s = await api("/api/state");
  record("删除：任务真的从库中消失", !s.tasks.some((t: any) => t.id === disposable.id), `id=${disposable.id}`);

  // --- 拖动排序 ---
  mark = calls.length;
  const grips = qa('[title="拖动排序"]');
  const rows = qa("[data-row]");
  if (grips.length && rows.length > 1) {
    const y0 = grips[0].getBoundingClientRect().y;
    const y1 = rows[rows.length - 1].getBoundingClientRect().y;
    grips[0].dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, clientX: 100, clientY: y0 }));
    document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: 100, clientY: y1 }));
    await wait(700);
  }
  record("拖动排序：发出 /api/order", hadSince(mark, "/api/order", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));

  // --- 整卡拖动 + 禁止文本拖选 ---
  const dragRow = qa("[data-row]")[0] as HTMLElement | undefined;
  const dragRows = qa("[data-row]") as HTMLElement[];
  const dragTop = dragRow?.getBoundingClientRect().y ?? 0;
  const dragBottom = (dragRows[dragRows.length - 1]?.getBoundingClientRect().y ?? dragTop) + 8;
  record("任务卡整块不可文本拖选", !!dragRow && getComputedStyle(dragRow).userSelect === "none", dragRow ? getComputedStyle(dragRow).userSelect : "no row");
  mark = calls.length;
  if (dragRow) {
    dragRow.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, clientX: 200, clientY: dragTop + 4 }));
    document.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, clientX: 200, clientY: dragTop + 44 }));
    const moving = document.querySelector('[data-row][data-dragging="true"]') as HTMLElement | null;
    const dragTransform = moving?.style.transform || "";
    record("拖动时卡片跟手有动画", dragTransform.includes("translateY") && !dragTransform.includes("scale"), dragTransform);
    record("拖动不放大卡片（避免左右边框被裁）", !dragTransform.includes("scale"), dragTransform);
    const gutter = document.querySelector(".gutter-stable") as HTMLElement | null;
    const listBox = document.querySelector(".gutter-stable.overflow-x-hidden") as HTMLElement | null;
    const gutterStyle = gutter ? getComputedStyle(gutter) : null;
    record("滚动条槽位固定（出现时不推布局）", gutterStyle?.scrollbarGutter === "stable", gutterStyle?.scrollbarGutter || "none");
    record("列表容器禁止横向滚动条", !!listBox && getComputedStyle(listBox).overflowX === "hidden", listBox ? getComputedStyle(listBox).overflowX : "no container");
    document.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, clientX: 200, clientY: dragBottom }));
    await wait(700);
  }
  record("拖动卡片主体也能排序", hadSince(mark, "/api/order", "POST"), JSON.stringify(calls.slice(mark).map((c) => c.url)));

  // --- 清理：删除测试任务、恢复顺序与配置 ---
  s = await api("/api/state");
  const finalIds: string[] = s.tasks.map((t: any) => t.id);
  for (const id of createdIds) {
    if (finalIds.includes(id)) await api(`/api/tasks/${id}`, "DELETE");
  }
  if (checkRowId && beforeToggle) {
    await api(`/api/tasks/${checkRowId}/status`, "POST", { status: beforeToggle });
  }
  await api("/api/autopilot/stop", "POST", { reason: "E2E 清理" });
  await api("/api/order", "POST", { ids: originalIds });
  await api("/api/config", "POST", {
    autopilot_goal: originalConfig.autopilot_goal || "",
    autopilot_rounds: originalConfig.autopilot_rounds ?? 3,
    autopilot_minutes: originalConfig.autopilot_minutes ?? 30,
    autopilot_auto_accept: !!originalConfig.autopilot_auto_accept,
  });
  await api("/api/queue/stop", "POST", {});
  const clean = await api("/api/state");
  const sameIds = clean.tasks.map((t: any) => t.id).sort().join(",") === originalIds.slice().sort().join(",");
  record("测试后数据还原（ID 与状态）", sameIds && clean.tasks.length === originalIds.length,
    `before=${originalIds.length} after=${clean.tasks.length} ids=${sameIds}`);

  URL.createObjectURL = origCreate;
  HTMLAnchorElement.prototype.click = origAnchorClick;
  record("运行期间无 JS 异常", runtimeErrors.length === 0, runtimeErrors.join(" | ").slice(0, 300));
  const summary = results.length;
  const passed = results.filter((r) => r.ok).length;
  record(`=== ${passed}/${summary} 通过 ===`, passed === summary, "");
}

// 正式界面只渲染组件；带 ?e2e=1 时才执行回归测试。
if (isE2E) {
  run().catch((e) => {
    record("测试脚本异常", false, String(e?.stack || e));
  });
}

// 仅供人工核对：加载后自动切到「对话记录」，方便 headless 截图。
if (params.get("chatshot") === "1") {
  setTimeout(() => {
    const btn = Array.from(document.querySelectorAll("button")).find((b) => (b.textContent || "").trim() === "对话记录");
    btn?.click();
  }, 2500);
}

// 仅供人工核对拖动视觉：按下并移动但不松开，方便 headless 截图。
if (params.get("dragshot") === "1") {
  setTimeout(() => {
    const rows = Array.from(document.querySelectorAll<HTMLElement>("[data-row]"));
    const row = rows[1] || rows[0];
    if (!row) return;
    const y = row.getBoundingClientRect().top + 10;
    row.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, clientX: 200, clientY: y }));
    document.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, clientX: 200, clientY: y + 60 }));
  }, 2500);
}

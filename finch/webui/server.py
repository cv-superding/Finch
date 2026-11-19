"""Finch Web UI 的服务端：静态页面 + 本地 JSON API，复用现有 Store / QueueEngine。"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
SETTINGS = ROOT / "settings.html"
AGENTS_DIR = ROOT.parent / "ui" / "assets" / "agents"
DIST_DIR = ROOT / "dist"
FLORAL_DIR = ROOT / "floral-dist"

_LOCK = threading.RLock()
_STORE = None
_CONFIG = None
_ENGINE = None
_HTTPD = None


def _boot():
    global _STORE, _CONFIG, _ENGINE
    if _STORE is None:
        from ..core.engine import QueueEngine
        from ..store import Store

        _STORE = Store()
        _CONFIG = _STORE.load_config()
        _STORE.recover_stale_tasks()
        _ENGINE = QueueEngine(_STORE, _CONFIG)
    return _STORE, _CONFIG, _ENGINE


def _task_json(task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "agent": task.agent or "",
        "cwd": task.cwd or "",
        "session_id": task.session_id or "",
        "status": task.status,
        "progress": task.progress or "",
        "tools": int(task.tool_count or 0),
        "resume": int(task.resume_count or 0),
        "followup": int(task.followup_count or 0),
        "seconds": int(task.duration or 0),
        "summary": task.summary or "",
        "completed": list(task.completed or []),
        "pending": list(task.pending or []),
        "issues": list(task.issues or []),
        "attention": task.attention_reason or "",
        "prompt": task.prompt or "",
        "attention_reason": task.attention_reason or "",
        "followup_prompt": task.followup_prompt or "",
        "pending_action": task.pending_action or "",
    }


def _read_log(log_path: str | None, limit: int = 400) -> list[str]:
    if not log_path:
        return []
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def _state() -> dict:
    store, config, engine = _boot()
    with _LOCK:
        tasks = store.list_tasks()
        payload = []
        for task in tasks:
            data = _task_json(task)
            runs = store.list_runs(task.id)
            data["runs"] = len(runs)
            payload.append(data)
        return {
            "tasks": payload,
            "engine": {
                "state": engine.state,
                "active": engine.active_task_id or "",
            },
            "config": {
                "agent": config.agent,
                "cwd": config.cwd or "",
            },
        }


def _task_conversation(task_id: str) -> dict:
    """读取 Agent CLI 落盘的完整会话，让 Finch 展示原始对话，而不是只有摘要。"""
    import json
    from pathlib import Path

    store, _, _ = _boot()
    task = store.get_task(task_id)
    if task is None:
        raise KeyError(task_id)

    session_id = (task.session_id or "").strip()
    roots = [Path.home() / ".codebuddy" / "projects",
             Path.home() / ".claude" / "projects"]
    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        if session_id:
            candidates += list(root.glob(f"*/{session_id}.jsonl"))
        # 沙箱目录名里带 task id，即使没记下 session id 也能定位
        for d in root.iterdir():
            if d.is_dir() and task_id in d.name:
                candidates += list(d.glob("*.jsonl"))

    seen: set[str] = set()
    files = []
    for c in candidates:
        key = str(c)
        if key not in seen and c.is_file():
            seen.add(key)
            files.append(c)
    files.sort(key=lambda f: (f.stat().st_size, f.stat().st_mtime), reverse=True)
    chosen = files[0] if files else None

    def text_of(value) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or item.get("name") or ""))
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(p for p in parts if p)
        if isinstance(value, dict):
            return str(value.get("text") or value.get("content") or "")
        return ""

    messages: list[dict] = []
    if chosen:
        for line in chosen.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            typ = obj.get("type") or ""
            role = obj.get("role") or ""
            ts = obj.get("timestamp") or 0
            if not session_id and obj.get("sessionId"):
                session_id = str(obj["sessionId"])
            if typ == "message" and role in ("user", "assistant"):
                text = text_of(obj.get("content"))
                if text.strip():
                    messages.append({"role": role, "text": text[:6000], "ts": ts})
            elif typ == "reasoning":
                text = text_of(obj.get("rawContent") or obj.get("content"))
                if text.strip():
                    messages.append({"role": "thinking", "text": text[:2000], "ts": ts})
            elif typ == "function_call":
                name = str(obj.get("name") or "tool")
                args = obj.get("arguments")
                detail = json.dumps(args, ensure_ascii=False)[:300] if args else ""
                messages.append({"role": "tool", "text": f"{name} {detail}".strip(), "ts": ts})
            elif typ == "function_call_result":
                out = obj.get("output")
                text = out if isinstance(out, str) else text_of(out)
                messages.append({"role": "tool_result", "text": (text or "")[:500], "ts": ts})

    return {
        "messages": messages,
        "session_id": session_id,
        "source": str(chosen) if chosen else "",
        "count": len(messages),
    }


def _create_task(payload: dict) -> dict:
    from ..models import Task

    store, config, _ = _boot()
    title = (payload.get("title") or "").strip()
    if not title:
        raise ValueError("任务标题不能为空")
    prompt = (payload.get("prompt") or "").strip() or title
    from ..agents import ADAPTER_KEYS

    # 明确传了非法 Agent 时报错，而不是悄悄换成别的；没传才用默认 Agent。
    raw_agent = (payload.get("agent") or "").strip()
    agent = raw_agent or config.agent
    if agent not in ADAPTER_KEYS:
        raise ValueError(f"未知 Agent: {agent}")
    task = Task(
        title=title,
        prompt=prompt,
        agent=agent,
        cwd=config.cwd,
    )
    with _LOCK:
        store.add_task(task)
    return _task_json(task)


def _toggle_task(task_id: str) -> dict:
    store, _, _ = _boot()
    with _LOCK:
        task = store.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status == "done":
            task.status = "queued"
            task.summary = ""
            task.ended_at = 0
        else:
            task.status = "done"
            task.summary = task.summary or "手动标记完成"
        store.save_task(task)
    return _task_json(task)


def _set_status(task_id: str, status: str) -> dict:
    from ..models import TaskStatus

    # 运行中/工具中/续传中等状态由引擎维护；界面手动伪造会让任务
    # 永远显示「执行中」却没有真实进程。
    user_settable = {"queued", "done", "attention", "interrupted", "failed"}
    if status not in user_settable:
        raise ValueError("该状态由引擎控制或非法: %s" % status)
    store, _, _ = _boot()
    with _LOCK:
        task = store.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        task.status = status
        if status == "queued":
            task.summary = ""
        store.save_task(task)
    return _task_json(task)


def _reorder(ids: list[str]) -> None:
    """按前端给的顺序重排；前端漏传的任务补在末尾，避免丢任务。"""
    store, _, _ = _boot()
    with _LOCK:
        existing = [task.id for task in store.list_tasks()]
        ordered = [str(i) for i in ids if str(i) in existing]
        seen = set(ordered)
        ordered += [task_id for task_id in existing if task_id not in seen]
        if ordered:
            store.reorder_tasks(ordered)


def _control(action: str, payload: dict) -> dict:
    store, _, engine = _boot()
    if action == "start":
        task_id = payload.get("task_id") or ""
        if task_id:
            ids = [task.id for task in store.list_tasks()]
            if task_id in ids:
                ids.remove(task_id)
                ids.insert(0, task_id)
                with _LOCK:
                    store.reorder_tasks(ids)
        engine.start()
    elif action == "pause":
        engine.pause()
    elif action == "stop":
        engine.stop()
    elif action == "skip-retry":
        engine.skip_retry()
    elif action == "force-next":
        engine.force_next()
    else:
        raise ValueError(f"未知操作: {action}")
    return {"state": engine.state, "active": engine.active_task_id or ""}


# ---------------------------------------------------------------- 引擎高级动作
def _autopilot_action(action: str, payload: dict) -> dict:
    _, _, engine = _boot()
    if action == "start":
        goal = (payload.get("goal") or "").strip()
        if not goal:
            raise ValueError("自动驾驶目标不能为空")
        engine.start_autopilot(
            goal,
            max(1, int(payload.get("rounds") or 3)),
            max(0, int(payload.get("minutes") or 30)),
            bool(payload.get("auto_accept")),
        )
    elif action == "stop":
        engine.stop_autopilot(payload.get("reason") or "用户手动停止")
    elif action == "resume":
        if not getattr(engine, "autopilot_resumable", False):
            raise ValueError("当前没有可继续的自动驾驶")
        engine.resume_autopilot()
    else:
        raise ValueError(f"未知操作: {action}")
    return engine.autopilot_state()


def _require_task(task_id: str) -> None:
    store, _, _ = _boot()
    if store.get_task(task_id) is None:
        raise KeyError(task_id)


def _decide_followup(task_id: str, payload: dict) -> dict:
    _require_task(task_id)
    store, _, engine = _boot()
    decision = payload.get("decision") or "skip"
    if decision not in {"approve", "skip", "force_next"}:
        raise ValueError("无效的决策")
    task = store.get_task(task_id)
    live = task_id in getattr(engine, "_decision_events", {})
    if not live and task.status not in ("awaiting", "attention") and task.pending_action != "followup":
        raise ValueError("该任务当前不在等待人工决策")
    if decision == "approve":
        prompt = (payload.get("prompt") or "").strip() or (task.followup_prompt or "").strip()
        if not prompt:
            raise ValueError("补做指令不能为空")
        if not live and not task.session_id:
            raise ValueError("会话 ID 丢失，无法补做；请先重试本轮")
    engine.resolve_followup(task_id, decision, payload.get("prompt") or "")
    return {"ok": True, "task_id": task_id, "decision": decision}


def _retry_task(task_id: str, payload: dict) -> dict:
    _require_task(task_id)
    _, _, engine = _boot()
    if engine.active_task_id == task_id:
        raise ValueError("任务正在执行，无法重置")
    engine.retry_task(task_id, bool(payload.get("autostart", True)))
    return {"ok": True, "task_id": task_id}


def _edit_task(task_id: str, payload: dict) -> dict:
    store, _, _ = _boot()
    with _LOCK:
        task = store.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        title = (payload.get("title") or "").strip()
        prompt = (payload.get("prompt") or "").strip()
        agent = (payload.get("agent") or "").strip()
        if title:
            task.title = title
        if prompt:
            task.prompt = prompt
        if agent:
            task.agent = agent
        store.save_task(task)
    return _task_json(task)


# ---------------------------------------------------------------- config API
SCALARS = {
    "agent": str,
    "cwd": str,
    "permission_mode": str,
    "isolate_mcp": bool,
    "text_idle_timeout": int,
    "first_output_grace": int,
    "tool_timeout": int,
    "max_resumes": int,
    "max_followups": int,
    "auto_followup": bool,
    "confirm_followup": bool,
    "optimize_followup": bool,
    "optimize_continue": bool,
    "continue_prompt": str,
    "followup_template": str,
    "analyzer_hints": str,
    "autopilot_goal": str,
    "autopilot_rounds": int,
    "autopilot_minutes": int,
    "autopilot_auto_accept": bool,
    "ui_font_scale": float,
}
NESTED = ("analyzer", "optimizer")


def _config_json() -> dict:
    store, cfg, engine = _boot()
    from dataclasses import asdict

    from ..config import data_dir

    payload = {name: getattr(cfg, name) for name in SCALARS}
    payload["agent_paths"] = dict(cfg.agent_paths or {})
    payload["agent_extra_args"] = dict(cfg.agent_extra_args or {})
    for name in NESTED:
        payload[name] = asdict(getattr(cfg, name))
    payload["data_dir"] = str(data_dir())
    payload["engine"] = {"state": engine.state, "active": engine.active_task_id or ""}
    return payload


def _save_config(payload: dict) -> dict:
    store, cfg, engine = _boot()
    with _LOCK:
        for name, caster in SCALARS.items():
            if name not in payload:
                continue
            value = payload[name]
            try:
                setattr(cfg, name, caster(value))
            except (TypeError, ValueError):
                continue
        paths = payload.get("agent_paths")
        if isinstance(paths, dict):
            clean = {str(k): str(v) for k, v in paths.items() if str(v).strip()}
            cfg.agent_paths = clean
        extra = payload.get("agent_extra_args")
        if isinstance(extra, dict):
            cfg.agent_extra_args = {str(k): str(v) for k, v in extra.items() if str(v).strip()}
        for name in NESTED:
            data = payload.get(name)
            block = getattr(cfg, name)
            if not isinstance(data, dict):
                continue
            for key, value in data.items():
                if not hasattr(block, key):
                    continue
                current = getattr(block, key)
                try:
                    if isinstance(current, bool):
                        setattr(block, key, bool(value))
                    elif isinstance(current, int):
                        setattr(block, key, int(value))
                    elif isinstance(current, float) or key == "temperature":
                        # 历史数据可能把浮点字段存成了字符串；按字段名兜底，
                        # 否则会一直沿用 str 分支，0.2 永远变不回 float。
                        setattr(block, key, float(value))
                    else:
                        setattr(block, key, str(value))
                except (TypeError, ValueError):
                    continue
        store.save_config(cfg)
        engine.update_config(cfg)
    return _config_json()


def _agents_json() -> dict:
    """轻量探测：只查可执行文件是否存在，不跑 --version（避免页面加载卡 12s）。"""
    import shutil
    from pathlib import Path

    from ..agents import ADAPTER_CLASSES

    store, cfg, _ = _boot()
    result = {}
    for cls in ADAPTER_CLASSES:
        try:
            path = cls(cfg).find_executable()
            exists = bool(path) and (Path(path).exists() or bool(shutil.which(path)))
        except Exception:
            path, exists = "", False
        result[cls.key] = {
            "label": cls.label,
            "path": path if exists else "",
            "found": exists,
        }
    return result


def _pick_dir(start: str = "") -> dict:
    """用独立子进程弹系统目录选择框，避免在 HTTP 线程里碰 Tk 的主循环。"""
    import subprocess
    import sys

    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        "print(filedialog.askdirectory(initialdir=%r) or '')\n"
    ) % (start or "")
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("无法打开目录选择框: %s" % exc)
    path = (proc.stdout or "").strip().splitlines()
    return {"path": path[-1] if path else ""}


def _open_dir(path: str = "", task_id: str = "") -> dict:
    import os
    import subprocess
    import sys

    from ..config import workspaces_dir

    target = (path or "").strip()
    if not target and task_id:
        target = str(workspaces_dir() / task_id)
    if not target or not os.path.isdir(target):
        raise ValueError("目录不存在: %s" % (target or "(空)"))
    if os.name == "nt":
        os.startfile(target)  # noqa: S606 - 打开资源管理器
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", target])
    return {"ok": True, "path": target}


def _test_analyzer(payload: dict) -> dict:
    """复用 core.llm.test_llm，和桌面版同一个实现。"""
    from ..config import LLMConfig
    from ..core.llm import test_llm

    cfg = LLMConfig(
        enabled=True,
        base_url=(payload.get("base_url") or "").strip(),
        api_key=(payload.get("api_key") or "").strip(),
        model=(payload.get("model") or "").strip(),
    )
    if not cfg.base_url or not cfg.model:
        return {"ok": False, "detail": "请先填写 Base URL 与模型"}
    ok, detail = test_llm(cfg)
    return {"ok": bool(ok), "detail": str(detail)[:300]}


def _test_mcp(payload: dict) -> dict:
    """复用 core.optimizer.MCPClient，验证 initialize + tools/list。"""
    from ..core.optimizer import MCPClient

    url = (payload.get("mcp_url") or "").strip()
    if not url:
        return {"ok": False, "detail": "请先填写 MCP 地址"}
    try:
        client = MCPClient(url, timeout=12)
        client.initialize()
        tools = client.list_tools()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": "%s: %s" % (exc.__class__.__name__, str(exc)[:200])}
    names = [item.get("name", "") for item in tools if isinstance(item, dict)]
    useful = [name for name in names if name.startswith("optimize")]
    if useful:
        return {"ok": True, "detail": "已连接，可用工具：" + ", ".join(useful[:4])}
    return {"ok": True, "detail": "服务可达，但未发现 optimize-* 工具（共 %d 个）" % len(names)}


def _history_json(limit: int = 200) -> dict:
    """执行记录：直接读 store 里真实落盘的 run，不拼凑。"""
    store, _, _ = _boot()
    tasks = {task.id: task for task in store.list_tasks()}
    rows = []
    for run in store.list_recent_runs(limit):
        task = tasks.get(run.task_id)
        ended = run.ended_at or 0
        started = run.started_at or 0
        rows.append(
            {
                "id": run.id,
                "task_id": run.task_id,
                "title": (task.title if task else "(任务已删除)"),
                "agent": (task.agent if task else ""),
                "kind": run.kind or "",
                "round": int(run.round or 0),
                "tools": int(run.tool_count or 0),
                "status": run.status or "",
                "exit": run.exit_code,
                "started": started,
                "ended": ended,
                "duration": max(0, int(ended - started)) if ended and started else 0,
            }
        )
    return {"rows": rows, "total": len(rows)}


def _task_runs(task_id: str) -> dict:
    store, _, _ = _boot()
    if store.get_task(task_id) is None:
        raise KeyError(task_id)
    rows = []
    for run in store.list_runs(task_id):
        started = run.started_at or 0
        ended = run.ended_at or 0
        rows.append(
            {
                "round": int(run.round or 0),
                "kind": run.kind or "",
                "status": run.status or "",
                "started": started,
                "ended": ended,
                "duration": max(0, int(ended - started)) if started and ended else 0,
                "tools": int(run.tool_count or 0),
                "exit": run.exit_code,
            }
        )
    return {"rows": rows}


class Handler(BaseHTTPRequestHandler):
    server_version = "FinchWeb/1.0"

    def log_message(self, *args) -> None:  # quiet
        pass

    def do_OPTIONS(self) -> None:
        """Tauri WebView 的跨域预检。"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- helpers --
    def _send(self, payload, code: int = 200, ctype: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8", "replace") or "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            # 静默当空对象会让「保存成功」的提示变成假的。
            raise ValueError(f"请求体不是合法 JSON: {exc.msg}") from exc

    # -- routes --
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        dist_index = DIST_DIR / "index.html"
        standalone_index = DIST_DIR / "standalone" / "finch-test.html"
        if path in ("/", "/index.html", "/settings", "/settings.html"):
            # 所有壳（浏览器 / pywebview / Tauri）都打开同一套可用的 Finch 界面。
            page = (
                standalone_index
                if standalone_index.is_file()
                else dist_index
                if dist_index.exists()
                else (SETTINGS if path.startswith("/settings") else INDEX)
            )
            ctype = "text/html; charset=utf-8"
            self._send(page.read_bytes(), ctype=ctype)
            return
        if path in ("/webui3", "/webui3/", "/webui3/index.html"):
            page = DIST_DIR / "webui3" / "webui3.html"
            if page.is_file():
                self._send(page.read_bytes(), ctype="text/html; charset=utf-8")
            else:
                self._send({"error": "webui3 not built"}, 404)
            return
        if path.startswith("/standalone/assets/") or path.startswith("/webui3/assets/"):
            sub = "webui3" if path.startswith("/webui3/") else "standalone"
            target = (DIST_DIR / sub / path[len("/" + sub + "/"):]).resolve()
            base = (DIST_DIR / sub).resolve()
            if base not in target.parents or not target.is_file():
                self._send({"error": "not found"}, 404)
                return
            ctype = {
                "js": "text/javascript; charset=utf-8",
                "css": "text/css; charset=utf-8",
                "ttf": "font/ttf",
                "woff2": "font/woff2",
                "svg": "image/svg+xml",
                "png": "image/png",
            }.get(target.suffix.lstrip(".").lower(), "application/octet-stream")
            self._send(target.read_bytes(), ctype=ctype)
            return
        if path in ("/floral", "/floral/", "/floral/index.html"):
            page = FLORAL_DIR / "index.html"
            if page.is_file():
                self._send(page.read_bytes(), ctype="text/html; charset=utf-8")
            else:
                self._send({"error": "floral build not found"}, 404)
            return
        if path.startswith("/floral/assets/"):
            target = (FLORAL_DIR / path[len("/floral/"):]).resolve()
            if FLORAL_DIR.resolve() not in target.parents or not target.is_file():
                self._send({"error": "not found"}, 404)
                return
            ctype = {
                "js": "text/javascript; charset=utf-8",
                "css": "text/css; charset=utf-8",
                "ttf": "font/ttf",
                "woff2": "font/woff2",
                "svg": "image/svg+xml",
            }.get(target.suffix.lstrip(".").lower(), "application/octet-stream")
            self._send(target.read_bytes(), ctype=ctype)
            return
        if path in ("/r", "/r.html"):
            page = DIST_DIR / "r.html"
            if page.is_file():
                self._send(page.read_bytes(), ctype="text/html; charset=utf-8")
            else:
                self._send({"error": "r.html not built"}, 404)
            return
        if path in ("/design", "/design.html"):
            design = ROOT / "design.html"
            if design.is_file():
                self._send(design.read_bytes(), ctype="text/html; charset=utf-8")
            else:
                self._send({"error": "design.html not found"}, 404)
            return
        if path in {"/v%d.html" % i for i in range(1, 7)}:
            target = DIST_DIR / path.lstrip("/")
            if target.is_file():
                self._send(target.read_bytes(), ctype="text/html; charset=utf-8")
                return
            self._send({"error": "not built"}, 404)
            return
        if path.startswith("/assets/") and not path.startswith("/assets/agents/"):
            target = (DIST_DIR / path.lstrip("/")).resolve()
            if DIST_DIR.resolve() not in target.parents or not target.is_file():
                self._send({"error": "not found"}, 404)
                return
            ctype = {
                "js": "text/javascript; charset=utf-8",
                "css": "text/css; charset=utf-8",
                "map": "application/json",
                "svg": "image/svg+xml",
                "woff2": "font/woff2",
            }.get(target.suffix.lstrip(".").lower(), "application/octet-stream")
            self._send(target.read_bytes(), ctype=ctype)
            return
        if path.startswith("/assets/agents/"):
            name = path.rsplit("/", 1)[-1]
            target = (AGENTS_DIR / name).resolve()
            if AGENTS_DIR.resolve() not in target.parents or not target.is_file():
                self._send({"error": "not found"}, 404)
                return
            ctype = {"svg": "image/svg+xml", "png": "image/png"}.get(
                target.suffix.lstrip(".").lower(), "application/octet-stream"
            )
            self._send(target.read_bytes(), ctype=ctype)
            return
        if path == "/api/config":
            self._send(_config_json())
            return
        if path == "/api/agents":
            self._send(_agents_json())
            return
        if path == "/api/history":
            limit = 200
            query = urlparse(self.path).query
            for part in query.split("&"):
                if part.startswith("limit="):
                    try:
                        limit = max(1, min(1000, int(part.split("=", 1)[1])))
                    except ValueError:
                        pass
            self._send(_history_json(limit))
            return
        if path == "/api/state":
            data = _state()
            data["autopilot"] = _boot()[2].autopilot_state()
            self._send(data)
            return
        if path == "/api/autopilot":
            self._send(_boot()[2].autopilot_state())
            return
        if path.startswith("/api/tasks/") and path.endswith("/conversation"):
            task_id = path.split("/")[3]
            try:
                self._send(_task_conversation(task_id))
            except KeyError:
                self._send({"error": "任务不存在"}, 404)
            return
        if path.startswith("/api/tasks/") and path.endswith("/runs"):
            task_id = path.split("/")[3]
            try:
                self._send(_task_runs(task_id))
            except KeyError:
                self._send({"error": "任务不存在"}, 404)
            return
        if path.startswith("/api/tasks/") and path.endswith("/log"):
            task_id = path.split("/")[3]
            store, _, _ = _boot()
            if store.get_task(task_id) is None:
                self._send({"error": "任务不存在"}, 404)
                return
            runs = store.list_runs(task_id)
            lines = _read_log(runs[-1].log_path if runs else None)
            self._send({"lines": lines})
            return
        self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/config":
                self._send(_save_config(payload))
                return
            if path == "/api/pick-dir":
                self._send(_pick_dir(payload.get("start") or ""))
                return
            if path == "/api/open-dir":
                self._send(_open_dir(payload.get("path") or "", payload.get("task_id") or ""))
                return
            if path == "/api/test-analyzer":
                self._send(_test_analyzer(payload))
                return
            if path == "/api/test-mcp":
                self._send(_test_mcp(payload))
                return
            if path == "/api/tasks":
                self._send(_create_task(payload), 201)
                return
            if path.startswith("/api/tasks/") and path.endswith("/toggle"):
                self._send(_toggle_task(path.split("/")[3]))
                return
            if path.startswith("/api/tasks/") and path.endswith("/status"):
                self._send(_set_status(path.split("/")[3], payload.get("status") or "queued"))
                return
            if path == "/api/order":
                _reorder(payload.get("ids") or [])
                self._send({"ok": True})
                return
            if path.startswith("/api/autopilot/"):
                self._send(_autopilot_action(path.rsplit("/", 1)[-1], payload))
                return
            if path.startswith("/api/tasks/") and path.endswith("/followup"):
                self._send(_decide_followup(path.split("/")[3], payload))
                return
            if path.startswith("/api/tasks/") and path.endswith("/retry"):
                self._send(_retry_task(path.split("/")[3], payload))
                return
            if path.startswith("/api/tasks/") and path.endswith("/edit"):
                self._send(_edit_task(path.split("/")[3], payload))
                return
            if path.startswith("/api/queue/"):
                self._send(_control(path.rsplit("/", 1)[-1], payload))
                return
            self._send({"error": "not found"}, 404)
        except KeyError as exc:
            self._send({"error": f"任务不存在: {exc}"}, 404)
        except Exception as exc:  # noqa: BLE001 - 直接把错误回给前端
            self._send({"error": str(exc)}, 400)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/tasks/"):
            store, _, _ = _boot()
            task_id = path.split("/")[3]
            with _LOCK:
                store.delete_task(task_id)
            self._send({"ok": True})
            return
        self._send({"error": "not found"}, 404)


def start_server(host: str = "127.0.0.1", port: int = 8766) -> ThreadingHTTPServer:
    """后台线程版：给桌面外壳用，不阻塞调用方。"""
    global _HTTPD
    _boot()
    _HTTPD = ThreadingHTTPServer((host, port), Handler)
    thread = threading.Thread(target=_HTTPD.serve_forever, daemon=True)
    thread.start()
    return _HTTPD


def shutdown_server() -> None:
    global _HTTPD, _ENGINE
    if _HTTPD is not None:
        try:
            _HTTPD.shutdown()
            _HTTPD.server_close()
        except Exception:
            pass
        _HTTPD = None
    if _ENGINE is not None:
        try:
            _ENGINE.shutdown()
        except Exception:
            pass
        _ENGINE = None


def serve(host: str = "127.0.0.1", port: int = 8766, open_browser: bool = True) -> None:
    _boot()
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Finch Web UI 已启动：{url}")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if _ENGINE is not None:
            _ENGINE.shutdown()

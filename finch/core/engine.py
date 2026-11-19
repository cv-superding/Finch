from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agents import ADAPTER_CLASSES, adapter_label, build_adapter
from ..agents.base import AgentEvent, AgentRequest, LaunchSpec
from ..config import AppConfig, data_dir, logs_dir, workspaces_dir
from ..models import (
    AnalysisResult,
    Interruption,
    Run,
    RunKind,
    RunStatus,
    Task,
    TaskStatus,
    ToolRecord,
    now,
)
from .analyzer import ResultAnalyzer
from .detector import (
    NETWORK_PATTERNS,
    REASON_LABELS,
    InterruptionDetector,
    InterruptReason,
    is_incomplete_reply,
)
from .llm import LLMError, chat_completion
from .optimizer import PromptOptimizer
from .prompts import build_followup_prompt
from .signals import EngineSignals

try:
    import psutil
except Exception:  # pragma: no cover - optional dependency
    psutil = None


AUTOPILOT_SYSTEM = """你是一个自动驾驶调度员，负责把一个长期目标拆成下一步可执行的编程任务。
你会读到：用户目标、最近已完成任务的摘要、当前队列状态。
只输出 JSON，不要 Markdown，结构：
{
  "done": true/false,
  "title": "不超过 20 字的下一步任务标题",
  "prompt": "可直接下发给编程 Agent 的完整任务提示词",
  "reason": "不超过 80 字，说明为什么这一步能推进目标"
}
判定规则：
- 若目标已达成或无需再做任何事，done 为 true，其余字段可为空。
- 否则 done 为 false，给出单一、具体、可验证的下一步任务；不要重复已完成的工作。
- prompt 要自包含：交代背景、要改什么、验收标准；适合一次独立下发。
- 不要臆造目标之外的需求。"""


@dataclass
class AttemptResult:
    kind: str
    final_text: str = ""
    accumulated: str = ""
    session_id: str = ""
    subtype: str = ""
    reason: str = ""
    detail: str = ""
    exit_code: int | None = None
    error: str = ""
    attention: bool = False


class RunLog:
    def __init__(self, path: Path, emitter, task_id: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.emitter = emitter
        self.task_id = task_id
        self.handle = path.open("w", encoding="utf-8", buffering=1)
        self._text_buffer = ""

    def _emit(self, line: str) -> None:
        self.handle.write(line + "\n")
        self.emitter.emit(self.task_id, line)

    def write(self, kind: str, text: str) -> None:
        if text is None:
            return
        text = str(text)
        if kind in ("text", "thinking"):
            self._text_buffer += text
            if "\n" in self._text_buffer or len(self._text_buffer) >= 260:
                self.flush_text()
            return
        self.flush_text()
        stamp = datetime.now().strftime("%H:%M:%S")
        for line in text.splitlines() or [""]:
            self._emit(f"[{stamp}] [{kind}] {line}")

    def flush_text(self) -> None:
        if not self._text_buffer:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        content = self._text_buffer
        self._text_buffer = ""
        for line in content.splitlines() or [""]:
            self._emit(f"[{stamp}] [输出] {line}")

    def close(self) -> None:
        self.flush_text()
        try:
            self.handle.close()
        except Exception:
            pass


class QueueEngine:
    def __init__(self, store, config: AppConfig, signals: EngineSignals | None = None):
        self.store = store
        self.config = config
        self.signals = signals or EngineSignals()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._paused = False
        self._force_next = False
        self._skip_retry = False
        self._shutdown_requested = False
        self._pending_followup_reason = ""
        self._active_proc: subprocess.Popen | None = None
        self._active_task_id = ""
        self._state = "idle"
        self._decisions: dict[str, dict[str, Any]] = {}
        self._decision_events: dict[str, threading.Event] = {}
        self._restored_followups: dict[str, str] = {}
        self._last_sync: dict[str, float] = {}
        self._logs: dict[str, Path] = {}
        self._autopilot: dict[str, Any] = {
            "active": False,
            "resumable": False,
            "goal": "",
            "max_rounds": 5,
            "minutes": 0,
            "auto_accept": True,
            "rounds_used": 0,
            "started_at": 0.0,
            "rounds": [],
            "stop_reason": "",
        }
        self._load_autopilot()

    # ------------------------------------------------------------------
    # public control surface
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def active_task_id(self) -> str:
        return self._active_task_id

    @property
    def paused(self) -> bool:
        return self._paused

    def update_config(self, config: AppConfig) -> None:
        with self._lock:
            self.config = config

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            if self._paused:
                self._paused = False
                self._set_state("running")
                self.signals.toast.emit("队列已恢复", "success")
            return
        tasks = self.store.list_tasks()
        eligible = [t for t in tasks if t.status in (TaskStatus.queued.value, TaskStatus.interrupted.value)]
        if not eligible and not self.autopilot_active:
            self._set_state("idle")
            if any(t.status == TaskStatus.attention.value for t in tasks):
                self.signals.toast.emit("没有可自动执行的任务，请处理待人工项", "warning")
            else:
                self.signals.toast.emit("队列里没有待执行任务", "info")
            return
        self._stop.clear()
        self._paused = False
        self._force_next = False
        self._skip_retry = False
        self._shutdown_requested = False
        self._thread = threading.Thread(target=self._loop, name="finch-engine", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._paused = True
        self._set_state("paused")
        self.signals.toast.emit("当前任务结束后暂停队列", "info")

    def stop(self) -> None:
        self._stop.set()
        self._terminate_active()
        for event in list(self._decision_events.values()):
            event.set()
        worker = getattr(self, "_thread", None)
        # 空闲队列没有 _loop 在跑，finally 不会执行；此处必须自己回到 idle，
        # 否则「终止」后状态永远停在 stopping，开始按钮会被挡住。
        if worker is None or not worker.is_alive():
            self._active_task_id = ""
            self._active_proc = None
            self._paused = False
            self._stop.clear()
            self._set_state("idle")
            self.signals.toast.emit("队列已停止", "info")
            return
        self._set_state("stopping")
        self.signals.toast.emit("正在终止当前任务", "warning")

    def force_next(self) -> None:
        if not self._active_task_id:
            self.signals.toast.emit("当前没有执行中的任务", "info")
            return
        self._force_next = True
        self._terminate_active()
        for tid, event in list(self._decision_events.items()):
            self._decisions[tid] = {"decision": "force_next", "prompt": ""}
            event.set()
        self.signals.toast.emit("已强制跳过当前任务", "warning")

    def skip_retry(self) -> None:
        if not self._active_task_id:
            self.signals.toast.emit("当前没有可跳过的续传/补做", "info")
            return
        self._skip_retry = True
        for tid, event in list(self._decision_events.items()):
            self._decisions[tid] = {"decision": "skip", "prompt": ""}
            event.set()
        if self._active_proc and self._active_proc.poll() is None:
            # Active retry/follow-up is abandoned; this task becomes 待人工.
            self._terminate_active()
        self.signals.toast.emit("已跳过当前任务的续传/补做", "info")

    def resolve_followup(self, task_id: str, decision: str, prompt: str = "") -> None:
        event = self._decision_events.get(task_id)
        if event:
            self._decisions[task_id] = {"decision": decision, "prompt": prompt}
            event.set()
            return
        # Restored "awaiting" task after an app restart: no live waiter exists.
        task = self.store.get_task(task_id)
        # attention 与 awaiting 都代表「等待人工决定」：前端决策卡按这两种
        # 状态展示，只认 awaiting 会让卡片上的按钮点了没有任何效果。
        if not task or task.status not in (TaskStatus.awaiting.value, TaskStatus.attention.value):
            return
        if decision == "approve":
            prompt = (prompt or task.followup_prompt).strip()
            if not prompt:
                self.signals.toast.emit("补做提示词为空", "warning")
                return
            if not task.session_id:
                self._attention(task, "会话 ID 丢失，无法在同一会话中继续补做，请重置任务")
                return
            task.followup_prompt = prompt
            task.pending_action = ""
            task.status = TaskStatus.queued.value
            task.ended_at = 0
            task.progress = "应用重启后，等待执行人工确认的补做"
            self.store.save_task(task)
            self._restored_followups[task_id] = prompt
            self.signals.task_updated.emit(task_id)
            self.signals.queue_updated.emit()
            self.start()
        else:
            task.status = TaskStatus.done.value
            task.pending_action = ""
            task.ended_at = now()
            task.attention_reason = "人工跳过补做"
            task.progress = "人工跳过补做，保留当前结果"
            self._finish_task(task, archive=True)

    def retry_task(self, task_id: str, autostart: bool = True) -> None:
        with self._lock:
            task = self.store.get_task(task_id)
            if not task:
                return
            if task.id == self._active_task_id:
                self.signals.toast.emit("任务正在执行，无法重置", "warning")
                return
            task.status = TaskStatus.queued.value
            task.session_id = ""
            task.summary = ""
            task.completed = []
            task.pending = []
            task.issues = []
            task.resume_count = 0
            task.followup_count = 0
            task.tool_count = 0
            task.started_at = 0
            task.ended_at = 0
            task.progress = "等待重新执行"
            task.attention_reason = ""
            task.followup_prompt = ""
            task.pending_action = ""
            task.error = ""
            self.store.save_task(task)
        self.signals.task_updated.emit(task_id)
        self.signals.queue_updated.emit()
        if autostart:
            self.start()

    def shutdown(self) -> None:
        self._shutdown_requested = True
        self._stop.set()
        self._terminate_active()
        for event in list(self._decision_events.values()):
            event.set()
        if self.autopilot_active:
            self._save_autopilot()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=8)

    # ------------------------------------------------------------------
    # autopilot
    # ------------------------------------------------------------------
    @property
    def autopilot_active(self) -> bool:
        return bool(self._autopilot["active"])

    @property
    def autopilot_resumable(self) -> bool:
        return bool(self._autopilot["resumable"])

    def autopilot_state(self) -> dict[str, Any]:
        return dict(self._autopilot)

    def start_autopilot(self, goal: str, max_rounds: int, minutes: int, auto_accept: bool) -> None:
        self._autopilot.update(
            active=True,
            resumable=False,
            goal=goal,
            max_rounds=max(1, int(max_rounds)),
            minutes=max(0, int(minutes)),
            auto_accept=bool(auto_accept),
            rounds_used=0,
            started_at=time.time(),
            rounds=[],
            stop_reason="",
        )
        self._save_autopilot()
        self.signals.autopilot_updated.emit()
        self.signals.toast.emit("自动驾驶已启动", "success")
        self.start()

    def stop_autopilot(self, reason: str = "") -> None:
        if not self._autopilot["active"] and not self._autopilot["resumable"]:
            return
        self._autopilot["active"] = False
        self._autopilot["resumable"] = False
        self._autopilot["stop_reason"] = reason
        self._save_autopilot()
        self.signals.autopilot_updated.emit()
        if reason:
            self.signals.toast.emit(f"自动驾驶已停止：{reason}", "info")

    def resume_autopilot(self) -> None:
        if not self._autopilot["resumable"]:
            return
        self._autopilot["resumable"] = False
        self._autopilot["active"] = True
        self._autopilot["started_at"] = time.time()
        self._autopilot["stop_reason"] = ""
        self._save_autopilot()
        self.signals.autopilot_updated.emit()
        self.signals.toast.emit("自动驾驶已从中断处继续", "success")
        self.start()

    def _autopilot_path(self) -> Path:
        return data_dir() / "autopilot.json"

    def _save_autopilot(self) -> None:
        try:
            self._autopilot_path().write_text(
                json.dumps(self._autopilot, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    def _load_autopilot(self) -> None:
        try:
            raw = json.loads(self._autopilot_path().read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        for key in self._autopilot:
            if key in raw:
                self._autopilot[key] = raw[key]
        if self._autopilot["active"]:
            self._autopilot["active"] = False
            self._autopilot["resumable"] = True

    def _autopilot_next(self) -> Task | None:
        ap = self._autopilot
        if ap["minutes"] and time.time() - ap["started_at"] > ap["minutes"] * 60:
            self.stop_autopilot("时间预算用尽")
            return None
        if ap["rounds_used"] >= ap["max_rounds"]:
            self.stop_autopilot("轮数用尽")
            return None
        if not self.config.analyzer.ready:
            self.stop_autopilot("未配置驱动模型，无法生成下一步")
            return None
        tasks = self.store.list_tasks()
        recent = [t for t in tasks if t.status == TaskStatus.done.value][-6:]
        history = "\n".join(f"- {t.title}：{t.summary or '已完成'}" for t in recent) or "（暂无已完成任务）"
        queued = sum(1 for t in tasks if t.status == TaskStatus.queued.value)
        user = (
            f"目标：{ap['goal'] or '（未填写，按轮数推进）'}\n"
            f"已完成：\n{history}\n"
            f"当前待执行队列：{queued} 条\n"
            f"已推进轮数：{ap['rounds_used']}/{ap['max_rounds']}\n"
            "请给出下一步任务。"
        )
        try:
            reply = chat_completion(self.config.analyzer, AUTOPILOT_SYSTEM, user, temperature=0.3)
        except LLMError as exc:
            self.stop_autopilot(f"驱动模型错误：{exc}")
            return None
        parsed = _parse_autopilot(reply)
        if parsed is None:
            self.stop_autopilot("驱动模型返回无法解析")
            return None
        if parsed.get("done"):
            self.stop_autopilot("目标达成")
            return None
        prompt = str(parsed.get("prompt") or "").strip()
        if not prompt:
            self.stop_autopilot("驱动模型未给出下一步")
            return None
        title = str(parsed.get("title") or "").strip() or f"自动驾驶第 {ap['rounds_used'] + 1} 轮"
        task = Task(title=title, prompt=prompt, agent=self.config.agent, cwd=self.config.cwd)
        self.store.add_task(task)
        ap["rounds_used"] += 1
        ap["rounds"].append(
            {
                "round": ap["rounds_used"],
                "title": title,
                "reason": str(parsed.get("reason") or ""),
                "prompt": prompt,
                "at": time.time(),
            }
        )
        self._save_autopilot()
        self.signals.queue_updated.emit()
        self.signals.autopilot_updated.emit()
        self.signals.toast.emit(f"自动驾驶第 {ap['rounds_used']} 轮：{title}", "info")
        return task

    # ------------------------------------------------------------------
    # engine loop
    # ------------------------------------------------------------------
    def _loop(self) -> None:
        try:
            self._set_state("running")
            while not self._stop.is_set():
                if self._paused:
                    self._set_state("paused")
                    time.sleep(0.2)
                    continue
                self._set_state("running")
                task = self._pick_task()
                if not task:
                    if self.autopilot_active:
                        generated = self._autopilot_next()
                        if generated is not None:
                            continue
                    self._set_state("idle")
                    tasks = self.store.list_tasks()
                    attention = sum(1 for t in tasks if t.status == TaskStatus.attention.value)
                    failed = sum(1 for t in tasks if t.status == TaskStatus.failed.value)
                    if attention or failed:
                        self.signals.toast.emit("队列已跑完，仍有需要人工处理的任务", "warning")
                    else:
                        self.signals.toast.emit("队列执行完成", "success")
                    break
                self._execute_task(task)
                self._active_task_id = ""
        except Exception:
            detail = traceback.format_exc()
            self._write_app_error(detail)
            self.signals.alert.emit("error", "调度引擎异常", detail[-1800:])
        finally:
            self._active_task_id = ""
            self._active_proc = None
            self._thread = None
            # 无论因为空闲、暂停还是终止退出，都要回到 idle，
            # 否则「终止」之后状态会永远停在 stopping，界面无法再次开始。
            self._paused = False
            self._stop.clear()
            self._set_state("idle")

    def _pick_task(self) -> Task | None:
        for task in self.store.list_tasks():
            if task.status == TaskStatus.queued.value:
                return task
            if task.status == TaskStatus.interrupted.value and task.pending_action != "followup":
                return task
        return None

    def _execute_task(self, task: Task) -> None:
        self._active_task_id = task.id
        self._force_next = False
        self._skip_retry = False
        self._pending_followup_reason = ""
        self._last_sync[task.id] = 0.0
        agent_key = task.agent or self.config.agent
        adapter = build_adapter(self.config, agent_key)
        if not task.started_at:
            task.started_at = now()
        task.ended_at = 0
        task.error = ""
        task.pending_action = ""
        task.followup_prompt = ""
        task.attention_reason = ""
        restored_followup = self._restored_followups.pop(task.id, None)
        resume_from_crash = (
            not restored_followup
            and task.status == TaskStatus.interrupted.value
            and bool(task.session_id)
        )
        next_kind = (
            RunKind.followup.value
            if restored_followup
            else RunKind.resume.value
            if resume_from_crash
            else RunKind.main.value
        )
        next_prompt = restored_followup or (
            self.config.continue_prompt if resume_from_crash else task.prompt
        )
        if resume_from_crash and self.config.optimize_continue:
            next_prompt = self._optimize_prompt(task, next_prompt, "续传")
        resume_reason = "程序重启/上次中断，恢复原会话" if resume_from_crash else ""
        if restored_followup:
            if not task.session_id:
                self._attention(task, "会话 ID 丢失，无法继续已确认的补做")
                return
            self._pending_followup_reason = "应用重启后，人工确认继续补做"
        if next_kind == RunKind.resume.value and not adapter.supports_resume:
            task.status = TaskStatus.attention.value
            task.attention_reason = f"{adapter.label} 不支持会话续传，请重新执行"
            task.ended_at = now()
            self._finish_task(task, archive=True)
            self.signals.alert.emit("warning", "无法自动续传", task.attention_reason)
            return
        task.status = (
            TaskStatus.patching.value
            if next_kind == RunKind.followup.value
            else TaskStatus.resuming.value
            if next_kind == RunKind.resume.value
            else TaskStatus.running.value
        )
        task.progress = (
            "执行已确认的补做" if restored_followup else "恢复会话继续执行" if resume_from_crash else "正在启动 Agent"
        )
        self._sync_task(task, force=True)
        self.signals.queue_updated.emit()

        while not self._stop.is_set():
            if self._force_next:
                task.status = TaskStatus.skipped.value
                task.progress = "已人工跳过"
                task.attention_reason = "人工强制进入下一任务"
                task.ended_at = now()
                self._finish_task(task, archive=True)
                return
            if self._skip_retry:
                task.status = TaskStatus.attention.value
                task.progress = "已人工跳过续传/补做"
                task.attention_reason = "人工跳过续传/补做，请检查结果"
                task.ended_at = now()
                self._finish_task(task, archive=True)
                self.signals.alert.emit("info", "已跳过续传/补做", task.attention_reason)
                return

            if next_kind == RunKind.resume.value:
                if task.resume_count >= max(0, self.config.max_resumes):
                    self._attention(task, f"续传次数达到上限（{self.config.max_resumes} 次），需要人工确认")
                    return
                task.resume_count += 1
                task.status = TaskStatus.resuming.value
                reason = resume_reason or "检测到真实中断，自动续传"
            elif next_kind == RunKind.followup.value:
                if task.followup_count >= max(0, self.config.max_followups):
                    self._attention(task, f"补做轮次达到上限（{self.config.max_followups} 轮），需要人工确认")
                    return
                task.followup_count += 1
                task.status = TaskStatus.patching.value
                reason = next_reason if (next_reason := self._pending_followup_reason) else "根据未完成项自动补做"
            else:
                task.status = TaskStatus.running.value
                reason = "下发主任务"

            run = Run(
                task_id=task.id,
                kind=next_kind,
                round=(
                    task.resume_count
                    if next_kind == RunKind.resume.value
                    else task.followup_count
                    if next_kind == RunKind.followup.value
                    else 0
                ),
                reason=reason,
                prompt=next_prompt,
                status=RunStatus.running.value,
                session_id=task.session_id,
                meta={"title": task.title, "agent": adapter.key, "cwd": task.cwd or self.config.cwd},
            )
            self.store.add_run(run)
            task.progress = f"{'续传' if next_kind == RunKind.resume.value else '补做' if next_kind == RunKind.followup.value else '执行'}进行中"
            self._sync_task(task, force=True)
            self.signals.run_updated.emit(task.id, run.id)
            self.signals.queue_updated.emit()

            outcome = self._run_attempt(task, run, adapter, next_prompt, next_kind)
            task.session_id = outcome.session_id or task.session_id
            run.session_id = task.session_id
            run.ended_at = now()
            run.output = outcome.final_text or outcome.accumulated
            run.exit_code = outcome.exit_code
            run.status = {
                "completed": RunStatus.completed.value,
                "interrupted": RunStatus.interrupted.value,
                "failed": RunStatus.failed.value,
                "stopped": RunStatus.stopped.value,
                "skipped": RunStatus.stopped.value,
                "attention": RunStatus.stopped.value,
            }.get(outcome.kind, RunStatus.failed.value)
            self.store.save_run(run)
            self.signals.run_updated.emit(task.id, run.id)

            if outcome.kind == "stopped":
                if self._shutdown_requested:
                    task.status = TaskStatus.interrupted.value
                    task.progress = "Finch 关闭时应用退出，下次启动可继续"
                    task.ended_at = 0
                    task.attention_reason = ""
                    self.store.save_task(task)
                    self.signals.task_updated.emit(task.id)
                    return
                task.status = TaskStatus.stopped.value
                task.progress = "已终止"
                task.ended_at = now()
                task.error = outcome.error or "用户终止"
                self._finish_task(task, archive=True)
                return
            if outcome.kind == "attention":
                self._skip_retry = False
                self._attention(task, "人工跳过续传/补做，请检查结果")
                return
            if outcome.kind == "skipped":
                task.status = TaskStatus.skipped.value
                task.progress = "已跳过"
                task.attention_reason = "人工强制进入下一任务"
                task.ended_at = now()
                self._finish_task(task, archive=True)
                return
            if outcome.kind == "failed":
                task.status = TaskStatus.failed.value
                task.ended_at = now()
                task.error = outcome.error or outcome.final_text or "执行失败"
                task.progress = f"失败：{task.error[:160]}"
                level = "error"
                title = "任务执行失败"
                if outcome.attention:
                    title = "Agent 认证/配置异常"
                    self._paused = True
                    self._set_state("paused")
                self._finish_task(task, archive=True)
                self.signals.alert.emit(level, title, f"「{task.title}」\n{task.error[:1200]}")
                if self.autopilot_active:
                    self.stop_autopilot("任务失败，自动驾驶已停机")
                if outcome.attention:
                    return
                break

            if outcome.kind == "interrupted":
                task.status = TaskStatus.interrupted.value
                task.progress = f"{REASON_LABELS.get(outcome.reason, '中断')}：{outcome.detail}"[:220]
                self._sync_task(task, force=True)
                if self._skip_retry:
                    continue
                if not task.session_id or not adapter.supports_resume:
                    self._attention(task, "检测到中断，但未获得可续传的会话 ID，需要人工处理")
                    return
                if task.resume_count >= max(0, self.config.max_resumes):
                    self._attention(task, f"续传次数达到上限（{self.config.max_resumes} 次），需要人工确认")
                    return
                next_kind = RunKind.resume.value
                next_prompt = self.config.continue_prompt
                if self.config.optimize_continue:
                    next_prompt = self._optimize_prompt(task, next_prompt, "续传")
                resume_reason = f"{REASON_LABELS.get(outcome.reason, '中断')}：{outcome.detail}"
                self._pending_followup_reason = ""
                time.sleep(0.35)
                continue

            # completed
            final_text = (outcome.final_text or outcome.accumulated or "").strip()
            incomplete = is_incomplete_reply(final_text, outcome.subtype)
            if incomplete:
                run.interruptions.append(
                    Interruption(
                        InterruptReason.INCOMPLETE,
                        incomplete,
                        kind="reply",
                    ).to_dict()
                )
                self.store.save_run(run)
                task.status = TaskStatus.interrupted.value
                task.progress = f"回复不完整：{incomplete}"
                self._sync_task(task, force=True)
                if self._skip_retry:
                    continue
                if not task.session_id or not adapter.supports_resume:
                    self._attention(task, f"回复不完整（{incomplete}），且无法自动续传")
                    return
                if task.resume_count >= max(0, self.config.max_resumes):
                    self._attention(task, f"回复不完整，续传次数达到上限（{self.config.max_resumes} 次）")
                    return
                next_kind = RunKind.resume.value
                next_prompt = self.config.continue_prompt
                if self.config.optimize_continue:
                    next_prompt = self._optimize_prompt(task, next_prompt, "续传")
                resume_reason = f"回复不完整：{incomplete}"
                time.sleep(0.35)
                continue

            task.status = TaskStatus.validating.value
            task.progress = "解析回复与未完成项"
            task.ended_at = 0
            self._sync_task(task, force=True)
            analysis = self._analyze(task, final_text)
            task.summary = analysis.summary
            task.completed = analysis.completed
            task.pending = analysis.pending
            task.issues = analysis.issues
            task.progress = (
                f"验收完成：完成 {len(task.completed)} 项 · 遗留 {len(task.pending)} 项 · 问题 {len(task.issues)} 项"
            )
            self._sync_task(task, force=True)
            self._log_event(task.id, "验收", task.progress)

            if not analysis.needs_followup:
                task.status = TaskStatus.done.value
                task.ended_at = now()
                task.progress = "全部验收项已落地"
                self._finish_task(task, archive=True)
                self.signals.toast.emit(f"「{task.title}」已完成", "success")
                break

            if not self.config.auto_followup and not self.autopilot_active:
                self._attention(task, "存在未完成项或已知问题，自动补做已关闭")
                return
            if task.followup_count >= max(0, self.config.max_followups):
                self._attention(
                    task,
                    f"还有 {len(task.pending) + len(task.issues)} 项未落地，补做轮次达到上限（{self.config.max_followups} 轮）",
                )
                return

            followup = build_followup_prompt(
                self.config,
                task.prompt,
                task.summary,
                task.pending,
                task.issues,
                task.title,
            )
            self._log_event(task.id, "补做", f"生成补做提示词，未完成 {len(task.pending)} 项，问题 {len(task.issues)} 项")
            if self.config.optimize_followup:
                task.progress = "优化补做提示词"
                self._sync_task(task)
                followup = self._optimize_prompt(task, followup, "补做")

            next_reason = (
                f"存在 {len(task.pending)} 项未完成、{len(task.issues)} 项问题，"
                f"自动补做第 {task.followup_count + 1} 轮"
            )
            if self.config.confirm_followup and not (
                self.autopilot_active and self._autopilot["auto_accept"]
            ):
                decision = self._await_followup(task, followup, next_reason)
                if decision.get("decision") == "shutdown":
                    return
                if self._stop.is_set():
                    task.status = TaskStatus.stopped.value
                    task.ended_at = now()
                    task.progress = "已终止"
                    self._finish_task(task, archive=True)
                    return
                if decision.get("decision") == "force_next":
                    task.status = TaskStatus.skipped.value
                    task.attention_reason = "待确认补做时人工跳过"
                    task.ended_at = now()
                    self._finish_task(task, archive=True)
                    return
                if decision.get("decision") != "approve":
                    task.status = TaskStatus.done.value
                    task.attention_reason = "人工跳过补做"
                    task.ended_at = now()
                    task.progress = "人工跳过补做，保留当前结果"
                    self._finish_task(task, archive=True)
                    return
                followup = decision.get("prompt") or followup
                next_reason = next_reason.replace("自动补做", "人工确认后补做")

            self._pending_followup_reason = next_reason
            task.pending_action = ""
            task.followup_prompt = ""
            next_kind = RunKind.followup.value
            next_prompt = followup
            time.sleep(0.25)
        if self._stop.is_set() and task.status not in (
            TaskStatus.done.value,
            TaskStatus.failed.value,
            TaskStatus.attention.value,
            TaskStatus.stopped.value,
            TaskStatus.skipped.value,
            TaskStatus.awaiting.value,
        ):
            if self._shutdown_requested:
                task.status = TaskStatus.interrupted.value
                task.progress = "Finch 关闭时应用退出，下次启动可继续"
                self.store.save_task(task)
                self.signals.task_updated.emit(task.id)
            else:
                task.status = TaskStatus.stopped.value
                task.progress = "队列终止"
                task.ended_at = now()
                self._finish_task(task, archive=True)

    _pending_followup_reason: str = ""

    # ------------------------------------------------------------------
    # single attempt
    # ------------------------------------------------------------------
    def _run_attempt(
        self,
        task: Task,
        run: Run,
        adapter,
        prompt: str,
        kind: str,
    ) -> AttemptResult:
        started = now()
        log_path = logs_dir() / task.id / f"{run.id}.log"
        run.log_path = str(log_path)
        self.store.save_run(run)
        log = RunLog(log_path, self.signals.log_line, task.id)
        log.write("run", f"开始执行 {run.label}｜Agent: {adapter.label}｜会话: {task.session_id or '新会话'}")
        log.write("prompt", prompt)
        self._log_event(task.id, "运行", f"{run.label} 开始｜{adapter.label}")

        try:
            request = AgentRequest(
                prompt=prompt,
                cwd=self._task_cwd(task),
                session_id=task.session_id if kind != RunKind.main.value else "",
                is_resume=kind != RunKind.main.value and bool(task.session_id),
                new_session_id=str(uuid.uuid4()),
                task_id=task.id,
                task_title=task.title,
            )
            launch = adapter.build_launch(request)
        except Exception as exc:
            message = f"无法启动 {adapter.label}：{exc}"
            log.write("error", message)
            log.close()
            run.status = RunStatus.failed.value
            run.ended_at = now()
            self.store.save_run(run)
            return AttemptResult("failed", error=message, exit_code=None)

        proc = self._spawn(launch)
        if proc is None:
            log.write("error", "进程创建失败")
            log.close()
            return AttemptResult("failed", error="进程创建失败")
        self._active_proc = proc
        if launch.stdin is not None:
            try:
                proc.stdin.write(launch.stdin)
                if not launch.stdin.endswith("\n"):
                    proc.stdin.write("\n")
                proc.stdin.close()
            except Exception as exc:
                log.write("stderr", f"写入 stdin 失败：{exc}")

        out_queue: queue.Queue = queue.Queue()
        readers = self._start_readers(proc, out_queue)
        detector = InterruptionDetector(
            text_timeout=max(1, self.config.text_idle_timeout),
            tool_timeout=max(2, self.config.tool_timeout),
            first_output_grace=max(1, self.config.first_output_grace),
        )
        parser = adapter.create_parser()
        tools: dict[str, ToolRecord] = {}
        tool_order: list[str] = []
        attempt_tool_count = 0
        accumulated: list[str] = []
        final_text = ""
        result_received = False
        result_error = False
        result_subtype = ""
        session_id = task.session_id if kind != RunKind.main.value else ""
        error_text = ""
        exit_code: int | None = None
        stdout_done = False
        stderr_done = False
        last_progress = 0.0
        last_child_check = 0.0
        interrupted: AttemptResult | None = None
        warning_lines: list[str] = []

        def base_status() -> str:
            if kind == RunKind.resume.value:
                return TaskStatus.resuming.value
            if kind == RunKind.followup.value:
                return TaskStatus.patching.value
            return TaskStatus.running.value

        def add_tool(event: AgentEvent) -> None:
            nonlocal last_progress, attempt_tool_count
            tool_id = str(event.data.get("tool_id") or f"tool-{len(tool_order)+1}")
            name = str(event.data.get("name") or "tool")
            tool_input = str(event.data.get("input") or "")
            created = tool_id not in tools
            if created:
                record = ToolRecord(id=tool_id, name=name, input=tool_input[:4000])
                tools[tool_id] = record
                tool_order.append(tool_id)
                task.tool_count += 1
                attempt_tool_count += 1
                detector.note_tool_start(tool_id, name)
                task.status = TaskStatus.tool.value
                task.progress = f"工具执行中：{name}"
                log.write("tool", f"开始 {name} · {tool_input[:600]}")
            else:
                record = tools[tool_id]
                if tool_input:
                    record.input = tool_input[:4000]
                detector.note_tool_activity()
            last_progress = time.monotonic()
            self._sync_task(task, force=created)

        def update_tool(event: AgentEvent) -> None:
            tool_id = str(event.data.get("tool_id") or "")
            record = tools.get(tool_id)
            if not record:
                return
            new_input = str(event.data.get("input") or "")
            if new_input and new_input != record.input:
                record.input = new_input[:4000]
                if new_input not in ("{}", "[]"):
                    log.write("tool", f"参数 {record.name} · {new_input[:600]}")
            if event.data.get("output"):
                record.output = str(event.data["output"])[:6000]
            detector.note_tool_activity()
            self._sync_task(task)

        def end_tool(event: AgentEvent) -> None:
            tool_id = str(event.data.get("tool_id") or "")
            record = tools.get(tool_id)
            if not record:
                record = ToolRecord(id=tool_id or f"tool-{len(tool_order)+1}", name=str(event.data.get("name") or "tool"))
                tools[record.id] = record
                tool_order.append(record.id)
                task.tool_count += 1
                attempt_tool_count += 1
            record.status = "error" if event.data.get("is_error") else "done"
            record.ended_at = now()
            if event.data.get("output"):
                record.output = str(event.data["output"])[:6000]
            detector.note_tool_end(record.id)
            log.write(
                "tool",
                f"结束 {record.name} · {'失败' if record.status == 'error' else '完成'}"
                + (f" · {record.output[:500]}" if record.output else ""),
            )
            if not detector.tool_ids and not detector.children_active:
                task.status = base_status()
                task.progress = "工具执行完成，继续输出"
            self._sync_task(task, force=True)

        try:
            while True:
                if self._stop.is_set():
                    interrupted = AttemptResult(
                        "stopped",
                        accumulated="".join(accumulated),
                        session_id=session_id,
                        reason=InterruptReason.USER,
                        detail="用户终止队列",
                        exit_code=proc.poll(),
                    )
                    break
                if self._force_next:
                    interrupted = AttemptResult(
                        "skipped",
                        accumulated="".join(accumulated),
                        session_id=session_id,
                        reason=InterruptReason.USER,
                        detail="人工强制进入下一任务",
                        exit_code=proc.poll(),
                    )
                    break
                if self._skip_retry:
                    interrupted = AttemptResult(
                        "attention",
                        accumulated="".join(accumulated),
                        session_id=session_id,
                        reason=InterruptReason.USER,
                        detail="人工跳过续传/补做",
                        exit_code=proc.poll(),
                    )
                    break

                now_mono = time.monotonic()
                if adapter.key == "opencode" and psutil and proc.poll() is None and now_mono - last_child_check > 1.2:
                    last_child_check = now_mono
                    try:
                        children = proc.children(recursive=True)
                        active_children = [c for c in children if c.is_running()]
                        detector.note_children(bool(active_children))
                        if active_children and detector.phase == "tool":
                            self._sync_task(task)
                    except Exception:
                        pass

                drained = False
                try:
                    while True:
                        channel, payload = out_queue.get_nowait()
                        drained = True
                        if channel == "eof_out":
                            stdout_done = True
                            continue
                        if channel == "eof_err":
                            stderr_done = True
                            continue
                        if channel == "stderr":
                            line = str(payload).rstrip("\r\n")
                            if line:
                                log.write("stderr", line)
                                detector.touch()
                                if NETWORK_PATTERNS.search(line):
                                    detector.note_network_error(line)
                                if re.search(r"\b(error|fatal|failed)\b", line, re.IGNORECASE) and len(warning_lines) < 20:
                                    warning_lines.append(line[:500])
                            continue
                        line = str(payload).rstrip("\r\n")
                        if not line:
                            continue
                        try:
                            events = parser.feed_line(line)
                        except Exception as exc:
                            log.write("parse", f"事件解析失败：{exc}｜{line[:300]}")
                            detector.touch()
                            continue
                        for event in events:
                            if event.data.get("session_id") and not session_id:
                                session_id = str(event.data["session_id"])
                                if session_id and task.session_id != session_id:
                                    task.session_id = session_id
                                    self._sync_task(task, force=True)
                                    log.write("run", f"会话 ID：{session_id}")
                            if event.kind == "text":
                                if event.text:
                                    accumulated.append(event.text)
                                    detector.note_output(event.text)
                                    log.write("text", event.text)
                                    if time.monotonic() - last_progress > 0.7:
                                        task.progress = "输出中：" + _snippet("".join(accumulated))
                                        last_progress = time.monotonic()
                                        self._sync_task(task)
                            elif event.kind == "thinking":
                                if event.text:
                                    detector.note_output("", )
                                    detector.touch()
                                    log.write("thinking", event.text)
                            elif event.kind == "tool_start":
                                add_tool(event)
                            elif event.kind == "tool_update":
                                update_tool(event)
                            elif event.kind == "tool_end":
                                end_tool(event)
                            elif event.kind == "init":
                                model = event.data.get("model") or ""
                                log.write("init", f"Agent 就绪 · 模型 {model or '默认'} · 权限 {event.data.get('permission_mode') or '-'}")
                                detector.touch()
                            elif event.kind == "retry":
                                info = (
                                    f"API 重试 {event.data.get('attempt') or '?'}"
                                    f"/{event.data.get('max_retries') or '?'}："
                                    f"{event.data.get('error') or event.data.get('status') or '未知错误'}"
                                )
                                log.write("retry", info)
                                detector.note_network_error(info)
                                task.progress = info
                                self._sync_task(task)
                            elif event.kind == "progress":
                                detector.touch()
                                if event.data.get("status") in ("step_start", "step_finish"):
                                    task.progress = "Agent 正在推理/执行"
                                    self._sync_task(task)
                            elif event.kind == "error":
                                error_text = event.text or error_text
                                log.write("error", event.text or "未知错误")
                                detector.touch()
                                if NETWORK_PATTERNS.search(event.text or ""):
                                    detector.note_network_error(event.text)
                            elif event.kind == "result":
                                result_received = True
                                final_text = event.text or ""
                                result_error = bool(event.data.get("is_error"))
                                result_subtype = str(event.data.get("subtype") or "")
                                detector.touch()
                                log.write(
                                    "result",
                                    f"结束 · subtype={result_subtype} · error={result_error} · "
                                    f"cost={event.data.get('total_cost_usd')}",
                                )
                                if result_error and final_text:
                                    error_text = final_text
                            elif event.kind == "raw":
                                log.write("raw", event.text)
                                detector.touch()
                                if NETWORK_PATTERNS.search(event.text):
                                    detector.note_network_error(event.text)
                                if TOOL_KEYWORD_RE.search(event.text):
                                    detector.note_tool_activity()
                    if result_received:
                        break
                except queue.Empty:
                    pass

                exit_code = proc.poll()
                if exit_code is not None and out_queue.empty() and (stdout_done or readers_finished(readers)):
                    break
                if stdout_done and exit_code is not None:
                    break
                check = detector.check()
                if check:
                    log.write("interrupt", f"{REASON_LABELS.get(check.reason, check.reason)}：{check.detail}")
                    interrupted = AttemptResult(
                        "interrupted",
                        accumulated="".join(accumulated),
                        session_id=session_id,
                        reason=check.reason,
                        detail=check.detail,
                        exit_code=proc.poll(),
                    )
                    break
                if not drained:
                    time.sleep(0.08)
        finally:
            if result_received and proc.poll() is None:
                try:
                    proc.wait(timeout=2.5)
                except subprocess.TimeoutExpired:
                    log.write("stderr", "收到最终结果后进程未退出，已终止")
                    self._terminate_process(proc)
            if proc.poll() is None:
                self._terminate_process(proc)
            exit_code = proc.poll() if exit_code is None else exit_code
            for reader in readers:
                reader.join(timeout=1.2)
            log.flush_text()
            log.write("run", f"结束 · exit={exit_code}")
            log.close()
            self._active_proc = None
            if run.log_path:
                self._logs[task.id] = Path(run.log_path)
            run.ended_at = now()
            run.exit_code = exit_code
            run.session_id = session_id or task.session_id
            run.tool_count = attempt_tool_count
            run.tools = [tools[tid].to_dict() for tid in tool_order if tid in tools]
            run.output = (final_text or "".join(accumulated))[:200000]
            for record in run.tools:
                if record.get("status") == "running":
                    record["status"] = "interrupted"
            self.store.save_run(run)
            self.signals.run_updated.emit(task.id, run.id)
            task.tool_count = max(task.tool_count, sum(1 for t in tool_order))

        if interrupted:
            if interrupted.kind == "interrupted":
                interruption = Interruption(
                    interrupted.reason,
                    interrupted.detail,
                    kind=kind,
                )
                run.interruptions.append(interruption.to_dict())
                self.store.save_run(run)
                self._log_event(
                    task.id,
                    "中断",
                    f"{REASON_LABELS.get(interrupted.reason, interrupted.reason)}：{interrupted.detail}",
                )
            return interrupted

        accumulated_text = "".join(accumulated)
        if result_received:
            if result_error:
                message = (final_text or error_text or "Agent 返回错误").strip()
                if _looks_auth_error(message):
                    return AttemptResult(
                        "failed",
                        final_text=message,
                        accumulated=accumulated_text,
                        session_id=session_id,
                        subtype=result_subtype,
                        error=f"认证失败，请先在本机完成 {adapter.label} 登录/配置：{message[:500]}",
                        exit_code=exit_code,
                        attention=True,
                    )
                if result_subtype == "error_max_turns":
                    return AttemptResult(
                        "interrupted",
                        final_text=message,
                        accumulated=accumulated_text,
                        session_id=session_id,
                        subtype=result_subtype,
                        reason=InterruptReason.INCOMPLETE,
                        detail="Agent 达到最大轮次，回复未完成",
                        exit_code=exit_code,
                    )
                if NETWORK_PATTERNS.search(message) or result_subtype in ("error_during_execution",):
                    return AttemptResult(
                        "interrupted",
                        final_text=message,
                        accumulated=accumulated_text,
                        session_id=session_id,
                        subtype=result_subtype,
                        reason=InterruptReason.NETWORK,
                        detail=message[:400],
                        exit_code=exit_code,
                    )
                return AttemptResult(
                    "failed",
                    final_text=message,
                    accumulated=accumulated_text,
                    session_id=session_id,
                    subtype=result_subtype,
                    error=message[:1200],
                    exit_code=exit_code,
                )
            return AttemptResult(
                "completed",
                final_text=final_text or accumulated_text,
                accumulated=accumulated_text,
                session_id=session_id,
                subtype=result_subtype,
                exit_code=exit_code,
            )

        # No explicit result event: adapters such as OpenCode close the stream.
        if exit_code == 0 and accumulated_text.strip():
            return AttemptResult(
                "completed",
                final_text=accumulated_text,
                accumulated=accumulated_text,
                session_id=session_id,
                subtype="eof_success",
                exit_code=exit_code,
            )
        combined_error = (error_text or " ".join(warning_lines) or f"进程退出码 {exit_code}").strip()
        if exit_code == 0 and not accumulated_text.strip() and not combined_error:
            combined_error = "Agent 正常退出但没有返回任何内容"
        if NETWORK_PATTERNS.search(combined_error):
            return AttemptResult(
                "interrupted",
                accumulated=accumulated_text,
                session_id=session_id,
                reason=InterruptReason.NETWORK,
                detail=combined_error[:500],
                exit_code=exit_code,
            )
        return AttemptResult(
            "failed",
            accumulated=accumulated_text,
            session_id=session_id,
            error=combined_error[:1200],
            exit_code=exit_code,
            attention=_looks_auth_error(combined_error),
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _spawn(self, launch: LaunchSpec) -> subprocess.Popen | None:
        env = dict(os.environ)
        env.update(launch.env)
        env.setdefault("NO_COLOR", "1")
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        try:
            return subprocess.Popen(
                launch.argv,
                cwd=launch.cwd,
                stdin=subprocess.PIPE if launch.stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                creationflags=flags,
                start_new_session=os.name != "nt",
            )
        except Exception as exc:
            self.signals.alert.emit("error", "启动 Agent 失败", str(exc))
            return None

    def _start_readers(self, proc: subprocess.Popen, out: queue.Queue) -> list[threading.Thread]:
        def read_stream(stream, channel: str, eof: str) -> None:
            try:
                for line in iter(stream.readline, ""):
                    out.put((channel, line))
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
                out.put((eof, None))

        readers = [
            threading.Thread(target=read_stream, args=(proc.stdout, "stdout", "eof_out"), daemon=True),
            threading.Thread(target=read_stream, args=(proc.stderr, "stderr", "eof_err"), daemon=True),
        ]
        for reader in readers:
            reader.start()
        return readers

    def _terminate_active(self) -> None:
        proc = self._active_proc
        if proc:
            self._terminate_process(proc)

    def _terminate_process(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=4)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _task_cwd(self, task: Task) -> str:
        raw = (task.cwd or self.config.cwd or "").strip()
        if raw:
            path = Path(os.path.expandvars(os.path.expanduser(raw)))
            if not path.exists():
                raise RuntimeError(f"工作目录不存在：{path}")
            if not path.is_dir():
                raise RuntimeError(f"工作目录不是文件夹：{path}")
            return str(path)
        path = workspaces_dir() / task.id
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _sync_task(self, task: Task, force: bool = False) -> None:
        current = time.monotonic()
        last = self._last_sync.get(task.id, 0.0)
        if not force and current - last < 0.65:
            return
        self._last_sync[task.id] = current
        try:
            self.store.save_task(task)
        except Exception:
            return
        self.signals.task_updated.emit(task.id)

    def _finish_task(self, task: Task, archive: bool = False) -> None:
        task.ended_at = task.ended_at or now()
        self.store.save_task(task)
        if archive:
            try:
                self.store.archive_task(task)
            except Exception:
                pass
        self._last_sync[task.id] = time.monotonic()
        self.signals.task_updated.emit(task.id)
        self.signals.queue_updated.emit()

    def _attention(self, task: Task, reason: str) -> None:
        task.status = TaskStatus.attention.value
        task.attention_reason = reason
        task.progress = reason
        task.ended_at = now()
        self._finish_task(task, archive=True)
        self._log_event(task.id, "人工", reason)
        self.signals.alert.emit("warning", "需要人工介入", f"「{task.title}」\n{reason}")
        if self.autopilot_active:
            self.stop_autopilot("需要人工介入，自动驾驶已停机")

    def _optimize_prompt(self, task: Task, prompt: str, label: str) -> str:
        try:
            optimized = PromptOptimizer(self.config).optimize(prompt, "user")
            self._log_event(task.id, label, f"提示词已优化（{optimized.engine}）")
            return optimized.text
        except Exception as exc:
            self._log_event(task.id, label, f"提示词优化失败，使用原文：{exc}")
            return prompt

    def _analyze(self, task: Task, final_text: str) -> AnalysisResult:
        analyzer = ResultAnalyzer(self.config, self.store.list_feedback())
        try:
            return analyzer.analyze(task.prompt, final_text)
        except Exception as exc:
            self._log_event(task.id, "验收", f"语义解析失败，回退规则：{exc}")
            from .analyzer import rule_analyze

            return rule_analyze(final_text)

    def _await_followup(self, task: Task, prompt: str, reason: str) -> dict[str, Any]:
        task.status = TaskStatus.awaiting.value
        task.pending_action = "followup"
        task.followup_prompt = prompt
        task.progress = "等待确认补做提示词"
        task.attention_reason = reason
        self._sync_task(task, force=True)
        event = threading.Event()
        self._decision_events[task.id] = event
        self._decisions.pop(task.id, None)
        self.signals.awaiting.emit(task.id)
        self.signals.alert.emit("info", "补做提示词已生成", "请在右侧详情中确认、编辑或跳过本次补做。")
        while not self._stop.is_set() and not self._force_next:
            event.wait(0.4)
            if event.is_set():
                break
        decision = self._decisions.pop(task.id, None)
        if decision is None:
            decision = {"decision": "skip", "prompt": ""}
        self._decision_events.pop(task.id, None)
        if self._force_next:
            decision = {"decision": "force_next", "prompt": ""}
            self._force_next = False
        if self._stop.is_set():
            if self._shutdown_requested:
                # Preserve the confirmation (and the generated prompt) across restarts.
                task.status = TaskStatus.awaiting.value
                task.pending_action = "followup"
                task.followup_prompt = prompt
                task.attention_reason = reason
                task.progress = "等待确认补做（应用重启后保留）"
                self.store.save_task(task)
                self.signals.task_updated.emit(task.id)
                return {"decision": "shutdown", "prompt": ""}
            decision = {"decision": "stop", "prompt": ""}
        task.pending_action = ""
        task.followup_prompt = ""
        self.store.save_task(task)
        self.signals.task_updated.emit(task.id)
        return decision

    def _set_state(self, state: str) -> None:
        if self._state == state:
            return
        self._state = state
        self.signals.state_changed.emit(state)

    def _log_event(self, task_id: str, kind: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.signals.log_line.emit(task_id, f"[{stamp}] [{kind}] {text}")

    def _write_app_error(self, detail: str) -> None:
        try:
            path = data_dir() / "engine-error.log"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n[{datetime.now().isoformat()}]\n{detail}\n")
        except Exception:
            pass


TOOL_KEYWORD_RE = re.compile(
    r"(npm install|pnpm install|pip install|git clone|docker build|pytest|npm test|"
    r"Downloading|Installing|Building|Compiling)",
    re.IGNORECASE,
)


def _snippet(text: str, length: int = 70) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[-length:] if len(text) > length else text


def _parse_autopilot(reply: str) -> dict[str, Any] | None:
    text = (reply or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def readers_finished(readers: list[threading.Thread]) -> bool:
    return all(not reader.is_alive() for reader in readers)


def _looks_auth_error(text: str) -> bool:
    return bool(
        re.search(
            r"(401|403|invalid api key|authentication|unauthorized|not logged in|"
            r"invalid_api_key|token is invalid|login fail|please run /login|登录|认证)",
            (text or "").lower(),
        )
    )

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


def now() -> float:
    return time.time()


def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex[:12]
    return f"{prefix}{value}" if prefix else value


class TaskStatus(StrEnum):
    queued = "queued"
    running = "running"
    tool = "tool"
    validating = "validating"
    interrupted = "interrupted"
    resuming = "resuming"
    patching = "patching"
    awaiting = "awaiting"
    done = "done"
    failed = "failed"
    attention = "attention"
    skipped = "skipped"
    stopped = "stopped"


STATUS_LABELS: dict[str, str] = {
    TaskStatus.queued: "待执行",
    TaskStatus.running: "执行中",
    TaskStatus.tool: "工具执行中",
    TaskStatus.validating: "校验中",
    TaskStatus.interrupted: "中断",
    TaskStatus.resuming: "续传中",
    TaskStatus.patching: "补做中",
    TaskStatus.awaiting: "待确认",
    TaskStatus.done: "已完成",
    TaskStatus.failed: "失败",
    TaskStatus.attention: "待人工",
    TaskStatus.skipped: "已跳过",
    TaskStatus.stopped: "已终止",
}

ACTIVE_STATUSES = {
    TaskStatus.running,
    TaskStatus.tool,
    TaskStatus.validating,
    TaskStatus.interrupted,
    TaskStatus.resuming,
    TaskStatus.patching,
    TaskStatus.awaiting,
}

RUNNING_STATUSES = {
    TaskStatus.running,
    TaskStatus.tool,
    TaskStatus.resuming,
    TaskStatus.patching,
}


class RunKind(StrEnum):
    main = "main"
    resume = "resume"
    followup = "followup"


RUN_KIND_LABELS: dict[str, str] = {
    RunKind.main: "主任务",
    RunKind.resume: "续传",
    RunKind.followup: "补做",
}


class RunStatus(StrEnum):
    running = "running"
    completed = "completed"
    interrupted = "interrupted"
    failed = "failed"
    stopped = "stopped"


@dataclass
class Task:
    id: str = field(default_factory=lambda: new_id("task_"))
    position: int = 0
    title: str = ""
    prompt: str = ""
    agent: str = ""  # empty means follow the global default
    cwd: str = ""
    status: str = TaskStatus.queued.value
    session_id: str = ""
    summary: str = ""
    completed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    resume_count: int = 0
    followup_count: int = 0
    tool_count: int = 0
    started_at: float = 0.0
    ended_at: float = 0.0
    progress: str = ""
    attention_reason: str = ""
    followup_prompt: str = ""
    pending_action: str = ""
    error: str = ""
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def duration(self) -> float:
        if not self.started_at:
            return 0.0
        live = self.status in RUNNING_STATUSES or self.status in (
            TaskStatus.interrupted,
            TaskStatus.validating,
            TaskStatus.awaiting,
        )
        end = self.ended_at or (now() if live else 0)
        return max(0.0, end - self.started_at)

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "position": self.position,
            "title": self.title,
            "prompt": self.prompt,
            "agent": self.agent,
            "cwd": self.cwd,
            "status": self.status,
            "session_id": self.session_id,
            "summary": self.summary,
            "completed": json.dumps(self.completed, ensure_ascii=False),
            "pending": json.dumps(self.pending, ensure_ascii=False),
            "issues": json.dumps(self.issues, ensure_ascii=False),
            "resume_count": self.resume_count,
            "followup_count": self.followup_count,
            "tool_count": self.tool_count,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "progress": self.progress,
            "attention_reason": self.attention_reason,
            "followup_prompt": self.followup_prompt,
            "pending_action": self.pending_action,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Any) -> "Task":
        data = dict(row)
        for key, default in (
            ("completed", []),
            ("pending", []),
            ("issues", []),
        ):
            try:
                data[key] = json.loads(data.get(key) or "[]")
            except Exception:
                data[key] = default
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class ToolRecord:
    id: str
    name: str
    input: str = ""
    status: str = "running"  # running | done | error
    started_at: float = field(default_factory=now)
    ended_at: float = 0.0
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "input": self.input,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "output": self.output,
        }


@dataclass
class Interruption:
    reason: str
    detail: str
    at: float = field(default_factory=now)
    kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "detail": self.detail, "at": self.at, "kind": self.kind}


@dataclass
class Run:
    id: str = field(default_factory=lambda: new_id("run_"))
    task_id: str = ""
    kind: str = RunKind.main.value
    round: int = 0
    reason: str = ""
    prompt: str = ""
    status: str = RunStatus.running.value
    started_at: float = field(default_factory=now)
    ended_at: float = 0.0
    exit_code: int | None = None
    session_id: str = ""
    output: str = ""
    log_path: str = ""
    tool_count: int = 0
    interruptions: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max(0.0, (self.ended_at or now()) - self.started_at)

    @property
    def label(self) -> str:
        base = RUN_KIND_LABELS.get(self.kind, self.kind)
        if self.kind == RunKind.main:
            return base
        return f"{base} #{self.round}"

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "kind": self.kind,
            "round": self.round,
            "reason": self.reason,
            "prompt": self.prompt,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "session_id": self.session_id,
            "output": self.output,
            "log_path": self.log_path,
            "tool_count": self.tool_count,
            "interruptions": json.dumps(self.interruptions, ensure_ascii=False),
            "tools": json.dumps(self.tools, ensure_ascii=False),
            "meta": json.dumps(self.meta, ensure_ascii=False),
        }

    @classmethod
    def from_row(cls, row: Any) -> "Run":
        data = dict(row)
        for key in ("interruptions", "tools"):
            try:
                data[key] = json.loads(data.get(key) or "[]")
            except Exception:
                data[key] = []
        try:
            data["meta"] = json.loads(data.get("meta") or "{}")
        except Exception:
            data["meta"] = {}
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class AnalysisResult:
    summary: str = ""
    completed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    needs_followup: bool = False
    source: str = "rules"

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "completed": self.completed,
            "pending": self.pending,
            "issues": self.issues,
            "needs_followup": self.needs_followup,
            "source": self.source,
        }


@dataclass
class AgentAvailability:
    key: str
    label: str
    available: bool
    path: str = ""
    version: str = ""
    note: str = ""

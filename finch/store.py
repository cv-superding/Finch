from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import AppConfig, data_dir
from .models import ACTIVE_STATUSES, Run, Task, TaskStatus, now


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    position INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT '',
    cwd TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    session_id TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    completed TEXT NOT NULL DEFAULT '[]',
    pending TEXT NOT NULL DEFAULT '[]',
    issues TEXT NOT NULL DEFAULT '[]',
    resume_count INTEGER NOT NULL DEFAULT 0,
    followup_count INTEGER NOT NULL DEFAULT 0,
    tool_count INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL DEFAULT 0,
    ended_at REAL NOT NULL DEFAULT 0,
    progress TEXT NOT NULL DEFAULT '',
    attention_reason TEXT NOT NULL DEFAULT '',
    followup_prompt TEXT NOT NULL DEFAULT '',
    pending_action TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    round INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    started_at REAL NOT NULL,
    ended_at REAL NOT NULL DEFAULT 0,
    exit_code INTEGER,
    session_id TEXT NOT NULL DEFAULT '',
    output TEXT NOT NULL DEFAULT '',
    log_path TEXT NOT NULL DEFAULT '',
    tool_count INTEGER NOT NULL DEFAULT 0,
    interruptions TEXT NOT NULL DEFAULT '[]',
    tools TEXT NOT NULL DEFAULT '[]',
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task_id, started_at);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT NOT NULL DEFAULT '',
    original TEXT NOT NULL DEFAULT '',
    corrected TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id TEXT PRIMARY KEY,
    task_title TEXT NOT NULL DEFAULT '',
    agent TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    started_at REAL NOT NULL DEFAULT 0,
    ended_at REAL NOT NULL DEFAULT 0,
    task_json TEXT NOT NULL DEFAULT '{}',
    runs_json TEXT NOT NULL DEFAULT '[]'
);
"""


class Store:
    def __init__(self, db_path: Path | None = None):
        self.path = Path(db_path) if db_path else data_dir() / "finch.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    # ---- settings -----------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def load_config(self) -> AppConfig:
        return AppConfig.from_json(self.get_setting("config", ""))

    def save_config(self, config: AppConfig) -> None:
        self.set_setting("config", config.to_json())

    # ---- tasks --------------------------------------------------------
    def list_tasks(self) -> list[Task]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY position ASC, created_at ASC").fetchall()
        return [Task.from_row(r) for r in rows]

    def get_task(self, task_id: str) -> Task | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return Task.from_row(row) if row else None

    def add_task(self, task: Task) -> Task:
        with self._conn() as conn:
            max_pos = conn.execute("SELECT COALESCE(MAX(position), -1) FROM tasks").fetchone()[0]
            task.position = int(max_pos) + 1
            task.created_at = task.created_at or now()
            task.updated_at = now()
            cols = ", ".join(task.to_row().keys())
            marks = ", ".join("?" for _ in task.to_row())
            conn.execute(f"INSERT INTO tasks ({cols}) VALUES ({marks})", tuple(task.to_row().values()))
        return task

    def save_task(self, task: Task) -> None:
        task.updated_at = now()
        data = task.to_row()
        data.pop("id", None)
        assignments = ", ".join(f"{k}=?" for k in data)
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {assignments} WHERE id=?", (*data.values(), task.id))

    def delete_task(self, task_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    def reorder_tasks(self, ordered_ids: list[str]) -> None:
        with self._conn() as conn:
            for index, task_id in enumerate(ordered_ids):
                conn.execute("UPDATE tasks SET position=? WHERE id=?", (index, task_id))

    def recover_stale_tasks(self) -> int:
        """Tasks left mid-flight by a crash become resumable interrupts."""
        count = 0
        for task in self.list_tasks():
            if task.status == TaskStatus.awaiting.value:
                task.progress = "等待确认补做（应用重启后保留）"
                self.save_task(task)
                continue
            if task.status in {s.value for s in ACTIVE_STATUSES}:
                task.status = TaskStatus.interrupted.value
                task.pending_action = ""
                task.progress = "上次运行被中断，队列启动后自动续跑"
                task.attention_reason = ""
                task.ended_at = 0
                self.save_task(task)
                count += 1
        return count

    # ---- runs ---------------------------------------------------------
    def add_run(self, run: Run) -> Run:
        data = run.to_row()
        cols = ", ".join(data.keys())
        marks = ", ".join("?" for _ in data)
        with self._conn() as conn:
            conn.execute(f"INSERT INTO runs ({cols}) VALUES ({marks})", tuple(data.values()))
        return run

    def save_run(self, run: Run) -> None:
        data = run.to_row()
        data.pop("id", None)
        assignments = ", ".join(f"{k}=?" for k in data)
        with self._conn() as conn:
            conn.execute(f"UPDATE runs SET {assignments} WHERE id=?", (*data.values(), run.id))

    def list_runs(self, task_id: str) -> list[Run]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE task_id=? ORDER BY started_at ASC", (task_id,)
            ).fetchall()
        return [Run.from_row(r) for r in rows]

    def get_run(self, run_id: str) -> Run | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return Run.from_row(row) if row else None

    def list_recent_runs(self, limit: int = 300) -> list[Run]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Run.from_row(r) for r in rows]

    # ---- analyzer feedback -------------------------------------------
    def add_feedback(self, task: str, original: str, corrected: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO feedback(task, original, corrected, created_at) VALUES(?,?,?,?)",
                (task[:2000], original[:8000], corrected[:8000], now()),
            )

    def list_feedback(self, limit: int = 3) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT task, original, corrected FROM feedback ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- history ------------------------------------------------------
    def archive_task(self, task: Task) -> None:
        runs = self.list_runs(task.id)
        with self._conn() as conn:
            conn.execute("DELETE FROM history WHERE id=?", (task.id,))
            conn.execute(
                "INSERT INTO history(id, task_title, agent, status, summary, started_at, ended_at, task_json, runs_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    task.id,
                    task.title,
                    task.agent,
                    task.status,
                    task.summary,
                    task.started_at,
                    task.ended_at or now(),
                    json.dumps(task.to_row(), ensure_ascii=False),
                    json.dumps([r.to_row() for r in runs], ensure_ascii=False),
                ),
            )

    def list_history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, task_title, agent, status, summary, started_at, ended_at "
                "FROM history ORDER BY ended_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_history(self, task_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM history WHERE id=?", (task_id,))

    def get_history(self, task_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM history WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["task"] = json.loads(data.pop("task_json") or "{}")
        data["runs"] = json.loads(data.pop("runs_json") or "[]")
        return data

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finch.config import AppConfig
from finch.models import Interruption, Run, Task, TaskStatus, ToolRecord
from finch.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="finch-store-"))
        self.store = Store(self.home / "finch.db")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_task_crud_and_order(self):
        first = self.store.add_task(Task(title="一", prompt="p1"))
        second = self.store.add_task(Task(title="二", prompt="p2"))
        third = self.store.add_task(Task(title="三", prompt="p3"))
        self.assertEqual([t.id for t in self.store.list_tasks()], [first.id, second.id, third.id])
        self.store.reorder_tasks([third.id, first.id, second.id])
        self.assertEqual([t.id for t in self.store.list_tasks()], [third.id, first.id, second.id])
        first.status = TaskStatus.done.value
        first.completed = ["a", "b"]
        first.pending = ["c"]
        first.issues = ["d"]
        self.store.save_task(first)
        loaded = self.store.get_task(first.id)
        self.assertEqual(loaded.status, TaskStatus.done.value)
        self.assertEqual(loaded.completed, ["a", "b"])
        self.assertEqual(loaded.pending, ["c"])
        self.assertEqual(loaded.issues, ["d"])
        self.store.delete_task(second.id)
        self.assertIsNone(self.store.get_task(second.id))

    def test_settings_and_config_roundtrip(self):
        self.store.set_setting("window_geometry", "abc")
        self.assertEqual(self.store.get_setting("window_geometry"), "abc")
        self.store.set_setting("window_geometry", "def")
        self.assertEqual(self.store.get_setting("window_geometry"), "def")
        config = AppConfig()
        config.agent = "codex"
        config.text_idle_timeout = 17
        config.auto_followup = False
        self.store.save_config(config)
        loaded = self.store.load_config()
        self.assertEqual(loaded.agent, "codex")
        self.assertEqual(loaded.text_idle_timeout, 17)
        self.assertFalse(loaded.auto_followup)

    def test_runs_and_feedback(self):
        task = self.store.add_task(Task(title="运行", prompt="p"))
        run = Run(task_id=task.id, kind="main", reason="测试")
        run.status = "completed"
        run.started_at = 10
        run.ended_at = 20
        run.tools = [ToolRecord("t1", "Bash", "ls", "done", output="ok").to_dict()]
        run.interruptions = [Interruption("idle_timeout", "20s").to_dict()]
        self.store.add_run(run)
        runs = self.store.list_runs(task.id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].tools[0]["name"], "Bash")
        self.assertEqual(runs[0].interruptions[0]["reason"], "idle_timeout")
        run.output = "done output"
        self.store.save_run(run)
        self.assertEqual(self.store.get_run(run.id).output, "done output")
        self.store.add_feedback("task", "before", "after")
        feedback = self.store.list_feedback()
        self.assertEqual(feedback[0]["original"], "before")
        self.assertEqual(feedback[0]["corrected"], "after")

    def test_archive_and_history(self):
        task = self.store.add_task(Task(title="归档任务", prompt="p", agent="mock"))
        task.status = TaskStatus.done.value
        task.summary = "完成"
        run = Run(task_id=task.id, kind="main", status="completed", started_at=1, ended_at=2, output="out")
        self.store.add_run(run)
        self.store.archive_task(task)
        records = self.store.list_history()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["task_title"], "归档任务")
        data = self.store.get_history(task.id)
        self.assertEqual(data["task"]["summary"], "完成")
        self.assertEqual(data["runs"][0]["output"], "out")
        self.store.delete_history(task.id)
        self.assertEqual(self.store.list_history(), [])

    def test_recover_stale_tasks(self):
        awaiting = self.store.add_task(Task(title="待确认", prompt="p"))
        awaiting.status = TaskStatus.awaiting.value
        self.store.save_task(awaiting)
        running = self.store.add_task(Task(title="运行中", prompt="p"))
        running.status = TaskStatus.running.value
        self.store.save_task(running)
        done = self.store.add_task(Task(title="完成", prompt="p"))
        done.status = TaskStatus.done.value
        self.store.save_task(done)
        recovered = self.store.recover_stale_tasks()
        self.assertEqual(recovered, 1)
        self.assertEqual(self.store.get_task(awaiting.id).status, TaskStatus.awaiting.value)
        self.assertEqual(self.store.get_task(running.id).status, TaskStatus.interrupted.value)
        self.assertEqual(self.store.get_task(done.id).status, TaskStatus.done.value)


if __name__ == "__main__":
    unittest.main()

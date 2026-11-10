from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finch.config import AppConfig
from finch.core.engine import QueueEngine
from finch.core.signals import EngineSignals
from finch.models import Task, TaskStatus
from finch.store import Store


TERMINAL = {
    TaskStatus.done.value,
    TaskStatus.failed.value,
    TaskStatus.attention.value,
    TaskStatus.stopped.value,
    TaskStatus.skipped.value,
}


def wait_until(predicate, timeout=20.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.old_home = os.environ.get("FINCH_HOME")
        self.home = tempfile.mkdtemp(prefix="finch-test-")
        os.environ["FINCH_HOME"] = self.home
        self.store = Store()
        self.config = self.store.load_config()
        self.config.agent = "mock"
        self.config.auto_followup = True
        self.config.confirm_followup = False
        self.config.optimize_followup = False
        self.config.text_idle_timeout = 2
        self.config.first_output_grace = 4
        self.config.tool_timeout = 2
        self.config.max_resumes = 2
        self.config.max_followups = 2
        self.store.save_config(self.config)
        self.cwd = Path(self.home) / "ws"
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.engine: QueueEngine | None = None

    def tearDown(self):
        if self.engine:
            self.engine.shutdown()
        if self.old_home is None:
            os.environ.pop("FINCH_HOME", None)
        else:
            os.environ["FINCH_HOME"] = self.old_home
        shutil.rmtree(self.home, ignore_errors=True)

    def _task(self, title: str, prompt: str) -> Task:
        task = Task(title=title, prompt=prompt, agent="mock", cwd=str(self.cwd))
        return self.store.add_task(task)

    def _engine(self) -> QueueEngine:
        self.engine = QueueEngine(self.store, self.config, EngineSignals())
        return self.engine

    def test_followup_loop_completes(self):
        task = self._task("实现待办清单", "请实现待办清单，包含新增、完成、删除。")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        self.assertGreaterEqual(task.followup_count, 1)
        runs = self.store.list_runs(task.id)
        self.assertEqual(runs[0].kind, "main")
        self.assertEqual(runs[1].kind, "followup")
        self.assertTrue(runs[1].prompt)
        self.assertEqual(len(self.store.list_history()), 1)

    def test_text_timeout_auto_resume(self):
        task = self._task("文本超时", "STALL_TEXT")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        self.assertEqual(task.resume_count, 1)
        runs = self.store.list_runs(task.id)
        self.assertEqual([r.kind for r in runs], ["main", "resume"])
        self.assertEqual(runs[0].status, "interrupted")
        self.assertIn("idle_timeout", [i.get("reason") for i in runs[0].interruptions])

    def test_tool_timeout_auto_resume(self):
        task = self._task("工具超时", "STALL_TOOL")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        runs = self.store.list_runs(task.id)
        self.assertEqual(runs[0].status, "interrupted")
        self.assertIn("tool_timeout", [i.get("reason") for i in runs[0].interruptions])

    def test_followup_confirmation(self):
        self.config.confirm_followup = True
        self.store.save_config(self.config)
        task = self._task("确认补做", "请实现待办清单。")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status == TaskStatus.awaiting.value, 30))
        awaiting = self.store.get_task(task.id)
        self.assertIn("补齐", awaiting.followup_prompt)
        engine.resolve_followup(task.id, "approve", awaiting.followup_prompt + "\n补充：必须运行测试")
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        runs = self.store.list_runs(task.id)
        self.assertTrue(any("必须运行测试" in run.prompt for run in runs))

    def test_max_resumes_requires_human(self):
        self.config.max_resumes = 1
        self.config.continue_prompt = "STALL_TEXT_ALWAYS 请继续执行当前未完成的任务"
        self.store.save_config(self.config)
        task = self._task("无限中断", "STALL_TEXT_ALWAYS")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.attention.value)
        self.assertIn("续传次数达到上限", task.attention_reason)
        self.assertEqual(task.resume_count, 1)

    def test_pause_between_tasks(self):
        self.config.auto_followup = False
        self.store.save_config(self.config)
        first = self._task("第一条", "请实现待办清单。")
        second = self._task("第二条", "请梳理验收标准。")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(first.id).status == TaskStatus.running.value, 10))
        engine.pause()
        self.assertTrue(wait_until(lambda: self.store.get_task(first.id).status in TERMINAL, 20))
        time.sleep(0.4)
        self.assertEqual(self.store.get_task(second.id).status, TaskStatus.queued.value)
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(second.id).status in TERMINAL, 20))

    def test_stop_queue(self):
        self.config.text_idle_timeout = 30
        self.store.save_config(self.config)
        task = self._task("终止测试", "STALL_TEXT_ALWAYS")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status == TaskStatus.running.value, 10))
        engine.stop()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 20))
        self.assertEqual(self.store.get_task(task.id).status, TaskStatus.stopped.value)

    def test_force_next(self):
        self.config.auto_followup = False
        self.store.save_config(self.config)
        first = self._task("被跳过", "STALL_TEXT_ALWAYS")
        second = self._task("下一条", "请梳理验收标准。")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: engine.active_task_id == first.id, 10))
        time.sleep(0.3)
        engine.force_next()
        self.assertTrue(wait_until(lambda: self.store.get_task(first.id).status in TERMINAL, 20))
        self.assertEqual(self.store.get_task(first.id).status, TaskStatus.skipped.value)
        self.assertTrue(wait_until(lambda: self.store.get_task(second.id).status in TERMINAL, 30))

    def test_error_event_without_result_fails_visibly(self):
        task = self._task("错误事件", "ERROR_EVENT_ONLY")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 20))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.failed.value)
        self.assertIn("Authentication", task.error)
        self.assertTrue(engine.paused)

    def test_restored_awaiting_can_be_approved(self):
        task = self._task("重启后确认补做", "请实现待办清单。")
        task.status = TaskStatus.awaiting.value
        task.session_id = "mock-session-awaiting"
        task.pending_action = "followup"
        task.followup_prompt = "请补齐空状态提示和快捷键，并运行测试。"
        task.attention_reason = "存在未完成项"
        self.store.save_task(task)
        engine = self._engine()
        engine.resolve_followup(task.id, "approve", task.followup_prompt)
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        runs = self.store.list_runs(task.id)
        self.assertEqual(runs[0].kind, "followup")
        self.assertIn("补齐", runs[0].prompt)

    def test_restart_recovery(self):
        task = self._task("断点继续", "请实现待办清单。")
        task.status = TaskStatus.running.value
        task.session_id = "mock-existing-session"
        task.progress = "上次运行中"
        self.store.save_task(task)
        recovered = self.store.recover_stale_tasks()
        self.assertEqual(recovered, 1)
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.interrupted.value)
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        runs = self.store.list_runs(task.id)
        self.assertEqual(runs[0].kind, "resume")

    def test_skip_retry_marks_attention(self):
        self.config.text_idle_timeout = 30
        self.config.first_output_grace = 20
        self.store.save_config(self.config)
        task = self._task("主动跳过续传", "STALL_TEXT_ALWAYS")
        engine = self._engine()
        engine.start()
        self.assertTrue(
            wait_until(lambda: self.store.get_task(task.id).status == TaskStatus.running.value, 10)
        )
        engine.skip_retry()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 20))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.attention.value)
        self.assertIn("人工跳过续传/补做", task.attention_reason)
        runs = self.store.list_runs(task.id)
        self.assertFalse(any(run.kind == "resume" for run in runs))

    def test_skip_awaiting_keeps_result(self):
        self.config.confirm_followup = True
        self.store.save_config(self.config)
        task = self._task("跳过待确认补做", "请实现待办清单。")
        engine = self._engine()
        engine.start()
        self.assertTrue(
            wait_until(lambda: self.store.get_task(task.id).status == TaskStatus.awaiting.value, 30)
        )
        engine.skip_retry()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 20))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        self.assertIn("人工跳过补做", task.attention_reason)
        runs = self.store.list_runs(task.id)
        self.assertEqual([run.kind for run in runs], ["main"])

    def test_followup_limit_requires_human(self):
        self.config.max_followups = 1
        self.store.save_config(self.config)
        task = self._task("补做循环", "LOOP_FOLLOWUP 请实现待办清单。")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 40))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.attention.value)
        self.assertIn("补做轮次达到上限", task.attention_reason)
        self.assertEqual(task.followup_count, 1)
        self.assertEqual([run.kind for run in self.store.list_runs(task.id)], ["main", "followup"])
        self.assertEqual(len(self.store.list_history()), 1)

    def test_auto_followup_disabled_requires_human(self):
        self.config.auto_followup = False
        self.store.save_config(self.config)
        task = self._task("关闭自动补做", "请实现待办清单。")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.attention.value)
        self.assertIn("自动补做已关闭", task.attention_reason)
        self.assertEqual([run.kind for run in self.store.list_runs(task.id)], ["main"])

    def test_two_tasks_complete_in_order(self):
        self.config.auto_followup = False
        self.store.save_config(self.config)
        first = self._task("先梳理", "请梳理一个待办清单的验收标准。")
        second = self._task("后自测", "请对刚才的实现执行自测和验证。")
        engine = self._engine()
        engine.start()
        self.assertTrue(
            wait_until(
                lambda: self.store.get_task(second.id).status in TERMINAL,
                40,
            )
        )
        self.assertEqual(self.store.get_task(first.id).status, TaskStatus.done.value)
        self.assertEqual(self.store.get_task(second.id).status, TaskStatus.done.value)
        self.assertEqual(len(self.store.list_history()), 2)


    def test_network_error_auto_resume(self):
        task = self._task("网络抖动", "NETWORK_STALL")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        self.assertEqual(task.resume_count, 1)
        runs = self.store.list_runs(task.id)
        self.assertEqual([run.kind for run in runs], ["main", "resume"])
        self.assertIn("network_error", [i.get("reason") for i in runs[0].interruptions])

    def test_incomplete_reply_auto_resume(self):
        task = self._task("截断回复", "INCOMPLETE_REPLY")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status in TERMINAL, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        self.assertEqual(task.resume_count, 1)
        runs = self.store.list_runs(task.id)
        self.assertEqual([run.kind for run in runs], ["main", "resume"])
        self.assertIn("incomplete_reply", [i.get("reason") for i in runs[0].interruptions])

    def test_retry_done_task(self):
        self.config.auto_followup = False
        self.store.save_config(self.config)
        task = self._task("重试任务", "请梳理验收标准。")
        engine = self._engine()
        engine.start()
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status == TaskStatus.done.value, 30))
        before = len(self.store.list_runs(task.id))
        engine.retry_task(task.id, autostart=True)
        self.assertTrue(wait_until(lambda: self.store.get_task(task.id).status == TaskStatus.done.value, 30))
        task = self.store.get_task(task.id)
        self.assertEqual(task.status, TaskStatus.done.value)
        self.assertEqual(task.resume_count, 0)
        self.assertEqual(len(self.store.list_runs(task.id)), before + 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finch.config import AppConfig, data_dir
from finch.core.engine import QueueEngine
from finch.models import TaskStatus
from finch.store import Store


def wait_until(predicate, timeout=25.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def reply(done=False, title="下一步", prompt="请梳理一个待办清单的验收标准。", reason="推进目标"):
    return json.dumps({"done": done, "title": title, "prompt": prompt, "reason": reason}, ensure_ascii=False)


class AutopilotTests(unittest.TestCase):
    def setUp(self):
        self.old_home = os.environ.get("FINCH_HOME")
        self.home = tempfile.mkdtemp(prefix="finch-auto-")
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
        self.config.analyzer.enabled = True
        self.config.analyzer.base_url = "http://127.0.0.1:1"
        self.config.analyzer.model = "fake"
        self.config.analyzer.timeout = 2
        self.store.save_config(self.config)
        self.engine = QueueEngine(self.store, self.config)

    def tearDown(self):
        self.engine.shutdown()
        if self.old_home is None:
            os.environ.pop("FINCH_HOME", None)
        else:
            os.environ["FINCH_HOME"] = self.old_home
        shutil.rmtree(self.home, ignore_errors=True)

    def test_generates_then_stops_on_goal_done(self):
        with patch(
            "finch.core.engine.chat_completion",
            side_effect=[reply(), reply(done=True)],
        ) as driver:
            self.engine.start_autopilot("完成待办清单", 5, 0, True)
            self.assertTrue(self.engine.autopilot_active)
            ok = wait_until(lambda: not self.engine.autopilot_active)
        self.assertTrue(ok, "autopilot should stop after goal done")
        self.assertEqual(driver.call_count, 2)
        state = self.engine.autopilot_state()
        self.assertEqual(state["rounds_used"], 1)
        self.assertEqual(state["stop_reason"], "目标达成")
        tasks = self.store.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].status, TaskStatus.done.value)

    def test_rounds_cap_stops(self):
        with patch("finch.core.engine.chat_completion", side_effect=[reply()]) as driver:
            self.engine.start_autopilot("", 1, 0, True)
            ok = wait_until(lambda: not self.engine.autopilot_active)
        self.assertTrue(ok)
        self.assertEqual(driver.call_count, 1)
        state = self.engine.autopilot_state()
        self.assertEqual(state["rounds_used"], 1)
        self.assertEqual(state["stop_reason"], "轮数用尽")

    def test_stop_and_resume_persistence(self):
        self.engine.start_autopilot("目标", 3, 0, True)
        self.engine.stop_autopilot("手动停止")
        self.assertFalse(self.engine.autopilot_active)
        self.assertFalse(self.engine.autopilot_resumable)
        path = data_dir() / "autopilot.json"
        self.assertTrue(path.exists())
        # Simulate a crash mid-run: persisted active flag becomes resumable on load.
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["active"] = True
        raw["rounds_used"] = 2
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        revived = QueueEngine(self.store, self.config)
        self.assertFalse(revived.autopilot_active)
        self.assertTrue(revived.autopilot_resumable)
        self.assertEqual(revived.autopilot_state()["rounds_used"], 2)
        revived.shutdown()

    def test_no_driver_model_stops(self):
        self.config.analyzer.enabled = False
        self.engine.update_config(self.config)
        self.engine.start_autopilot("目标", 3, 0, True)
        ok = wait_until(lambda: not self.engine.autopilot_active)
        self.assertTrue(ok)
        self.assertIn("驱动模型", self.engine.autopilot_state()["stop_reason"])


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finch.core.detector import InterruptionDetector, InterruptReason, is_incomplete_reply


class DetectorTests(unittest.TestCase):
    def test_tool_execution_is_exempt_from_text_timeout(self):
        d = InterruptionDetector(text_timeout=5, tool_timeout=600, first_output_grace=5)
        d.note_output("working")
        d.note_tool_start("t1", "Bash")
        now = d.last_activity + 30
        self.assertIsNone(d.check(now))
        d.note_tool_end("t1", now=now)
        self.assertIsNotNone(d.check(now + 6))

    def test_tool_timeout(self):
        d = InterruptionDetector(text_timeout=5, tool_timeout=20, first_output_grace=5)
        d.note_tool_start("t1", "Bash")
        check = d.check(d.tool_last_activity + 21)
        self.assertIsNotNone(check)
        self.assertEqual(check.reason, InterruptReason.TOOL)

    def test_text_timeout(self):
        d = InterruptionDetector(text_timeout=5, tool_timeout=20, first_output_grace=9)
        d.note_output("hello")
        check = d.check(d.last_activity + 6)
        self.assertIsNotNone(check)
        self.assertEqual(check.reason, InterruptReason.IDLE)

    def test_first_output_grace(self):
        d = InterruptionDetector(text_timeout=5, tool_timeout=20, first_output_grace=10)
        self.assertIsNone(d.check(d.last_activity + 8))
        self.assertIsNotNone(d.check(d.last_activity + 11))

    def test_network_error(self):
        d = InterruptionDetector(text_timeout=5, tool_timeout=20, first_output_grace=5)
        d.note_network_error("connection refused", now=100)
        check = d.check(106)
        self.assertIsNotNone(check)
        self.assertEqual(check.reason, InterruptReason.NETWORK)

    def test_incomplete_reply(self):
        self.assertTrue(is_incomplete_reply("```python\nprint(1)"))
        self.assertTrue(is_incomplete_reply("我先分析一下，接下来我会"))
        self.assertFalse(is_incomplete_reply("全部完成，验收通过。"))
        self.assertFalse(is_incomplete_reply("OK"))


if __name__ == "__main__":
    unittest.main()

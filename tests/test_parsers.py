from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finch.agents.claude import ClaudeParser
from finch.agents.codex import CodexParser
from finch.agents.cursor import CursorParser
from finch.agents.opencode import OpenCodeParser
from finch.agents.zcode import ZCodeParser


def feed(parser, *payloads):
    events = []
    for payload in payloads:
        events.extend(parser.feed_line(json.dumps(payload, ensure_ascii=False)))
    return events


class ClaudeParserTests(unittest.TestCase):
    def test_stream_tool_and_result(self):
        parser = ClaudeParser()
        events = feed(
            parser,
            {"type": "system", "subtype": "init", "session_id": "s1", "model": "m", "tools": ["Bash"]},
            {"type": "stream_event", "session_id": "s1", "event": {"type": "message_start", "message": {"id": "m1"}}},
            {
                "type": "stream_event",
                "session_id": "s1",
                "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}},
            },
            {
                "type": "stream_event",
                "session_id": "s1",
                "event": {
                    "type": "content_block_start",
                    "content_block": {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}},
                },
            },
            {
                "type": "assistant",
                "session_id": "s1",
                "message": {
                    "id": "m1",
                    "content": [
                        {"type": "text", "text": "Hello world"},
                        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "npm test"}},
                    ],
                },
            },
            {
                "type": "user",
                "session_id": "s1",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "tests passed"}]
                },
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "Hello world done",
                "session_id": "s1",
                "total_cost_usd": 0.01,
            },
        )
        kinds = [event.kind for event in events]
        self.assertIn("tool_start", kinds)
        self.assertIn("tool_update", kinds)
        self.assertIn("tool_end", kinds)
        self.assertTrue(parser.saw_result)
        self.assertEqual(parser.final_text, "Hello world done")
        self.assertEqual(parser.session_id, "s1")

    def test_auth_error_result(self):
        parser = ClaudeParser()
        feed(
            parser,
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "Failed to authenticate. API Error: 401 Invalid API Key",
                "session_id": "s2",
            },
        )
        self.assertTrue(parser.saw_result)
        self.assertTrue(parser.result_error)


class CursorParserTests(unittest.TestCase):
    def test_tool_call_events(self):
        parser = CursorParser()
        events = feed(
            parser,
            {"type": "system", "subtype": "init", "session_id": "c1"},
            {
                "type": "tool_call",
                "subtype": "started",
                "call_id": "call1",
                "tool_call": {"readToolCall": {"args": {"path": "a.txt"}}},
                "session_id": "c1",
            },
            {
                "type": "tool_call",
                "subtype": "completed",
                "call_id": "call1",
                "tool_call": {"readToolCall": {"result": {"success": {"content": "abc"}}}},
                "session_id": "c1",
            },
            {"type": "assistant", "session_id": "c1", "message": {"id": "m", "content": [{"type": "text", "text": "done"}]}},
            {"type": "result", "subtype": "success", "is_error": False, "result": "done", "session_id": "c1"},
        )
        kinds = [event.kind for event in events]
        self.assertIn("tool_start", kinds)
        self.assertIn("tool_end", kinds)
        self.assertEqual(parser.final_text, "done")


class CodexParserTests(unittest.TestCase):
    def test_json_events(self):
        parser = CodexParser()
        events = feed(
            parser,
            {"type": "thread.started", "thread_id": "th1"},
            {"type": "turn.started"},
            {
                "type": "item.started",
                "item": {"id": "i1", "type": "command_execution", "command": "npm test", "status": "in_progress"},
            },
            {
                "type": "item.completed",
                "item": {"id": "i1", "type": "command_execution", "command": "npm test", "aggregated_output": "ok", "status": "completed", "exit_code": 0},
            },
            {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "全部完成"}},
            {"type": "turn.completed", "usage": {"input_tokens": 10}},
        )
        kinds = [event.kind for event in events]
        self.assertIn("tool_start", kinds)
        self.assertIn("tool_end", kinds)
        self.assertTrue(parser.saw_result)
        self.assertEqual(parser.final_text, "全部完成")
        self.assertEqual(parser.session_id, "th1")


class OpenCodeParserTests(unittest.TestCase):
    def test_text_and_tool(self):
        parser = OpenCodeParser()
        events = feed(
            parser,
            {"type": "text", "sessionID": "o1", "part": {"id": "p1", "text": "Hel"}},
            {"type": "text", "sessionID": "o1", "part": {"id": "p1", "text": "Hello"}},
            {
                "type": "tool_use",
                "sessionID": "o1",
                "part": {
                    "id": "tool1",
                    "tool": "bash",
                    "state": {"status": "completed", "input": {"command": "npm test"}, "output": "ok"},
                },
            },
            {"type": "step_finish", "sessionID": "o1", "part": {"reason": "stop"}},
        )
        text = "".join(event.text for event in events if event.kind == "text")
        self.assertEqual(text, "Hello")
        self.assertIn("tool_start", [event.kind for event in events])
        self.assertIn("tool_end", [event.kind for event in events])
        self.assertEqual(parser.session_id, "o1")


class ZCodeParserTests(unittest.TestCase):
    def test_compact_response(self):
        parser = ZCodeParser()
        feed(parser, {"sessionId": "z1", "response": "完成", "eventCount": 3})
        self.assertEqual(parser.final_text, "完成")
        self.assertTrue(parser.saw_result)


if __name__ == "__main__":
    unittest.main()

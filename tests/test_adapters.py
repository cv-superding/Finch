from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finch.agents import ADAPTER_CLASSES, adapter_label
from finch.agents.base import AgentRequest
from finch.agents.claude import ClaudeAdapter
from finch.agents.codex import CodexAdapter
from finch.agents.cursor import CursorAdapter
from finch.agents.mock import MockAdapter
from finch.agents.opencode import OpenCodeAdapter
from finch.agents.zcode import ZCodeAdapter
from finch.config import AppConfig


class AdapterCommandTests(unittest.TestCase):
    def setUp(self):
        self.cwd = tempfile.gettempdir()
        self.config = AppConfig()
        self.config.agent_paths = {cls.key: sys.executable for cls in ADAPTER_CLASSES}
        self.config.permission_mode = "acceptEdits"
        self.config.isolate_mcp = False

    def request(self, *, resume: bool = False) -> AgentRequest:
        return AgentRequest(
            prompt="请帮我完成任务",
            cwd=self.cwd,
            session_id="session-old" if resume else "",
            is_resume=resume,
            new_session_id="session-new",
        )

    def test_all_adapters_are_registered(self):
        keys = {cls.key for cls in ADAPTER_CLASSES}
        self.assertEqual(keys, {"claude", "codex", "zcode", "opencode", "cursor", "mock"})
        self.assertEqual(adapter_label("claude"), "Claude Code")

    def test_claude_command_and_stdin(self):
        adapter = ClaudeAdapter(self.config)
        request = self.request()
        args = adapter._args(request)
        self.assertIn("stream-json", args)
        self.assertIn("--include-partial-messages", args)
        self.assertIn("--session-id", args)
        self.assertIn("session-new", args)
        self.assertIn("--permission-mode", args)
        self.assertIn("acceptEdits", args)
        launch = adapter.build_launch(request)
        self.assertEqual(launch.stdin, request.prompt)
        self.assertEqual(launch.cwd, self.cwd)
        self.assertEqual(launch.argv[0], sys.executable)
        self.assertEqual(launch.argv[1:], args)
        resume_args = adapter._args(self.request(resume=True))
        self.assertIn("--resume", resume_args)
        self.assertIn("session-old", resume_args)
        self.assertNotIn("--session-id", resume_args)

    def test_claude_strict_mcp(self):
        self.config.isolate_mcp = True
        args = ClaudeAdapter(self.config)._args(self.request())
        self.assertIn("--strict-mcp-config", args)
        self.assertIn("--mcp-config", args)
        self.assertIn("{}", args)

    def test_codex_command(self):
        adapter = CodexAdapter(self.config)
        prompt = "请实现功能"
        request = AgentRequest(prompt=prompt, cwd=self.cwd)
        args = adapter._args(request)
        self.assertEqual(args[:2], ["exec", "--json"])
        self.assertIn("--full-auto", args)
        self.assertIn(prompt, args)
        self.assertIsNone(adapter.build_launch(request).stdin)
        resume = AgentRequest(prompt=prompt, cwd=self.cwd, session_id="thread-1", is_resume=True)
        resume_args = adapter._args(resume)
        self.assertEqual(resume_args[:3], ["exec", "resume", "thread-1"])
        self.assertIn(prompt, resume_args)

    def test_zcode_command(self):
        adapter = ZCodeAdapter(self.config)
        request = self.request()
        args = adapter._args(request)
        self.assertIn("--prompt", args)
        self.assertIn(request.prompt, args)
        self.assertIn("--cwd", args)
        self.assertIn(self.cwd, args)
        self.assertIn("--no-color", args)
        self.assertNotIn("--resume", args)
        resume_args = adapter._args(self.request(resume=True))
        self.assertIn("--resume", resume_args)
        self.assertIn("session-old", resume_args)

    def test_opencode_command(self):
        adapter = OpenCodeAdapter(self.config)
        request = self.request()
        args = adapter._args(request)
        self.assertEqual(args[:3], ["run", "--format", "json"])
        self.assertEqual(args[-1], request.prompt)
        self.assertNotIn("--session", args)
        resume_args = adapter._args(self.request(resume=True))
        self.assertIn("--session", resume_args)
        self.assertIn("session-old", resume_args)

    def test_cursor_command(self):
        adapter = CursorAdapter(self.config)
        request = self.request()
        args = adapter._args(request)
        self.assertIn("--print", args)
        self.assertIn("stream-json", args)
        self.assertIn("--force", args)
        self.assertEqual(args[-1], request.prompt)
        resume_args = adapter._args(self.request(resume=True))
        self.assertIn("--resume", resume_args)
        self.assertIn("session-old", resume_args)

    def test_mock_command_and_availability(self):
        adapter = MockAdapter(self.config)
        request = self.request()
        args = adapter._args(request)
        self.assertTrue(args[0].endswith("mock_agent.py"))
        self.assertIn("--session-id", args)
        resume_args = adapter._args(self.request(resume=True))
        self.assertIn("--resume", resume_args)
        self.assertTrue(adapter.availability().available)

    def test_extra_args_are_appended(self):
        self.config.agent_extra_args["codex"] = "--foo bar"
        args = CodexAdapter(self.config)._args(self.request())
        self.assertIn("--foo", args)
        self.assertIn("bar", args)


    def test_availability_with_configured_path(self):
        adapter = ClaudeAdapter(self.config)
        availability = adapter.availability()
        self.assertTrue(availability.available)
        self.assertTrue(availability.version)
        self.assertEqual(availability.path, sys.executable)

    def test_availability_with_missing_path(self):
        missing = str(Path(tempfile.gettempdir()) / "definitely-missing-finch-agent.exe")
        self.config.agent_paths["claude"] = missing
        availability = ClaudeAdapter(self.config).availability()
        self.assertFalse(availability.available)


if __name__ == "__main__":
    unittest.main()

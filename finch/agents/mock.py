from __future__ import annotations

import sys
from pathlib import Path

from .base import AgentAdapter, AgentEventParser, AgentRequest
from .claude import ClaudeParser


MOCK_AGENT = Path(__file__).with_name("mock_agent.py")


class MockAdapter(AgentAdapter):
    key = "mock"
    label = "示例 Agent"
    color = "#7C5CFF"
    badge = "EX"
    description = "本地脚本模拟完整流式协议，用于演示与自测，不消耗额度"
    stdin_prompt = True

    def find_executable(self) -> str:
        return sys.executable

    def availability(self):
        from ..models import AgentAvailability

        return AgentAvailability(self.key, self.label, True, path=str(MOCK_AGENT), version="built-in")

    def _args(self, request: AgentRequest) -> list[str]:
        args = [str(MOCK_AGENT)]
        if request.is_resume and request.session_id:
            args += ["--resume", request.session_id]
        elif request.new_session_id:
            args += ["--session-id", request.new_session_id]
        return args

    def create_parser(self) -> AgentEventParser:
        return ClaudeParser()

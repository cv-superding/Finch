from __future__ import annotations

import json
from typing import Any

from .base import AgentAdapter, AgentEvent, AgentEventParser, AgentRequest
from .claude import ClaudeParser


class ZCodeParser(ClaudeParser):
    """ZCode's stream-json is close to Claude Code's event protocol.

    Unknown lines are retained; a top-level ``response`` object is treated as
    a final result so builds that use the compact JSON shape still finish.
    """

    def parse(self, payload: dict[str, Any]) -> list[AgentEvent]:
        events = super().parse(payload)
        if events and all(ev.kind == "raw" for ev in events):
            sid = str(payload.get("sessionId") or payload.get("session_id") or "")
            if "response" in payload and payload.get("response") is not None:
                return [
                    AgentEvent(
                        "result",
                        text=str(payload.get("response") or ""),
                        data={"session_id": sid, "is_error": False, "subtype": "success"},
                    )
                ]
            if payload.get("type") in ("error", "turn.failed"):
                return [AgentEvent("error", text=json.dumps(payload, ensure_ascii=False)[:4000])]
        return events


class ZCodeAdapter(AgentAdapter):
    key = "zcode"
    label = "ZCode"
    color = "#316BFF"
    badge = "ZC"
    description = "Z.ai ZCode CLI，支持 stream-json 与 --resume 会话恢复"
    default_executables = ("zcode", "zcode.exe")

    def _args(self, request: AgentRequest) -> list[str]:
        args = [
            "--prompt",
            request.prompt,
            "--output-format",
            "stream-json",
            "--cwd",
            request.cwd,
            "--no-color",
        ]
        if request.is_resume and request.session_id:
            args += ["--resume", request.session_id]
        args += self.extra_args()
        return args

    def create_parser(self) -> AgentEventParser:
        return ZCodeParser()

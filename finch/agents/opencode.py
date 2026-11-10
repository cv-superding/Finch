from __future__ import annotations

import json
from typing import Any

from .base import AgentAdapter, AgentEvent, AgentEventParser, AgentRequest


class OpenCodeParser(AgentEventParser):
    def __init__(self) -> None:
        super().__init__()
        self._texts: dict[str, str] = {}
        self._tools: set[str] = set()

    def parse(self, payload: dict[str, Any]) -> list[AgentEvent]:
        etype = str(payload.get("type") or "")
        sid = str(payload.get("sessionID") or payload.get("session_id") or "")
        part = payload.get("part") or {}
        if not isinstance(part, dict):
            part = {}
        events: list[AgentEvent] = []
        if etype == "text":
            text = str(part.get("text") or "")
            pid = str(part.get("id") or "")
            old = self._texts.get(pid, "")
            if text:
                self._texts[pid] = text
                if text.startswith(old):
                    delta = text[len(old):]
                else:
                    delta = text
                if delta:
                    events.append(AgentEvent("text", text=delta, data={"session_id": sid}))
        elif etype == "reasoning":
            text = str(part.get("text") or "")
            if text:
                events.append(AgentEvent("thinking", text=text, data={"session_id": sid}))
        elif etype == "tool_use":
            tool_id = str(part.get("id") or part.get("callID") or "")
            state = part.get("state") or {}
            status = str(state.get("status") or "")
            name = str(part.get("tool") or state.get("title") or "tool")
            tool_input = state.get("input")
            output = state.get("output") or state.get("error") or ""
            if isinstance(tool_input, (dict, list)):
                tool_input = json.dumps(tool_input, ensure_ascii=False)
            if tool_id not in self._tools:
                self._tools.add(tool_id)
                events.append(
                    AgentEvent(
                        "tool_start",
                        data={"session_id": sid, "tool_id": tool_id, "name": name, "input": str(tool_input or "")},
                    )
                )
            events.append(
                AgentEvent(
                    "tool_end",
                    data={
                        "session_id": sid,
                        "tool_id": tool_id,
                        "name": name,
                        "output": str(output)[:6000],
                        "is_error": status == "error",
                    },
                )
            )
        elif etype in ("step_start", "step_finish"):
            reason = str(part.get("reason") or "")
            events.append(
                AgentEvent(
                    "progress",
                    data={"session_id": sid, "status": etype, "reason": reason},
                )
            )
        elif etype == "error":
            error = payload.get("error") or {}
            message = ""
            if isinstance(error, dict):
                data = error.get("data") or {}
                message = str(data.get("message") or error.get("name") or "") if isinstance(data, dict) else str(data)
            events.append(
                AgentEvent("error", text=message or json.dumps(payload, ensure_ascii=False)[:2000], data={"session_id": sid})
            )
        else:
            events.append(AgentEvent("raw", text=json.dumps(payload, ensure_ascii=False)[:2000]))
        return events


class OpenCodeAdapter(AgentAdapter):
    key = "opencode"
    label = "OpenCode"
    color = "#3B82F6"
    badge = "OC"
    description = "OpenCode run --format json，支持 --session 会话恢复"
    default_executables = ("opencode", "opencode.exe")

    def _args(self, request: AgentRequest) -> list[str]:
        args = ["run", "--format", "json"]
        if request.is_resume and request.session_id:
            args += ["--session", request.session_id]
        args.append(request.prompt)
        args += self.extra_args()
        return args

    def create_parser(self) -> AgentEventParser:
        return OpenCodeParser()

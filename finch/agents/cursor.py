from __future__ import annotations

import json
from typing import Any

from .base import AgentAdapter, AgentEvent, AgentEventParser, AgentRequest
from .claude import ClaudeParser


class CursorParser(ClaudeParser):
    def parse(self, payload: dict[str, Any]) -> list[AgentEvent]:
        etype = payload.get("type")
        sid = str(payload.get("session_id") or payload.get("sessionId") or "")
        if etype == "tool_call":
            subtype = str(payload.get("subtype") or "")
            call_id = str(payload.get("call_id") or payload.get("callId") or "")
            call = payload.get("tool_call") or {}
            name = "tool"
            detail: Any = call
            if isinstance(call, dict) and call:
                key = next(iter(call.keys()))
                name = {
                    "readToolCall": "Read",
                    "writeToolCall": "Write",
                    "shellToolCall": "Bash",
                    "grepToolCall": "Grep",
                    "globToolCall": "Glob",
                    "listToolCall": "List",
                }.get(key, key.replace("ToolCall", ""))
                detail = call[key]
            if isinstance(detail, dict):
                args = detail.get("args") or {}
                result = detail.get("result") or {}
                detail = json.dumps(args if subtype == "started" else result, ensure_ascii=False)
            if subtype == "started":
                return [
                    AgentEvent(
                        "tool_start",
                        data={"session_id": sid, "tool_id": call_id, "name": name, "input": str(detail)[:4000]},
                    )
                ]
            if subtype in ("completed", "failed"):
                return [
                    AgentEvent(
                        "tool_end",
                        data={
                            "session_id": sid,
                            "tool_id": call_id,
                            "name": name,
                            "output": str(detail)[:6000],
                            "is_error": subtype == "failed",
                        },
                    )
                ]
            return []
        if etype in ("thinking", "reasoning"):
            text = str(payload.get("text") or (payload.get("message") or {}).get("text") or "")
            return [AgentEvent("thinking", text=text, data={"session_id": sid})] if text else []
        events = super().parse(payload)
        if events and all(ev.kind == "raw" for ev in events):
            sid = str(
                payload.get("session_id")
                or payload.get("sessionId")
                or payload.get("chat_id")
                or payload.get("chatId")
                or ""
            )
            etype = payload.get("type")
            if etype in ("result", "done", "completion"):
                text = payload.get("result") or payload.get("text") or payload.get("message") or ""
                return [
                    AgentEvent(
                        "result",
                        text=str(text),
                        data={
                            "session_id": sid,
                            "is_error": bool(payload.get("is_error")),
                            "subtype": str(payload.get("subtype") or "success"),
                        },
                    )
                ]
            if etype == "error":
                return [AgentEvent("error", text=str(payload.get("message") or payload))]
            if etype == "text":
                return [AgentEvent("text", text=str(payload.get("text") or ""))]
        return events


class CursorAdapter(AgentAdapter):
    key = "cursor"
    label = "Cursor Agent"
    color = "#5B5BD6"
    badge = "CU"
    description = "Cursor Agent CLI，-p 非交互模式与 chat 恢复"
    default_executables = ("cursor-agent", "cursor-agent.exe")

    def _args(self, request: AgentRequest) -> list[str]:
        args = ["--print", "--output-format", "stream-json", "--force"]
        if request.is_resume and request.session_id:
            args += ["--resume", request.session_id]
        args += self.extra_args()
        args.append(request.prompt)
        return args

    def create_parser(self) -> AgentEventParser:
        return CursorParser()

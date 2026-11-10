from __future__ import annotations

import json
from typing import Any

from ..config import AppConfig
from ..models import AgentAvailability
from .base import AgentAdapter, AgentEvent, AgentEventParser, AgentRequest, _flatten_content


def _tool_input(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:4000]
    try:
        return json.dumps(value, ensure_ascii=False)[:4000]
    except Exception:
        return str(value)[:4000]


class ClaudeParser(AgentEventParser):
    def __init__(self) -> None:
        super().__init__()
        self._msg_id = ""
        self._partial_msgs: set[str] = set()
        self._partial_tools: set[str] = set()
        self._started_tools: set[str] = set()
        self._tool_names: dict[str, str] = {}

    def parse(self, payload: dict[str, Any]) -> list[AgentEvent]:
        sid = payload.get("session_id") or payload.get("sessionId") or ""
        etype = payload.get("type")
        events: list[AgentEvent] = []

        if etype == "system":
            subtype = payload.get("subtype")
            if subtype == "init":
                events.append(
                    AgentEvent(
                        "init",
                        data={
                            "session_id": sid,
                            "model": payload.get("model", ""),
                            "tools": payload.get("tools", []),
                            "mcp_servers": payload.get("mcp_servers", []),
                            "permission_mode": payload.get("permissionMode", ""),
                        },
                    )
                )
            elif subtype == "api_retry":
                events.append(
                    AgentEvent(
                        "retry",
                        text="",
                        data={
                            "session_id": sid,
                            "attempt": payload.get("attempt"),
                            "max_retries": payload.get("max_retries"),
                            "error": payload.get("error") or "",
                            "status": payload.get("error_status"),
                            "delay_ms": payload.get("retry_delay_ms"),
                        },
                    )
                )
            elif subtype in ("status", "hook_started", "hook_response"):
                events.append(
                    AgentEvent("progress", data={"session_id": sid, "status": payload.get("status", subtype)})
                )
            else:
                events.append(AgentEvent("raw", text=json.dumps(payload, ensure_ascii=False)[:2000]))
            return events

        if etype == "stream_event":
            event = payload.get("event") or {}
            et = event.get("type")
            if et == "message_start":
                message = event.get("message") or {}
                self._msg_id = str(message.get("id") or "")
            elif et == "content_block_start":
                block = event.get("content_block") or {}
                if block.get("type") == "text":
                    self._msg_id = self._msg_id or ""
                elif block.get("type") == "tool_use":
                    tool_id = str(block.get("id") or "")
                    name = str(block.get("name") or "tool")
                    self._tool_names[tool_id] = name
                    self._partial_tools.add(tool_id)
                    self._started_tools.add(tool_id)
                    events.append(
                        AgentEvent(
                            "tool_start",
                            data={
                                "session_id": sid,
                                "tool_id": tool_id,
                                "name": name,
                                "input": _tool_input(block.get("input")),
                            },
                        )
                    )
            elif et == "content_block_delta":
                delta = event.get("delta") or {}
                dtype = delta.get("type")
                if dtype == "text_delta":
                    text = str(delta.get("text") or "")
                    if text:
                        if self._msg_id:
                            self._partial_msgs.add(self._msg_id)
                        events.append(AgentEvent("text", text=text, data={"session_id": sid}))
                elif dtype == "thinking_delta":
                    text = str(delta.get("thinking") or "")
                    if text:
                        events.append(AgentEvent("thinking", text=text, data={"session_id": sid}))
            elif et == "message_delta":
                usage = event.get("usage") or {}
                if usage:
                    events.append(AgentEvent("progress", data={"session_id": sid, "usage": usage}))
            return events

        if etype == "assistant":
            message = payload.get("message") or {}
            msg_id = str(message.get("id") or "")
            if payload.get("error"):
                events.append(
                    AgentEvent(
                        "error",
                        text=str(payload.get("error")),
                        data={"session_id": sid, "raw_error": payload.get("error")},
                    )
                )
                return events
            blocks = message.get("content") or []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    if msg_id not in self._partial_msgs:
                        text = str(block.get("text") or "")
                        if text:
                            events.append(AgentEvent("text", text=text, data={"session_id": sid, "whole": True}))
                elif btype == "thinking":
                    text = str(block.get("thinking") or "")
                    if text:
                        events.append(AgentEvent("thinking", text=text, data={"session_id": sid, "whole": True}))
                elif btype == "tool_use":
                    tool_id = str(block.get("id") or "")
                    name = str(block.get("name") or "tool")
                    self._tool_names[tool_id] = name
                    if tool_id in self._started_tools:
                        events.append(
                            AgentEvent(
                                "tool_update",
                                data={
                                    "session_id": sid,
                                    "tool_id": tool_id,
                                    "name": name,
                                    "input": _tool_input(block.get("input")),
                                },
                            )
                        )
                    else:
                        self._started_tools.add(tool_id)
                        events.append(
                            AgentEvent(
                                "tool_start",
                                data={
                                    "session_id": sid,
                                    "tool_id": tool_id,
                                    "name": name,
                                    "input": _tool_input(block.get("input")),
                                },
                            )
                        )
            return events

        if etype == "user":
            message = payload.get("message") or {}
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_id = str(block.get("tool_use_id") or "")
                    output = _flatten_content(block.get("content"))
                    self.closed_tools.add(tool_id)
                    events.append(
                        AgentEvent(
                            "tool_end",
                            data={
                                "session_id": sid,
                                "tool_id": tool_id,
                                "name": self._tool_names.get(tool_id, "tool"),
                                "output": output[:6000],
                                "is_error": bool(block.get("is_error")),
                            },
                        )
                    )
            return events

        if etype == "result":
            text = str(payload.get("result") or "")
            subtype = str(payload.get("subtype") or "")
            events.append(
                AgentEvent(
                    "result",
                    text=text,
                    data={
                        "session_id": sid,
                        "is_error": bool(payload.get("is_error")),
                        "subtype": subtype,
                        "duration_ms": payload.get("duration_ms"),
                        "duration_api_ms": payload.get("duration_api_ms"),
                        "num_turns": payload.get("num_turns"),
                        "total_cost_usd": payload.get("total_cost_usd"),
                        "api_error_status": payload.get("api_error_status"),
                        "usage": payload.get("usage"),
                    },
                )
            )
            return events

        if etype in ("rate_limit_event", "rate_limit"):
            events.append(
                AgentEvent(
                    "retry",
                    data={
                        "session_id": sid,
                        "error": etype,
                        "status": payload.get("status") or payload.get("rate_limit_info"),
                    },
                )
            )
            return events

        if etype in ("prompt_suggestion", "tool_progress", "tool_use_summary"):
            text = payload.get("suggestion") or payload.get("summary") or ""
            return [AgentEvent("progress", text=str(text), data={"session_id": sid, "type": etype})]

        if etype == "error":
            return [
                AgentEvent(
                    "error",
                    text=str(payload.get("message") or payload.get("error") or ""),
                    data={"session_id": sid},
                )
            ]

        return [AgentEvent("raw", text=json.dumps(payload, ensure_ascii=False)[:2000])]


class ClaudeAdapter(AgentAdapter):
    key = "claude"
    label = "Claude Code"
    color = "#D97757"
    badge = "CC"
    description = "Anthropic Claude Code CLI，支持 stream-json 与会话恢复"
    default_executables = ("claude", "claude.exe")
    stdin_prompt = True

    def _args(self, request: AgentRequest) -> list[str]:
        args = [
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        if request.is_resume and request.session_id:
            args += ["--resume", request.session_id]
        elif request.new_session_id:
            args += ["--session-id", request.new_session_id]
        if self.config.permission_mode:
            args += ["--permission-mode", self.config.permission_mode]
        if self.config.isolate_mcp:
            args += ["--strict-mcp-config", "--mcp-config", "{}"]
        args += self.extra_args()
        return args

    def create_parser(self) -> AgentEventParser:
        return ClaudeParser()

from __future__ import annotations

import json
from typing import Any

from .base import AgentAdapter, AgentEvent, AgentEventParser, AgentRequest


class CodexParser(AgentEventParser):
    def __init__(self) -> None:
        super().__init__()
        self._messages: list[str] = []
        self._tools: dict[str, dict[str, Any]] = {}
        self.turn_completed = False

    def parse(self, payload: dict[str, Any]) -> list[AgentEvent]:
        etype = str(payload.get("type") or "")
        events: list[AgentEvent] = []
        if etype == "thread.started":
            sid = str(payload.get("thread_id") or payload.get("threadId") or "")
            events.append(AgentEvent("init", data={"session_id": sid}))
        elif etype == "turn.started":
            events.append(AgentEvent("progress", data={"status": "thinking"}))
        elif etype in ("item.started", "item.updated", "item.completed"):
            item = payload.get("item") or {}
            itype = str(item.get("type") or "")
            item_id = str(item.get("id") or "")
            if itype == "agent_message":
                text = str(item.get("text") or "")
                if etype == "item.completed" and text:
                    self._messages.append(text)
                    events.append(AgentEvent("text", text=text, data={"whole": True}))
            elif itype in ("command_execution", "file_change", "mcp_tool_call", "web_search", "patch_apply"):
                name = {
                    "command_execution": "Bash",
                    "file_change": "FileChange",
                    "mcp_tool_call": item.get("tool") or "MCP",
                    "web_search": "WebSearch",
                    "patch_apply": "ApplyPatch",
                }.get(itype, itype)
                summary = (
                    item.get("command")
                    or item.get("tool")
                    or item.get("query")
                    or item.get("changes")
                    or ""
                )
                if isinstance(summary, (dict, list)):
                    summary = json.dumps(summary, ensure_ascii=False)
                if etype == "item.started":
                    self._tools[item_id] = {"name": name, "input": str(summary)[:4000]}
                    events.append(
                        AgentEvent(
                            "tool_start",
                            data={"tool_id": item_id, "name": name, "input": str(summary)[:4000]},
                        )
                    )
                elif etype == "item.updated":
                    output = item.get("aggregated_output") or item.get("output") or ""
                    events.append(
                        AgentEvent(
                            "tool_update",
                            data={"tool_id": item_id, "name": name, "output": str(output)[:4000]},
                        )
                    )
                else:
                    output = item.get("aggregated_output") or item.get("output") or ""
                    status = str(item.get("status") or "")
                    is_error = status not in ("completed", "success") or bool(item.get("exit_code"))
                    events.append(
                        AgentEvent(
                            "tool_end",
                            data={
                                "tool_id": item_id,
                                "name": name,
                                "output": str(output)[:6000],
                                "is_error": is_error,
                                "exit_code": item.get("exit_code"),
                            },
                        )
                    )
            elif itype == "reasoning":
                text = str(item.get("text") or "")
                if text:
                    events.append(AgentEvent("thinking", text=text, data={"whole": True}))
            else:
                events.append(AgentEvent("raw", text=json.dumps(item, ensure_ascii=False)[:1500]))
        elif etype == "turn.completed":
            self.turn_completed = True
            final = self._messages[-1] if self._messages else ""
            usage = payload.get("usage") or {}
            events.append(
                AgentEvent(
                    "result",
                    text=final,
                    data={"is_error": False, "subtype": "success", "usage": usage},
                )
            )
        elif etype in ("turn.failed", "error"):
            message = (
                payload.get("message")
                or (payload.get("error") or {}).get("message")
                or json.dumps(payload, ensure_ascii=False)
            )
            events.append(AgentEvent("error", text=str(message)[:4000]))
            events.append(
                AgentEvent(
                    "result",
                    text="",
                    data={"is_error": True, "subtype": "turn_failed"},
                )
            )
        else:
            events.append(AgentEvent("raw", text=json.dumps(payload, ensure_ascii=False)[:2000]))
        return events


class CodexAdapter(AgentAdapter):
    key = "codex"
    label = "Codex CLI"
    color = "#10A37F"
    badge = "CX"
    description = "OpenAI Codex CLI，exec --json 事件流，支持 thread 恢复"
    default_executables = ("codex", "codex.exe")

    def _args(self, request: AgentRequest) -> list[str]:
        extra = self.extra_args()
        if request.is_resume and request.session_id:
            args = [
                "exec",
                "resume",
                request.session_id,
                "--json",
                "--skip-git-repo-check",
                "--full-auto",
                request.prompt,
            ]
            return args + extra
        args = ["exec", "--json", "--skip-git-repo-check", "--full-auto", request.prompt]
        return args + extra

    def create_parser(self) -> AgentEventParser:
        return CodexParser()

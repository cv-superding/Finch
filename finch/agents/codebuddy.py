from __future__ import annotations

from typing import Any

from .base import AgentEvent, AgentRequest, LaunchSpec
from .claude import ClaudeAdapter, ClaudeParser


class CodeBuddyParser(ClaudeParser):
    """CodeBuddy Code 的 stream-json 与 Claude Code 对齐。

    额外处理 cbc 的用量/后台任务事件，以及 ``--output-format json`` 的顶层
    ``result`` 对象，让引擎在两种输出格式下都能正确判定「跑完了」。
    """

    def parse(self, payload: dict[str, Any]) -> list[AgentEvent]:
        etype = payload.get("type")
        subtype = str(payload.get("subtype") or "")
        sid = str(payload.get("session_id") or payload.get("sessionId") or "")

        if etype == "system" and subtype in (
            "usage_update",
            "task_started",
            "task_progress",
            "task_updated",
            "task_notification",
        ):
            return [
                AgentEvent(
                    "progress",
                    text=str(payload.get("summary") or payload.get("description") or subtype),
                    data={"session_id": sid, "type": subtype},
                )
            ]

        if not etype and "result" in payload:
            return [
                AgentEvent(
                    "result",
                    text=str(payload.get("result") or ""),
                    data={
                        "session_id": sid,
                        "is_error": bool(payload.get("is_error")),
                        "subtype": str(payload.get("subtype") or "success"),
                    },
                )
            ]
        return super().parse(payload)


class CodeBuddyAdapter(ClaudeAdapter):
    key = "codebuddy"
    label = "CodeBuddy Code"
    color = "#1E6FFF"
    badge = "CB"
    description = "CodeBuddy Code CLI（codebuddy / cbc），兼容 Claude stream-json，支持 -y 无头执行与 --resume"
    default_executables = ("codebuddy", "cbc", "codebuddy.exe", "cbc.exe")
    stdin_prompt = True

    def _args(self, request: AgentRequest) -> list[str]:
        # -y 是 CodeBuddy 非交互模式的必需参数；不加会被权限拦截，
        # 文件读写、命令执行都会失败。
        args = [
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "-y",
        ]
        if request.is_resume and request.session_id:
            args += ["--resume", request.session_id]
        if self.config.permission_mode:
            args += ["--permission-mode", self.config.permission_mode]
        args += self.extra_args()
        return args

    def build_launch(self, request: AgentRequest) -> LaunchSpec:
        spec = super().build_launch(request)
        # 纯 -p 单发模式不支持跨轮后台任务，禁用后 CLI 不会尝试推回事件。
        spec.env.setdefault("CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS", "1")
        return spec

    def create_parser(self):
        return CodeBuddyParser()

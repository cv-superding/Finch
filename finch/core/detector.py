from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


class InterruptReason:
    IDLE = "idle_timeout"
    TOOL = "tool_timeout"
    NETWORK = "network_error"
    PROCESS = "process_error"
    INCOMPLETE = "incomplete_reply"
    USER = "user_stop"


REASON_LABELS = {
    InterruptReason.IDLE: "纯文本输出超时",
    InterruptReason.TOOL: "工具执行超时",
    InterruptReason.NETWORK: "网络/连接异常",
    InterruptReason.PROCESS: "进程异常退出",
    InterruptReason.INCOMPLETE: "回复不完整",
    InterruptReason.USER: "人工终止",
}

NETWORK_PATTERNS = re.compile(
    r"(ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|socket hang up|connection reset|"
    r"connection refused|network error|fetch failed|request timed out|stream ended|"
    r"prematurely closed|TLS handshake|upstream connect error|502 Bad Gateway|503 Service|"
    r"504 Gateway|overloaded_error|api_retry|authentication_failed)",
    re.IGNORECASE,
)

TOOL_HINTS = re.compile(
    r"(npm install|pnpm install|yarn install|pip install|git clone|docker build|docker compose|"
    r"cargo build|go build|make\b|pytest|npm test|pnpm test|yarn test|webpack|vite build|"
    r"正在下载|正在安装|正在执行|Building|Installing|Downloading|Compiling|Running tests)",
    re.IGNORECASE,
)


@dataclass
class InterruptCheck:
    reason: str
    detail: str


@dataclass
class InterruptionDetector:
    text_timeout: float = 30.0
    tool_timeout: float = 600.0
    first_output_grace: float = 90.0

    phase: str = "text"
    started_at: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    tool_last_activity: float = 0.0
    tool_ids: set[str] = field(default_factory=set)
    tool_names: dict[str, str] = field(default_factory=dict)
    got_output: bool = False
    network_detail: str = ""
    network_at: float = 0.0
    children_active: bool = False
    implicit_tool: bool = False
    text_chars: int = 0

    def touch(self, now: float | None = None) -> None:
        current = now if now is not None else time.monotonic()
        self.last_activity = current
        if self.phase == "tool":
            self.tool_last_activity = current

    def note_output(self, text: str = "", now: float | None = None) -> None:
        current = now if now is not None else time.monotonic()
        self.got_output = True
        self.text_chars += len(text)
        self.last_activity = current

    def note_tool_start(self, tool_id: str, name: str, now: float | None = None) -> None:
        current = now if now is not None else time.monotonic()
        self.tool_ids.add(tool_id)
        self.tool_names[tool_id] = name
        self.phase = "tool"
        self.tool_last_activity = current
        self.last_activity = current

    def note_tool_end(self, tool_id: str, now: float | None = None) -> None:
        current = now if now is not None else time.monotonic()
        self.tool_ids.discard(tool_id)
        if not self.tool_ids and not self.implicit_tool and not self.children_active:
            self.phase = "text"
        self.last_activity = current
        self.tool_last_activity = current

    def note_tool_activity(self, now: float | None = None) -> None:
        current = now if now is not None else time.monotonic()
        self.tool_last_activity = current
        self.last_activity = current

    def note_children(self, active: bool, now: float | None = None) -> None:
        current = now if now is not None else time.monotonic()
        if active and not self.children_active:
            self.children_active = True
            self.phase = "tool"
            self.tool_last_activity = current
            self.last_activity = current
        elif not active and self.children_active:
            self.children_active = False
            if not self.tool_ids and not self.implicit_tool:
                self.phase = "text"
                self.last_activity = current

    def note_implicit_tool(self, active: bool, now: float | None = None) -> None:
        current = now if now is not None else time.monotonic()
        self.implicit_tool = active
        if active:
            self.phase = "tool"
            self.tool_last_activity = current
        elif not self.tool_ids and not self.children_active:
            self.phase = "text"
        self.last_activity = current

    def note_network_error(self, detail: str, now: float | None = None) -> None:
        self.network_detail = detail.strip()[:500]
        self.network_at = now if now is not None else time.monotonic()
        self.last_activity = self.network_at

    def check(self, now: float | None = None) -> InterruptCheck | None:
        current = now if now is not None else time.monotonic()
        tool_active = bool(self.tool_ids) or self.children_active or self.implicit_tool or self.phase == "tool"
        if tool_active:
            idle = current - max(self.tool_last_activity, self.last_activity)
            if idle > self.tool_timeout:
                names = ", ".join(sorted(set(self.tool_names.values()))) or "命令/工具"
                return InterruptCheck(
                    InterruptReason.TOOL,
                    f"{names} 已连续 {int(idle)}s 没有进度输出，超过工具执行阈值 {int(self.tool_timeout)}s",
                )
            return None
        limit = self.text_timeout if self.got_output else max(self.text_timeout, self.first_output_grace)
        idle = current - self.last_activity
        if idle > limit:
            if self.network_at and current - self.network_at < 300:
                return InterruptCheck(
                    InterruptReason.NETWORK,
                    f"连接异常后 {int(idle)}s 无新输出：{self.network_detail or '网络连接中断'}",
                )
            label = "首次输出" if not self.got_output else "文本输出"
            return InterruptCheck(
                InterruptReason.IDLE,
                f"{label}已连续 {int(idle)}s 无新内容，超过阈值 {int(limit)}s",
            )
        return None


def is_incomplete_reply(text: str, subtype: str = "") -> str:
    body = (text or "").strip()
    if not body:
        return "Agent 未返回有效内容"
    if subtype in ("error_max_turns", "error_during_execution", "turn_failed"):
        return f"Agent 以异常状态结束（{subtype}）"
    if body.count("```") % 2 == 1:
        return "代码块未闭合，回复疑似被截断"
    if re.search(r"(\.\.\.|…|等等|稍后继续|接下来我会|接下来我将|后续继续|正在生成)[\s\"'）)]*$", body[-80:]):
        return "结尾停在未完成语气上，回复疑似被截断"
    if body.endswith(("：", ":")) and len(body) > 80:
        return "回复停在冒号后，缺少后续内容"
    tail = body[-200:]
    for left, right in (("(", ")"), ("[", "]"), ("{", "}")):
        if tail.count(left) > tail.count(right):
            return "结尾括号未闭合，回复疑似被截断"
    last_line = body.splitlines()[-1].strip()
    if last_line in ("-", "*", "+", "```"):
        return "结尾停在空列表项或代码围栏上"
    if len(body) < 4 and body not in ("OK", "ok"):
        return "回复内容过短"
    return ""

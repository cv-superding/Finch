from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..models import AgentAvailability
from .launcher import find_agent_executable


@dataclass
class AgentRequest:
    prompt: str
    cwd: str
    session_id: str = ""
    is_resume: bool = False
    new_session_id: str = ""
    task_id: str = ""
    task_title: str = ""


@dataclass
class LaunchSpec:
    argv: list[str]
    cwd: str
    stdin: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    shell: bool = False


@dataclass
class AgentEvent:
    kind: str  # init, text, thinking, tool_start, tool_update, tool_end, progress, retry, error, result, raw
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class AgentEventParser(ABC):
    def __init__(self) -> None:
        self.session_id = ""
        self.final_text = ""
        self.saw_result = False
        self.result_error = False
        self.result_subtype = ""
        self.text_parts: list[str] = []
        self.closed_tools: set[str] = set()

    def feed_line(self, line: str) -> list[AgentEvent]:
        line = line.rstrip("\r\n")
        if not line:
            return []
        try:
            import json

            payload = json.loads(line)
        except Exception:
            return [AgentEvent("raw", text=line)]
        if not isinstance(payload, dict):
            return [AgentEvent("raw", text=line)]
        events = self.parse(payload)
        for ev in events:
            if ev.kind == "text" and ev.text:
                self.text_parts.append(ev.text)
            if ev.data.get("session_id") and not self.session_id:
                self.session_id = str(ev.data["session_id"])
            if ev.kind == "result":
                self.saw_result = True
                self.result_error = bool(ev.data.get("is_error"))
                self.result_subtype = str(ev.data.get("subtype") or "")
                if ev.text:
                    self.final_text = ev.text
        return events

    @abstractmethod
    def parse(self, payload: dict[str, Any]) -> list[AgentEvent]:
        raise NotImplementedError

    def accumulated_text(self) -> str:
        return self.final_text or "".join(self.text_parts)


def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return ""


class AgentAdapter(ABC):
    key = "base"
    label = "Agent"
    color = "#111113"
    badge = "AI"
    description = ""
    supports_resume = True
    stdin_prompt = False
    default_executables: tuple[str, ...] = ()

    def __init__(self, config: AppConfig):
        self.config = config

    # ---- discovery ----------------------------------------------------
    def configured_path(self) -> str:
        return (self.config.agent_paths.get(self.key) or "").strip()

    def find_executable(self) -> str:
        configured = self.configured_path()
        if configured:
            if Path(configured).exists():
                return configured
            return shutil.which(configured) or configured
        return find_agent_executable(self.default_executables)

    def availability(self) -> AgentAvailability:
        path = self.find_executable()
        if not path:
            return AgentAvailability(self.key, self.label, False, note="未找到可执行文件")
        version = ""
        try:
            proc = subprocess.run(
                self._version_argv(path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=12,
                creationflags=_no_window(),
            )
            raw = (proc.stdout or proc.stderr or "").strip()
            version = raw.splitlines()[0][:80] if raw else ""
        except Exception as exc:
            version = f"检测失败: {exc.__class__.__name__}"
        exists = Path(path).exists() or bool(shutil.which(path))
        return AgentAvailability(self.key, self.label, exists, path=path, version=version)

    def _version_argv(self, path: str) -> list[str]:
        return [*self._launcher(path, ["--version"])]

    # ---- launch -------------------------------------------------------
    def build_launch(self, request: AgentRequest) -> LaunchSpec:
        path = self.find_executable()
        if not path:
            raise RuntimeError(f"未找到 {self.label} 可执行文件，请在设置中填写路径")
        argv = self._launcher(path, self._args(request))
        stdin = request.prompt if self.stdin_prompt else None
        return LaunchSpec(argv=argv, cwd=request.cwd or os.getcwd(), stdin=stdin)

    @abstractmethod
    def _args(self, request: AgentRequest) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def create_parser(self) -> AgentEventParser:
        raise NotImplementedError

    # ---- process helpers ---------------------------------------------
    def _launcher(self, path: str, args: list[str]) -> list[str]:
        return resolve_launcher(path, args)

    def extra_args(self) -> list[str]:
        raw = (self.config.agent_extra_args.get(self.key) or "").strip()
        if not raw:
            return []
        try:
            return shlex.split(raw, posix=os.name != "nt")
        except ValueError:
            return raw.split()

    def _base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.setdefault("NO_COLOR", "1")
        env.setdefault("FORCE_COLOR", "0")
        return env


def _no_window() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _node() -> str:
    return shutil.which("node") or "node"


def _inner_target(cmd_path: Path) -> list[str] | None:
    """Resolve npm .cmd shims to the real executable or JS entrypoint."""
    try:
        content = cmd_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    patterns = [
        r'"%dp0%\\([^"]+?\.exe)"',
        r'"%~dp0\\([^"]+?\.exe)"',
        r'"%~dp0/([^"]+?\.exe)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            candidate = cmd_path.parent / match.group(1).replace("\\", os.sep)
            if candidate.exists():
                return [str(candidate)]
    match = re.search(r'"%_prog%"\s+"%dp0%\\([^"]+)"', content, re.IGNORECASE)
    if match:
        candidate = cmd_path.parent / match.group(1).replace("\\", os.sep)
        if candidate.exists():
            return [_node(), str(candidate)]
    match = re.search(r'node(?:\.exe)?"\s+"%dp0%\\([^"]+)"', content, re.IGNORECASE)
    if match:
        candidate = cmd_path.parent / match.group(1).replace("\\", os.sep)
        if candidate.exists():
            return [_node(), str(candidate)]
    for pattern in (
        r'"%dp0%\\([^"]+?\.(?:js|cjs|mjs))"',
        r'"%~dp0\\([^"]+?\.(?:js|cjs|mjs))"',
    ):
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            candidate = cmd_path.parent / match.group(1).replace("\\", os.sep)
            if candidate.exists():
                return [_node(), str(candidate)]
    return None


def resolve_launcher(path: str, args: list[str]) -> list[str]:
    path = os.path.expandvars(os.path.expanduser(path.strip().strip('"')))
    if not Path(path).exists():
        resolved = shutil.which(path)
        if resolved:
            path = resolved
    p = Path(path)
    if os.name != "nt":
        return [path, *args]
    if p.suffix.lower() in (".cmd", ".bat") and p.exists():
        inner = _inner_target(p)
        if inner:
            return [*inner, *args]
        cmdline = subprocess.list2cmdline([str(p), *args])
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", cmdline]
    if p.suffix.lower() == ".ps1":
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p), *args]
    if p.suffix.lower() in (".js", ".cjs", ".mjs"):
        return [_node(), str(p), *args]
    if p.suffix.lower() == ".exe":
        return [str(p), *args]
    if p.exists():
        try:
            first = p.open("r", encoding="utf-8", errors="ignore").readline()
        except Exception:
            first = ""
        if first.startswith("#!") and "node" in first:
            return [_node(), str(p), *args]
    return [path, *args]

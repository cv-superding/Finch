from __future__ import annotations

from ..config import AppConfig
from .base import AgentAdapter, AgentEvent, AgentEventParser, AgentRequest, LaunchSpec
from .claude import ClaudeAdapter
from .codebuddy import CodeBuddyAdapter
from .codex import CodexAdapter
from .cursor import CursorAdapter
from .mock import MockAdapter
from .opencode import OpenCodeAdapter
from .zcode import ZCodeAdapter


ADAPTER_CLASSES: list[type[AgentAdapter]] = [
    ClaudeAdapter,
    CodeBuddyAdapter,
    CodexAdapter,
    ZCodeAdapter,
    OpenCodeAdapter,
    CursorAdapter,
    MockAdapter,
]

ADAPTER_KEYS = [cls.key for cls in ADAPTER_CLASSES]


def build_adapter(config: AppConfig, key: str) -> AgentAdapter:
    for cls in ADAPTER_CLASSES:
        if cls.key == key:
            return cls(config)
    return MockAdapter(config)


def adapter_label(key: str) -> str:
    for cls in ADAPTER_CLASSES:
        if cls.key == key:
            return cls.label
    return key or "默认 Agent"


def adapter_color(key: str) -> str:
    for cls in ADAPTER_CLASSES:
        if cls.key == key:
            return cls.color
    return "#7C5CFF"


def adapter_badge(key: str) -> str:
    for cls in ADAPTER_CLASSES:
        if cls.key == key:
            return cls.badge
    return "AI"


__all__ = [
    "AgentAdapter",
    "AgentEvent",
    "AgentEventParser",
    "AgentRequest",
    "LaunchSpec",
    "ADAPTER_CLASSES",
    "ADAPTER_KEYS",
    "build_adapter",
    "adapter_label",
    "adapter_color",
    "adapter_badge",
]

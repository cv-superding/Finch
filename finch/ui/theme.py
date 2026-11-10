from __future__ import annotations

import re

from PyQt6.QtCore import QFile, QIODevice
from PyQt6.QtGui import QColor, QFont, QFontDatabase
from qfluentwidgets import (
    FluentStyleSheet,
    FluentThemeColor,
    ThemeColor,
    setThemeColor,
)


def _qt(value: str) -> str:
    """Convert a CSS rgba() token from the library into Qt's #AARRGGBB form."""
    match = re.match(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)", value)
    if not match:
        return value
    r, g, b, a = match.groups()
    return f"#{round(float(a) * 255):02X}{int(r):02X}{int(g):02X}{int(b):02X}"


def _library_neutrals() -> dict[str, str]:
    """Read the canonical neutral colours out of the library's own stylesheets.

    The Fluent widget library ships its palette inside the Qt resources; we
    take the very same tokens instead of inventing our own hex values.
    """
    wanted = {
        "text": "rgba(0, 0, 0, 0.896)",
        "muted": "rgba(0, 0, 0, 0.6063)",
        "subtle": "rgba(0, 0, 0, 0.43)",
        "border": "rgba(0, 0, 0, 0.06)",
        "line": "rgba(0, 0, 0, 0.0578)",
        "card": "rgba(255, 255, 255, 0.67)",
        "subtle_fill": "rgba(249, 249, 249, 0.5)",
    }
    found: dict[str, str] = {}
    for style in FluentStyleSheet:
        try:
            path = style.path()
        except Exception:
            continue
        handle = QFile(path)
        if not handle.exists():
            continue
        handle.open(QIODevice.OpenModeFlag.ReadOnly)
        text = handle.readAll().data().decode("utf-8", "ignore")
        for key, token in wanted.items():
            if key in found:
                continue
            if token in text:
                found[key] = token
    return {key: _qt(found.get(key, token)) for key, token in wanted.items()}


NEUTRALS = _library_neutrals()


def _tint(color: QColor, alpha: float) -> str:
    """Fluent style subtle fill: the accent at low alpha over the surface."""
    return f"#{round(alpha * 255):02X}{color.red():02X}{color.green():02X}{color.blue():02X}"


def _hex(color: QColor) -> str:
    return color.name()


# The application accent is one of the library's own Fluent colours; every
# other token is derived from the library palette.
ACCENT_COLOR = QColor(FluentThemeColor.DEFAULT_BLUE.color())
ACCENT = _hex(ThemeColor.PRIMARY.color())
ACCENT_DARK = _hex(ThemeColor.DARK_1.color())
ACCENT_DARKER = _hex(ThemeColor.DARK_2.color())
ACCENT_SOFT = _tint(ThemeColor.PRIMARY.color(), 0.12)
ACCENT_LINE = _tint(ThemeColor.PRIMARY.color(), 0.28)
ACCENT_LIGHT_TINT = _tint(ThemeColor.LIGHT_1.color(), 0.4)

PRIMARY = ACCENT
PRIMARY_HOVER = ACCENT_DARK
PRIMARY_PRESS = ACCENT_DARKER
PRIMARY_SOFT = ACCENT_SOFT

BG = "#ffffff"
BG_SOFT = NEUTRALS["subtle_fill"]
CARD = NEUTRALS["card"]
SIDEBAR = NEUTRALS["card"]
SIDEBAR_SOFT = NEUTRALS["subtle_fill"]
SIDEBAR_LINE = NEUTRALS["line"]
SIDEBAR_TEXT = NEUTRALS["text"]
SIDEBAR_MUTED = NEUTRALS["muted"]
SIDEBAR_SUBTLE = NEUTRALS["subtle"]

TEXT = NEUTRALS["text"]
TEXT_SOFT = NEUTRALS["muted"]
MUTED = NEUTRALS["muted"]
SUBTLE = NEUTRALS["subtle"]
BORDER = NEUTRALS["border"]
BORDER_STRONG = "rgba(0, 0, 0, 0.12)"
BORDER_SOFT = NEUTRALS["line"]

BLUE = _hex(FluentThemeColor.COOL_BLUE_BRIGHT.color())
GREEN = _hex(FluentThemeColor.GREEN.color())
ORANGE = _hex(FluentThemeColor.ORANGE_BRIGHT.color())
RED = _hex(FluentThemeColor.MOD_RED.color())
VIOLET = _hex(FluentThemeColor.ORCHID.color())

BLUE_TINT = BLUE
BLUE_SOFT = _tint(QColor(BLUE), 0.12)
GREEN_SOFT = _tint(QColor(GREEN), 0.12)
GREEN_TINT = GREEN
ORANGE_SOFT = _tint(QColor(ORANGE), 0.12)
ORANGE_TINT = ORANGE
RED_SOFT = _tint(QColor(RED), 0.12)
RED_TINT = RED
VIOLET_SOFT = _tint(QColor(VIOLET), 0.12)
VIOLET_TINT = VIOLET
SLATE_SOFT = NEUTRALS["subtle_fill"]

RUN_TONES = {
    "resume": (BLUE_SOFT, BLUE_TINT),
    "followup": (VIOLET_SOFT, VIOLET_TINT),
    "main": (SLATE_SOFT, MUTED),
}

STATUS_COLORS = {
    "queued": (MUTED, SLATE_SOFT),
    "running": (ACCENT, ACCENT_SOFT),
    "tool": (ACCENT, ACCENT_SOFT),
    "validating": (BLUE_TINT, BLUE_SOFT),
    "interrupted": (ORANGE_TINT, ORANGE_SOFT),
    "resuming": (ACCENT, ACCENT_SOFT),
    "patching": (ACCENT, ACCENT_SOFT),
    "awaiting": (VIOLET_TINT, VIOLET_SOFT),
    "done": (GREEN_TINT, GREEN_SOFT),
    "failed": (RED_TINT, RED_SOFT),
    "attention": (RED_TINT, RED_SOFT),
    "skipped": (SUBTLE, SLATE_SOFT),
    "stopped": (SUBTLE, SLATE_SOFT),
}


def _column_tones() -> dict[str, tuple[str, str, str]]:
    """Column chips follow Fluent's semantic roles, one hue per meaning.

    neutral (queued) -> accent (running) -> warning (needs attention) ->
    success (done); nothing is painted as a large surface.
    """
    tones = {}
    for key, accent in (
        ("todo", MUTED),
        ("progress", ACCENT),
        ("review", ORANGE),
        ("done", GREEN),
    ):
        color = QColor(accent)
        tones[key] = (accent, _tint(color, 0.16), _tint(color, 0.06))
    return tones


COLUMN_TONES = _column_tones()

# Fluent 2 motion tokens (fluent2.microsoft.design/motion)
DURATION_FAST = 100
DURATION_NORMAL = 200
DURATION_SLOW = 300
EASE_DECELERATE = "cubic-bezier(0.1, 0.9, 0.2, 1.0)"


def _palette() -> dict[str, object]:
    """Rebuild every colour token from the library's current palette."""
    primary = ThemeColor.PRIMARY.color()
    accent = _hex(primary)
    accent_dark = _hex(ThemeColor.DARK_1.color())
    accent_darker = _hex(ThemeColor.DARK_2.color())
    accent_light = _hex(ThemeColor.LIGHT_1.color())
    accent_lighter = _hex(ThemeColor.LIGHT_2.color())
    accent_soft = _tint(primary, 0.12)
    accent_line = _tint(primary, 0.28)
    tokens = {
        "ACCENT": accent,
        "ACCENT_DARK": accent_dark,
        "ACCENT_DARKER": accent_darker,
        "ACCENT_LIGHT": accent_light,
        "ACCENT_LIGHTER": accent_lighter,
        "ACCENT_SOFT": accent_soft,
        "ACCENT_LINE": accent_line,
        "PRIMARY": accent,
        "PRIMARY_HOVER": accent_dark,
        "PRIMARY_PRESS": accent_darker,
        "PRIMARY_SOFT": accent_soft,
    }
    tokens["COLUMN_TONES"] = _column_tones()
    tokens["STATUS_COLORS"] = {
        "queued": (MUTED, SLATE_SOFT),
        "running": (accent, accent_soft),
        "tool": (accent, accent_soft),
        "validating": (BLUE_TINT, BLUE_SOFT),
        "interrupted": (ORANGE_TINT, ORANGE_SOFT),
        "resuming": (accent, accent_soft),
        "patching": (accent, accent_soft),
        "awaiting": (VIOLET_TINT, VIOLET_SOFT),
        "done": (GREEN_TINT, GREEN_SOFT),
        "failed": (RED_TINT, RED_SOFT),
        "attention": (RED_TINT, RED_SOFT),
        "skipped": (SUBTLE, SLATE_SOFT),
        "stopped": (SUBTLE, SLATE_SOFT),
    }
    return tokens


def apply_theme() -> None:
    """Align the Fluent widget library with the app palette."""
    setThemeColor(ACCENT_COLOR, save=False, lazy=False)
    globals().update(_palette())


def fluent_icon(name: str):
    """Icon from the library's Fluent icon set."""
    from .glyphs import line_icon

    return line_icon(name)


def font_family() -> str:
    families = set(QFontDatabase.families())
    for candidate in ("Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", "Segoe UI"):
        if candidate in families:
            return candidate
    return "Segoe UI"


def mono_family() -> str:
    families = set(QFontDatabase.families())
    for candidate in ("Cascadia Mono", "JetBrains Mono", "Consolas", "Menlo"):
        if candidate in families:
            return candidate
    return "Consolas"


def app_font(size: float = 10.0) -> QFont:
    font = QFont(font_family(), 10)
    font.setPointSizeF(size)
    return font


# Only the widgets we still own are styled here; every Fluent component keeps
# the library's own stylesheet. Colours come from the library palette above.
STYLESHEET = f"""
QWidget#Root, QWidget#Page {{
    background: transparent;
}}
QFrame#AppSidebar {{
    background: transparent;
    border: none;
}}
QFrame#Workspace {{
    background: {CARD};
    border: none;
}}
QFrame#Inspector {{
    background: {BG_SOFT};
    border: none;
    border-left: 1px solid {BORDER_SOFT};
}}
QFrame#Card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#InsetCard {{
    background: {BG_SOFT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 6px;
}}
QFrame#BottomBar {{
    background: {CARD};
    border-top: 1px solid {BORDER_SOFT};
}}
QFrame#SettingsFooter {{
    background: transparent;
    border-top: 1px solid {BORDER};
}}
QFrame#SideNavPanel {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#Divider, QFrame#Hairline {{
    background: {BORDER_SOFT};
    min-height: 1px;
    max-height: 1px;
    border: none;
}}
QFrame#VDivider {{
    background: {BORDER_SOFT};
    min-width: 1px;
    max-width: 1px;
    border: none;
}}
QFrame#DialogFooter {{
    background: {BG_SOFT};
    border-top: 1px solid {BORDER};
}}
QLabel#PageTitle {{
    font-size: 28px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#PageSubtitle {{
    font-size: 12px;
    color: {MUTED};
}}
QLabel#CardTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#TaskTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#Muted {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#Subtle {{
    color: {SUBTLE};
    font-size: 12px;
}}
QLabel#SectionLabel {{
    color: {SUBTLE};
    font-size: 11px;
    font-weight: 600;
}}
QFrame#Toast {{
    background: {TEXT};
    border-radius: 8px;
}}
QLabel#ToastText {{
    color: #FFFFFF;
    font-size: 12px;
}}
QPlainTextEdit#LogView {{
    background: {BG_SOFT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 6px;
    font-family: "Cascadia Mono", "Consolas";
    font-size: 12px;
    color: {TEXT_SOFT};
    padding: 10px;
}}
QPlainTextEdit#PromptEdit {{
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
    padding: 10px;
}}
QPlainTextEdit#ReadView {{
    background: {BG_SOFT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 6px;
    font-size: 12px;
    color: {TEXT_SOFT};
    padding: 10px;
}}
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase
from qfluentwidgets import Theme, setTheme, setThemeColor

# ---------------------------------------------------------------------------
# Finch dark design tokens.
# Deep charcoal canvas, one brand indigo, semantic dots only.
# ---------------------------------------------------------------------------

ACCENT_COLOR = QColor("#6E6BF0")

# brand
ACCENT = "#6E6BF0"
ACCENT_DARK = "#5A57E0"
ACCENT_DARKER = "#4B48C8"
ACCENT_SOFT = "#1A1A2B"
ACCENT_LINE = "#2F2D57"
ACCENT_LIGHT_TINT = "#1A1A2B"

PRIMARY = ACCENT
PRIMARY_HOVER = ACCENT_DARK
PRIMARY_PRESS = ACCENT_DARKER
PRIMARY_SOFT = ACCENT_SOFT

# surfaces
BG = "#0D0D0F"
BG_SOFT = "#121216"
CARD = "#16161A"
SURFACE = "#16161A"
SURFACE_2 = "#1C1C22"
SIDEBAR = "#101014"
SIDEBAR_SOFT = "#1C1C22"
SIDEBAR_LINE = "#232328"
SIDEBAR_TEXT = "#EDEDEF"
SIDEBAR_MUTED = "#8E8E96"
SIDEBAR_SUBTLE = "#5F5F68"

# text
TEXT = "#EDEDEF"
TEXT_SOFT = "#A6A6AE"
MUTED = "#8E8E96"
SUBTLE = "#5F5F68"

# lines
BORDER = "#232328"
BORDER_STRONG = "#2A2A30"
BORDER_SOFT = "#232328"
BORDER_HOVER = "#3A3A44"
BORDER_INPUT = "#2E2E36"
TEXT_DISABLED = "#4A4A52"
SCROLL_THUMB = "#2C2C33"

# semantic
QUEUED = "#55555C"
RUNNING = "#6E6BF0"
GREEN = "#3FB950"
GREEN_TINT = "#3FB950"
GREEN_SOFT = "#12261A"
RED = "#F85149"
RED_TINT = "#F85149"
RED_SOFT = "#2A1616"
ORANGE = "#D29922"
ORANGE_TINT = "#D29922"
ORANGE_SOFT = "#2A2214"
VIOLET = "#8B5CF6"
VIOLET_TINT = "#8B5CF6"
VIOLET_SOFT = "#1F1A2E"
BLUE = "#58A6FF"
BLUE_TINT = "#58A6FF"
BLUE_SOFT = "#12233A"
SLATE_SOFT = "#1C1C22"

def _build_derived() -> None:
    """语义色依赖上面的 token，切换主题时要重建。"""
    global RUN_TONES, STATUS_COLORS, COLUMN_TONES
    RUN_TONES = {
        "resume": (BLUE_SOFT, BLUE_TINT),
        "followup": (VIOLET_SOFT, VIOLET_TINT),
        "main": (SLATE_SOFT, MUTED),
    }

    STATUS_COLORS = {
        "queued": (QUEUED, SLATE_SOFT),
        "running": (RUNNING, ACCENT_SOFT),
        "tool": (RUNNING, ACCENT_SOFT),
        "validating": (BLUE_TINT, BLUE_SOFT),
        "interrupted": (ORANGE_TINT, ORANGE_SOFT),
        "resuming": (RUNNING, ACCENT_SOFT),
        "patching": (RUNNING, ACCENT_SOFT),
        "awaiting": (ORANGE_TINT, ORANGE_SOFT),
        "done": (GREEN_TINT, GREEN_SOFT),
        "failed": (RED_TINT, RED_SOFT),
        "attention": (RED_TINT, RED_SOFT),
        "skipped": (SUBTLE, SLATE_SOFT),
        "stopped": (SUBTLE, SLATE_SOFT),
    }

    COLUMN_TONES = {
        "todo": (QUEUED, "#1C1C22", "#141418"),
        "progress": (RUNNING, ACCENT_SOFT, "#141425"),
        "review": (ORANGE_TINT, ORANGE_SOFT, "#171509"),
        "done": (GREEN_TINT, GREEN_SOFT, "#0F1A12"),
    }


_build_derived()


DURATION_FAST = 100
DURATION_NORMAL = 200
DURATION_SLOW = 300
EASE_DECELERATE = "cubic-bezier(0.1, 0.9, 0.2, 1.0)"

_FONT_CACHE: dict[str, str] = {}


DARK_TOKENS = {
    "BG": "#0D0D0F", "BG_SOFT": "#121216", "CARD": "#16161A", "SURFACE": "#16161A",
    "SURFACE_2": "#1C1C22", "SIDEBAR": "#101014", "SIDEBAR_SOFT": "#1C1C22",
    "SIDEBAR_LINE": "#232328", "SIDEBAR_TEXT": "#EDEDEF", "SIDEBAR_MUTED": "#8E8E96",
    "SIDEBAR_SUBTLE": "#5F5F68", "TEXT": "#EDEDEF", "TEXT_SOFT": "#A6A6AE",
    "MUTED": "#8E8E96", "SUBTLE": "#5F5F68",
    "BORDER": "#232328", "BORDER_STRONG": "#2A2A30", "BORDER_SOFT": "#232328",
    "BORDER_HOVER": "#3A3A44", "BORDER_INPUT": "#2E2E36",
    "TEXT_DISABLED": "#4A4A52", "SCROLL_THUMB": "#2C2C33",
    "ACCENT_SOFT": "#1A1A2B", "ACCENT_LINE": "#2F2D57", "ACCENT_LIGHT_TINT": "#1A1A2B",
    "SLATE_SOFT": "#1C1C22",
    "GREEN_SOFT": "#12261A", "GREEN_TINT": "#3FB950",
    "RED_SOFT": "#2A1616", "RED_TINT": "#F85149",
    "ORANGE_SOFT": "#2A2214", "ORANGE_TINT": "#D29922",
    "VIOLET_SOFT": "#1F1A2E", "VIOLET_TINT": "#8B5CF6",
    "BLUE_SOFT": "#12233A", "BLUE_TINT": "#58A6FF",
    "QUEUED": "#55555C", "RUNNING": "#6E6BF0",
}

LIGHT_TOKENS = {
    "BG": "#F6F6F7", "BG_SOFT": "#FFFFFF", "CARD": "#FFFFFF", "SURFACE": "#FFFFFF",
    "SURFACE_2": "#ECECEF", "SIDEBAR": "#FAFAFB", "SIDEBAR_SOFT": "#ECECEF",
    "SIDEBAR_LINE": "#E8E8EB", "SIDEBAR_TEXT": "#1B1B1F", "SIDEBAR_MUTED": "#6B6B73",
    "SIDEBAR_SUBTLE": "#9A9AA2", "TEXT": "#1B1B1F", "TEXT_SOFT": "#3F3F46",
    "MUTED": "#6B6B73", "SUBTLE": "#9A9AA2",
    "BORDER": "#E8E8EB", "BORDER_STRONG": "#DEDEE3", "BORDER_SOFT": "#E8E8EB",
    "BORDER_HOVER": "#C9C9D1", "BORDER_INPUT": "#D8D8DE",
    "TEXT_DISABLED": "#A1A1AA", "SCROLL_THUMB": "#D5D5DC",
    "ACCENT_SOFT": "#EFEEFF", "ACCENT_LINE": "#CFCDFA", "ACCENT_LIGHT_TINT": "#EFEEFF",
    "SLATE_SOFT": "#F1F1F4",
    "GREEN_SOFT": "#E8F6EC", "GREEN_TINT": "#1A7F37",
    "RED_SOFT": "#FDECEA", "RED_TINT": "#CF222E",
    "ORANGE_SOFT": "#FBF3E2", "ORANGE_TINT": "#9A6700",
    "VIOLET_SOFT": "#F3EEFE", "VIOLET_TINT": "#6D3BD1",
    "BLUE_SOFT": "#EAF2FF", "BLUE_TINT": "#1F6FEB",
    "QUEUED": "#8A8A93", "RUNNING": "#5B58E8",
}


_APP = None
_BASE_QSS = ""
_APPLIED_QSS = ""



def _remap_widget_styles(mapping: dict[str, str]) -> None:
    """把控件内联样式里的旧配色替换成新配色（一次性正则，避免逐色遍历）。"""
    if _APP is None or not mapping:
        return
    import re

    ordered = sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True)
    combined = re.compile("|".join(re.escape(old) for old, _ in ordered), re.I)
    lookup = {old.lower(): new for old, new in ordered}

    def _replace(match):
        return lookup.get(match.group(0).lower(), match.group(0))

    for widget in _APP.allWidgets():
        current = widget.styleSheet()
        if not current or not combined.search(current):
            continue
        widget.setStyleSheet(combined.sub(_replace, current))


def _capture_palette(palette: dict[str, str]) -> dict[str, str]:
    return {key: globals().get(key, "") for key in palette}

def bind_app(app) -> None:
    """记住 QApplication，用于切换主题时原地重刷样式。"""
    global _APP
    _APP = app


def refresh_app_stylesheet() -> None:
    global _APPLIED_QSS
    if _APP is None:
        return
    _APPLIED_QSS = STYLESHEET
    _APP.setStyleSheet(_BASE_QSS + _APPLIED_QSS)


def apply_theme(mode: str = "dark") -> None:
    """切换主题：重设 token、语义色与 QSS（需要在建窗口之前调用）。"""
    global STYLESHEET
    light = (mode or "dark").strip().lower() == "light"
    palette = LIGHT_TOKENS if light else DARK_TOKENS
    before = _capture_palette(palette)
    for key, value in palette.items():
        globals()[key] = value
    setTheme(Theme.LIGHT if light else Theme.DARK)
    setThemeColor(ACCENT_COLOR, save=False, lazy=False)
    _build_derived()
    STYLESHEET = build_stylesheet()
    # 库自己的 QSS 会随 setTheme 变化：先剥掉上一次叠上去的，再记住新基线
    global _BASE_QSS
    if _APP is not None:
        current = _APP.styleSheet()
        if _APPLIED_QSS and current.endswith(_APPLIED_QSS):
            current = current[: -len(_APPLIED_QSS)]
        _BASE_QSS = current
    mapping = {
        before[key]: palette[key]
        for key in palette
        if before.get(key) and before[key] != palette[key]
    }
    _remap_widget_styles(mapping)


def fluent_icon(name: str):
    from .glyphs import line_icon

    return line_icon(name)


def font_family() -> str:
    if "sans" in _FONT_CACHE:
        return _FONT_CACHE["sans"]
    families = set(QFontDatabase.families())
    for candidate in ("Inter", "SF Pro Text", "Microsoft YaHei UI", "PingFang SC", "Segoe UI"):
        if candidate in families:
            _FONT_CACHE["sans"] = candidate
            return candidate
    _FONT_CACHE["sans"] = "Segoe UI"
    return _FONT_CACHE["sans"]


def mono_family() -> str:
    if "mono" in _FONT_CACHE:
        return _FONT_CACHE["mono"]
    families = set(QFontDatabase.families())
    for candidate in ("JetBrains Mono", "Cascadia Mono", "Consolas", "Menlo"):
        if candidate in families:
            _FONT_CACHE["mono"] = candidate
            return candidate
    _FONT_CACHE["mono"] = "Consolas"
    return _FONT_CACHE["mono"]


def app_font(size: float = 10.0) -> QFont:
    font = QFont(font_family(), 10)
    font.setPointSizeF(size)
    return font


def build_stylesheet() -> str:
    return (
        f"""
QWidget#Root, QWidget#Page {{
    background: {BG};
}}
QAbstractScrollArea, QScrollArea {{
    background: transparent;
    border: none;
}}
QAbstractScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QFrame#AppSidebar {{
    background: {SIDEBAR};
    border: none;
    border-right: 1px solid {BORDER};
}}
QWidget#AppWindow {{
    background: {SIDEBAR};
}}
QWidget#AppTitleBar {{
    background: {SIDEBAR};
}}
QWidget#AppTitleBar QLabel {{
    color: {TEXT};
}}
QPushButton#NavItem {{
    text-align: left;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 6px;
    padding: 2px 8px 2px 9px;
    color: {SIDEBAR_MUTED};
    font-size: 13px;
    background: transparent;
}}
QPushButton#NavItem:hover {{
    background: {SURFACE_2};
    color: {TEXT};
}}
QPushButton#NavItem[active="true"] {{
    background: {SURFACE_2};
    border-left: 3px solid {ACCENT};
    color: {TEXT};
    font-weight: 600;
}}
QPushButton#AgentItem {{
    text-align: left;
    border: none;
    border-radius: 6px;
    padding: 2px 8px;
    color: {SIDEBAR_MUTED};
    font-size: 12.5px;
    background: transparent;
}}
QPushButton#AgentItem:hover {{
    background: {SURFACE_2};
    color: {TEXT};
}}
QPushButton#AgentItem[active="true"] {{
    background: {SURFACE_2};
    color: {TEXT};
}}
QLabel#SideLabel {{
    color: {SUBTLE};
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.12em;
    padding: 0 8px;
}}
QLabel#SideBadge {{
    background: {SURFACE_2};
    color: {MUTED};
    border-radius: 4px;
    padding: 1px 6px;
    font-family: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
    font-size: 10.5px;
}}
QLabel#Wordmark {{
    color: {TEXT};
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.01em;
}}
QLabel#SideState {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#SideMeta {{
    color: {SUBTLE};
    font-size: 11px;
}}
QFrame#Workspace {{
    background: {BG};
    border: none;
}}
QFrame#Inspector {{
    background: {CARD};
    border: none;
    border-left: 1px solid {BORDER};
}}
QFrame#Card {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
}}
QFrame#InsetCard {{
    background: {BG_SOFT};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#BottomBar {{
    background: {CARD};
    border-top: 1px solid {BORDER};
}}
QFrame#SettingsFooter {{
    background: transparent;
    border-top: 1px solid {BORDER};
}}
QFrame#Divider, QFrame#Hairline {{
    background: {BORDER};
    min-height: 1px;
    max-height: 1px;
    border: none;
}}
QFrame#VDivider {{
    background: {BORDER};
    min-width: 1px;
    max-width: 1px;
    border: none;
}}
QFrame#DialogFooter {{
    background: {BG_SOFT};
    border-top: 1px solid {BORDER};
}}
QLabel#PageTitle {{
    font-size: 24px;
    font-weight: 600;
    color: {TEXT};
    letter-spacing: -0.01em;
}}
QLabel#PageSubtitle {{
    font-size: 13px;
    color: {MUTED};
}}
QLabel#CardTitle {{
    font-size: 16px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#TaskTitle {{
    font-size: 15px;
    font-weight: 500;
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
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.12em;
}}
QLabel#FieldLabel {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#StatValue {{
    font-family: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
    font-size: 28px;
    font-weight: 600;
    color: {TEXT};
}}
QLabel#StatLabel {{
    color: {SUBTLE};
    font-size: 11px;
}}
QLabel#StatValueSmall {{
    font-family: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
    font-size: 17px;
    font-weight: 600;
    color: {TEXT};
}}
QFrame#Toast {{
    background: {SURFACE_2};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
}}
QLabel#ToastText {{
    color: {TEXT};
    font-size: 12px;
}}
QLineEdit {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 0 10px;
    font-size: 12.5px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit#QuickAdd {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 0 12px;
    font-size: 13px;
    color: {TEXT};
}}
QLineEdit#QuickAdd:focus {{
    border: 1px solid {ACCENT};
}}
QPushButton#RunCircle {{
    background: {ACCENT};
    border: none;
    border-radius: 20px;
}}
QPushButton#RunCircle:hover {{
    background: {ACCENT_DARK};
}}
QPushButton#RunCircle:pressed {{
    background: {ACCENT_DARKER};
}}
QPushButton#RunCircle[paused="true"] {{
    background: {CARD};
    border: 1px solid {ACCENT_LINE};
}}
QProgressBar#CardProgress {{
    background: {ACCENT_SOFT};
    border: none;
    border-radius: 2px;
    max-height: 3px;
}}
QProgressBar#CardProgress::chunk {{
    background: {ACCENT};
    border-radius: 2px;
}}
QProgressBar#StatusProgress {{
    background: {SURFACE_2};
    border: none;
    border-radius: 2px;
    max-height: 3px;
    min-height: 3px;
}}
QProgressBar#StatusProgress::chunk {{
    background: {ACCENT};
    border-radius: 2px;
}}
QPlainTextEdit#LogView {{
    background: {BG_SOFT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-family: "JetBrains Mono", "Cascadia Mono", Consolas, monospace;
    font-size: 11.5px;
    color: {TEXT_SOFT};
    padding: 10px;
}}
QPlainTextEdit#PromptEdit {{
    font-family: "Inter", "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
    padding: 10px;
}}
QPlainTextEdit#ReadView {{
    background: {BG_SOFT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-size: 12px;
    color: {TEXT_SOFT};
    padding: 10px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {SCROLL_THUMB};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {BORDER_HOVER};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0 2px 2px 2px;
}}
QScrollBar::handle:horizontal {{
    background: {SCROLL_THUMB};
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
    width: 0;
}}
QPushButton#GhostButton {{
    background: transparent;
    border: 1px solid {BORDER_INPUT};
    border-radius: 8px;
    color: {MUTED};
    font-size: 13px;
    padding: 0 14px;
}}
QPushButton#GhostButton:hover {{
    background: {SURFACE_2};
    border-color: {BORDER_HOVER};
    color: {TEXT};
}}
QPushButton#GhostButton:disabled {{
    color: {TEXT_DISABLED};
    border-color: {BORDER};
}}
QFrame#AgentCard {{
    background: {CARD};
    border: 1px solid {BORDER_STRONG};
    border-radius: 12px;
}}
QFrame#AgentCard:hover {{
    border-color: {BORDER_STRONG};
}}
QPushButton#UnderlineTab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {MUTED};
    font-size: 15px;
    padding: 6px 2px 12px;
}}
QPushButton#UnderlineTab:hover {{
    color: {TEXT};
}}
QPushButton#UnderlineTab[active="true"] {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
    font-weight: 600;
}}
"""
    )


STYLESHEET = build_stylesheet()


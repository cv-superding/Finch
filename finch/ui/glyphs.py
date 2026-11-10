from __future__ import annotations

from PyQt6.QtGui import QIcon
from qfluentwidgets import FluentIcon

# Semantic name -> Fluent system icon. Fluent icons are monochrome SVGs that
# follow the application theme, so the color argument is only kept for
# call-site compatibility.
_ICON_NAMES: dict[str, str] = {
    "play": "PLAY",
    "play-solid": "PLAY_SOLID",
    "pause": "PAUSE",
    "plus": "ADD",
    "add": "ADD",
    "spark": "BRIGHTNESS",
    "sparkles": "BRIGHTNESS",
    "optimize": "BRIGHTNESS",
    "ellipsis": "MORE",
    "more": "MORE",
    "chevron-right": "CHEVRON_RIGHT",
    "chevron-down": "CHEVRON_DOWN_MED",
    "close": "CLOSE",
    "menu": "MENU",
    "layers": "TILES",
    "queue": "TILES",
    "list": "TILES",
    "task": "TILES",
    "board": "TILES",
    "clock": "HISTORY",
    "history": "HISTORY",
    "sliders": "VIEW",
    "settings": "VIEW",
    "folder": "FOLDER",
    "timer": "DATE_TIME",
    "repeat": "SYNC",
    "archive": "FOLDER",
    "search": "SEARCH",
    "analyze": "SEARCH",
    "bot": "ROBOT",
    "arrow-up-right": "SEND",
    "open": "SEND",
    "check": "ACCEPT",
    "done": "ACCEPT",
    "copy": "COPY",
    "edit": "EDIT",
    "download": "DOWNLOAD",
    "refresh": "SYNC",
    "trash": "DELETE",
    "delete": "DELETE",
    "stop": "CANCEL",
    "flag": "FLAG",
    "chat": "CHAT",
    "globe": "GLOBE",
    "pin": "PIN",
    "broom": "BROOM",
    "zoom": "ZOOM",
    "view": "VIEW",
    "hide": "HIDE",
    "sync": "SYNC",
    "cancel": "CANCEL",
    "tiles": "TILES",
    "add": "ADD",
    "edit": "EDIT",
    "delete": "DELETE",
    "copy": "COPY",
    "folder": "FOLDER",
}

_FALLBACK = FluentIcon.MORE


def _resolve(name: str) -> FluentIcon:
    key = _ICON_NAMES.get(name)
    if key:
        member = getattr(FluentIcon, key, None)
        if member is not None:
            return member
    return _FALLBACK


def fluent_icon(name: str) -> FluentIcon:
    return _resolve(name)


def line_icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    icon = _resolve(name).icon()
    if size and icon.isNull() is False:
        return icon
    return icon

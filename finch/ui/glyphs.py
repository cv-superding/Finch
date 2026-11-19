from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
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
    "sliders": "ALIGNMENT",
    "settings": "SETTING",
    "folder": "FOLDER",
    "timer": "DATE_TIME",
    "repeat": "SYNC",
    "archive": "DOCUMENT",
    "search": "SEARCH",
    "analyze": "SEARCH",
    "bot": "ROBOT",
    "code": "CODE",
    "command": "COMMAND_PROMPT",
    "devtools": "DEVELOPER_TOOLS",
    "cube": "IOT",
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
    "help": "INFO",
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


def _tint(source: QIcon, color: str, size: int) -> QIcon:
    """Fluent icons follow the system theme; tint them so色值可控。"""
    scale = 2
    pixmap = source.pixmap(size * scale, size * scale)
    if pixmap.isNull():
        return source
    tinted = QPixmap(pixmap.size())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor(color))
    painter.end()
    tinted.setDevicePixelRatio(scale)
    return QIcon(tinted)


def line_icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    icon = _resolve(name).icon()
    if color and not icon.isNull():
        return _tint(icon, color, size or 16)
    return icon


def transport_icon(kind: str, color: str, size: int = 14) -> QIcon:
    """Play / pause drawn by hand — the Fluent pause glyph blurs into "00" at 14px."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    s = float(size)
    if kind == "pause":
        bar = max(2.0, s * 0.15)
        gap = s * 0.22
        height = s * 0.60
        radius = bar / 2
        left = (s - (bar * 2 + gap)) / 2
        top = (s - height) / 2
        painter.drawRoundedRect(QRectF(left, top, bar, height), radius, radius)
        painter.drawRoundedRect(
            QRectF(left + bar + gap, top, bar, height), radius, radius
        )
    else:
        path = QPainterPath()
        width, height = s * 0.42, s * 0.54
        x = (s - width) / 2 + s * 0.03
        path.moveTo(x, (s - height) / 2)
        path.lineTo(x + width, s / 2)
        path.lineTo(x, (s + height) / 2)
        path.closeSubpath()
        painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


def check_icon(color: str, size: int = 11, stroke: float = 1.8) -> QIcon:
    """勾选图标自绘：库里的 ACCEPT 自带留白，小尺寸下明显偏右下。"""
    scale = 3
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), stroke * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    s = float(size * scale)
    path = QPainterPath()
    path.moveTo(s * 0.24, s * 0.52)
    path.lineTo(s * 0.43, s * 0.70)
    path.lineTo(s * 0.77, s * 0.31)
    painter.drawPath(path)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)

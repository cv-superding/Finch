from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap

ASSET_DIR = Path(__file__).with_name("assets") / "agents"

FILES = {
    "claude": "claudecode-color.svg",
    "codex": "codex-color.svg",
    "zcode": "zcode.png",
    "opencode": "opencode.svg",
    "cursor": "cursor.svg",
}

FALLBACK = {
    "mock": ("EX", "#7C5CFF"),
    "claude": ("CC", "#D97757"),
    "codex": ("CX", "#4D7CFE"),
    "zcode": ("ZC", "#111113"),
    "opencode": ("OC", "#111113"),
    "cursor": ("CU", "#111113"),
}


def agent_icon_path(key: str) -> Path | None:
    name = FILES.get(key)
    if not name:
        return None
    path = ASSET_DIR / name
    return path if path.exists() else None


@lru_cache(maxsize=64)
def agent_qicon(key: str) -> QIcon:
    path = agent_icon_path(key)
    if path:
        return QIcon(str(path))
    return QIcon(fallback_pixmap(key, 64))


@lru_cache(maxsize=64)
def fallback_pixmap(key: str, size: int = 64) -> QPixmap:
    badge, color = FALLBACK.get(key, ("AI", "#7C5CFF"))
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(2, 2, size - 4, size - 4)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(rect, size * 0.3, size * 0.3)
    if key == "mock":
        painter.setBrush(QColor("#FFFFFF"))
        path = QPainterPath()
        cx, cy = size / 2, size / 2
        outer, inner = size * 0.27, size * 0.085
        for index in range(8):
            angle = -1.5708 + index * 0.7854
            radius = outer if index % 2 == 0 else inner
            x = cx + radius * __import__("math").cos(angle)
            y = cy + radius * __import__("math").sin(angle)
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
    else:
        font = QFont("Microsoft YaHei UI", max(7, int(size * 0.32)))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, badge)
    painter.end()
    return pix


@lru_cache(maxsize=64)
def agent_mono_icon(key: str, color: str, size: int = 16) -> QIcon:
    """把彩色图标压成单色：空闲 Agent 用线条风格，运行中才显示原色。"""
    scale = 2
    base = agent_qicon(key).pixmap(size * scale, size * scale)
    if base.isNull():
        return QIcon()
    out = QPixmap(base.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, base)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), QColor(color))
    painter.end()
    out.setDevicePixelRatio(scale)
    return QIcon(out)

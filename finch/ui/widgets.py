from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Any, Callable, Sequence

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    DotInfoBadge,
    InfoBadge,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    MessageBox,
    MessageBoxBase,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    theme,
)

from . import theme as finch_theme
from .glyphs import line_icon
from ..models import STATUS_LABELS


def _paint_finch_mark(painter: QPainter, size: float, inset: float = 0.0) -> None:
    rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    accent = QColor(finch_theme.ACCENT)
    gradient.setColorAt(0.0, accent.lighter(115))
    gradient.setColorAt(0.55, accent)
    gradient.setColorAt(1.0, accent.darker(118))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    radius = size * 0.27
    painter.drawRoundedRect(rect, radius, radius)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 48), max(1.0, size * 0.012)))
    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

    stem_x = size * 0.42
    stem_top = size * 0.34
    stem_bottom = size * 0.76
    pen = QPen(QColor("#FFFFFF"), max(1.4, size * 0.095), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(stem_x, stem_top), QPointF(stem_x, stem_bottom))
    hook = QPainterPath()
    hook.moveTo(stem_x, size * 0.38)
    hook.cubicTo(stem_x, size * 0.30, size * 0.49, size * 0.27, size * 0.57, size * 0.30)
    painter.drawPath(hook)
    painter.drawLine(QPointF(size * 0.28, size * 0.49), QPointF(size * 0.63, size * 0.49))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 210))
    painter.drawEllipse(QPointF(size * 0.71, size * 0.27), size * 0.052, size * 0.052)


def make_app_icon(size: int = 64) -> QIcon:
    icon = QIcon()
    for edge in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        pix = QPixmap(edge, edge)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_finch_mark(painter, edge, edge * 0.03)
        painter.end()
        icon.addPixmap(pix)
    return icon


def apply_shadow(widget: QWidget, blur: int = 12, y: int = 2, alpha: int = 10) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(15, 18, 25, alpha))
    widget.setGraphicsEffect(effect)


def divider(horizontal: bool = True) -> QFrame:
    line = QFrame()
    line.setObjectName("Divider" if horizontal else "VDivider")
    return line


def format_time(timestamp: float) -> str:
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def format_duration(seconds: float) -> str:
    seconds = int(max(0.0, seconds or 0.0))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minute = divmod(minutes, 60)
    return f"{hours}h {minute:02d}m"


def pick_folder(parent: QWidget, current: str = "", title: str = "选择工作目录") -> str:
    """Open the library's folder picker and return the chosen path."""
    from qfluentwidgets import FolderListDialog

    paths = [current] if current else []
    dialog = FolderListDialog(paths, title, "确认要使用的目录后点击「完成」。", parent)
    dialog.completeButton.setText("完成")
    dialog.exec()
    chosen = dialog.folderPaths
    return chosen[-1] if chosen else ""


class ElidedLabel(QLabel):
    def __init__(
        self,
        text: str = "",
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight,
        parent: QWidget | None = None,
    ):
        super().__init__(text, parent)
        self._full_text = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        self.setToolTip(self._full_text if self._full_text else "")
        super().setText(self._full_text)
        self.update()

    def full_text(self) -> str:
        return self._full_text

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.font())
        return QSize(60, metrics.height() + 2)

    def minimumSizeHint(self) -> QSize:
        metrics = QFontMetrics(self.font())
        return QSize(0, metrics.height() + 2)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        elided = QFontMetrics(self.font()).elidedText(self._full_text, self._mode, rect.width())
        painter.drawText(rect, int(self.alignment()), elided)


class StatusDot(DotInfoBadge):
    """Library dot badge that mirrors the task state colour."""

    def __init__(self, status: str = "queued", size: int = 10, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        fg, _bg = finch_theme.STATUS_COLORS.get(status, (finch_theme.MUTED, finch_theme.SLATE_SOFT))
        self.setCustomBackgroundColor(QColor(fg), QColor(fg))


class StatusPill(InfoBadge):
    """Library info badge used as a status chip."""

    def __init__(self, status: str = "queued", label: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.set_status(status, label)

    def set_status(self, status: str, label: str | None = None) -> None:
        fg, _bg = finch_theme.STATUS_COLORS.get(status, (finch_theme.MUTED, finch_theme.SLATE_SOFT))
        self.setText(label or STATUS_LABELS.get(status, status))
        self.setCustomBackgroundColor(QColor(fg), QColor(fg))


class ToggleSwitch(SwitchButton):
    """Fluent switch with the toggled signal our panels expect."""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        # The library renders an English On/Off caption next to the indicator;
        # the Chinese UI only needs the pill itself.
        self.setOnText("")
        self.setOffText("")
        self.setChecked(checked)
        self.checkedChanged.connect(self.toggled.emit)


class Select(ComboBox):
    """Fluent combo box keeping Finch's key/value API."""

    changed = pyqtSignal(str)

    def __init__(
        self,
        options: Sequence[tuple[str, str]] | None = None,
        value: str = "",
        parent: QWidget | None = None,
        icons: Callable[[str], QIcon | None] | None = None,
    ):
        super().__init__(parent)
        self._icons = icons
        self._keys: list[str] = []
        self.currentIndexChanged.connect(self._on_index_changed)
        self.set_options(options or [], value)

    def _on_index_changed(self, _index: int) -> None:
        self.changed.emit(self.value())

    def value(self) -> str:
        data = self.currentData()
        return str(data) if data is not None else ""

    def label(self) -> str:
        return self.currentText()

    def set_options(self, options: Sequence[tuple[str, str]], value: str | None = None) -> None:
        self.clear()
        self._keys = []
        for key, label in options:
            icon = self._icons(key) if self._icons else None
            if icon is not None:
                self.addItem(label, icon, key)
            else:
                self.addItem(label, None, key)
            self._keys.append(key)
        if value is not None:
            self.set_value(value)
        elif self._keys:
            self.setCurrentIndex(0)

    def set_value(self, value: str) -> None:
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)


class BaseDialog(MessageBoxBase):
    """Fluent mask dialog with Finch's body/footer layout."""

    def __init__(self, parent: QWidget | None, title: str, width: int = 720, height: int | None = None):
        super().__init__(parent)
        self.setDraggable(True)
        self.setMaskColor(QColor(0, 0, 0, 76))
        self.widget.setFixedWidth(width)
        self.title_label = SubtitleLabel(title, self.widget)
        self.viewLayout.addWidget(self.title_label)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self.viewLayout.addLayout(self.body)
        self.buttonLayout.removeWidget(self.yesButton)
        self.buttonLayout.removeWidget(self.cancelButton)
        self.yesButton.hide()
        self.cancelButton.hide()
        self.buttonLayout.setContentsMargins(24, 12, 24, 12)
        self.footer = QHBoxLayout()
        self.footer.setSpacing(8)
        self.buttonLayout.addLayout(self.footer, 1)
        self.buttonGroup.setFixedHeight(60)
        if height:
            self.widget.setFixedHeight(height)

    def add_footer_stretch(self) -> None:
        self.footer.addStretch(1)


class ConfirmDialog(MessageBox):
    """Fluent message box with a confirm / cancel pair."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        confirm_text: str = "确认",
        danger: bool = False,
    ):
        super().__init__(title, message, parent)
        self.yesButton.setText(confirm_text)
        self.cancelButton.setText("取消")
        if danger:
            danger = QColor(finch_theme.RED)
            self.yesButton.setStyleSheet(
                "QPushButton { background: %s; color: white; border-radius: 5px; }"
                "QPushButton:hover { background: %s; }"
                % (danger.name(), danger.darker(112).name())
            )

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        title: str,
        message: str,
        confirm_text: str = "确认",
        danger: bool = False,
    ) -> bool:
        box = cls(parent, title, message, confirm_text, danger)
        return box.exec() == MessageBox.Accepted


class NoticeDialog(MessageBox):
    def __init__(self, parent: QWidget | None, title: str, message: str, level: str = "info"):
        marker = {"error": "✕", "warning": "!", "info": "i"}.get(level, "i")
        super().__init__(title, f"{marker}  {message}", parent)
        self.yesButton.setText("知道了")
        self.hideCancelButton()

    @classmethod
    def present(cls, parent: QWidget, title: str, message: str, level: str = "info") -> "NoticeDialog":
        dialog = cls(parent, title, message, level)
        dialog.show()
        dialog.raise_()
        return dialog


class Toast:
    """Fluent info bar used as an in-window toast."""

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._bar: InfoBar | None = None

    def show_message(self, message: str, level: str = "info", duration: int = 3200) -> None:
        icon = {
            "success": InfoBarIcon.SUCCESS,
            "warning": InfoBarIcon.WARNING,
            "error": InfoBarIcon.ERROR,
            "info": InfoBarIcon.INFORMATION,
        }.get(level, InfoBarIcon.INFORMATION)
        self.hide()
        self._bar = InfoBar(
            icon,
            "",
            message,
            position=InfoBarPosition.TOP,
            isClosable=True,
            duration=duration,
            parent=self._parent,
        )
        self._bar.show()

    def hide(self) -> None:
        if self._bar is not None:
            try:
                self._bar.close()
            except Exception:
                pass
            self._bar = None

    def isVisible(self) -> bool:
        return self._bar is not None and self._bar.isVisible()

    def reposition(self) -> None:
        return None


class _WorkerThread(QThread):
    done = pyqtSignal(bool, object)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            ok, result = True, self._fn()
        except Exception as exc:  # noqa: BLE001 - surfaced to the callback
            ok, result = False, exc
        self.done.emit(ok, result)


class BackgroundTask(QObject):
    """Run a callable off the UI thread and report the result on it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._worker: _WorkerThread | None = None
        self._callback = None

    def run(self, fn, callback) -> None:
        self._callback = callback
        worker = _WorkerThread(fn)
        worker.done.connect(self._on_done, Qt.ConnectionType.QueuedConnection)
        self._worker = worker
        worker.start()

    @pyqtSlot(bool, object)
    def _on_done(self, ok: bool, value) -> None:
        if self._callback is not None:
            self._callback(ok, value)


class BackgroundTask(QObject):
    """Run a callable off the UI thread and report the result on it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._worker: _WorkerThread | None = None
        self._callback = None

    def run(self, fn, callback) -> None:
        self._callback = callback
        worker = _WorkerThread(fn)
        worker.done.connect(self._on_done, Qt.ConnectionType.QueuedConnection)
        self._worker = worker
        worker.start()

    @pyqtSlot(bool, object)
    def _on_done(self, ok: bool, value) -> None:
        if self._callback is not None:
            self._callback(ok, value)


class Chip(QLabel):
    def __init__(self, text: str = "", tone: str = "muted", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        colors = {
            "muted": (finch_theme.SLATE_SOFT, finch_theme.MUTED),
            "green": (finch_theme.GREEN_SOFT, finch_theme.GREEN_TINT),
            "orange": (finch_theme.ORANGE_SOFT, finch_theme.ORANGE_TINT),
            "red": (finch_theme.RED_SOFT, finch_theme.RED_TINT),
            "violet": (finch_theme.VIOLET_SOFT, finch_theme.VIOLET_TINT),
        }
        bg, fg = colors.get(tone, colors["muted"])
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 6px; padding: 3px 8px;"
            "font-size: 12px; font-weight: 500;"
        )

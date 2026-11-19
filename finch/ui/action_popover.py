from __future__ import annotations

from typing import Callable, Sequence
from weakref import WeakKeyDictionary

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtGui import QFontMetrics, QIcon
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, TransparentToolButton

from . import theme
from .widgets import ElidedLabel

_OPEN_POPOVERS: list["ActionPopover"] = []


def _forget(popover: "ActionPopover") -> None:
    """按身份移除，避免对已销毁的 C++ 对象做比较。"""
    for item in list(_OPEN_POPOVERS):
        if item is popover:
            _OPEN_POPOVERS.remove(item)


def close_all() -> None:
    """退出前统一收起，避免残留的顶层卡片在销毁阶段回调。"""
    for popover in list(_OPEN_POPOVERS):
        try:
            popover.hide()
        except RuntimeError:
            _forget(popover)
    _OPEN_POPOVERS.clear()
_POPOVERS: "WeakKeyDictionary[QWidget, ActionPopover]" = WeakKeyDictionary()


class ActionPopover(CardWidget):
    """Fluent action list that opens next to a button.

    The library's popup menu relies on an acrylic window that is not stable in
    every environment, so the actions are shown in a small card built from
    library widgets instead.
    """

    def __init__(self, anchor: QWidget, items: Sequence[tuple[str, QIcon, Callable[[], None]]]):
        super().__init__(anchor.window() if anchor.window() else anchor)
        self._anchor = anchor
        self.setObjectName("ActionPopover")
        self.setBorderRadius(8)
        self.setFixedWidth(200)
        self.setStyleSheet(
            f"QWidget#ActionPopover {{ background: {theme.CARD};"
            f" border: 1px solid {theme.BORDER_STRONG}; border-radius: 8px; }}"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(2)
        self.set_items(items)
        self.hide()

    def set_items(self, items: Sequence[tuple[str, QIcon, Callable[[], None]]]) -> None:
        self.hide()
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        # 宽度按最长文案算，避免 176px 固定宽把「清理（独立目录）与队列顺序」截断
        metrics = QFontMetrics(self.font())
        widest = max(
            (metrics.horizontalAdvance(text) for text, _icon, _cb in items),
            default=0,
        )
        self.setFixedWidth(max(200, min(320, widest + 86)))

        for text, icon, callback in items:
            button = TransparentToolButton()
            button.setIcon(icon)
            button.setIconSize(self._anchor.iconSize())
            button.setToolTip(text)
            button.setFixedSize(20, 28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row = QHBoxLayout()
            row.setContentsMargins(8, 0, 8, 0)
            row.setSpacing(8)
            row.addWidget(button, 0)
            label = ElidedLabel(text, parent=self)
            label.setStyleSheet(
                f"background: transparent; font-size: 13px; color: {theme.TEXT};"
            )
            label.setToolTip(text)
            row.addWidget(label, 1)
            holder = QWidget(self)
            holder.setObjectName("PopoverRow")
            holder.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            holder.setLayout(row)
            holder.setCursor(Qt.CursorShape.PointingHandCursor)
            holder.setStyleSheet(
                "QWidget#PopoverRow { background: transparent; border-radius: 6px; }"
                "QWidget#PopoverRow:hover { background: rgba(255, 255, 255, 0.07); }"
            )
            holder.mouseReleaseEvent = lambda _event, cb=callback: self._run(cb)()
            button.clicked.connect(self._run(callback))
            self._layout.addWidget(holder)

    def _run(self, callback: Callable[[], None]) -> Callable[[], None]:
        def invoke() -> None:
            self.hide()
            callback()

        return invoke

    def hide(self) -> None:
        super().hide()
        _forget(self)

    def popup(self) -> None:
        self.adjustSize()
        anchor = self._anchor
        window = anchor.window()
        if window is None:
            return
        margin = 8
        below = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        above = anchor.mapToGlobal(QPoint(0, -self.height() - 4))
        position = window.mapFromGlobal(below)
        # 下方放不下就翻到上方；左右都夹在窗口内，避免贴边被裁
        if position.y() + self.height() > window.height() - margin:
            position.setY(window.mapFromGlobal(above).y())
        position.setX(
            max(margin, min(position.x(), window.width() - self.width() - margin))
        )
        position.setY(
            max(margin, min(position.y(), window.height() - self.height() - margin))
        )
        self.move(position)
        self.show()
        self.raise_()
        if self not in _OPEN_POPOVERS:
            _OPEN_POPOVERS.append(self)


def open_popover(
    anchor: QWidget, items: Sequence[tuple[str, QIcon, Callable[[], None]]]
) -> ActionPopover:
    """Show the action list of `anchor`, reusing the card across openings."""
    popover = _POPOVERS.get(anchor)
    if popover is None:
        popover = ActionPopover(anchor, items)
        _POPOVERS[anchor] = popover
        anchor.destroyed.connect(popover.deleteLater)
        popover.destroyed.connect(lambda _=None, p=popover: _forget(p))
    else:
        popover.set_items(items)
    popover.popup()
    return popover


class PopoverWatcher(QObject):
    """Close open popovers when the user clicks elsewhere or presses Escape."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            position = event.globalPosition().toPoint()
            for popover in list(_OPEN_POPOVERS):
                window = popover.parentWidget()
                if window is None:
                    continue
                try:
                    inside = popover.geometry().contains(window.mapFromGlobal(position))
                except RuntimeError:
                    _forget(popover)
                    continue
                if not inside:
                    popover.hide()
        elif event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            for popover in list(_OPEN_POPOVERS):
                popover.hide()
        return False

from __future__ import annotations

from typing import Callable, Sequence
from weakref import WeakKeyDictionary

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, TransparentToolButton

_OPEN_POPOVERS: list["ActionPopover"] = []
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
        self.setFixedWidth(176)
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
            label = BodyLabel(text, self)
            label.setStyleSheet("background: transparent; font-size: 13px;")
            row.addWidget(label, 1)
            holder = QWidget(self)
            holder.setLayout(row)
            holder.setCursor(Qt.CursorShape.PointingHandCursor)
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
        if self in _OPEN_POPOVERS:
            _OPEN_POPOVERS.remove(self)

    def popup(self) -> None:
        self.adjustSize()
        anchor = self._anchor
        window = anchor.window()
        if window is None:
            return
        global_pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        screen = window.screen()
        geometry = screen.availableGeometry() if screen else None
        if geometry is not None and global_pos.y() + self.height() > geometry.bottom():
            global_pos = anchor.mapToGlobal(QPoint(0, -self.height() - 4))
        position = window.mapFromGlobal(global_pos)
        position.setX(max(4, min(position.x(), window.width() - self.width() - 4)))
        position.setY(max(4, min(position.y(), window.height() - self.height() - 4)))
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
                    _OPEN_POPOVERS.remove(popover)
                    continue
                if not inside:
                    popover.hide()
        elif event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            for popover in list(_OPEN_POPOVERS):
                popover.hide()
        return False

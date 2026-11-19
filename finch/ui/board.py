from __future__ import annotations

from PyQt6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QPainter, QPen
from PyQt6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel, TransparentToolButton

from ..agents import adapter_label
from ..models import Run, STATUS_LABELS, Task, TaskStatus
from qfluentwidgets import SmoothScrollArea

from qfluentwidgets import FluentIcon

from . import theme
from .agent_icons import agent_qicon
from .glyphs import line_icon
from .action_popover import open_popover
from .task_row import DRAG_MIME
from .widgets import ElidedLabel

COLUMN_DEFS = [
    ("todo", "待办", {TaskStatus.queued.value, TaskStatus.interrupted.value}),
    (
        "progress",
        "进行中",
        {
            TaskStatus.running.value,
            TaskStatus.tool.value,
            TaskStatus.resuming.value,
            TaskStatus.patching.value,
            TaskStatus.validating.value,
        },
    ),
    ("review", "待处理", {TaskStatus.awaiting.value, TaskStatus.attention.value, TaskStatus.failed.value}),
    ("done", "已完成", {TaskStatus.done.value, TaskStatus.skipped.value, TaskStatus.stopped.value}),
]

COLUMN_MIME = "application/x-finch-column"
DEFAULT_WIDTH = 240
MIN_WIDTH = 140
SNAP_WIDTHS = (160, 200, 240, 280, 320)


class BoardCard(QFrame):
    """Board card with an explicit background — the library card widget
    intermittently failed to paint its surface in the dark theme."""

    selected = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    optimize_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, task: Task, runs: list[Run], default_agent: str, draggable: bool, parent=None):
        super().__init__(parent)
        self.task_id = task.id
        self._draggable = draggable
        self._selected = False
        self._press_pos: QPoint | None = None
        self.setObjectName("BoardCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.title = ElidedLabel(task.title or "未命名任务")
        self.title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT};")
        top.addWidget(self.title, 1)
        self.more = TransparentToolButton()
        self.more.setIcon(line_icon("ellipsis", theme.SUBTLE, 14))
        self.more.setIconSize(QSize(14, 14))
        self.more.setFixedSize(22, 22)
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.clicked.connect(self._open_menu)
        top.addWidget(self.more, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(top)

        # 悬停才显示操作，占位不消失避免标题抖动
        self._more_fx = QGraphicsOpacityEffect(self.more)
        self._more_fx.setOpacity(0.0)
        self.more.setGraphicsEffect(self._more_fx)
        self.more.setEnabled(False)

        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.agent_icon = QLabel()
        self.agent_icon.setFixedSize(14, 14)
        foot.addWidget(self.agent_icon)
        self.agent_label = ElidedLabel("")
        self.agent_label.setMinimumWidth(40)
        self.agent_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 11px;")
        foot.addWidget(self.agent_label, 1)
        self.pill = CaptionLabel("")
        self.pill.setStyleSheet(f"color: {theme.MUTED}; font-weight: 500;")
        foot.addWidget(self.pill)
        layout.addLayout(foot)

        self.meta = ElidedLabel("")
        self.meta.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 11px;")
        layout.addWidget(self.meta)
        self.set_selected(False)
        self.update_data(task, runs, default_agent)

    def update_data(self, task: Task, runs: list[Run], default_agent: str) -> None:
        self.title.setText(task.title or "未命名任务")
        self.title.setToolTip(task.title or "")
        agent = task.agent or default_agent
        self.agent_icon.setPixmap(
            agent_qicon(agent)
            .pixmap(QSize(28, 28))
            .scaled(14, 14, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        self.agent_label.setText(adapter_label(agent))
        fg, _bg = theme.STATUS_COLORS.get(task.status, (theme.MUTED, theme.SLATE_SOFT))
        self.pill.setText(STATUS_LABELS.get(task.status, task.status))
        self.pill.setStyleSheet(f"color: {fg}; font-weight: 500;")
        bits = []
        if task.resume_count:
            bits.append(f"续传 {task.resume_count}")
        if task.followup_count:
            bits.append(f"补做 {task.followup_count}")
        if task.tool_count:
            bits.append(f"工具 {task.tool_count}")
        if task.status in (TaskStatus.attention.value, TaskStatus.failed.value):
            bits.append(task.attention_reason or task.error or "待人工")
        elif task.status == TaskStatus.awaiting.value:
            bits.append("等待确认补做")
        elif task.status == TaskStatus.done.value:
            bits.append(task.summary or "已完成")
        elif task.progress:
            bits.append(task.progress)
        text = " · ".join(bits)
        self.meta.setText(text)
        self.meta.setToolTip(text)
        self.meta.setVisible(bool(bits))

    def enterEvent(self, event) -> None:
        self._more_fx.setOpacity(1.0)
        self.more.setEnabled(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._more_fx.setOpacity(1.0 if self._selected else 0.0)
        self.more.setEnabled(self._selected)
        super().leaveEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._more_fx.setOpacity(1.0 if selected or self.underMouse() else 0.0)
        bg = theme.ACCENT_SOFT if selected else theme.CARD
        border = theme.ACCENT if selected else theme.BORDER_STRONG
        self.setStyleSheet(
            f"QFrame#BoardCard {{ background: {bg}; border: 1px solid {border};"
            " border-radius: 8px; }"
        )

    def _open_menu(self) -> None:
        open_popover(
            self.more,
            [
                ("编辑任务", line_icon("edit"), lambda: self.edit_requested.emit(self.task_id)),
                ("优化提示词", line_icon("optimize"), lambda: self.optimize_requested.emit(self.task_id)),
                ("重新执行", line_icon("sync"), lambda: self.retry_requested.emit(self.task_id)),
                ("删除任务", line_icon("delete"), lambda: self.delete_requested.emit(self.task_id)),
            ],
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._draggable and self._press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (event.position().toPoint() - self._press_pos).manhattanLength() > 12:
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData(DRAG_MIME, self.task_id.encode("utf-8"))
                drag.setMimeData(mime)
                self._press_pos = None
                drag.exec(Qt.DropAction.MoveAction)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            self._press_pos = None
            self.selected.emit(self.task_id)
        super().mouseReleaseEvent(event)


class ColumnGrip(QWidget):
    """Right-edge resize handle with magnetic snapping."""

    resized = pyqtSignal(int)

    def __init__(self, column: "BoardColumn"):
        super().__init__(column)
        self._column = column
        self._press_x = 0
        self._start_width = 0
        self.setFixedWidth(6)
        self.setCursor(Qt.CursorShape.SplitHCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_x = int(event.globalPosition().x())
            self._start_width = self._column.width()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            delta = int(event.globalPosition().x()) - self._press_x
            width = max(MIN_WIDTH, self._start_width + delta)
            snapped = min(SNAP_WIDTHS, key=lambda value: abs(value - width))
            if abs(snapped - width) <= 12:
                width = snapped
            else:
                width = round(width / 8) * 8
            self._column.set_column_width(width)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._column.commit_width()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(theme.BORDER_STRONG), 1))
        painter.drawLine(2, 6, 2, self.height() - 6)


class BoardColumn(QFrame):
    add_requested = pyqtSignal()
    selected = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    optimize_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    drop_before = pyqtSignal(str, str)  # dragged task id, before id ("" = append)
    column_dragged = pyqtSignal(str, int)  # column key, drop index
    column_hidden = pyqtSignal(str)
    column_width_changed = pyqtSignal(str, int)

    def __init__(self, key: str, label: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("BoardColumn")
        fg, pill_bg, _col_bg = theme.COLUMN_TONES[key]
        self._col_bg = theme.CARD
        self.setStyleSheet(
            "QFrame#BoardColumn { background: transparent; border: 1px solid transparent; border-radius: 8px; }"
        )
        self.setAcceptDrops(True)
        self.setMinimumWidth(MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        self._root_layout = root
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(8)

        self.header = QWidget()
        head = QHBoxLayout(self.header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(4)
        self.handle = TransparentToolButton()
        self.handle.setIcon(line_icon("menu", theme.SUBTLE, 12))
        self.handle.setIconSize(QSize(12, 12))
        self.handle.setFixedSize(18, 18)
        self.handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self.handle.setToolTip("拖动可调整列顺序")
        self.handle.mousePressEvent = self._handle_press
        self.handle.mouseMoveEvent = self._handle_move
        head.addWidget(self.handle)
        self.tone_dot = QLabel()
        self.tone_dot.setFixedSize(6, 6)
        self.tone_dot.setStyleSheet(f"background: {fg}; border-radius: 3px;")
        head.addWidget(self.tone_dot)
        self.pill = QLabel(label)
        self.pill.setStyleSheet(
            f"color: {theme.TEXT_SOFT}; font-size: 12.5px; font-weight: 600;"
        )
        head.addWidget(self.pill)
        self.count = QLabel("0")
        self.count.setStyleSheet(
            f"background: {theme.SURFACE_2}; color: {theme.MUTED}; border-radius: 4px;"
            " padding: 1px 6px; font-size: 11px; font-weight: 600;"
        )
        head.addWidget(self.count)
        head.addStretch(1)
        self.menu_btn = TransparentToolButton()
        self.menu_btn.setIcon(line_icon("ellipsis", theme.SUBTLE, 14))
        self.menu_btn.setIconSize(QSize(14, 14))
        self.menu_btn.setFixedSize(22, 22)
        self.menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.menu_btn.setToolTip("列设置")
        self.menu_btn.clicked.connect(self._open_menu)
        head.addWidget(self.menu_btn)
        root.addWidget(self.header)

        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.host.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.host)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        self.add_btn = TransparentToolButton()
        self.add_btn.setIcon(line_icon("plus", theme.MUTED, 12))
        self.add_btn.setIconSize(QSize(12, 12))
        self.add_btn.setFixedSize(20, 20)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setToolTip("新增任务")
        self.add_btn.clicked.connect(self.add_requested.emit)
        self.add_btn.setVisible(key == "todo")
        head.addWidget(self.add_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.grip = ColumnGrip(self)
        root.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignRight)

        self.cards: dict[str, BoardCard] = {}
        self._order: list[str] = []
        self._drag_hover = False
        self._drag_start: QPoint | None = None
        self._vertical = False
        self._order_index = 0

    # -- geometry ------------------------------------------------------
    def set_column_width(self, width: int) -> None:
        self.setFixedWidth(max(MIN_WIDTH, width))

    def commit_width(self) -> None:
        self.column_width_changed.emit(self.key, self.width())

    def _reset_width(self) -> None:
        self.set_column_width(DEFAULT_WIDTH)
        self.commit_width()

    def set_vertical(self, vertical: bool) -> None:
        if vertical == self._vertical:
            self._sync_minimum_height()
            return
        self._vertical = vertical
        self._apply_layout_mode(vertical)

    def _apply_layout_mode(self, vertical: bool) -> None:
        """Switch the column between a scrolling column and a stacked block.

        The layout order never changes: only the scroll policy and the height
        do, so the header can never end up underneath the cards.
        """
        if vertical:
            self.scroll.setWidgetResizable(False)
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.grip.hide()
        else:
            self.scroll.setWidgetResizable(True)
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.grip.show()
        self._sync_minimum_height()

    def _sync_minimum_height(self) -> None:
        """In the stacked layout a column must be as tall as its cards."""
        if not self._vertical:
            self.setMinimumHeight(120)
            self.setMaximumHeight(16777215)
            self.host.setMinimumHeight(0)
            self.host.setMaximumHeight(16777215)
            return
        cards = max(self.host.sizeHint().height(), self.host.minimumSizeHint().height())
        self.host.setMinimumHeight(cards)
        self.host.setFixedHeight(cards)
        self.setMinimumHeight(cards + 64)
        self.setMaximumHeight(cards + 64)
        QTimer.singleShot(0, self._sync_minimum_height)

    def set_order_index(self, index: int) -> None:
        self._order_index = index

    def _sync_minimum_height(self) -> None:
        """In the stacked layout a column must be as tall as its cards."""
        if not self._vertical:
            self.setMinimumHeight(120)
            return
        cards = self.host.sizeHint().height()
        self.setMinimumHeight((cards + 64) if cards > 0 else 72)

    # -- column dragging ------------------------------------------------
    def _handle_press(self, event) -> None:
        self._drag_start = event.position().toPoint()
        self.handle.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _handle_move(self, event) -> None:
        if self._drag_start is None:
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 12:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(COLUMN_MIME, self.key.encode("utf-8"))
        drag.setMimeData(mime)
        self._drag_start = None
        drag.exec(Qt.DropAction.MoveAction)

    # -- menu ------------------------------------------------------------
    def _open_menu(self) -> None:
        open_popover(
            self.menu_btn,
            [
                ("隐藏此列", line_icon("hide"), lambda: self.column_hidden.emit(self.key)),
                ("恢复默认宽度", line_icon("view"), self._reset_width),
            ],
        )

    # -- cards ------------------------------------------------------------
    def set_cards(self, tasks: list[Task], runs_map, default_agent: str, selected_id: str) -> None:
        ids = [t.id for t in tasks]
        if ids != self._order:
            while self.cards_layout.count():
                item = self.cards_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    # 先脱离父级，旧卡片不会在删除前继续画在列里
                    widget.setParent(None)
                    widget.deleteLater()
            self.cards.clear()
            self._order = ids
            for task in tasks:
                card = BoardCard(task, runs_map.get(task.id, []), default_agent, self.key == "todo")
                card.set_selected(task.id == selected_id)
                card.selected.connect(self.selected.emit)
                card.edit_requested.connect(self.edit_requested.emit)
                card.optimize_requested.connect(self.optimize_requested.emit)
                card.retry_requested.connect(self.retry_requested.emit)
                card.delete_requested.connect(self.delete_requested.emit)
                self.cards_layout.addWidget(card)
                self.cards[task.id] = card
        else:
            for task in tasks:
                card = self.cards.get(task.id)
                if card:
                    card.update_data(task, runs_map.get(task.id, []), default_agent)
                    card.set_selected(task.id == selected_id)
        self.count.setText(str(len(tasks)))
        self._sync_minimum_height()

    def set_selected(self, selected_id: str) -> None:
        for tid, card in self.cards.items():
            card.set_selected(tid == selected_id)

    def _card_at(self, y: int) -> str:
        for tid in self._order:
            card = self.cards.get(tid)
            if card and y < card.geometry().center().y():
                return tid
        return ""

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(DRAG_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(COLUMN_MIME):
            self._drag_hover = True
            self.setStyleSheet(
                f"QFrame#BoardColumn {{ background: {theme.ACCENT_SOFT}; border: 1px solid {theme.ACCENT_LINE};"
                " border-radius: 8px; }"
            )
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._drag_hover = False
        self.setStyleSheet(
            "QFrame#BoardColumn { background: transparent; border: 1px solid transparent; border-radius: 8px; }"
        )

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(DRAG_MIME) or event.mimeData().hasFormat(COLUMN_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(DRAG_MIME):
            task_id = bytes(event.mimeData().data(DRAG_MIME)).decode("utf-8")
            local_y = self.host.mapFrom(self, event.position().toPoint()).y()
            before = self._card_at(local_y)
            self.dragLeaveEvent(event)
            self.drop_before.emit(task_id, before)
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(COLUMN_MIME):
            key = bytes(event.mimeData().data(COLUMN_MIME)).decode("utf-8")
            if key == self.key:
                event.ignore()
                return
            pos = event.position().toPoint()
            before = (pos.y() if self._vertical else pos.x()) < (
                self.height() if self._vertical else self.width()
            ) / 2
            target = self._order_index if before else self._order_index + 1
            self.dragLeaveEvent(event)
            self.column_dragged.emit(key, target)
            event.acceptProposedAction()
            return
        event.ignore()


class KanbanBoard(QWidget):
    selected = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    optimize_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    add_requested = pyqtSignal()
    reorder_before = pyqtSignal(str, str)
    layout_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("KanbanBoard")
        self.setStyleSheet("QWidget#KanbanBoard { background: transparent; }")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self.row = QBoxLayout(QBoxLayout.Direction.LeftToRight, host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(10)
        self.scroll.setWidget(host)
        outer.addWidget(self.scroll)

        self.columns: dict[str, BoardColumn] = {}
        self.order: list[str] = [key for key, _label, _statuses in COLUMN_DEFS]
        self.hidden: list[str] = []
        self.widths: dict[str, int] = {}
        self.vertical = False
        for key, label, _statuses in COLUMN_DEFS:
            col = BoardColumn(key, label)
            col.add_requested.connect(self.add_requested.emit)
            col.drop_before.connect(self.reorder_before.emit)
            col.column_dragged.connect(self._on_column_dragged)
            col.column_hidden.connect(self._hide_column)
            col.column_width_changed.connect(self._on_width_changed)
            col.selected.connect(self.selected.emit)
            col.edit_requested.connect(self.edit_requested.emit)
            col.optimize_requested.connect(self.optimize_requested.emit)
            col.retry_requested.connect(self.retry_requested.emit)
            col.delete_requested.connect(self.delete_requested.emit)
            self.columns[key] = col
        self._rebuild()

    # -- configuration ---------------------------------------------------
    def apply_layout(self, state: dict) -> None:
        """Restore persisted column order, widths, hidden columns and mode."""
        order = [key for key in state.get("order", []) if key in self.columns]
        for key in self.order:
            if key not in order:
                order.append(key)
        self.order = order
        self.hidden = [key for key in state.get("hidden", []) if key in self.columns]
        self.widths = {k: int(v) for k, v in (state.get("widths") or {}).items() if k in self.columns}
        self.vertical = bool(state.get("vertical", False))
        self._rebuild()

    def layout_state(self) -> dict:
        return {
            "order": list(self.order),
            "hidden": list(self.hidden),
            "widths": dict(self.widths),
            "vertical": self.vertical,
        }

    def set_vertical(self, vertical: bool) -> None:
        self.vertical = bool(vertical)
        self._rebuild()
        self.layout_changed.emit(self.layout_state())

    def _rebuild(self) -> None:
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(self.scroll.widget())
        self.row.setDirection(
            QBoxLayout.Direction.TopToBottom if self.vertical else QBoxLayout.Direction.LeftToRight
        )
        for key in self.order:
            col = self.columns[key]
            col.setVisible(key not in self.hidden)
            col.set_vertical(self.vertical)
            col._sync_minimum_height()
            if self.vertical:
                col.setMinimumWidth(0)
                col.setMaximumWidth(16777215)
                col.setMaximumHeight(16777215)
            else:
                col.setMinimumHeight(0)
                col.setMaximumHeight(16777215)
                if key in self.widths:
                    col.setFixedWidth(self.widths[key])
                else:
                    # Not sized by the user yet: share the available width.
                    col.setMinimumWidth(MIN_WIDTH)
                    col.setMaximumWidth(16777215)
            self.row.addWidget(col)
        for index, key in enumerate(self.order):
            self.columns[key].set_order_index(index)
        bar = self.scroll.verticalScrollBar()
        if bar.value() > bar.minimum():
            bar.setValue(bar.minimum())
        self._sync_host_height()

    def _sync_host_height(self) -> None:
        host = self.scroll.widget()
        if self.vertical:
            visible = [self.columns[key] for key in self.order if key not in self.hidden]
            spacing = self.row.spacing() * max(0, len(visible) - 1)
            total = sum(col.minimumHeight() for col in visible) + spacing + 8
            required = self.row.totalMinimumSize().height()
            height = max(total, required, self.row.sizeHint().height())
            host.setMinimumHeight(height)
            host.setMaximumHeight(height)
            self.scroll.setWidgetResizable(False)
            host.setFixedWidth(max(320, self.scroll.viewport().width()))
            host.setFixedHeight(height)
        else:
            host.setMinimumHeight(0)
            host.setMaximumHeight(16777215)
            self.scroll.setWidgetResizable(True)

    def _hide_column(self, key: str) -> None:
        if key in self.hidden:
            return
        self.hidden.append(key)
        self._rebuild()
        self.layout_changed.emit(self.layout_state())

    def restore_column(self, key: str) -> None:
        if key not in self.hidden:
            return
        self.hidden.remove(key)
        self._rebuild()
        self.layout_changed.emit(self.layout_state())

    def hidden_columns(self) -> list[str]:
        return list(self.hidden)

    def _on_width_changed(self, key: str, width: int) -> None:
        self.widths[key] = width
        self.layout_changed.emit(self.layout_state())

    def _on_column_dragged(self, key: str, index: int) -> None:
        if key not in self.order:
            return
        self.order.remove(key)
        insert_at = max(0, min(index, len(self.order)))
        self.order.insert(insert_at, key)
        self._rebuild()
        self.layout_changed.emit(self.layout_state())

    # -- content ----------------------------------------------------------
    def set_tasks(self, tasks: list[Task], runs_map, default_agent: str, selected_id: str) -> None:
        for key, _label, statuses in COLUMN_DEFS:
            members = [t for t in tasks if t.status in statuses]
            self.columns[key].set_cards(members, runs_map, default_agent, selected_id)
        self._sync_host_height()

    def set_selected(self, selected_id: str) -> None:
        for col in self.columns.values():
            col.set_selected(selected_id)

    def update_task(self, task: Task, runs: list[Run], default_agent: str, selected_id: str) -> bool:
        for key, _label, statuses in COLUMN_DEFS:
            if task.status in statuses:
                col = self.columns[key]
                if task.id in col.cards:
                    col.cards[task.id].update_data(task, runs, default_agent)
                    col.cards[task.id].set_selected(task.id == selected_id)
                    return True
                return False
        return False

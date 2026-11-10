from __future__ import annotations

import os

from PyQt6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SegmentedWidget,
    SmoothScrollArea,
    TransparentToolButton,
)

from ..agents import ADAPTER_CLASSES, adapter_label
from ..config import AppConfig
from ..demo import add_demo_tasks
from ..models import Run, Task, TaskStatus
from ..store import Store
from . import theme
from .action_popover import open_popover
from .agent_icons import agent_qicon
from .autopilot_dialog import AutopilotDialog
from .board import COLUMN_DEFS, KanbanBoard
from .detail_panel import TaskDetailPanel
from .editor_dialog import OptimizeDialog, TaskEditorDialog
from .glyphs import line_icon
from .overview_panel import OverviewPanel
from .task_row import AddTaskRow, TaskRow
from .widgets import ConfirmDialog, Select, pick_folder

RUNNING = {
    TaskStatus.running.value,
    TaskStatus.tool.value,
    TaskStatus.resuming.value,
    TaskStatus.patching.value,
    TaskStatus.validating.value,
}


class QueueGlyph(QWidget):
    def __init__(self, size: int = 44, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        w = self._size
        painter.setBrush(QColor(theme.ACCENT_SOFT))
        painter.drawRoundedRect(QRectF(0, 0, w, w), w * 0.22, w * 0.22)
        for index, height in enumerate((0.50, 0.66, 0.38)):
            x = w * (0.18 + index * 0.24)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(QRectF(x, w * 0.24, w * 0.15, w * height), w * 0.05, w * 0.05)


class QueueList(QWidget):
    reorder_requested = pyqtSignal(str, int)
    selected = pyqtSignal(str)
    optimize_requested = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    run_requested = pyqtSignal(str, str)
    empty_new_requested = pyqtSignal()
    empty_demo_requested = pyqtSignal()
    add_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("QueueList")
        self.setStyleSheet("QWidget#QueueList { background: transparent; }")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 8)
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows: dict[str, TaskRow] = {}
        self._order: list[str] = []
        self._selected_id = ""
        self._drag_y = -1
        self._drag_active = False
        self._initialized = False

    def set_tasks(self, tasks, runs_map, default_agent, selected_id):
        ids = [task.id for task in tasks]
        missing = any(task.id not in self.rows for task in tasks)
        if not self._initialized or ids != self._order or missing:
            self._rebuild(tasks, runs_map, default_agent, selected_id)
            self._initialized = True
        else:
            for task in tasks:
                row = self.rows.get(task.id)
                if row:
                    row.update_data(task, runs_map.get(task.id, []), default_agent, task.id == selected_id)
        self._selected_id = selected_id

    def _rebuild(self, tasks, runs_map, default_agent, selected_id):
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.rows.clear()
        self._order = [task.id for task in tasks]
        if not tasks:
            self._layout.addWidget(self._empty_state())
            return
        for index, task in enumerate(tasks):
            row = TaskRow(task, runs_map.get(task.id, []), default_agent, index=index + 1, first=index == 0)
            row.selected.connect(self.selected.emit)
            row.optimize_requested.connect(self.optimize_requested.emit)
            row.edit_requested.connect(self.edit_requested.emit)
            row.retry_requested.connect(self.retry_requested.emit)
            row.delete_requested.connect(self.delete_requested.emit)
            row.run_requested.connect(self.run_requested.emit)
            row.set_selected(task.id == selected_id)
            self._layout.addWidget(row)
            self.rows[task.id] = row
        add = AddTaskRow()
        add.clicked.connect(self.add_requested.emit)
        self._layout.addWidget(add)

    def _empty_state(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(16, 40, 16, 40)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QueueGlyph(40), 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(4)
        title = QLabel("建立第一条任务")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        text = QLabel("把主提示词排进队列，Finch 会监听中断、自动续传，并在完成后验收与补做。")
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setFixedWidth(380)
        text.setMinimumHeight(40)
        text.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        layout.addWidget(text, 0, Qt.AlignmentFlag.AlignHCenter)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        new = PrimaryPushButton("新建任务")
        new.clicked.connect(self.empty_new_requested.emit)
        demo = PushButton("载入示例队列")
        demo.clicked.connect(self.empty_demo_requested.emit)
        buttons.addStretch(1)
        buttons.addWidget(demo)
        buttons.addWidget(new)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return host

    def update_task(self, task, runs, default_agent, selected_id) -> bool:
        self._selected_id = selected_id
        row = self.rows.get(task.id)
        if not row:
            return False
        row.update_data(task, runs, default_agent, task.id == selected_id)
        return True

    def set_selected(self, selected_id: str) -> None:
        self._selected_id = selected_id
        for task_id, row in self.rows.items():
            row.set_selected(task_id == selected_id)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(DRAG_MIME):
            event.acceptProposedAction()
            self._drag_active = True
            self.update()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(DRAG_MIME):
            event.ignore()
            return
        self._drag_y = int(event.position().y())
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drag_active = False
        self._drag_y = -1
        self.update()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(DRAG_MIME):
            event.ignore()
            return
        task_id = bytes(event.mimeData().data(DRAG_MIME)).decode("utf-8")
        index = self._index_at(int(event.position().y()))
        self._drag_active = False
        self._drag_y = -1
        self.update()
        self.reorder_requested.emit(task_id, index)
        event.acceptProposedAction()

    def _index_at(self, y: int) -> int:
        rows = [self.rows[tid] for tid in self._order if tid in self.rows]
        for index, row in enumerate(rows):
            geo = row.geometry()
            if y < geo.center().y():
                return index
        return len(rows)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._drag_active or self._drag_y < 0:
            return
        rows = [self.rows[tid] for tid in self._order if tid in self.rows]
        y = self.height() - 20
        for row in rows:
            if self._drag_y < row.geometry().center().y():
                y = row.geometry().top()
                break
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(theme.ACCENT))
        painter.drawLine(18, y, self.width() - 18, y)


class QueuePage(QWidget):
    notify = pyqtSignal(str, str)
    open_settings = pyqtSignal()
    toast_requested = pyqtSignal(str, str)
    filter_changed = pyqtSignal(str)

    def __init__(self, store: Store, engine, config: AppConfig, parent=None):
        super().__init__(parent)
        self.store = store
        self.engine = engine
        self.config = config
        self.selected_id = ""
        self.agent_filter = ""
        self._search = ""
        self._display_ids: list[str] = []
        self.setObjectName("Page")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header_wrap = QWidget()
        header = QHBoxLayout(header_wrap)
        header.setContentsMargins(32, 22, 32, 12)
        header.setSpacing(12)
        header.addWidget(QueueGlyph(40))
        left = QVBoxLayout()
        left.setSpacing(3)
        title = QLabel("任务队列")
        title.setObjectName("PageTitle")
        left.addWidget(title)
        subtitle = QLabel("按顺序下发提示词，区分工具执行与真实中断，自动续传、验收与补做。")
        subtitle.setObjectName("PageSubtitle")
        left.addWidget(subtitle)
        header.addLayout(left, 1)
        self.autopilot_btn = PushButton("自动驾驶")
        self.autopilot_btn.setIcon(line_icon("bot", theme.TEXT_SOFT, 16))
        self.autopilot_btn.setIconSize(QSize(16, 16))
        self.autopilot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autopilot_btn.clicked.connect(self._open_autopilot)
        header.addWidget(self.autopilot_btn)
        self.run_btn = PrimaryPushButton("开始队列")
        self.run_btn.setIcon(line_icon("play-solid"))
        self.run_btn.setIconSize(QSize(16, 16))
        self.run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_btn.clicked.connect(self._toggle_run)
        header.addWidget(self.run_btn)
        root.addWidget(header_wrap)

        toolbar_wrap = QWidget()
        toolbar = QHBoxLayout(toolbar_wrap)
        toolbar.setContentsMargins(32, 0, 32, 10)
        toolbar.setSpacing(6)
        self.view_tabs = SegmentedWidget()
        self.view_tabs.addItem("board", "看板", lambda: self._set_view(0))
        self.view_tabs.addItem("list", "清单", lambda: self._set_view(1))
        self.view_tabs.setCurrentItem("board")
        toolbar.addWidget(self.view_tabs)
        toolbar.addStretch(1)
        self.filter_chip = PushButton("")
        self.filter_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.filter_chip.setToolTip("清除 Agent 过滤")
        self.filter_chip.clicked.connect(lambda: self.set_agent_filter(""))
        self.filter_chip.hide()
        toolbar.addWidget(self.filter_chip)
        self.search_edit = SearchLineEdit()
        self.search_edit.setPlaceholderText("搜索任务…")
        self.search_edit.setFixedWidth(180)
        self.search_edit.textChanged.connect(self._on_search)
        toolbar.addWidget(self.search_edit)
        self.agent_select = Select(options=[], value=config.agent, icons=self._agent_icon)
        self.agent_select.setMinimumWidth(120)
        self.agent_select.setMaximumWidth(160)
        self.agent_select.changed.connect(self._on_agent_changed)
        toolbar.addWidget(self.agent_select)
        self.cwd_chip = PushButton("")
        self.cwd_chip.setIcon(line_icon("folder", theme.SUBTLE, 14))
        self.cwd_chip.setIconSize(QSize(14, 14))
        self.cwd_chip.setMaximumWidth(140)
        self.cwd_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cwd_chip.clicked.connect(self._choose_cwd)
        toolbar.addWidget(self.cwd_chip)
        self.new_btn = PushButton("新建")
        self.new_btn.setIcon(line_icon("plus", theme.TEXT_SOFT, 14))
        self.new_btn.setIconSize(QSize(14, 14))
        self.new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_btn.clicked.connect(self._new_task)
        toolbar.addWidget(self.new_btn)
        self.layout_btn = TransparentToolButton()
        self.layout_btn.setIcon(line_icon("layers", theme.TEXT_SOFT, 16))
        self.layout_btn.setIconSize(QSize(16, 16))
        self.layout_btn.setFixedSize(30, 30)
        self.layout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.layout_btn.setToolTip("横向 / 纵向切换看板排列")
        self.layout_btn.clicked.connect(self._toggle_layout)
        toolbar.addWidget(self.layout_btn)
        self.columns_btn = TransparentToolButton()
        self.columns_btn.setIcon(line_icon("sliders", theme.TEXT_SOFT, 16))
        self.columns_btn.setIconSize(QSize(16, 16))
        self.columns_btn.setFixedSize(30, 30)
        self.columns_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.columns_btn.setToolTip("列设置：显示已隐藏的列")
        self.columns_btn.clicked.connect(self._open_columns_menu)
        toolbar.addWidget(self.columns_btn)
        self.inspector_btn = TransparentToolButton()
        self.inspector_btn.setIcon(line_icon("view", theme.TEXT_SOFT, 16))
        self.inspector_btn.setIconSize(QSize(16, 16))
        self.inspector_btn.setFixedSize(30, 30)
        self.inspector_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.inspector_btn.setToolTip("显示 / 隐藏右侧概览面板")
        self.inspector_btn.clicked.connect(self._toggle_inspector)
        toolbar.addWidget(self.inspector_btn)
        root.addWidget(toolbar_wrap)

        content_wrap = QWidget()
        content_layout = QHBoxLayout(content_wrap)
        content_layout.setContentsMargins(32, 0, 0, 0)
        content_layout.setSpacing(0)

        self.view_stack = QStackedWidget()
        self.view_stack.setMinimumWidth(0)
        self.board = KanbanBoard()
        self.board.selected.connect(self._select_task)
        self.board.optimize_requested.connect(self._optimize_task)
        self.board.edit_requested.connect(self._edit_task)
        self.board.retry_requested.connect(self._retry_task)
        self.board.delete_requested.connect(self._delete_task)
        self.board.add_requested.connect(self._new_task)
        self.board.reorder_before.connect(self._reorder_before)
        self.board.layout_changed.connect(self._on_board_layout)
        if self.config.board_layout:
            self.board.apply_layout(self.config.board_layout)
        self.view_stack.addWidget(self.board)

        self.scroll = SmoothScrollArea()
        self.scroll.setMinimumWidth(0)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_list = QueueList()
        self.queue_list.setMinimumWidth(0)
        self.queue_list.selected.connect(self._select_task)
        self.queue_list.optimize_requested.connect(self._optimize_task)
        self.queue_list.edit_requested.connect(self._edit_task)
        self.queue_list.retry_requested.connect(self._retry_task)
        self.queue_list.delete_requested.connect(self._delete_task)
        self.queue_list.run_requested.connect(self._select_run)
        self.queue_list.empty_new_requested.connect(self._new_task)
        self.queue_list.empty_demo_requested.connect(self._load_demo)
        self.queue_list.add_requested.connect(self._new_task)
        self.queue_list.reorder_requested.connect(self._reorder_list)
        self.scroll.setWidget(self.queue_list)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.view_stack.addWidget(self.scroll)
        content_layout.addWidget(self.view_stack, 1)

        self.detail = TaskDetailPanel(self, store, engine)
        self.overview = OverviewPanel(config, engine)
        self.overview.auto_toggled.connect(self._on_auto_toggled)
        self.overview.open_task_requested.connect(self._select_task)
        self.rail_stack = QStackedWidget()
        self.rail_stack.setMinimumWidth(0)
        self.rail_stack.addWidget(self.overview)
        self.rail_stack.addWidget(self.detail)
        self.inspector = QFrame()
        self.inspector.setMinimumWidth(0)
        self.inspector.setObjectName("Inspector")
        self.inspector.setFixedWidth(300)
        inspector_layout = QVBoxLayout(self.inspector)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(0)
        inspector_layout.addWidget(self.rail_stack)
        content_layout.addWidget(self.inspector)
        self._apply_inspector_state()
        root.addWidget(content_wrap, 1)

        bottom = QFrame()
        bottom.setObjectName("BottomBar")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(32, 7, 32, 7)
        bottom_layout.setSpacing(8)
        self.state_dot = QLabel("•")
        self.state_dot.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        bottom_layout.addWidget(self.state_dot)
        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        bottom_layout.addWidget(self.stats_label)
        bottom_layout.addStretch(1)
        self.stop_btn = PushButton("终止")
        self.stop_btn.setFixedHeight(26)
        self.stop_btn.clicked.connect(self._stop_queue)
        self.skip_btn = PushButton("跳过续传/补做")
        self.skip_btn.setFixedHeight(26)
        self.skip_btn.clicked.connect(self._skip_retry)
        self.next_btn = PushButton("下一条")
        self.next_btn.setFixedHeight(26)
        self.next_btn.clicked.connect(self._force_next)
        for button in (self.stop_btn, self.skip_btn, self.next_btn):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            bottom_layout.addWidget(button)
        root.addWidget(bottom)

        self._latest_activity = ""
        self.detail.closed.connect(self._detail_closed)
        self.detail.optimize_requested.connect(self._optimize_task)
        self.detail.retry_requested.connect(self._retry_task)
        self.detail.notify.connect(self.notify.emit)
        self._connect_engine()
        self._update_agent_options()
        self.refresh(force=True)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick_active)
        self._tick_timer.start()

    # ------------------------------------------------------------------
    def _connect_engine(self) -> None:
        signals = self.engine.signals
        signals.queue_updated.connect(lambda: self.refresh())
        signals.task_updated.connect(self._on_task_updated)
        signals.run_updated.connect(self._on_run_updated)
        signals.state_changed.connect(lambda _state: self._update_controls())
        signals.log_line.connect(self.detail.append_log)
        signals.log_line.connect(self._on_log_activity)
        signals.awaiting.connect(self._on_awaiting)
        signals.autopilot_updated.connect(self._update_autopilot_btn)

    def _set_view(self, index: int) -> None:
        self.view_stack.setCurrentIndex(index)
        route = "board" if index == 0 else "list"
        if self.view_tabs.currentItem() != route:
            self.view_tabs.setCurrentItem(route)

    def _agent_icon(self, key: str) -> QIcon | None:
        return agent_qicon(key)

    def _update_agent_options(self) -> None:
        options = []
        for cls in ADAPTER_CLASSES:
            adapter = cls(self.config)
            installed = bool(adapter.find_executable())
            label = cls.label + ("" if installed else " · 未安装")
            options.append((cls.key, label))
        self.agent_select.set_options(options, self.config.agent)

    def _display_tasks(self, tasks: list[Task]) -> list[Task]:
        out = []
        for task in tasks:
            if self.agent_filter and (task.agent or self.config.agent) != self.agent_filter:
                continue
            if self._search:
                hay = f"{task.title} {task.prompt}".lower()
                if self._search not in hay:
                    continue
            out.append(task)
        return out

    def refresh(self, force: bool = False) -> None:
        tasks = self.store.list_tasks()
        runs_map = {task.id: self.store.list_runs(task.id) for task in tasks}
        if self.selected_id and self.selected_id not in {task.id for task in tasks}:
            self.selected_id = ""
            self.detail.hide()
            self.rail_stack.setCurrentWidget(self.overview)
        display = self._display_tasks(tasks)
        self._display_ids = [task.id for task in display]
        self.board.set_tasks(display, runs_map, self.config.agent, self.selected_id)
        self.board.set_selected(self.selected_id)
        self.queue_list.set_tasks(display, runs_map, self.config.agent, self.selected_id)
        self.queue_list.set_selected(self.selected_id)
        self.agent_select.set_value(self.config.agent)
        self._update_toolbar(tasks)
        self._update_controls(tasks)
        self._update_autopilot_btn()
        self._sync_layout_button()
        self.overview.refresh(tasks, self.engine.state, self.engine.active_task_id)
        if self.selected_id and self.rail_stack.currentWidget() is self.detail:
            self.detail.refresh()

    def _update_toolbar(self, tasks: list[Task]) -> None:
        path = self.config.cwd or "独立目录"
        display = path if len(path) <= 12 else "…" + path[-10:]
        self.cwd_chip.setText(display)
        self.cwd_chip.setToolTip(path)
        if self.agent_filter:
            self.filter_chip.setText(adapter_label(self.agent_filter) + " ✕")
            self.filter_chip.show()
        else:
            self.filter_chip.hide()
        done = sum(1 for task in tasks if task.status == TaskStatus.done.value)
        active = sum(1 for task in tasks if task.status in RUNNING)
        attention = sum(1 for task in tasks if task.status in (TaskStatus.attention.value, TaskStatus.failed.value))
        queued = sum(1 for task in tasks if task.status == TaskStatus.queued.value)
        awaiting = sum(1 for task in tasks if task.status == TaskStatus.awaiting.value)
        parts = [f"{done}/{len(tasks)} 完成"]
        if queued:
            parts.append(f"{queued} 待执行")
        if active:
            parts.append(f"{active} 进行中")
        if awaiting:
            parts.append(f"{awaiting} 待确认")
        if attention:
            parts.append(f"{attention} 待处理")
        resume_total = sum(task.resume_count for task in tasks)
        followup_total = sum(task.followup_count for task in tasks)
        tool_total = sum(task.tool_count for task in tasks)
        if resume_total:
            parts.append(f"{resume_total} 次续传")
        if followup_total:
            parts.append(f"{followup_total} 次补做")
        if tool_total:
            parts.append(f"{tool_total} 次工具")
        self.stats_label.setText(" · ".join(parts))

    def _update_autopilot_btn(self) -> None:
        if self.engine.autopilot_active:
            state = self.engine.autopilot_state()
            self.autopilot_btn.setText(f"自动 {state['rounds_used']}/{state['max_rounds']}")
        elif self.engine.autopilot_resumable:
            self.autopilot_btn.setText("继续自动")
        else:
            self.autopilot_btn.setText("自动驾驶")

    def _update_controls(self, tasks: list[Task] | None = None) -> None:
        state = self.engine.state
        if state == "running":
            self.run_btn.setText("暂停队列")
            self.run_btn.setIcon(line_icon("pause", theme.CARD, 16))
        elif state == "paused":
            self.run_btn.setText("继续队列")
            self.run_btn.setIcon(line_icon("play-solid", theme.CARD, 16))
        elif state == "stopping":
            self.run_btn.setText("正在终止…")
            self.run_btn.setIcon(line_icon("pause", theme.CARD, 16))
        else:
            self.run_btn.setText("开始队列")
            self.run_btn.setIcon(line_icon("play-solid", theme.CARD, 16))
        self.stop_btn.setEnabled(state in ("running", "paused"))
        self.next_btn.setEnabled(bool(self.engine.active_task_id))
        current = self.store.get_task(self.engine.active_task_id) if self.engine.active_task_id else None
        skip_enabled = bool(current) and (
            current.status in (
                TaskStatus.interrupted.value,
                TaskStatus.resuming.value,
                TaskStatus.patching.value,
                TaskStatus.awaiting.value,
            )
            or current.resume_count > 0
            or current.followup_count > 0
        )
        self.skip_btn.setEnabled(bool(skip_enabled))
        color = {
            "running": theme.ACCENT,
            "paused": theme.ORANGE,
            "stopping": theme.RED,
            "idle": theme.SUBTLE,
        }.get(state, theme.SUBTLE)
        if state == "idle":
            all_tasks = self.store.list_tasks()
            if all_tasks and all(t.status == TaskStatus.done.value for t in all_tasks):
                color = theme.GREEN
        self.state_dot.setStyleSheet(f"color: {color}; font-size: 12px;")
        for button, tip in (
            (self.stop_btn, "终止当前 Agent 进程并结束队列"),
            (self.skip_btn, "跳过当前任务的自动续传/补做，保留结果并继续"),
            (self.next_btn, "强制结束当前任务，直接执行下一条主任务"),
        ):
            button.setToolTip(tip)

    # ------------------------------------------------------------------
    def _toggle_run(self) -> None:
        if self.engine.state == "running":
            self.engine.pause()
            self._update_controls()
            return
        self.engine.start()
        self._update_controls()

    def _toggle_inspector(self) -> None:
        self.config.inspector_collapsed = not self.config.inspector_collapsed
        self.store.save_config(self.config)
        self._apply_inspector_state()

    def _apply_inspector_state(self) -> None:
        collapsed = bool(self.config.inspector_collapsed)
        self.inspector.setVisible(not collapsed)
        self.inspector_btn.setToolTip("显示概览面板" if collapsed else "隐藏概览面板")

    def _on_board_layout(self, state: dict) -> None:
        self.config.board_layout = state
        self.store.save_config(self.config)
        self._sync_layout_button()

    def _sync_layout_button(self) -> None:
        vertical = bool(self.config.board_layout.get("vertical"))
        self.layout_btn.setToolTip("切换为横向排列" if vertical else "切换为纵向排列")

    def _toggle_layout(self) -> None:
        self.board.set_vertical(not bool(self.config.board_layout.get("vertical")))

    def _open_columns_menu(self) -> None:
        hidden = self.board.hidden_columns()
        if not hidden:
            self.notify.emit("所有列都已显示", "info")
            return
        items = []
        for key in hidden:
            label = next((name for k, name, _s in COLUMN_DEFS if k == key), key)
            items.append(
                (f"显示「{label}」列", line_icon("add"), lambda k=key: self.board.restore_column(k))
            )
        open_popover(self.columns_btn, items)

    def _on_search(self, text: str) -> None:
        self._search = text.strip().lower()
        self.refresh(force=True)

    def set_agent_filter(self, key: str) -> None:
        self.agent_filter = key
        self.refresh(force=True)
        self.filter_changed.emit(key)

    def _select_task(self, task_id: str) -> None:
        if self.selected_id == task_id and self.detail.isVisible():
            return
        self.selected_id = task_id
        self.queue_list.set_selected(task_id)
        self.board.set_selected(task_id)
        self.rail_stack.setCurrentWidget(self.detail)
        self.detail.show_task(task_id)

    def _select_run(self, task_id: str, run_id: str) -> None:
        self.selected_id = task_id
        self.queue_list.set_selected(task_id)
        self.board.set_selected(task_id)
        self.rail_stack.setCurrentWidget(self.detail)
        self.detail.show_task(task_id, tab="records", run_id=run_id)

    def _detail_closed(self) -> None:
        self.selected_id = ""
        self.queue_list.set_selected("")
        self.board.set_selected("")
        self.rail_stack.setCurrentWidget(self.overview)
        self.overview.refresh(self.store.list_tasks(), self.engine.state, self.engine.active_task_id)

    def _on_task_updated(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if not task:
            self.refresh(force=True)
            return
        runs = self.store.list_runs(task_id)
        in_list = self.queue_list.update_task(task, runs, self.config.agent, self.selected_id)
        in_board = self.board.update_task(task, runs, self.config.agent, self.selected_id)
        if not in_list or not in_board:
            self.refresh(force=True)
        self._update_controls()
        if self.selected_id == task_id and self.rail_stack.currentWidget() is self.detail:
            self.detail.refresh()
        self._update_toolbar(self.store.list_tasks())

    def _on_run_updated(self, task_id: str, run_id: str) -> None:
        self._on_task_updated(task_id)

    def _tick_active(self) -> None:
        for task in self.store.list_tasks():
            if task.status in RUNNING or task.id == self.engine.active_task_id or task.status in (
                TaskStatus.validating.value,
                TaskStatus.awaiting.value,
            ):
                runs = self.store.list_runs(task.id)
                self.queue_list.update_task(task, runs, self.config.agent, self.selected_id)
                self.board.update_task(task, runs, self.config.agent, self.selected_id)
        self.overview.refresh(self.store.list_tasks(), self.engine.state, self.engine.active_task_id)
        if self.selected_id and self.rail_stack.currentWidget() is self.detail:
            self.detail.refresh()

    def _on_awaiting(self, task_id: str) -> None:
        self._select_task(task_id)
        self.detail.show_task(task_id, tab="summary")

    def _on_log_activity(self, task_id: str, line: str) -> None:
        text = line.strip()
        if any(marker in text for marker in ("[输出]", "[tool]", "[retry]", "[interrupt]", "[人工]", "[验收]", "[run]", "[init]")):
            self._latest_activity = text
            self.overview.set_activity(text)

    # ------------------------------------------------------------------
    def _on_agent_changed(self, key: str) -> None:
        self.config.agent = key
        self.store.save_config(self.config)
        self.engine.update_config(self.config)
        self.refresh(force=True)
        self.notify.emit(f"默认 Agent 已切换为 {adapter_label(key)}", "info")

    def _on_auto_toggled(self, checked: bool) -> None:
        self.config.auto_followup = checked
        self.store.save_config(self.config)
        self.engine.update_config(self.config)
        self._update_toolbar(self.store.list_tasks())
        self.overview.reload_config()
        self.notify.emit("自动补做已开启" if checked else "自动补做已关闭", "info")

    def _open_autopilot(self) -> None:
        dialog = AutopilotDialog(self, self.config, self.engine)
        dialog.start_requested.connect(self._start_autopilot)
        dialog.stop_requested.connect(self._stop_autopilot)
        dialog.resume_requested.connect(self._resume_autopilot)
        dialog.exec()
        self.refresh(force=True)

    def _start_autopilot(self, goal: str, rounds: int, minutes: int, auto_accept: bool) -> None:
        self.config.autopilot_goal = goal
        self.config.autopilot_rounds = rounds
        self.config.autopilot_minutes = minutes
        self.config.autopilot_auto_accept = auto_accept
        self.store.save_config(self.config)
        self.engine.update_config(self.config)
        self.engine.start_autopilot(goal, rounds, minutes, auto_accept)

    def _stop_autopilot(self) -> None:
        self.engine.stop_autopilot("手动停止")

    def _resume_autopilot(self) -> None:
        self.engine.resume_autopilot()

    def _choose_cwd(self) -> None:
        items = [
            ("选择全局工作目录…", line_icon("folder"), self._pick_cwd),
            ("清除（独立目录）", line_icon("cancel"), self._clear_cwd),
        ]
        if self.config.cwd:
            items.append(("打开当前目录", line_icon("folder"), self._open_cwd))
        open_popover(self.cwd_chip, items)

    def _pick_cwd(self) -> None:
        path = pick_folder(self.window(), self.config.cwd or "", "选择默认工作目录")
        if path:
            self.config.cwd = path
            self.store.save_config(self.config)
            self.engine.update_config(self.config)
            self.refresh(force=True)

    def _clear_cwd(self) -> None:
        self.config.cwd = ""
        self.store.save_config(self.config)
        self.engine.update_config(self.config)
        self.refresh(force=True)

    def _open_cwd(self) -> None:
        if not self.config.cwd:
            return
        os.startfile(self.config.cwd) if os.name == "nt" else None

    def _new_task(self) -> None:
        dialog = TaskEditorDialog(self, self.config, default_cwd=self.config.cwd)
        dialog.optimized_new_task.connect(self._create_optimized_task)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_task:
            self.store.add_task(dialog.result_task)
            self.refresh(force=True)
            self.engine.signals.queue_updated.emit()
            self.notify.emit("任务已加入队列", "success")

    def _create_optimized_task(self, title: str, prompt: str) -> None:
        task = Task(title=title, prompt=prompt, agent="", cwd=self.config.cwd)
        self.store.add_task(task)
        self.refresh(force=True)
        self.engine.signals.queue_updated.emit()
        self.notify.emit("优化结果已另存为新任务", "success")

    def _edit_task(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        if task.status in RUNNING:
            self.notify.emit("任务执行中，暂不能编辑", "warning")
            return
        dialog = TaskEditorDialog(self, self.config, task=task, default_cwd=self.config.cwd)
        dialog.optimized_new_task.connect(self._create_optimized_task)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_task:
            self.store.save_task(dialog.result_task)
            self.refresh(force=True)
            if self.selected_id:
                self.detail.refresh()
            self.notify.emit("任务已更新", "success")

    def _optimize_task(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        if task.status in RUNNING:
            self.notify.emit("任务执行中，暂不能优化提示词", "warning")
            return
        dialog = OptimizeDialog(self, self.config, task.prompt, "user", task.title)
        dialog.replace_requested.connect(lambda text: self._replace_prompt(task_id, text))
        dialog.save_as_new_requested.connect(
            lambda text: self._create_optimized_task((task.title or "任务") + "（优化）", text)
        )
        dialog.exec()

    def _replace_prompt(self, task_id: str, text: str) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        task.prompt = text
        self.store.save_task(task)
        self.refresh(force=True)
        if self.selected_id == task_id:
            self.detail.refresh()
        self.notify.emit("提示词已替换", "success")

    def _retry_task(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        if not ConfirmDialog.ask(
            self,
            "重置并重新执行",
            "将清空当前验收结果，从主提示词重新开始。历史执行记录仍会保留。",
            "重新执行",
        ):
            return
        self.engine.retry_task(task_id, autostart=True)
        self.refresh(force=True)
        self.notify.emit("任务已重置，准备重新执行", "success")

    def _delete_task(self, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        if task.status in RUNNING or task.status == TaskStatus.awaiting.value:
            self.notify.emit("任务正在执行或等待确认，无法删除", "warning")
            return
        if not ConfirmDialog.ask(
            self,
            "删除任务",
            f"确定删除「{task.title}」吗？执行记录仍保留在历史中。",
            "删除",
            danger=True,
        ):
            return
        self.store.delete_task(task_id)
        if self.selected_id == task_id:
            self.selected_id = ""
            self.detail.hide()
        self.refresh(force=True)
        self.engine.signals.queue_updated.emit()
        self.notify.emit("任务已删除", "info")

    def _load_demo(self) -> None:
        add_demo_tasks(self.store)
        self.refresh(force=True)
        self.notify.emit("已载入 3 条示例任务，使用示例 Agent 演示闭环", "success")

    def _reorder_before(self, task_id: str, before_id: str) -> None:
        ids = [task.id for task in self.store.list_tasks()]
        if task_id not in ids:
            return
        if before_id and before_id in ids and before_id != task_id:
            target = ids.index(before_id)
        else:
            target = len(ids)
        self._apply_reorder(task_id, target)

    def _reorder_list(self, task_id: str, local_index: int) -> None:
        before = self._display_ids[local_index] if local_index < len(self._display_ids) else ""
        self._reorder_before(task_id, before)

    def _apply_reorder(self, task_id: str, target_index: int) -> None:
        ids = [task.id for task in self.store.list_tasks()]
        if task_id not in ids:
            return
        source_index = ids.index(task_id)
        ids.remove(task_id)
        if source_index < target_index:
            target_index -= 1
        target_index = max(0, min(target_index, len(ids)))
        ids.insert(target_index, task_id)
        self.store.reorder_tasks(ids)
        self.refresh(force=True)

    # ------------------------------------------------------------------
    def _stop_queue(self) -> None:
        if not ConfirmDialog.ask(
            self,
            "终止队列",
            "将结束当前 Agent 进程并停止队列。已完成的任务不受影响。",
            "终止",
            danger=True,
        ):
            return
        self.engine.stop()
        self._update_controls()
        self.notify.emit("正在终止队列", "warning")

    def _skip_retry(self) -> None:
        self.engine.skip_retry()
        self._update_controls()

    def _force_next(self) -> None:
        self.engine.force_next()
        self._update_controls()

    def reload_config(self) -> None:
        self.config = self.engine.config
        self._update_agent_options()
        self.overview.reload_config()
        self.refresh(force=True)

    def shutdown_ui(self) -> None:
        self._tick_timer.stop()
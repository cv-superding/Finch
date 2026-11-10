from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QMimeData, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDrag
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    FluentIcon,
    CaptionLabel,
    PushButton,
    IconWidget,
    RadioButton,
    StrongBodyLabel,
    TransparentToolButton,
)

from ..agents import adapter_label
from ..models import Run, Task, TaskStatus
from . import theme
from .action_popover import open_popover
from .agent_icons import agent_qicon
from .glyphs import line_icon
from .widgets import ElidedLabel, format_duration

DRAG_MIME = "application/x-finch-task"
ACTIVE = ("running", "tool", "resuming", "patching", "validating")


class DragHandle(TransparentToolButton):
    """Library tool button that starts a drag to reorder the queue."""

    def __init__(self, row: "TaskRow", parent=None):
        super().__init__(parent)
        self.row = row
        self._press: QPoint | None = None
        self._draggable = True
        self.setIcon(theme.fluent_icon("move"))
        self.setIconSize(QSize(14, 14))
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("拖动排序")

    def set_draggable(self, value: bool) -> None:
        self._draggable = value
        self.setCursor(Qt.CursorShape.OpenHandCursor if value else Qt.CursorShape.ArrowCursor)
        self.setToolTip("拖动排序" if value else "")
        self.setEnabled(value)

    def mousePressEvent(self, event) -> None:
        if self._draggable and event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press is None or not self._draggable:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._press).manhattanLength() < 8:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(DRAG_MIME, self.row.task_id.encode("utf-8"))
        drag.setMimeData(mime)
        pixmap = self.row.grab()
        if pixmap.width() > 620:
            pixmap = pixmap.scaledToWidth(620, Qt.TransformationMode.SmoothTransformation)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(24, 24))
        self._press = None
        drag.exec(Qt.DropAction.MoveAction)


class StatusMarker(QWidget):
    """Fluent radio button / progress ring that shows the task state."""

    def __init__(self, status: str = "queued", parent=None):
        super().__init__(parent)
        self._status = status
        self.setFixedWidth(20)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.radio = RadioButton(self)
        self.radio.setEnabled(False)
        layout.addWidget(self.radio)
        self._apply()

    def set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self._apply()

    def _apply(self) -> None:
        self.radio.setChecked(self._status == TaskStatus.done.value)


class ChildRunRow(QFrame):
    clicked = pyqtSignal(str)

    def __init__(self, run: Run, parent=None):
        super().__init__(parent)
        self.run_id = run.id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        _bg, fg = theme.RUN_TONES.get(run.kind, theme.RUN_TONES["main"])
        self.tag = CaptionLabel(run.label)
        self.tag.setStyleSheet(f"color: {fg}; font-weight: 600;")
        layout.addWidget(self.tag, 0, Qt.AlignmentFlag.AlignTop)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.reason = ElidedLabel(run.reason or run.label)
        self.reason.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        text_col.addWidget(self.reason)
        self.result = ElidedLabel(_run_excerpt(run))
        self.result.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        text_col.addWidget(self.result)
        layout.addLayout(text_col, 1)
        status_color = {
            "completed": theme.GREEN_TINT,
            "interrupted": theme.ORANGE_TINT,
            "failed": theme.RED_TINT,
            "stopped": theme.SUBTLE,
            "running": theme.BLUE_TINT,
        }.get(run.status, theme.SUBTLE)
        state = CaptionLabel(
            {
                "completed": "完成",
                "interrupted": "中断",
                "failed": "失败",
                "stopped": "终止",
                "running": "执行中",
            }.get(run.status, run.status)
        )
        state.setStyleSheet(f"color: {status_color}; font-weight: 500;")
        layout.addWidget(state)
        duration = CaptionLabel(format_duration(run.duration))
        duration.setStyleSheet(f"color: {theme.SUBTLE};")
        layout.addWidget(duration)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.run_id)
        super().mouseReleaseEvent(event)


@dataclass
class RowActions:
    can_optimize: bool = True
    can_edit: bool = True
    can_retry: bool = True
    can_delete: bool = True


class TaskRow(QWidget):
    selected = pyqtSignal(str)
    optimize_requested = pyqtSignal(str)
    edit_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    run_requested = pyqtSignal(str, str)

    def __init__(
        self,
        task: Task,
        runs: list[Run],
        default_agent: str,
        index: int = 1,
        first: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.task_id = task.id
        self._task = task
        self._runs = runs
        self._default_agent = default_agent
        self._selected = False
        self._hover = False
        self._child_sig = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 0, 18, 0)
        root.setSpacing(0)

        self.main = QWidget()
        self.main.setCursor(Qt.CursorShape.PointingHandCursor)
        self.main_layout = QHBoxLayout(self.main)
        self.main_layout.setContentsMargins(0, 4, 0, 4)
        self.main_layout.setSpacing(6)
        self.drag_handle = DragHandle(self)
        self.main_layout.addWidget(self.drag_handle)
        self.marker = StatusMarker(task.status)
        self.main_layout.addWidget(self.marker)
        self.body = QFrame()
        self.body.setObjectName("TaskBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(10, 8, 10, 8)
        body_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self.title = ElidedLabel(task.title or "未命名任务")
        self.title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT};")
        title_row.addWidget(self.title, 1)
        self.pill = CaptionLabel("")
        self.pill.setStyleSheet(f"color: {theme.MUTED}; font-weight: 500;")
        title_row.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.more_btn = TransparentToolButton()
        self.more_btn.setIcon(theme.fluent_icon("more"))
        self.more_btn.setIconSize(QSize(15, 15))
        self.more_btn.setFixedSize(24, 24)
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.setToolTip("更多操作")
        self.more_btn.clicked.connect(self._open_menu)
        title_row.addWidget(self.more_btn)
        body_layout.addLayout(title_row)

        self.subtitle = ElidedLabel("")
        self.subtitle.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        body_layout.addWidget(self.subtitle)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        self.badge = IconWidget()
        self.badge.setFixedSize(16, 16)
        meta_row.addWidget(self.badge)
        self.agent_label = CaptionLabel("")
        self.agent_label.setStyleSheet(f"color: {theme.MUTED};")
        meta_row.addWidget(self.agent_label)
        self.meta_label = ElidedLabel("")
        self.meta_label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        meta_row.addWidget(self.meta_label, 1)
        body_layout.addLayout(meta_row)
        self.main_layout.addWidget(self.body, 1)
        root.addWidget(self.main)

        self.children = QWidget()
        self.children_layout = QVBoxLayout(self.children)
        self.children_layout.setContentsMargins(44, 0, 14, 8)
        self.children_layout.setSpacing(2)
        root.addWidget(self.children)
        self.children.setVisible(False)
        self.update_data(task, runs, default_agent)

    def _effective_agent(self) -> str:
        return self._task.agent or self._default_agent

    def update_data(self, task: Task, runs: list[Run], default_agent: str, selected: bool | None = None) -> None:
        self._task = task
        self._runs = runs
        self._default_agent = default_agent
        if selected is not None:
            self._selected = selected
        agent = self._effective_agent()
        self.badge.setIcon(agent_qicon(agent))
        self.marker.set_status(task.status)
        self._update_pill(task.status)
        title = task.title or _first_line(task.prompt) or "未命名任务"
        self.title.setText(title)
        self.setToolTip(task.prompt[:800])
        self.subtitle.setText(self._subtitle_text(task))
        self.agent_label.setText(adapter_label(agent))
        stats = []
        if task.resume_count:
            stats.append(f"续传 {task.resume_count}")
        if task.followup_count:
            stats.append(f"补做 {task.followup_count}")
        if task.tool_count:
            stats.append(f"工具 {task.tool_count}")
        if task.duration:
            stats.append(format_duration(task.duration))
        self.meta_label.setText(("·   " + "   ·   ".join(stats)) if stats else "")
        active = task.status in ACTIVE
        self.drag_handle.set_draggable(not active)
        self._rebuild_children()
        self._apply_style()

    def _update_pill(self, status: str) -> None:
        from ..models import STATUS_LABELS

        fg, _bg = theme.STATUS_COLORS.get(status, (theme.MUTED, theme.SLATE_SOFT))
        self.pill.setText(STATUS_LABELS.get(status, status))
        self.pill.setStyleSheet(f"color: {fg}; font-weight: 500;")

    def _subtitle_text(self, task: Task) -> str:
        status = task.status
        if status in (TaskStatus.running.value, TaskStatus.tool.value, TaskStatus.resuming.value, TaskStatus.patching.value):
            return task.progress or "正在执行"
        if status == TaskStatus.validating.value:
            return task.progress or "正在解析回复并校验完成度"
        if status == TaskStatus.awaiting.value:
            return "补做提示词已生成，等待你确认"
        if status in (TaskStatus.failed.value, TaskStatus.attention.value):
            return task.attention_reason or task.error or task.progress or "需要人工处理"
        if status == TaskStatus.interrupted.value:
            return task.progress or "检测到中断，可继续"
        if status == TaskStatus.done.value:
            return task.summary or "全部验收项已落地"
        return _first_line(task.prompt) or task.progress or "等待执行"

    def _apply_style(self) -> None:
        if self._selected:
            bg = theme.ACCENT_SOFT
        elif self._hover:
            bg = theme.BG_SOFT
        else:
            bg = "transparent"
        self.body.setStyleSheet(
            f"QFrame#TaskBody {{ background: {bg}; border: 1px solid transparent; border-radius: 8px; }}"
        )

    def _rebuild_children(self) -> None:
        children = [run for run in self._runs if run.kind != "main"]
        signature = tuple(
            (run.id, run.status, len(run.output or ""), run.tool_count) for run in children
        )
        if signature == self._child_sig:
            return
        self._child_sig = signature
        while self.children_layout.count():
            item = self.children_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not children:
            self.children.setVisible(False)
            self.updateGeometry()
            return
        self.children.setVisible(True)
        shown = children[-4:]
        if len(children) > len(shown):
            more = CaptionLabel(f"还有 {len(children) - len(shown)} 条续传/补做记录，点击任务查看全部")
            more.setStyleSheet(f"color: {theme.SUBTLE};")
            self.children_layout.addWidget(more)
        for run in shown:
            row = ChildRunRow(run)
            row.clicked.connect(lambda run_id, task_id=self.task_id: self.run_requested.emit(task_id, run_id))
            self.children_layout.addWidget(row)

    def _open_menu(self) -> None:
        active = self._task.status in ACTIVE
        items = [
            ("编辑任务", line_icon("edit"), lambda: self.edit_requested.emit(self.task_id)),
            ("优化提示词", line_icon("optimize"), lambda: self.optimize_requested.emit(self.task_id)),
            ("重置并重新执行", line_icon("sync"), lambda: self.retry_requested.emit(self.task_id)),
            ("复制提示词", line_icon("copy"), self._copy_prompt),
            ("删除任务", line_icon("delete"), lambda: self.delete_requested.emit(self.task_id)),
        ]
        open_popover(self.more_btn, items)

    def _copy_prompt(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._task.prompt)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def enterEvent(self, event) -> None:
        self._hover = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._apply_style()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.task_id)
        super().mouseReleaseEvent(event)


class AddTaskRow(QWidget):
    """Library command button used as the "add next task" row."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(44, 2, 18, 8)
        layout.setSpacing(0)
        self.button = PushButton("添加下一条任务", self)
        self.button.setIcon(theme.fluent_icon("add"))
        self.button.setToolTip("新增一条主提示词")
        self.button.clicked.connect(self.clicked.emit)
        layout.addWidget(self.button, 1)


def _first_line(text: str, limit: int = 90) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:limit]
    return ""


def _run_excerpt(run: Run) -> str:
    lines = [line.strip() for line in (run.output or "").splitlines() if line.strip()]
    for line in lines:
        stripped = line.lstrip("#-*•· ").strip()
        if not stripped or stripped.endswith(("：", ":")):
            continue
        if stripped in ("已完成", "未完成", "已知问题", "无"):
            continue
        return stripped[:90]
    if lines:
        return lines[0][:90]
    return {
        "completed": "执行完成",
        "interrupted": "执行中断",
        "failed": "执行失败",
        "stopped": "已终止",
        "running": "执行中",
    }.get(run.status, run.status)

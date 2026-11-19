from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import (
    QEvent,
    QMimeData,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QDrag, QFont, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..agents import adapter_label
from ..models import Run, Task, TaskStatus
from . import theme
from .action_popover import open_popover
from .glyphs import check_icon, line_icon, transport_icon
from .widgets import ElidedLabel, StatusDot, format_duration

DRAG_MIME = "application/x-finch-task"
ACTIVE = ("running", "tool", "resuming", "patching", "validating")


def _blend(a: QColor, b: QColor, ratio: float) -> QColor:
    """QColor.lerp is not exposed by this PyQt6 build."""
    ratio = max(0.0, min(1.0, float(ratio)))
    return QColor(
        round(a.red() + (b.red() - a.red()) * ratio),
        round(a.green() + (b.green() - a.green()) * ratio),
        round(a.blue() + (b.blue() - a.blue()) * ratio),
    )


class DragHandle(QWidget):
    """Six dot grip that starts a drag to reorder the queue."""

    def __init__(self, row: "TaskRow", parent=None):
        super().__init__(parent)
        self.row = row
        self._press: QPoint | None = None
        self._draggable = True
        self.setFixedSize(14, 22)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("拖动排序")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

    def set_draggable(self, value: bool) -> None:
        self._draggable = value
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if value else Qt.CursorShape.ArrowCursor
        )
        self.setToolTip("拖动排序" if value else "")
        self.setVisible(value)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SUBTLE))
        for row in range(3):
            for col in range(2):
                painter.drawEllipse(
                    QPointF(4 + col * 6, 5 + row * 6), 1.3, 1.3
                )

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
        self._press = None
        self.row.start_drag()


class TaskCard(QFrame):
    """Flat card surface: no shadow, 1px border, 150ms hover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._hover = 0.0
        self._selected = False
        self._live = False
        self._done = False

    def set_hover_value(self, value: float) -> None:
        self._hover = max(0.0, min(1.0, float(value)))
        self.update()

    def set_flags(self, *, selected: bool = False, live: bool = False, done: bool = False) -> None:
        self._selected = selected
        self._live = live
        self._done = done
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        base = QColor(theme.CARD)
        if self._done:
            base = QColor(theme.BG_SOFT)
        bg = _blend(base, QColor(theme.SURFACE_2), self._hover)
        if self._selected:
            bg = QColor(theme.SURFACE_2)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 8, 8)

        border = QColor(theme.BORDER_STRONG)
        if self._selected:
            border = QColor(theme.ACCENT)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(rect, 8, 8)

        if self._live:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(
                QRectF(0, 9, 2.5, max(6, self.height() - 18)), 1.25, 1.25
            )


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
        self.tag = QLabel(run.label)
        self.tag.setStyleSheet(f"color: {fg}; font-size: 11px; font-weight: 600;")
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
        state = QLabel(
            {
                "completed": "完成",
                "interrupted": "中断",
                "failed": "失败",
                "stopped": "终止",
                "running": "执行中",
            }.get(run.status, run.status)
        )
        state.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 500;")
        layout.addWidget(state)
        duration = QLabel(format_duration(run.duration))
        duration.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 11px;")
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
    pause_requested = pyqtSignal()
    complete_toggled = pyqtSignal(str)

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
        self._press_pos: QPoint | None = None
        self._hover_anim = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 8)
        root.setSpacing(0)

        self.body = TaskCard()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        inner = QWidget()
        self.inner = inner
        self.main_layout = QHBoxLayout(inner)
        self.main_layout.setContentsMargins(11, 9, 11, 9)
        self.main_layout.setSpacing(10)

        self.drag_handle = DragHandle(self)
        self.main_layout.addWidget(self.drag_handle)

        self.check = QPushButton()
        self.check.setFixedSize(16, 16)
        self.check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check.setToolTip("标记完成 / 取消完成")
        self.check.clicked.connect(lambda: self.complete_toggled.emit(self.task_id))
        self.main_layout.addWidget(self.check)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        self.title = ElidedLabel(task.title or "未命名任务")
        self.title.setObjectName("TaskTitle")
        text_col.addWidget(self.title)

        meta = QHBoxLayout()
        meta.setSpacing(6)
        self.agent_label = QLabel("")
        self.agent_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        meta.addWidget(self.agent_label)
        meta.addWidget(self._separator())
        self.status_dot = StatusDot("queued", 6)
        meta.addWidget(self.status_dot)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        meta.addWidget(self.status_label)
        self.meta_sep = self._separator()
        self.meta_sep.setVisible(False)
        meta.addWidget(self.meta_sep)
        self.meta_label = ElidedLabel("")
        self.meta_label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        meta.addWidget(self.meta_label, 1)
        text_col.addLayout(meta)
        self.main_layout.addLayout(text_col, 1)

        self.duration = QLabel("—")
        self.duration.setStyleSheet(
            f"color: {theme.SUBTLE}; font-family: {theme.mono_family()}; font-size: 11.5px;"
        )
        self.duration.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.main_layout.addWidget(self.duration)

        self.play = QPushButton()
        self.play.setFixedSize(26, 26)
        self.play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play.setToolTip("开始这条任务")
        self.play.clicked.connect(self._on_play)
        self.main_layout.addWidget(self.play)

        self.more_btn = QPushButton()
        self.more_btn.setFixedSize(22, 22)
        self.more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_btn.setIcon(line_icon("more", theme.SUBTLE, 15))
        self.more_btn.setIconSize(QSize(15, 15))
        self.more_btn.setToolTip("更多操作")
        self.more_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 5px; }"
            f"QPushButton:hover {{ background: {theme.SURFACE_2}; }}"
        )
        self.more_btn.clicked.connect(self._open_menu)
        self.main_layout.addWidget(self.more_btn)

        # 悬停才显示操作，但保留占位避免标题在悬停时抖动
        self._play_fx = QGraphicsOpacityEffect(self.play)
        self._play_fx.setOpacity(0.0)
        self.play.setGraphicsEffect(self._play_fx)
        self._more_fx = QGraphicsOpacityEffect(self.more_btn)
        self._more_fx.setOpacity(0.0)
        self.more_btn.setGraphicsEffect(self._more_fx)

        body_layout.addWidget(inner)
        root.addWidget(self.body)

        self.children = QWidget()
        self.children_layout = QVBoxLayout(self.children)
        self.children_layout.setContentsMargins(46, 4, 14, 6)
        self.children_layout.setSpacing(2)
        root.addWidget(self.children)
        self.children.setVisible(False)

        self.update_data(task, runs, default_agent)

        for surface in (
            self.body,
            inner,
            self.title,
            self.agent_label,
            self.status_label,
            self.meta_label,
            self.duration,
        ):
            surface.installEventFilter(self)

    @staticmethod
    def _separator() -> QLabel:
        label = QLabel("·")
        label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        return label

    def start_drag(self) -> None:
        if self._task.status in ACTIVE:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(DRAG_MIME, self.task_id.encode("utf-8"))
        drag.setMimeData(mime)
        pixmap = self.grab()
        if pixmap.width() > 620:
            pixmap = pixmap.scaledToWidth(
                620, Qt.TransformationMode.SmoothTransformation
            )
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(24, 24))
        drag.exec(Qt.DropAction.MoveAction)

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if (
            etype == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            if self._task.status not in ACTIVE:
                self._press_pos = event.position().toPoint()
        elif etype == QEvent.Type.MouseMove and self._press_pos is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                if (
                    event.position().toPoint() - self._press_pos
                ).manhattanLength() >= 8:
                    self._press_pos = None
                    self.start_drag()
                    return True
        elif etype == QEvent.Type.MouseButtonRelease:
            self._press_pos = None
        return super().eventFilter(obj, event)

    def _effective_agent(self) -> str:
        return self._task.agent or self._default_agent

    def _on_play(self) -> None:
        if self._task.status in ACTIVE:
            self.pause_requested.emit()
        else:
            self.run_requested.emit(self.task_id, "")

    def update_data(
        self,
        task: Task,
        runs: list[Run],
        default_agent: str,
        selected: bool | None = None,
    ) -> None:
        self._task = task
        self._runs = runs
        self._default_agent = default_agent
        if selected is not None:
            self._selected = selected

        agent = self._effective_agent()
        title = task.title or _first_line(task.prompt) or "未命名任务"
        self.title.setText(title)
        self.setToolTip(task.prompt[:800])
        self.agent_label.setText(adapter_label(agent))
        self.status_dot.set_status(task.status)
        self.status_label.setText(task.status_label)
        self.duration.setText(format_duration(task.duration) if task.duration else "")

        stats = []
        if task.tool_count:
            stats.append(f"工具 {task.tool_count}")
        if task.resume_count:
            stats.append(f"续传 {task.resume_count}")
        if task.followup_count:
            stats.append(f"补做 {task.followup_count}")
        subtitle = _subtitle_text(task)
        label = task.status_label
        if subtitle.startswith(label + " · "):
            subtitle = subtitle[len(label) + 3:]
        elif subtitle == label:
            subtitle = ""
        if subtitle:
            stats.append(subtitle)
        self.meta_label.setText("  ·  ".join(stats))
        self.meta_sep.setVisible(bool(stats))

        active = task.status in ACTIVE
        done = task.status == TaskStatus.done.value
        self.drag_handle.set_draggable(not active)
        self._apply_style()
        self._rebuild_children()
        self.play.setVisible(not done)
        self._show_actions(self._hover or self._selected)

    def _show_actions(self, visible: bool) -> None:
        opacity = 1.0 if visible else 0.0
        self._play_fx.setOpacity(opacity)
        self._more_fx.setOpacity(opacity)
        self.play.setEnabled(visible)
        self.more_btn.setEnabled(visible)

    def _apply_style(self) -> None:
        active = self._task.status in ACTIVE
        done = self._task.status == TaskStatus.done.value
        self.body.set_flags(selected=self._selected, live=active, done=done)

        fg, _bg = theme.STATUS_COLORS.get(
            self._task.status, (theme.MUTED, theme.SLATE_SOFT)
        )
        self.check.setStyleSheet(
            "QPushButton { border: 1px solid #3A3A42; border-radius: 8px; background: transparent; }"
            "QPushButton:hover { border-color: #6E6BF0; }"
            + (
                "QPushButton { background: #3FB950; border-color: #3FB950; }"
                if done
                else ""
            )
        )
        self.check.setIcon(check_icon("#FFFFFF", 11, 1.7) if done else QIcon())

        # 卡片内是图标按钮，不是实心色块：运行中用品牌色暂停，其余用中性播放
        icon_color = theme.ACCENT if active else theme.MUTED
        self.play.setIcon(
            transport_icon("pause" if active else "play", icon_color, 14)
        )
        self.play.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 6px; }"
            f"QPushButton:hover {{ background: {theme.SURFACE_2}; }}"
        )

        font = QFont(theme.font_family())
        font.setPixelSize(15)
        font.setWeight(QFont.Weight.Medium)
        font.setStrikeOut(done)
        self.title.setFont(font)
        self.title.setStyleSheet(
            f"color: {theme.SUBTLE if done else theme.TEXT};"
        )

    def _rebuild_children(self) -> None:
        children = [run for run in self._runs if run.kind != "main"]
        signature = tuple(
            (run.id, run.status, len(run.output or ""), run.tool_count)
            for run in children
        )
        if signature == self._child_sig:
            if not self._selected:
                self.children.setVisible(False)
            return
        self._child_sig = signature
        while self.children_layout.count():
            item = self.children_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not children or not self._selected:
            self.children.setVisible(False)
            self.updateGeometry()
            return
        self.children.setVisible(True)
        for run in children[-4:]:
            row = ChildRunRow(run)
            row.clicked.connect(
                lambda run_id, task_id=self.task_id: self.run_requested.emit(
                    task_id, run_id
                )
            )
            self.children_layout.addWidget(row)

    def _open_menu(self) -> None:
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
        self._rebuild_children()
        self.play.setVisible(self._task.status != TaskStatus.done.value)
        self._show_actions(self._hover or self._selected)

    def enterEvent(self, event) -> None:
        self._hover = True
        self._animate_hover(1.0)
        self.play.setVisible(self._task.status != TaskStatus.done.value)
        self._show_actions(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self._animate_hover(0.0)
        self._show_actions(self._selected)
        super().leaveEvent(event)

    def _animate_hover(self, target: float) -> None:
        from PyQt6.QtCore import QVariantAnimation

        if self._hover_anim is not None:
            self._hover_anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(150)
        anim.setStartValue(self.body._hover)
        anim.setEndValue(target)
        anim.valueChanged.connect(self.body.set_hover_value)
        self._hover_anim = anim
        anim.start()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.task_id)
        super().mouseReleaseEvent(event)


class AddTaskRow(QWidget):
    """Inline dashed input that creates a task on enter."""

    clicked = pyqtSignal()
    quick_add_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 8)
        layout.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("添加任务，回车创建")
        self.edit.setFixedHeight(34)
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: 1px dashed {theme.BORDER_INPUT};"
            " border-radius: 8px; color: #8E8E96; font-size: 12.5px; padding-left: 12px; }"
            f"QLineEdit:focus {{ border: 1px solid {theme.ACCENT}; color: {theme.TEXT}; }}"
        )
        self.edit.returnPressed.connect(self._submit)
        layout.addWidget(self.edit, 1)
        self.detail_btn = QPushButton("详细")
        self.detail_btn.setObjectName("GhostButton")
        self.detail_btn.setFixedHeight(34)
        self.detail_btn.setFixedWidth(60)
        self.detail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detail_btn.setToolTip("打开完整任务编辑器")
        self.detail_btn.clicked.connect(self.clicked.emit)
        layout.addWidget(self.detail_btn)

    def _submit(self) -> None:
        text = self.edit.text().strip()
        if not text:
            return
        self.edit.clear()
        self.quick_add_requested.emit(text)


def _first_line(text: str, limit: int = 90) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:limit]
    return ""


def _subtitle_text(task: Task) -> str:
    status = task.status
    label = task.status_label
    if status in (
        TaskStatus.running.value,
        TaskStatus.tool.value,
        TaskStatus.resuming.value,
        TaskStatus.patching.value,
    ):
        text = (task.progress or "").strip()
        return "" if text in (label, "执行中", "工具执行中", "进行中") else text
    if status == TaskStatus.validating.value:
        text = (task.progress or "").strip()
        return "" if text == label else (text or "正在校验完成度")
    if status == TaskStatus.awaiting.value:
        return "等待你确认补做"
    if status in (TaskStatus.failed.value, TaskStatus.attention.value):
        return task.attention_reason or task.error or "需要人工处理"
    if status == TaskStatus.interrupted.value:
        return task.progress or "检测到中断，可继续"
    if status == TaskStatus.done.value:
        return task.summary or "全部验收项已落地"
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

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ProgressRing as ProgressRingBase,
    SmoothScrollArea,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    StrongBodyLabel,
    SubtitleLabel,
)

from ..models import STATUS_LABELS, Task, TaskStatus
from . import theme
from .widgets import ElidedLabel, ToggleSwitch, divider

RUNNING = {
    TaskStatus.running.value,
    TaskStatus.tool.value,
    TaskStatus.resuming.value,
    TaskStatus.patching.value,
    TaskStatus.validating.value,
}


class ProgressRing(ProgressRingBase):
    """Library progress ring with the Finch accent colour."""

    def __init__(self, size: int = 64, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCustomBarColor(QColor(theme.ACCENT), QColor(theme.ACCENT))
        self.setCustomBackgroundColor(QColor(theme.BORDER_SOFT), QColor(theme.BORDER_SOFT))

    def set_value(self, value: float, color: str) -> None:
        self.setCustomBarColor(QColor(color), QColor(color))
        self.setValue(int(round(max(0.0, min(1.0, value)) * 100)))


class ClickableFrame(CardWidget):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class OverviewPanel(QFrame):
    auto_toggled = pyqtSignal(bool)
    open_task_requested = pyqtSignal(str)
    open_settings_requested = pyqtSignal()

    def __init__(self, config, engine, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self.engine = engine
        self._tasks: list[Task] = []
        self._active_task: Task | None = None
        self._activity = ""
        self.setObjectName("OverviewPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = SubtitleLabel("运行概览", self)
        header.addWidget(title)
        header.addStretch(1)
        self.state_chip = QLabel("空闲")
        self.state_chip.setStyleSheet(
            f"background: {theme.SLATE_SOFT}; color: {theme.MUTED}; border-radius: 4px;"
            "padding: 3px 8px; font-size: 12px; font-weight: 500;"
        )
        header.addWidget(self.state_chip)
        root.addLayout(header)

        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.enableTransparentBackground()
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        content = QVBoxLayout(host)
        content.setContentsMargins(0, 0, 4, 0)
        content.setSpacing(12)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        hero = QHBoxLayout()
        hero.setSpacing(12)
        self.ring = ProgressRing(64)
        hero.addWidget(self.ring)
        hero_text = QVBoxLayout()
        hero_text.setSpacing(2)
        self.big_number = StrongBodyLabel("0 / 0", self)
        self.big_number.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {theme.TEXT};")
        hero_text.addWidget(self.big_number)
        done_label = CaptionLabel("任务完成", self)
        hero_text.addWidget(done_label)
        self.progress_caption = BodyLabel("")
        self.progress_caption.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        hero_text.addWidget(self.progress_caption)
        hero_text.addStretch(1)
        hero.addLayout(hero_text, 1)
        content.addLayout(hero)

        current_label = CaptionLabel("当前任务", self)
        current_label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 11px; font-weight: 600;")
        content.addWidget(current_label)
        self.current_card = ClickableFrame(self)
        self.current_card.setBorderRadius(8)
        self.current_layout = QVBoxLayout(self.current_card)
        self.current_layout.setContentsMargins(14, 12, 14, 12)
        self.current_layout.setSpacing(6)
        self.current_top = QHBoxLayout()
        self.current_top.setSpacing(6)
        self.current_pill = CaptionLabel("空闲")
        self.current_pill.setStyleSheet(f"color: {theme.MUTED}; font-weight: 500;")
        self.current_top.addWidget(self.current_pill)
        self.current_top.addStretch(1)
        self.current_elapsed = CaptionLabel("", self)
        self.current_elapsed.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 11px;")
        self.current_top.addWidget(self.current_elapsed)
        self.current_layout.addLayout(self.current_top)
        self.current_title = StrongBodyLabel("", self)
        self.current_title.setWordWrap(True)
        self.current_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT};")
        self.current_layout.addWidget(self.current_title)
        self.current_detail = BodyLabel("", self)
        self.current_detail.setWordWrap(True)
        self.current_detail.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        self.current_layout.addWidget(self.current_detail)
        self.current_action = CaptionLabel("", self)
        self.current_action.setStyleSheet(f"color: {theme.ACCENT_DARK}; font-size: 12px; font-weight: 600;")
        self.current_layout.addWidget(self.current_action)
        self.current_card.setCursor(Qt.CursorShape.ArrowCursor)
        self.current_card.clicked.connect(self._current_clicked)
        content.addWidget(self.current_card)

        metrics = QHBoxLayout()
        metrics.setSpacing(0)
        self.metric_values: dict[str, QLabel] = {}
        for index, (key, label_text) in enumerate(
            (
                ("resume", "续传"),
                ("followup", "补做"),
                ("tools", "工具"),
                ("attention", "待人工"),
            )
        ):
            if index:
                line = QFrame()
                line.setFixedWidth(1)
                line.setStyleSheet(f"background: {theme.BORDER_SOFT};")
                metrics.addWidget(line)
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(8, 0, 4, 0)
            cell_layout.setSpacing(1)
            value = StrongBodyLabel("0", cell)
            value.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {theme.TEXT};")
            cell_layout.addWidget(value)
            caption = CaptionLabel(label_text, cell)
            caption.setStyleSheet(f"color: {theme.MUTED}; font-size: 11px;")
            cell_layout.addWidget(caption)
            metrics.addWidget(cell, 1)
            self.metric_values[key] = value
        content.addLayout(metrics)

        strategy_label = CaptionLabel("运行策略", self)
        strategy_label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 11px; font-weight: 600;")
        content.addWidget(strategy_label)
        strategy = QWidget()
        strategy_layout = QVBoxLayout(strategy)
        strategy_layout.setContentsMargins(0, 0, 0, 0)
        strategy_layout.setSpacing(8)
        self.strategy_rows: dict[str, QLabel] = {}
        for index, (key, label_text) in enumerate(
            (
                ("text", "文本空闲超时"),
                ("tool", "工具执行超时"),
                ("limits", "续传 / 补做上限"),
            )
        ):
            if index:
                strategy_layout.addWidget(divider())
            row = QHBoxLayout()
            row.setSpacing(8)
            name = BodyLabel(label_text, strategy)
            name.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
            row.addWidget(name)
            row.addStretch(1)
            value = BodyLabel("", strategy)
            value.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px; font-weight: 500;")
            row.addWidget(value)
            strategy_layout.addLayout(row)
            self.strategy_rows[key] = value
        strategy_layout.addWidget(divider())
        auto_row = QHBoxLayout()
        auto_row.setSpacing(8)
        auto_switch = ToggleSwitch(self.config.auto_followup)
        auto_switch.toggled.connect(self.auto_toggled.emit)
        self.auto_switch = auto_switch
        auto_row.addWidget(auto_switch)
        auto_text = BodyLabel("自动补做", strategy)
        auto_text.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        auto_row.addWidget(auto_text)
        auto_row.addStretch(1)
        self.auto_mode = CaptionLabel("", strategy)
        self.auto_mode.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 11px;")
        auto_row.addWidget(self.auto_mode)
        strategy_layout.addLayout(auto_row)
        content.addWidget(strategy)
        content.addStretch(1)

        root.addWidget(divider())
        activity_row = QHBoxLayout()
        activity_row.setSpacing(7)
        self.activity_dot = QWidget()
        self.activity_dot.setFixedSize(6, 6)
        self.activity_dot.setStyleSheet(f"background: {theme.SUBTLE}; border-radius: 3px;")
        activity_row.addWidget(self.activity_dot)
        activity_label = CaptionLabel("最新动态", self)
        activity_label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 11px; font-weight: 600;")
        activity_row.addWidget(activity_label)
        self.activity = ElidedLabel("等待任务开始…")
        self.activity.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        activity_row.addWidget(self.activity, 1)
        root.addLayout(activity_row)

        self.refresh([], "idle", "")

    def _current_clicked(self) -> None:
        if self._active_task:
            self.open_task_requested.emit(self._active_task.id)

    def set_activity(self, text: str) -> None:
        self._activity = text or ""
        if self._activity:
            self.activity.setText(self._activity)

    def reload_config(self) -> None:
        self.config = self.engine.config
        self.auto_switch.blockSignals(True)
        self.auto_switch.setChecked(self.config.auto_followup)
        self.auto_switch.blockSignals(False)
        self.refresh(self._tasks, self.engine.state, self.engine.active_task_id)

    def refresh(self, tasks: list[Task], state: str, active_task_id: str) -> None:
        self._tasks = tasks
        active_now = next((task for task in tasks if task.id == active_task_id), None)
        if active_now and active_now.status == TaskStatus.awaiting.value:
            state = "awaiting"
        total = len(tasks)
        done = sum(1 for task in tasks if task.status == TaskStatus.done.value)
        running = sum(1 for task in tasks if task.status in RUNNING)
        queued = sum(1 for task in tasks if task.status == TaskStatus.queued.value)
        awaiting = sum(1 for task in tasks if task.status == TaskStatus.awaiting.value)
        attention = sum(
            1
            for task in tasks
            if task.status in (TaskStatus.attention.value, TaskStatus.failed.value, TaskStatus.awaiting.value)
        )
        ratio = done / total if total else 0.0
        self.big_number.setText(f"{done} / {total}")
        ring_color = theme.GREEN if total and done == total else theme.ACCENT
        self.ring.set_value(ratio, ring_color)
        if total and done == total:
            self.progress_caption.setText("全部任务已完成")
        else:
            caption = [f"进行中 {running}"]
            if queued:
                caption.append(f"待执行 {queued}")
            if awaiting:
                caption.append(f"待确认 {awaiting}")
            elif attention:
                caption.append(f"待人工 {attention}")
            self.progress_caption.setText(" · ".join(caption))

        labels = {
            "idle": "空闲",
            "running": "执行中",
            "paused": "已暂停",
            "stopping": "终止中",
            "awaiting": "待确认",
        }
        colors = {
            "idle": (theme.MUTED, theme.SLATE_SOFT),
            "running": (theme.ACCENT_DARK, theme.ACCENT_SOFT),
            "paused": (theme.ORANGE_TINT, theme.ORANGE_SOFT),
            "stopping": (theme.RED_TINT, theme.RED_SOFT),
            "awaiting": (theme.VIOLET_TINT, theme.VIOLET_SOFT),
        }
        fg, bg = colors.get(state, colors["idle"])
        if state == "idle" and total and done == total:
            fg, bg = theme.GREEN_TINT, theme.GREEN_SOFT
            labels = dict(labels)
            labels["idle"] = "已完成"
        self.state_chip.setText(labels.get(state, state))
        self.state_chip.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 4px;"
            "padding: 2px 6px; font-size: 12px; font-weight: 500;"
        )
        activity_color = {
            "running": theme.ACCENT,
            "paused": theme.ORANGE,
            "stopping": theme.RED,
            "awaiting": theme.VIOLET,
        }.get(state, theme.SUBTLE)
        self.activity_dot.setStyleSheet(f"background: {activity_color}; border-radius: 3px;")

        active = next((task for task in tasks if task.id == active_task_id), None)
        self._active_task = active
        if active:
            fg, _bg = theme.STATUS_COLORS.get(active.status, (theme.MUTED, theme.SLATE_SOFT))
            self.current_pill.setText(STATUS_LABELS.get(active.status, active.status))
            self.current_pill.setStyleSheet(f"color: {fg}; font-weight: 500;")
        elif total and done == total:
            self.current_pill.setText("已完成")
            self.current_pill.setStyleSheet(f"color: {theme.GREEN_TINT}; font-weight: 500;")
        else:
            self.current_pill.setText("空闲")
            self.current_pill.setStyleSheet(f"color: {theme.MUTED}; font-weight: 500;")
        if active:
            self.current_card.setCursor(Qt.CursorShape.PointingHandCursor)
            self.current_title.setText(active.title or "未命名任务")
            self.current_detail.setText(active.progress or self._status_hint(active))
            self.current_elapsed.setText(self._duration_text(active))
            self.current_elapsed.setVisible(True)
            self.current_action.setText("打开详情  →")
            self.current_action.setVisible(True)
        else:
            self.current_card.setCursor(Qt.CursorShape.ArrowCursor)
            self.current_title.setText("队列已完成" if total and done == total else "队列空闲")
            hint = "全部任务已完成，可查看执行记录或新建任务" if total and done == total else (
                "点击「开始队列」按顺序执行任务" if queued else "新建任务，或载入示例队列体验闭环"
            )
            if state == "paused":
                self.current_title.setText("队列已暂停")
                hint = "当前任务结束后暂停；点击「继续队列」恢复"
            elif state == "stopping":
                self.current_title.setText("正在终止")
                hint = "正在结束当前 Agent 进程"
            self.current_detail.setText(hint)
            self.current_elapsed.setText("")
            self.current_elapsed.setVisible(False)
            self.current_action.setText("")
            self.current_action.setVisible(False)

        resume = sum(task.resume_count for task in tasks)
        followup = sum(task.followup_count for task in tasks)
        tools = sum(task.tool_count for task in tasks)
        self.metric_values["resume"].setText(str(resume))
        self.metric_values["followup"].setText(str(followup))
        self.metric_values["tools"].setText(str(tools))
        self.metric_values["attention"].setText(str(attention))
        self.metric_values["attention"].setStyleSheet(
            f"font-size: 17px; font-weight: 600; color: {theme.RED_TINT if attention else theme.SUBTLE};"
        )

        self.strategy_rows["text"].setText(f"{self.config.text_idle_timeout}s")
        self.strategy_rows["tool"].setText(self._minutes(self.config.tool_timeout))
        self.strategy_rows["limits"].setText(f"{self.config.max_resumes} / {self.config.max_followups}")
        self.auto_switch.blockSignals(True)
        self.auto_switch.setChecked(self.config.auto_followup)
        self.auto_switch.blockSignals(False)
        if not self.config.auto_followup:
            mode = "关闭"
        elif self.config.confirm_followup:
            mode = "人工确认"
        else:
            mode = "全自动"
        self.auto_mode.setText(mode)
        if self._activity:
            self.activity.setText(self._activity)

    @staticmethod
    def _duration_text(task: Task) -> str:
        seconds = max(0, int(task.duration))
        if seconds < 60:
            return f"{seconds}s"
        minutes, sec = divmod(seconds, 60)
        return f"{minutes}m {sec:02d}s"

    @staticmethod
    def _minutes(seconds: int) -> str:
        if seconds >= 60 and seconds % 60 == 0:
            return f"{seconds // 60}m"
        return f"{seconds}s"

    @staticmethod
    def _status_hint(task: Task) -> str:
        if task.status == TaskStatus.awaiting.value:
            return "补做提示词已生成，等待确认"
        if task.status == TaskStatus.done.value:
            return task.summary or "全部验收项已落地"
        return task.summary or "正在执行"

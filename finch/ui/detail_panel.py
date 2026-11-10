from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..agents import adapter_badge, adapter_color, adapter_label
from ..models import Run, STATUS_LABELS, Task, TaskStatus
from ..store import Store
from qfluentwidgets import (
    IconWidget,
    SmoothScrollArea,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    TransparentToolButton,
)

from . import theme
from .agent_icons import agent_qicon
from .glyphs import line_icon
from .widgets import (
    BaseDialog,
    ConfirmDialog,
    ElidedLabel,
    Select,
    StatusDot,
    StatusPill,
    ToggleSwitch,
    divider,
    format_duration,
    format_time,
)

RUN_STATUS_LABEL = {
    "completed": "完成",
    "interrupted": "中断",
    "failed": "失败",
    "stopped": "终止",
    "running": "执行中",
}


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()
        else:
            child = item.layout()
            if child:
                clear_layout(child)


def copy_text(text: str, parent: QWidget | None = None, toast=None) -> None:
    QApplication.clipboard().setText(text or "")
    if toast:
        toast("已复制到剪贴板", "success")


def _tool_arg_text(raw: str) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        return raw.replace("\n", " ")[:140]
    if isinstance(data, dict):
        for key in ("command", "cmd", "path", "file_path", "query", "pattern", "url", "description", "title"):
            if key in data and data[key]:
                value = data[key]
                if isinstance(value, (list, tuple)):
                    value = " ".join(str(item) for item in value)
                return str(value).replace("\n", " ")[:140]
        return json.dumps(data, ensure_ascii=False)[:140]
    return str(data)[:140]


def task_export_payload(store: Store, task: Task) -> dict:
    runs = store.list_runs(task.id)
    logs = {}
    for run in runs:
        if run.log_path and Path(run.log_path).exists():
            try:
                logs[run.id] = Path(run.log_path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                logs[run.id] = ""
    return {
        "app": "Finch",
        "exported_at": __import__("datetime").datetime.now().isoformat(),
        "task": task.to_row(),
        "runs": [run.to_row() for run in runs],
        "logs": logs,
    }


def export_task(parent: QWidget | None, store: Store, task: Task) -> None:
    safe = "".join(ch for ch in (task.title or task.id) if ch not in '\\/:*?"<>|')[:60]
    path, _ = QFileDialog.getSaveFileName(parent, "导出任务记录", f"{safe or 'task'}.json", "JSON 文件 (*.json)")
    if not path:
        return
    Path(path).write_text(
        json.dumps(task_export_payload(store, task), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class OutputDialog(BaseDialog):
    def __init__(self, parent, title: str, content: str):
        super().__init__(parent, title, width=700, height=560)
        editor = PlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(content or "（无输出）")
        editor.setObjectName("LogView")
        self.body.addWidget(editor)
        self.add_footer_stretch()
        copy = PushButton("复制全文")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(editor.toPlainText()))
        close = PrimaryPushButton("关闭")
        close.clicked.connect(self.accept)
        self.footer.addWidget(copy)
        self.footer.addWidget(close)


class TaskDetailPanel(QFrame):
    closed = pyqtSignal()
    optimize_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    followup_decision = pyqtSignal(str, str, str)
    notify = pyqtSignal(str, str)

    def __init__(self, parent: QWidget, store: Store, engine):
        super().__init__(parent)
        self.store = store
        self.engine = engine
        self.task_id = ""
        self._run_selector_value = ""
        self._log_filter = "all"
        self._log_run_id = ""
        self._log_manual = False
        self._summary_sig = None
        self._records_sig = None
        self._logs_sig = None
        self.setObjectName("DetailPanel")
        self.setStyleSheet("QFrame#DetailPanel { background: transparent; border: none; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 14, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title_col = QVBoxLayout()
        title_col.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.status_pill = StatusPill()
        top.addWidget(self.status_pill)
        self.agent_logo = IconWidget()
        self.agent_logo.setIcon(agent_qicon("mock"))
        self.agent_logo.setFixedSize(20, 20)
        top.addWidget(self.agent_logo)
        top.addStretch(1)
        title_col.addLayout(top)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {theme.TEXT};")
        title_col.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        self.meta.setWordWrap(True)
        title_col.addWidget(self.meta)
        header.addLayout(title_col, 1)
        close = TransparentToolButton()
        close.setIcon(line_icon("close", theme.MUTED, 16))
        close.setIconSize(QSize(16, 16))
        close.setFixedSize(26, 26)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("收起详情")
        close.clicked.connect(self._close)
        header.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        tabbar = QWidget()
        tab_layout = QHBoxLayout(tabbar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(16)
        self.tab_buttons: dict[str, QPushButton] = {}
        for key, label in (("summary", "摘要"), ("records", "执行记录"), ("logs", "完整日志")):
            button = PushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._switch_tab(k))
            tab_layout.addWidget(button)
            self.tab_buttons[key] = button
        tab_layout.addStretch(1)
        root.addWidget(tabbar)
        root.addWidget(divider())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.summary_scroll = SmoothScrollArea()
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.summary_host = QWidget()
        self.summary_layout = QVBoxLayout(self.summary_host)
        self.summary_layout.setContentsMargins(0, 6, 2, 16)
        self.summary_layout.setSpacing(12)
        self.summary_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.summary_scroll.setWidget(self.summary_host)
        self.stack.addWidget(self.summary_scroll)

        self.records_scroll = SmoothScrollArea()
        self.records_scroll.setWidgetResizable(True)
        self.records_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.records_host = QWidget()
        self.records_layout = QVBoxLayout(self.records_host)
        self.records_layout.setContentsMargins(0, 6, 2, 16)
        self.records_layout.setSpacing(12)
        self.records_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.records_scroll.setWidget(self.records_host)
        self.stack.addWidget(self.records_scroll)

        self.log_page = QWidget()
        log_layout = QVBoxLayout(self.log_page)
        log_layout.setContentsMargins(0, 8, 0, 0)
        log_layout.setSpacing(8)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.run_select = Select(options=[("all", "全部日志")])
        self.run_select.setMinimumWidth(150)
        self.run_select.changed.connect(self._on_run_select)
        controls.addWidget(self.run_select, 1)
        self.filter_select = Select(
            options=[("all", "全部"), ("text", "文本"), ("tool", "工具"), ("system", "系统")]
        )
        self.filter_select.setMinimumWidth(88)
        self.filter_select.changed.connect(self._on_filter)
        controls.addWidget(self.filter_select)
        log_layout.addLayout(controls)
        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)
        self.autoscroll = ToggleSwitch(True)
        tools_row.addWidget(self.autoscroll)
        auto_label = QLabel("自动滚动")
        auto_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        tools_row.addWidget(auto_label)
        tools_row.addStretch(1)
        copy_log = TransparentToolButton("复制")
        copy_log.clicked.connect(self._copy_log)
        open_log = TransparentToolButton("打开文件")
        open_log.clicked.connect(self._open_log_file)
        tools_row.addWidget(copy_log)
        tools_row.addWidget(open_log)
        log_layout.addLayout(tools_row)
        self.log_view = PlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(12000)
        log_layout.addWidget(self.log_view, 1)
        self.stack.addWidget(self.log_page)
        self._switch_tab("summary")
        self.hide()

    # ------------------------------------------------------------------
    # data / rendering
    # ------------------------------------------------------------------
    def show_task(self, task_id: str, tab: str = "summary", run_id: str = "") -> None:
        changed_task = task_id != self.task_id
        self.task_id = task_id
        if changed_task:
            self._log_run_id = ""
            self._log_manual = False
            self._summary_sig = None
            self._records_sig = None
            self._logs_sig = None
        self.refresh(run_id=run_id if run_id else None)
        self._switch_tab(tab)

    def refresh(self, run_id: str | None = None) -> None:
        if not self.task_id:
            return
        task = self.store.get_task(self.task_id)
        if not task:
            self._close()
            return
        runs = self.store.list_runs(task.id)
        self.status_pill.set_status(task.status)
        effective_agent = task.agent or self.engine.config.agent
        self.agent_logo.setIcon(agent_qicon(effective_agent))
        self.title.setText(task.title or "未命名任务")
        cwd = task.cwd or self.engine.config.cwd or "独立工作目录"
        short_cwd = Path(cwd.rstrip("\\/")).name or cwd
        self.meta.setText(f"{adapter_label(effective_agent)} · {short_cwd} · {format_duration(task.duration)}")
        self.meta.setToolTip(cwd)
        progress_sig = task.progress if task.status in (
            TaskStatus.interrupted.value,
            TaskStatus.attention.value,
            TaskStatus.failed.value,
        ) else ""
        summary_sig = (
            task.status,
            task.summary,
            tuple(task.completed),
            tuple(task.pending),
            tuple(task.issues),
            task.resume_count,
            task.followup_count,
            task.tool_count,
            task.attention_reason,
            task.followup_prompt,
            task.pending_action,
            task.error,
            progress_sig,
        )
        if summary_sig != self._summary_sig:
            self._summary_sig = summary_sig
            self._render_summary(task, runs)
        runs_sig = tuple(
            (run.id, run.status, run.tool_count, len(run.output or ""), len(run.interruptions), len(run.tools))
            for run in runs
        )
        if runs_sig != self._records_sig:
            self._records_sig = runs_sig
            self._render_records(task, runs)
        if runs_sig != self._logs_sig:
            self._logs_sig = runs_sig
            self._render_log_selector(runs, run_id=run_id)

    def _render_summary(self, task: Task, runs: list[Run]) -> None:
        clear_layout(self.summary_layout)
        if task.status in (TaskStatus.attention.value, TaskStatus.failed.value):
            banner = self._banner(
                "需要人工处理" if task.status == TaskStatus.attention.value else "执行失败",
                task.attention_reason or task.error or task.progress or "请检查执行记录",
                "error" if task.status == TaskStatus.failed.value else "warm",
            )
            self.summary_layout.addWidget(banner)
        elif task.status == TaskStatus.interrupted.value:
            self.summary_layout.addWidget(
                self._banner("已检测到中断", task.progress or "启动队列后会从原会话继续", "warm")
            )

        if task.status == TaskStatus.awaiting.value and task.pending_action == "followup":
            self.summary_layout.addWidget(self._followup_card(task))

        summary_title_row = QHBoxLayout()
        label = QLabel("执行摘要")
        label.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px; font-weight: 600;")
        summary_title_row.addWidget(label)
        summary_title_row.addStretch(1)
        self.summary_layout.addLayout(summary_title_row)
        summary_actions = QHBoxLayout()
        summary_actions.setSpacing(6)
        for text, slot in (
            ("复制", lambda: copy_text(self._summary_text(task), self, self.notify.emit)),
            ("修正", self._edit_analysis),
            ("导出", lambda: export_task(self, self.store, task)),
        ):
            button = TransparentToolButton(text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(24)
            button.clicked.connect(slot)
            summary_actions.addWidget(button)
        summary_actions.addStretch(1)
        retry = TransparentToolButton("重试")
        retry.setCursor(Qt.CursorShape.PointingHandCursor)
        retry.setFixedHeight(24)
        retry.setEnabled(task.status not in (
            TaskStatus.running.value, TaskStatus.tool.value, TaskStatus.resuming.value,
            TaskStatus.patching.value, TaskStatus.validating.value, TaskStatus.awaiting.value,
        ))
        retry.setToolTip("重置并重新执行")
        retry.clicked.connect(lambda: self._confirm_retry(task))
        summary_actions.addWidget(retry)
        optimize = TransparentToolButton("优化")
        optimize.setCursor(Qt.CursorShape.PointingHandCursor)
        optimize.setFixedHeight(24)
        optimize.clicked.connect(lambda: self.optimize_requested.emit(task.id))
        summary_actions.addWidget(optimize)
        self.summary_layout.addLayout(summary_actions)
        summary = QLabel(task.summary or "运行结束后会自动生成摘要、未完成项与问题清单。")
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setStyleSheet(
            f"color: {theme.TEXT_SOFT if task.summary else theme.MUTED}; font-size: 14px;"
        )
        self.summary_layout.addWidget(summary)

        chips_host = QWidget()
        chips = QGridLayout(chips_host)
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setHorizontalSpacing(6)
        chips.setVerticalSpacing(6)
        for index, (text, tone) in enumerate(
            (
                (f"完成 {len(task.completed)}", "green"),
                (f"未完成 {len(task.pending)}", "orange"),
                (f"问题 {len(task.issues)}", "red"),
                (f"续传 {task.resume_count}", "muted"),
                (f"补做 {task.followup_count}", "muted"),
                (f"工具 {task.tool_count}", "muted"),
            )
        ):
            chip = QLabel(text)
            bg, fg = {
                "green": (theme.GREEN_SOFT, theme.GREEN_TINT),
                "orange": (theme.ORANGE_SOFT, theme.ORANGE_TINT),
                "red": (theme.RED_SOFT, theme.RED_TINT),
                "muted": (theme.SLATE_SOFT, theme.MUTED),
            }[tone]
            chip.setStyleSheet(
                f"background: {bg}; color: {fg}; border-radius: 4px; padding: 2px 6px;"
                "font-size: 12px; font-weight: 500;"
            )
            chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            chips.addWidget(chip, index // 3, index % 3, Qt.AlignmentFlag.AlignLeft)
        self.summary_layout.addWidget(chips_host)

        self.summary_layout.addWidget(self._item_section("已完成", task.completed, theme.GREEN, "暂无记录"))
        self.summary_layout.addWidget(self._item_section("未完成 / 缺漏", task.pending, theme.ORANGE, "没有识别到未完成项"))
        self.summary_layout.addWidget(self._item_section("问题 / 风险 / 待优化", task.issues, theme.RED, "没有识别到问题"))

        self.summary_layout.addStretch(1)

    def _summary_text(self, task: Task) -> str:
        lines = [task.title, "", "摘要：" + (task.summary or "-")]
        for label, items in (("已完成", task.completed), ("未完成", task.pending), ("已知问题", task.issues)):
            lines.append("")
            lines.append(label + "：")
            lines.extend(f"- {item}" for item in items) if items else lines.append("- 无")
        return "\n".join(lines)

    def _item_section(self, title: str, items: list[str], color: str, empty: str) -> QWidget:
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(divider())
        body = QVBoxLayout()
        body.setContentsMargins(0, 2, 0, 4)
        body.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        dot = QWidget()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background: {color}; border-radius: 3.5px;")
        head.addWidget(dot)
        label = QLabel(title)
        label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT};")
        head.addWidget(label)
        count = QLabel(str(len(items)))
        count.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        head.addWidget(count)
        head.addStretch(1)
        body.addLayout(head)
        if not items:
            empty_label = QLabel(empty)
            empty_label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
            body.addWidget(empty_label)
        else:
            for item in items:
                bullet = QLabel("·  " + item)
                bullet.setWordWrap(True)
                bullet.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                bullet.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 13px;")
                body.addWidget(bullet)
        layout.addLayout(body)
        return frame

    def _banner(self, title: str, body: str, tone: str = "warm") -> QFrame:
        frame = QFrame()
        frame.setObjectName("BannerError" if tone == "error" else "BannerWarm" if tone == "warm" else "Banner")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        head = QLabel(title)
        head.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT};")
        layout.addWidget(head)
        text = QLabel(body)
        text.setWordWrap(True)
        text.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 13px;")
        layout.addWidget(text)
        return frame

    def _followup_card(self, task: Task) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Banner")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        head = QHBoxLayout()
        label = QLabel("待确认补做")
        label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {theme.ACCENT_DARK};")
        head.addWidget(label)
        head.addStretch(1)
        hint = QLabel("可编辑后下发")
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        head.addWidget(hint)
        layout.addLayout(head)
        reason = QLabel(task.attention_reason or "已生成补做提示词")
        reason.setWordWrap(True)
        reason.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 13px;")
        layout.addWidget(reason)
        editor = PlainTextEdit()
        editor.setPlainText(task.followup_prompt)
        editor.setFixedHeight(160)
        editor.setObjectName("PromptEdit")
        layout.addWidget(editor)
        buttons = QHBoxLayout()
        skip = PushButton("跳过补做")
        skip.clicked.connect(lambda: self._decide_followup(task.id, "skip", ""))
        approve = PrimaryPushButton("下发补做")
        approve.clicked.connect(lambda: self._decide_followup(task.id, "approve", editor.toPlainText()))
        buttons.addWidget(skip)
        buttons.addStretch(1)
        buttons.addWidget(approve)
        layout.addLayout(buttons)
        return frame

    def _decide_followup(self, task_id: str, decision: str, prompt: str) -> None:
        self.engine.resolve_followup(task_id, decision, prompt)
        self.notify.emit("已下发补做" if decision == "approve" else "已跳过补做", "info")

    def _confirm_retry(self, task: Task) -> None:
        if ConfirmDialog.ask(
            self,
            "重新执行任务",
            "将清空当前验收结果并从主提示词重新执行，历史执行记录仍会保留。",
            "重新执行",
        ):
            self.retry_requested.emit(task.id)

    # ------------------------------------------------------------------
    # records
    # ------------------------------------------------------------------
    def _render_records(self, task: Task, runs: list[Run]) -> None:
        clear_layout(self.records_layout)
        if not runs:
            empty = QLabel("还没有执行记录。启动队列后，这里会保留每一轮输出、工具与中断信息。")
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {theme.MUTED}; font-size: 14px;")
            self.records_layout.addWidget(empty)
            self.records_layout.addStretch(1)
            return
        for run in sorted(runs, key=lambda item: item.started_at):
            self.records_layout.addWidget(self._run_card(run))
        self.records_layout.addStretch(1)

    def _run_card(self, run: Run) -> QWidget:
        card = QFrame()
        card.setObjectName("InsetCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        kind_label = QLabel(run.label)
        bg, fg = theme.RUN_TONES.get(run.kind, theme.RUN_TONES["main"])
        kind_label.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 6px; padding: 3px 8px;"
            "font-size: 12px; font-weight: 500;"
        )
        head.addWidget(kind_label)
        status = QLabel(RUN_STATUS_LABEL.get(run.status, run.status))
        color = {
            "completed": theme.GREEN,
            "interrupted": theme.ORANGE,
            "failed": theme.RED,
            "stopped": theme.SUBTLE,
            "running": theme.BLUE,
        }.get(run.status, theme.SUBTLE)
        status.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 500;")
        head.addWidget(status)
        head.addStretch(1)
        duration = QLabel(format_duration(run.duration))
        duration.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        head.addWidget(duration)
        layout.addLayout(head)
        reason = QLabel(run.reason or "执行")
        reason.setWordWrap(True)
        reason.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 13px;")
        layout.addWidget(reason)
        if run.tool_count or run.output:
            meta = []
            if run.tool_count:
                meta.append(f"工具 {run.tool_count} 次")
            if run.exit_code is not None:
                meta.append(f"exit {run.exit_code}")
            if meta:
                meta_label = QLabel(" · ".join(meta))
                meta_label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
                layout.addWidget(meta_label)
        if run.interruptions:
            for interruption in run.interruptions:
                reason_text = {
                    "idle_timeout": "纯文本输出超时",
                    "tool_timeout": "工具执行超时",
                    "network_error": "网络异常",
                    "process_error": "进程异常",
                    "incomplete_reply": "回复不完整",
                    "user_stop": "人工终止",
                }.get(interruption.get("reason"), interruption.get("reason", "中断"))
                when = ""
                if interruption.get("at"):
                    try:
                        when = datetime.fromtimestamp(interruption["at"]).strftime("%H:%M:%S") + " "
                    except Exception:
                        when = ""
                item = QLabel(f"中断 · {when}{reason_text} · {interruption.get('detail', '')}")
                item.setWordWrap(True)
                item.setStyleSheet(f"color: {theme.ORANGE}; font-size: 12px;")
                layout.addWidget(item)
        if run.tools:
            tool_head = QLabel(f"工具执行记录（{len(run.tools)}）")
            tool_head.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px; font-weight: 600;")
            layout.addWidget(tool_head)
            for tool in run.tools[:5]:
                name = str(tool.get("name") or "tool")
                status = str(tool.get("status") or "")
                state_text = {"done": "完成", "error": "失败", "running": "执行中", "interrupted": "中断"}.get(status, status)
                args = str(tool.get("input") or "").replace("\n", " ")[:100]
                line = QLabel(f"{name} · {state_text}" + (f" · {args}" if args and args != "{}" else ""))
                line.setWordWrap(True)
                line.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 12px;")
                output = str(tool.get("output") or "").strip()
                if output:
                    line.setToolTip(output[:1500])
                layout.addWidget(line)
            if len(run.tools) > 5:
                more = QLabel(f"还有 {len(run.tools) - 5} 个工具调用，完整记录见日志")
                more.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
                layout.addWidget(more)
        if run.output:
            preview = run.output.strip().splitlines()
            preview_text = "\n".join(preview[:3])[:260]
            label = QLabel(preview_text + ("…" if len(run.output) > 260 else ""))
            label.setWordWrap(True)
            label.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
            layout.addWidget(label)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        view = TransparentToolButton("查看完整输出")
        view.setFixedHeight(24)
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        view.clicked.connect(lambda: OutputDialog(self, f"{run.label} · 完整输出", run.output or "（无输出）").exec())
        copy = TransparentToolButton("复制")
        copy.setFixedHeight(24)
        copy.setCursor(Qt.CursorShape.PointingHandCursor)
        copy.clicked.connect(lambda: self._copy_run_output(run))
        buttons.addWidget(view)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return card

    def _copy_run_output(self, run: Run) -> None:
        QApplication.clipboard().setText(run.output or "")
        self.notify.emit("已复制本轮输出", "success")

    # ------------------------------------------------------------------
    # logs
    # ------------------------------------------------------------------
    def _render_log_selector(self, runs: list[Run], run_id: str | None = None) -> None:
        options = [("all", "全部日志")]
        for run in reversed(runs):
            options.append((run.id, f"{run.label} · {format_time(run.started_at)}"))
        current = self.run_select.value()
        self.run_select.set_options(options, current if current in [o[0] for o in options] else (run_id or (runs[-1].id if runs else "all")))
        self._log_run_id = self.run_select.value()

    def _on_run_select(self, value: str) -> None:
        self._log_run_id = value
        self._log_manual = True
        self._load_logs()

    def _on_filter(self, value: str) -> None:
        self._log_filter = value
        self._load_logs()

    def _run_logs(self, run_id: str) -> str:
        runs = self.store.list_runs(self.task_id)
        if run_id == "all":
            chunks = []
            for run in runs:
                chunks.append(f"══════ {run.label} · {RUN_STATUS_LABEL.get(run.status, run.status)} · {format_time(run.started_at)} ══════")
                if run.log_path and Path(run.log_path).exists():
                    try:
                        chunks.append(Path(run.log_path).read_text(encoding="utf-8", errors="replace"))
                    except Exception as exc:
                        chunks.append(f"[读取日志失败] {exc}")
                else:
                    chunks.append("（暂无日志）")
            return "\n".join(chunks)
        run = next((item for item in runs if item.id == run_id), None)
        if not run or not run.log_path or not Path(run.log_path).exists():
            return "（暂无日志）"
        try:
            return Path(run.log_path).read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"[读取日志失败] {exc}"

    def _filter_line(self, line: str) -> bool:
        if self._log_filter == "all":
            return True
        if self._log_filter == "text":
            return "[输出]" in line or "[text]" in line or "[thinking]" in line
        if self._log_filter == "tool":
            return "[tool]" in line or "[interrupt]" in line
        return not ("[输出]" in line or "[text]" in line or "[thinking]" in line or "[tool]" in line)

    def _load_logs(self) -> None:
        if not self.task_id:
            return
        text = self._run_logs(self._log_run_id)
        lines = [line for line in text.splitlines() if self._filter_line(line)]
        self.log_view.setPlainText("\n".join(lines))
        if self.autoscroll.isChecked():
            self._scroll_bottom()

    def _scroll_bottom(self) -> None:
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def append_log(self, task_id: str, line: str) -> None:
        if task_id != self.task_id or self.stack.currentIndex() != 2:
            return
        if self._log_manual and self._log_run_id != "all":
            return
        if not self._filter_line(line):
            return
        self.log_view.appendPlainText(line)
        if self.autoscroll.isChecked():
            QTimer.singleShot(0, self._scroll_bottom)

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_view.toPlainText())
        self.notify.emit("完整日志已复制", "success")

    def _open_log_file(self) -> None:
        runs = self.store.list_runs(self.task_id)
        if not runs:
            self.notify.emit("暂无日志文件", "info")
            return
        run = next((item for item in runs if item.id == self._log_run_id), runs[-1])
        if not run.log_path or not Path(run.log_path).exists():
            self.notify.emit("日志文件不存在", "info")
            return
        os.startfile(run.log_path) if os.name == "nt" else __import__("subprocess").Popen(["xdg-open", run.log_path])

    # ------------------------------------------------------------------
    def _switch_tab(self, key: str) -> None:
        index = {"summary": 0, "records": 1, "logs": 2}.get(key, 0)
        for name, button in self.tab_buttons.items():
            button.setChecked(name == key)
        self.stack.setCurrentIndex(index)
        if key == "logs":
            self._load_logs()

    def _close(self) -> None:
        self.hide()
        self.task_id = ""
        self.closed.emit()

    def _edit_analysis(self) -> None:
        task = self.store.get_task(self.task_id)
        if not task:
            return
        from .editor_dialog import AnalysisEditDialog

        dialog = AnalysisEditDialog(self, task)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.result_data()
            from ..models import AnalysisResult

            original = AnalysisResult(
                summary=task.summary,
                completed=list(task.completed),
                pending=list(task.pending),
                issues=list(task.issues),
            )
            task.summary = result.summary
            task.completed = result.completed
            task.pending = result.pending
            task.issues = result.issues
            self.store.save_task(task)
            if dialog.use_as_feedback():
                self.store.add_feedback(
                    task.prompt,
                    json.dumps(original.to_dict(), ensure_ascii=False),
                    json.dumps(result.to_dict(), ensure_ascii=False),
                )
            self.refresh()
            self.notify.emit("识别结果已修正", "success")



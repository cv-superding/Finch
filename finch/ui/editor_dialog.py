from __future__ import annotations

import queue
import threading
from typing import Any

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..agents import ADAPTER_CLASSES, adapter_badge, adapter_color, adapter_label
from ..config import AppConfig
from ..core.optimizer import PromptOptimizer
from ..models import AnalysisResult, Task
from qfluentwidgets import (
    IndeterminateProgressRing,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    TransparentToolButton,
)

from . import theme
from .agent_icons import agent_qicon
from qfluentwidgets import BodyLabel, CaptionLabel, StrongBodyLabel

from .widgets import BaseDialog, Select, ToggleSwitch, divider, pick_folder


def agent_icon(key: str) -> QIcon | None:
    return agent_qicon(key)


class OptimizeDialog(BaseDialog):
    replace_requested = pyqtSignal(str)
    save_as_new_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None, config: AppConfig, text: str, kind: str = "user", title: str = ""):
        super().__init__(parent, "优化提示词", width=800, height=540)
        self.config = config
        self.original = text
        self.kind = kind
        self._result_queue: queue.Queue = queue.Queue()
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._poll)
        self._thread: threading.Thread | None = None

        hint = QLabel(
            f"使用 {'系统提示词' if kind == 'system' else '用户提示词'} 优化。"
            "优先调用 prompt-optimizer MCP，不可用时回退到内置优化模型。原意保持不变。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 14px;")
        self.body.addWidget(hint)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(7)
        left_label = CaptionLabel("原始提示词")
        left_label.setObjectName("SectionLabel")
        left.addWidget(left_label)
        self.original_edit = PlainTextEdit()
        self.original_edit.setPlainText(text)
        self.original_edit.setReadOnly(True)
        self.original_edit.setObjectName("ReadView")
        left.addWidget(self.original_edit, 1)
        columns.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(7)
        right_head = QHBoxLayout()
        right_label = CaptionLabel("优化结果")
        right_label.setObjectName("SectionLabel")
        right_head.addWidget(right_label)
        right_head.addStretch(1)
        self.spinner = IndeterminateProgressRing(self, start=False)
        self.spinner.setFixedSize(16, 16)
        self.spinner.start()
        right_head.addWidget(self.spinner)
        self.state = BodyLabel("正在优化…")
        self.state.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        right_head.addWidget(self.state)
        right.addLayout(right_head)
        self.result_edit = PlainTextEdit()
        self.result_edit.setObjectName("PromptEdit")
        self.result_edit.setPlaceholderText("优化结果会出现在这里，可继续编辑")
        right.addWidget(self.result_edit, 1)
        columns.addLayout(right, 1)
        self.body.addLayout(columns, 1)

        self.error = BodyLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {theme.RED}; font-size: 13px;")
        self.error.hide()
        self.body.addWidget(self.error)

        self.add_footer_stretch()
        self.close_btn = PushButton("关闭")
        self.close_btn.clicked.connect(self.reject)
        self.copy_btn = TransparentToolButton("复制结果")
        self.copy_btn.setFixedHeight(32)
        self.copy_btn.clicked.connect(self._copy)
        self.save_new_btn = PushButton("另存为新任务")
        self.save_new_btn.clicked.connect(self._save_new)
        self.replace_btn = PrimaryPushButton("替换原提示词")
        self.replace_btn.clicked.connect(self._replace)
        for button in (self.copy_btn, self.save_new_btn, self.replace_btn):
            button.setEnabled(False)
        self.footer.addWidget(self.close_btn)
        self.footer.addWidget(self.copy_btn)
        self.footer.addStretch(1)
        self.footer.addWidget(self.save_new_btn)
        self.footer.addWidget(self.replace_btn)
        self._start()

    def _start(self) -> None:
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()
        self._timer.start()

    def _work(self) -> None:
        try:
            result = PromptOptimizer(self.config).optimize(self.original, self.kind)
            self._result_queue.put(("ok", result.text, result.engine, result.note))
        except Exception as exc:
            self._result_queue.put(("error", "", "", str(exc)))

    def _poll(self) -> None:
        try:
            status, text, engine, note = self._result_queue.get_nowait()
        except queue.Empty:
            return
        self._timer.stop()
        self.spinner.stop()
        self.spinner.hide()
        if status == "ok":
            self.result_edit.setPlainText(text)
            self.result_edit.setFocus()
            self.state.setText(engine)
            self.state.setStyleSheet(f"color: {theme.GREEN}; font-size: 13px;")
            self.error.hide()
            for button in (self.copy_btn, self.save_new_btn, self.replace_btn):
                button.setEnabled(True)
        else:
            self.state.setText("优化失败")
            self.state.setStyleSheet(f"color: {theme.RED}; font-size: 13px;")
            self.error.setText(note)
            self.error.show()

    def _result_text(self) -> str:
        return self.result_edit.toPlainText().strip()

    def _copy(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._result_text())

    def _replace(self) -> None:
        text = self._result_text()
        if not text:
            return
        self.replace_requested.emit(text)
        self.accept()

    def _save_new(self) -> None:
        text = self._result_text()
        if not text:
            return
        self.save_as_new_requested.emit(text)
        self.accept()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)


class TaskEditorDialog(BaseDialog):
    optimized_new_task = pyqtSignal(str, str)  # title, prompt

    def __init__(
        self,
        parent: QWidget | None,
        config: AppConfig,
        task: Task | None = None,
        default_cwd: str = "",
    ):
        super().__init__(parent, "编辑任务" if task else "新建任务", width=680, height=640)
        self.config = config
        self.task = task
        self.result_task: Task | None = None

        title_row = QVBoxLayout()
        title_row.setSpacing(6)
        label = CaptionLabel("任务标题")
        label.setObjectName("SectionLabel")
        title_row.addWidget(label)
        self.title_edit = LineEdit()
        self.title_edit.setText(task.title if task else "")
        self.title_edit.setPlaceholderText("留空时自动取提示词第一行")
        self.title_edit.setCursorPosition(0)
        title_row.addWidget(self.title_edit)
        self.body.addLayout(title_row)

        prompt_head = QHBoxLayout()
        prompt_label = CaptionLabel("主提示词")
        prompt_label.setObjectName("SectionLabel")
        prompt_head.addWidget(prompt_label)
        prompt_head.addStretch(1)
        self.opt_kind = Select(options=[("user", "用户提示词"), ("system", "系统提示词")], value="user")
        self.opt_kind.setMinimumWidth(112)
        prompt_head.addWidget(self.opt_kind)
        self.optimize_btn = PushButton("优化提示词")
        self.optimize_btn.setFixedHeight(32)
        self.optimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.optimize_btn.clicked.connect(self._optimize)
        prompt_head.addWidget(self.optimize_btn)
        self.body.addLayout(prompt_head)
        self.prompt_edit = PlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "写清楚目标、范围、技术约束和验收标准。队列会按顺序下发这条提示词。"
        )
        self.prompt_edit.setObjectName("PromptEdit")
        self.prompt_edit.setPlainText(task.prompt if task else "")
        self.prompt_edit.setMinimumHeight(200)
        self.body.addWidget(self.prompt_edit, 1)
        self.counter = CaptionLabel("")
        self.counter.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 14px;")
        self.prompt_edit.textChanged.connect(self._update_counter)
        self._update_counter()

        grid = QHBoxLayout()
        grid.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(6)
        agent_label = CaptionLabel("使用 Agent")
        agent_label.setObjectName("SectionLabel")
        left.addWidget(agent_label)
        options = [("", f"跟随默认（{adapter_label(config.agent)}）")] + [
            (cls.key, cls.label) for cls in ADAPTER_CLASSES
        ]
        self.agent_select = Select(options=options, value=(task.agent if task else ""), icons=agent_icon)
        self.agent_select.setMinimumWidth(220)
        left.addWidget(self.agent_select)
        grid.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(6)
        cwd_label = CaptionLabel("工作目录")
        cwd_label.setObjectName("SectionLabel")
        right.addWidget(cwd_label)
        cwd_row = QHBoxLayout()
        cwd_row.setSpacing(6)
        self.cwd_edit = LineEdit()
        self.cwd_edit.setText(task.cwd if task else default_cwd)
        self.cwd_edit.setPlaceholderText("留空使用全局工作目录或独立目录")
        self.cwd_edit.setCursorPosition(0)
        cwd_row.addWidget(self.cwd_edit, 1)
        browse = PushButton("浏览")
        browse.setFixedHeight(32)
        browse.clicked.connect(self._browse)
        cwd_row.addWidget(browse)
        right.addLayout(cwd_row)
        grid.addLayout(right, 1)
        self.body.addLayout(grid)

        self.error = BodyLabel("")
        self.error.setStyleSheet(f"color: {theme.RED}; font-size: 13px;")
        self.error.setWordWrap(True)
        self.error.hide()
        self.body.addWidget(self.error)

        self.footer.addStretch(1)
        cancel = PushButton("取消")
        cancel.clicked.connect(self.reject)
        save = PrimaryPushButton("保存修改" if task else "添加到队列")
        save.clicked.connect(self._save)
        self.footer.addWidget(cancel)
        self.footer.addWidget(save)

    def _update_counter(self) -> None:
        text = self.prompt_edit.toPlainText()
        self.counter.setText(f"{len(text)} 字")

    def _browse(self) -> None:
        path = pick_folder(self.window(), self.cwd_edit.text() or "", "选择工作目录")
        if path:
            self.cwd_edit.setText(path)

    def _optimize(self) -> None:
        text = self.prompt_edit.toPlainText().strip()
        if not text:
            self._show_error("请先填写提示词")
            return
        dialog = OptimizeDialog(self, self.config, text, self.opt_kind.value(), self.title_edit.text())
        dialog.setProperty("centered", False)
        dialog.replace_requested.connect(self._replace_prompt)
        dialog.save_as_new_requested.connect(self._save_optimized_new)
        dialog.exec()

    def _replace_prompt(self, text: str) -> None:
        self.prompt_edit.setPlainText(text)
        self._update_counter()

    def _save_optimized_new(self, text: str) -> None:
        title = (self.title_edit.text().strip() or self._auto_title()) + "（优化）"
        self.optimized_new_task.emit(title, text)

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def _auto_title(self) -> str:
        for line in self.prompt_edit.toPlainText().splitlines():
            if line.strip():
                return line.strip().lstrip("#").strip()[:40] or "未命名任务"
        return "未命名任务"

    def _save(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            self._show_error("主提示词不能为空")
            return
        if self.task:
            task = self.task
        else:
            task = Task()
        task.title = self.title_edit.text().strip() or self._auto_title()
        task.prompt = prompt
        task.agent = self.agent_select.value()
        task.cwd = self.cwd_edit.text().strip()
        self.result_task = task
        self.accept()


class AnalysisEditDialog(BaseDialog):
    def __init__(self, parent: QWidget | None, task: Task):
        super().__init__(parent, "修正识别结果", width=600, height=620)
        hint = BodyLabel("修正后会立即更新任务详情。开启下方开关，后续语义识别会参考这些修正。")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 14px;")
        self.body.addWidget(hint)

        summary_head = CaptionLabel("执行摘要")
        summary_head.setObjectName("SectionLabel")
        self.body.addWidget(summary_head)
        self.summary_edit = PlainTextEdit()
        self.summary_edit.setPlainText(task.summary)
        self.summary_edit.setFixedHeight(72)
        self.summary_edit.setObjectName("PromptEdit")
        self.body.addWidget(self.summary_edit)

        lists = QHBoxLayout()
        lists.setSpacing(12)
        self.completed_edit = self._list_editor("已完成（每行一项）", task.completed, lists)
        self.pending_edit = self._list_editor("未完成 / 缺漏", task.pending, lists)
        self.issues_edit = self._list_editor("问题 / 风险 / 待优化", task.issues, lists)
        self.body.addLayout(lists, 1)

        use_row = QHBoxLayout()
        self.feedback_toggle = ToggleSwitch(True)
        use_row.addWidget(self.feedback_toggle)
        use_label = BodyLabel("把这次修正作为后续识别的偏好示例")
        use_label.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 14px;")
        use_row.addWidget(use_label)
        use_row.addStretch(1)
        self.body.addLayout(use_row)

        self.footer.addStretch(1)
        cancel = PushButton("取消")
        cancel.clicked.connect(self.reject)
        save = PrimaryPushButton("保存修正")
        save.clicked.connect(self.accept)
        self.footer.addWidget(cancel)
        self.footer.addWidget(save)

    def _list_editor(self, title: str, items: list[str], parent_layout: QHBoxLayout) -> QPlainTextEdit:
        column = QVBoxLayout()
        column.setSpacing(6)
        label = StrongBodyLabel(title)
        label.setObjectName("SectionLabel")
        column.addWidget(label)
        editor = PlainTextEdit()
        editor.setPlainText("\n".join(items))
        editor.setObjectName("PromptEdit")
        column.addWidget(editor, 1)
        parent_layout.addLayout(column, 1)
        return editor

    @staticmethod
    def _lines(text: str) -> list[str]:
        return [line.strip().lstrip("-*•· ").strip() for line in text.splitlines() if line.strip()]

    def result_data(self) -> AnalysisResult:
        result = AnalysisResult(
            summary=self.summary_edit.toPlainText().strip(),
            completed=self._lines(self.completed_edit.toPlainText()),
            pending=self._lines(self.pending_edit.toPlainText()),
            issues=self._lines(self.issues_edit.toPlainText()),
            source="manual",
        )
        result.needs_followup = bool(result.pending or result.issues)
        return result

    def use_as_feedback(self) -> bool:
        return self.feedback_toggle.isChecked()

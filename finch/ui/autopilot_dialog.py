from __future__ import annotations

import time

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from qfluentwidgets import (
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
)

from . import theme
from qfluentwidgets import BodyLabel, CaptionLabel

from .widgets import BaseDialog, ConfirmDialog, ToggleSwitch


class AutopilotDialog(BaseDialog):
    start_requested = pyqtSignal(str, int, int, bool)
    stop_requested = pyqtSignal()
    resume_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None, config: AppConfig, engine):
        super().__init__(parent, "自动驾驶", width=560)
        self.config = config
        self.engine = engine

        intro = BodyLabel(
            "让驱动模型读取目标与已完成记录，自动写下一条任务并下发，一轮接一轮推进；"
            "轮数、时限、目标达成、出错或手动停止都会停机。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        self.body.addWidget(intro)

        # ---- config view ----
        self.config_view = QWidget()
        cv = QVBoxLayout(self.config_view)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(10)
        goal_label = CaptionLabel("目标（可选）")
        goal_label.setObjectName("SectionLabel")
        cv.addWidget(goal_label)
        self.goal_edit = PlainTextEdit()
        self.goal_edit.setPlainText(config.autopilot_goal)
        self.goal_edit.setObjectName("PromptEdit")
        self.goal_edit.setPlaceholderText("写清楚要达成什么，达成后自动停；不填就只看轮数。")
        self.goal_edit.setFixedHeight(84)
        cv.addWidget(self.goal_edit)

        limits = QHBoxLayout()
        limits.setSpacing(12)
        rounds_box = QVBoxLayout()
        rounds_box.setSpacing(4)
        rounds_label = CaptionLabel("最多轮数")
        rounds_label.setObjectName("SectionLabel")
        rounds_box.addWidget(rounds_label)
        self.rounds_spin = SpinBox()
        self.rounds_spin.setRange(1, 50)
        self.rounds_spin.setValue(config.autopilot_rounds)
        rounds_box.addWidget(self.rounds_spin)
        limits.addLayout(rounds_box, 1)
        minutes_box = QVBoxLayout()
        minutes_box.setSpacing(4)
        minutes_label = CaptionLabel("时限（分钟，0 不限）")
        minutes_label.setObjectName("SectionLabel")
        minutes_box.addWidget(minutes_label)
        self.minutes_spin = SpinBox()
        self.minutes_spin.setRange(0, 600)
        self.minutes_spin.setValue(config.autopilot_minutes)
        minutes_box.addWidget(self.minutes_spin)
        limits.addLayout(minutes_box, 1)
        cv.addLayout(limits)

        accept_row = QHBoxLayout()
        accept_row.setSpacing(8)
        self.accept_switch = ToggleSwitch(config.autopilot_auto_accept)
        accept_row.addWidget(self.accept_switch)
        accept_text = BodyLabel("自动验收 / 自动确认补做")
        accept_text.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        accept_row.addWidget(accept_text)
        accept_row.addStretch(1)
        cv.addLayout(accept_row)
        self.body.addWidget(self.config_view)

        # ---- running / resumable view ----
        self.run_view = QWidget()
        rv = QVBoxLayout(self.run_view)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(10)
        state_row = QHBoxLayout()
        state_row.setSpacing(8)
        self.state_chip = CaptionLabel("")
        state_row.addWidget(self.state_chip)
        state_row.addStretch(1)
        self.elapsed_label = CaptionLabel("")
        self.elapsed_label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        state_row.addWidget(self.elapsed_label)
        rv.addLayout(state_row)
        self.goal_label = BodyLabel("")
        self.goal_label.setWordWrap(True)
        self.goal_label.setStyleSheet(f"color: {theme.TEXT}; font-size: 13px; font-weight: 500;")
        rv.addWidget(self.goal_label)
        log_label = CaptionLabel("每轮推理与下发")
        log_label.setObjectName("SectionLabel")
        rv.addWidget(log_label)
        self.rounds_log = PlainTextEdit()
        self.rounds_log.setObjectName("ReadView")
        self.rounds_log.setReadOnly(True)
        self.rounds_log.setFixedHeight(150)
        rv.addWidget(self.rounds_log)
        self.stop_reason_label = CaptionLabel("")
        self.stop_reason_label.setWordWrap(True)
        self.stop_reason_label.setStyleSheet(f"color: {theme.ORANGE_TINT}; font-size: 12px;")
        rv.addWidget(self.stop_reason_label)
        self.body.addWidget(self.run_view)

        self.add_footer_stretch()
        self.cancel_btn = PushButton("关闭")
        self.cancel_btn.clicked.connect(self.reject)
        self.footer.addWidget(self.cancel_btn)
        self.resume_btn = PrimaryPushButton("从中断处继续")
        self.resume_btn.clicked.connect(self._resume)
        self.footer.addWidget(self.resume_btn)
        self.stop_btn = PushButton("停止自动驾驶")
        self.stop_btn.clicked.connect(self._stop)
        self.footer.addWidget(self.stop_btn)
        self.start_btn = PrimaryPushButton("启动自动驾驶")
        self.start_btn.clicked.connect(self._start)
        self.footer.addWidget(self.start_btn)

        self.refresh()

    def refresh(self) -> None:
        state = self.engine.autopilot_state()
        active = self.engine.autopilot_active
        resumable = self.engine.autopilot_resumable
        self.config_view.setVisible(not active and not resumable)
        self.run_view.setVisible(active or resumable)
        self.start_btn.setVisible(not active and not resumable)
        self.stop_btn.setVisible(active)
        self.resume_btn.setVisible(resumable)
        if active or resumable:
            rounds = state.get("rounds", [])
            used = state.get("rounds_used", 0)
            maxr = state.get("max_rounds", 0)
            if active:
                self.state_chip.setText(f"自动 {used}/{maxr}")
                self.state_chip.setStyleSheet(
                    f"background: {theme.ACCENT_SOFT}; color: {theme.ACCENT_DARK};"
                    "border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600;"
                )
                started = state.get("started_at", 0)
                mins = int(max(0, time.time() - started) // 60) if started else 0
                self.elapsed_label.setText(f"已运行 {mins} 分钟")
            else:
                self.state_chip.setText("上次中断")
                self.state_chip.setStyleSheet(
                    f"background: {theme.ORANGE_SOFT}; color: {theme.ORANGE_TINT};"
                    "border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600;"
                )
                self.elapsed_label.setText("")
            self.goal_label.setText(state.get("goal") or "（未填写目标，按轮数推进）")
            lines = []
            for r in rounds:
                lines.append(f"第 {r.get('round')} 轮 · {r.get('title')}")
                if r.get("reason"):
                    lines.append(f"    推理：{r.get('reason')}")
                lines.append(f"    下发：{r.get('prompt', '')[:160]}")
                lines.append("")
            self.rounds_log.setPlainText("\n".join(lines) or "还没有生成任何一轮。")
            reason = state.get("stop_reason", "")
            self.stop_reason_label.setText(f"停机原因：{reason}" if reason and not active else "")
        else:
            self.stop_reason_label.setText("")

    def _start(self) -> None:
        goal = self.goal_edit.toPlainText().strip()
        rounds = self.rounds_spin.value()
        minutes = self.minutes_spin.value()
        auto_accept = self.accept_switch.isChecked()
        if not ConfirmDialog.ask(
            self,
            "启动自动驾驶",
            "自动驾驶会以你的身份自动向 Agent 下发任务并自动验收。确定启动吗？",
            "启动",
        ):
            return
        self.start_requested.emit(goal, rounds, minutes, auto_accept)
        self.accept()

    def _stop(self) -> None:
        self.stop_requested.emit()
        self.refresh()

    def _resume(self) -> None:
        self.resume_requested.emit()
        self.accept()
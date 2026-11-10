from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    ProgressBar,
    PushButton,
)

from . import theme
from .widgets import divider, format_time


class ArchiveBar(ProgressBar):
    """Library progress bar showing the archived share of the records."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self.setTextVisible(False)
        self.setCustomBarColor(QColor(theme.GREEN), QColor(theme.GREEN))

    def set_stats(self, done: int, attention: int, total: int) -> None:
        self.setValue(int(done * 100 / total) if total else 0)


class HistoryRail(QFrame):
    export_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("HistoryRail")
        self.setStyleSheet("QFrame#HistoryRail { background: transparent; border: none; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 10)
        root.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("归档概览")
        title.setObjectName("CardTitle")
        head.addWidget(title)
        head.addStretch(1)
        chip = QLabel("本机")
        chip.setStyleSheet(
            f"background: {theme.SLATE_SOFT}; color: {theme.MUTED}; border-radius: 6px;"
            "padding: 3px 8px; font-size: 12px; font-weight: 500;"
        )
        head.addWidget(chip)
        root.addLayout(head)

        summary = QHBoxLayout()
        summary.setSpacing(8)
        self.big = QLabel("0")
        self.big.setStyleSheet(f"font-size: 24px; font-weight: 600; color: {theme.TEXT};")
        summary.addWidget(self.big)
        self.big_caption = QLabel("份执行存档")
        self.big_caption.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        summary.addWidget(self.big_caption, 0, Qt.AlignmentFlag.AlignBottom)
        summary.addStretch(1)
        self.rate = QLabel("")
        self.rate.setStyleSheet(f"color: {theme.GREEN_TINT}; font-size: 12px; font-weight: 600;")
        summary.addWidget(self.rate, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(summary)
        self.bar = ArchiveBar()
        root.addWidget(self.bar)

        root.addSpacing(2)
        band = QWidget()
        band_layout = QVBoxLayout(band)
        band_layout.setContentsMargins(0, 0, 0, 0)
        band_layout.setSpacing(10)
        band_layout.addWidget(divider())
        tiles = QGridLayout()
        tiles.setHorizontalSpacing(20)
        tiles.setVerticalSpacing(12)
        self.values: dict[str, QLabel] = {}
        for index, (key, label_text) in enumerate(
            (
                ("done", "已完成"),
                ("attention", "待人工"),
                ("runs", "执行轮次"),
                ("tools", "工具调用"),
            )
        ):
            cell = QWidget()
            layout = QVBoxLayout(cell)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(1)
            value = QLabel("0")
            value.setStyleSheet(f"font-size: 17px; font-weight: 600; color: {theme.TEXT};")
            layout.addWidget(value)
            caption = QLabel(label_text)
            caption.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
            layout.addWidget(caption)
            tiles.addWidget(cell, index // 2, index % 2)
            self.values[key] = value
        band_layout.addLayout(tiles)
        band_layout.addWidget(divider())
        root.addWidget(band)

        label = QLabel("最近归档")
        label.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px; font-weight: 600;")
        root.addWidget(label)
        recent = QWidget()
        recent_layout = QVBoxLayout(recent)
        recent_layout.setContentsMargins(0, 0, 0, 0)
        recent_layout.setSpacing(3)
        self.recent_title = QLabel("还没有归档")
        self.recent_title.setWordWrap(True)
        self.recent_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT};")
        recent_layout.addWidget(self.recent_title)
        self.recent_meta = QLabel("")
        self.recent_meta.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        recent_layout.addWidget(self.recent_meta)
        root.addWidget(recent)
        root.addStretch(1)

        export = PushButton("导出全部记录")
        export.setFixedHeight(30)
        export.setCursor(Qt.CursorShape.PointingHandCursor)
        export.clicked.connect(self.export_requested.emit)
        root.addWidget(export)
        tip = QLabel("JSON 会包含任务、每轮输出与完整日志。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        root.addWidget(tip)

    def update_stats(self, records: list[dict], details: list[dict]) -> None:
        total = len(records)
        done = sum(1 for record in records if record.get("status") == "done")
        attention = sum(1 for record in records if record.get("status") in ("attention", "failed"))
        runs = sum(len(data.get("runs") or []) for data in details)
        tools = sum(int(run.get("tool_count") or 0) for data in details for run in (data.get("runs") or []))
        self.big.setText(str(total))
        self.rate.setText(f"完成率 {int(round(done / total * 100))}%" if total else "完成率 —")
        self.rate.setStyleSheet(
            f"color: {theme.GREEN_TINT if total else theme.SUBTLE}; font-size: 12px; font-weight: 600;"
        )
        self.bar.set_stats(done, attention, total)
        self.values["done"].setText(str(done))
        self.values["attention"].setText(str(attention))
        self.values["attention"].setStyleSheet(
            f"font-size: 17px; font-weight: 600; color: {theme.RED_TINT if attention else theme.SUBTLE};"
        )
        self.values["runs"].setText(str(runs))
        self.values["tools"].setText(str(tools))
        if records:
            self.recent_title.setText(records[0].get("task_title") or "未命名任务")
            self.recent_meta.setText(format_time(records[0].get("ended_at") or 0))
        else:
            self.recent_title.setText("还没有归档")
            self.recent_meta.setText("任务进入终态后会自动出现")

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..agents import adapter_badge, adapter_color, adapter_label
from ..models import STATUS_LABELS
from ..store import Store
from qfluentwidgets import (
    FluentIcon,
    IconWidget,
    IconWidget,
    SmoothScrollArea,
    PrimaryPushButton,
    PushButton,
    TransparentToolButton,
)

from . import theme
from .agent_icons import agent_qicon
from .history_rail import HistoryRail
from .widgets import (
    BaseDialog,
    ElidedLabel,
    StatusPill,
    divider,
    format_duration,
    format_time,
)


def _parse_list(value) -> list[str]:
    """Archived analysis lists may arrive as a list or as joined text."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        except json.JSONDecodeError:
            pass
    parts = [part.strip(" -•\t*") for part in re.split(r"[\n;；,，]+", text)]
    return [part for part in parts if part]


class HistoryDetailDialog(BaseDialog):
    def __init__(self, parent: QWidget | None, data: dict):
        title = data.get("task_title") or "执行记录"
        super().__init__(parent, title, width=700, height=600)
        task = data.get("task") or {}
        header = QHBoxLayout()
        header.setSpacing(8)
        status = task.get("status") or data.get("status") or "done"
        pill = StatusPill(status, STATUS_LABELS.get(status, status))
        header.addWidget(pill)
        agent = task.get("agent") or data.get("agent") or ""
        meta = QLabel(f"{adapter_label(agent)} · {format_time(data.get('ended_at') or 0)}")
        meta.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        header.addWidget(meta)
        header.addStretch(1)
        header.addWidget(QLabel(f"{len(data.get('runs') or [])} 轮执行"))
        self.body.addLayout(header)

        summary = QLabel(task.get("summary") or "无摘要")
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 14px;")
        self.body.addWidget(summary)

        columns = QHBoxLayout()
        columns.setSpacing(10)
        for title_text, key, color in (
            ("已完成", "completed", theme.GREEN),
            ("未完成", "pending", theme.ORANGE),
            ("问题", "issues", theme.RED),
        ):
            frame = QFrame()
            frame.setObjectName("InsetCard")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(12, 10, 12, 10)
            layout.setSpacing(5)
            label = QLabel(title_text)
            label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 600;")
            layout.addWidget(label)
            items = _parse_list(task.get(key))
            for item in items[:8]:
                line = QLabel("· " + item)
                line.setWordWrap(True)
                line.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 13px;")
                layout.addWidget(line)
            if not items:
                empty = QLabel("无")
                empty.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 13px;")
                layout.addWidget(empty)
            layout.addStretch(1)
            columns.addWidget(frame, 1)
        self.body.addLayout(columns)

        label = QLabel("执行轮次")
        label.setObjectName("SectionLabel")
        self.body.addWidget(label)
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 4, 0)
        host_layout.setSpacing(8)
        for run in data.get("runs") or []:
            frame = QFrame()
            frame.setObjectName("InsetCard")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(12, 9, 12, 9)
            layout.setSpacing(4)
            top = QHBoxLayout()
            kind = {"main": "主任务", "resume": "续传", "followup": "补做"}.get(run.get("kind"), run.get("kind"))
            kind_label = QLabel(f"{kind} #{run.get('round', 0)}" if run.get("kind") != "main" else "主任务")
            kind_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {theme.TEXT};")
            top.addWidget(kind_label)
            status_label = QLabel(
                {"completed": "完成", "interrupted": "中断", "failed": "失败", "stopped": "终止"}.get(run.get("status"), run.get("status"))
            )
            status_label.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
            top.addWidget(status_label)
            top.addStretch(1)
            duration = max(0, (run.get("ended_at") or 0) - (run.get("started_at") or 0))
            top.addWidget(QLabel(format_duration(duration)))
            layout.addLayout(top)
            reason = QLabel(run.get("reason") or "")
            reason.setWordWrap(True)
            reason.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
            layout.addWidget(reason)
            output = (run.get("output") or "").strip().splitlines()
            if output:
                preview = QLabel("\n".join(output[:2])[:240])
                preview.setWordWrap(True)
                preview.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 13px;")
                layout.addWidget(preview)
            host_layout.addWidget(frame)
        host_layout.addStretch(1)
        scroll.setWidget(host)
        self.body.addWidget(scroll, 1)

        self.add_footer_stretch()
        copy = PushButton("复制存档 JSON")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(json.dumps(data, ensure_ascii=False, indent=2)))
        close = PrimaryPushButton("关闭")
        close.clicked.connect(self.accept)
        self.footer.addWidget(copy)
        self.footer.addWidget(close)


class HistoryPage(QWidget):
    notify = pyqtSignal(str, str)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setObjectName("Page")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 12)
        root.setSpacing(14)
        header = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(6)
        title = QLabel("执行记录")
        title.setObjectName("PageTitle")
        left.addWidget(title)
        subtitle = QLabel("每条任务的摘要、续传、补做与完整输出会自动归档，可随时回溯和导出。")
        subtitle.setObjectName("PageSubtitle")
        left.addWidget(subtitle)
        header.addLayout(left, 1)
        export_all = PushButton("导出全部")
        export_all.setFixedHeight(32)
        export_all.clicked.connect(self._export_all)
        header.addWidget(export_all)
        root.addLayout(header)

        workspace = QFrame()
        workspace.setObjectName("Workspace")
        ws_layout = QHBoxLayout(workspace)
        ws_layout.setContentsMargins(0, 0, 0, 0)
        ws_layout.setSpacing(0)
        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(16, 12, 16, 12)
        head_layout.setSpacing(6)
        label = QLabel("归档列表")
        label.setObjectName("CardTitle")
        head_layout.addWidget(label)
        self.count_chip = QLabel("0 条")
        self.count_chip.setStyleSheet(
            f"background: transparent; color: {theme.MUTED};"
            "padding: 0px; font-size: 12px; font-weight: 500;"
        )
        head_layout.addWidget(self.count_chip)
        head_layout.addStretch(1)
        left_layout.addWidget(head)
        left_layout.addWidget(divider())
        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.list_layout = QVBoxLayout(self.host)
        self.list_layout.setContentsMargins(12, 6, 12, 12)
        self.list_layout.setSpacing(0)
        self.scroll.setWidget(self.host)
        left_layout.addWidget(self.scroll, 1)
        ws_layout.addWidget(left_pane, 1)
        inspector = QFrame()
        inspector.setObjectName("Inspector")
        inspector.setFixedWidth(300)
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(0)
        self.rail = HistoryRail()
        self.rail.export_requested.connect(self._export_all)
        inspector_layout.addWidget(self.rail)
        ws_layout.addWidget(inspector)
        root.addWidget(workspace, 1)
        self.refresh()

    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        records = self.store.list_history()
        details = [self.store.get_history(record["id"]) or {} for record in records]
        self.count_chip.setText(f"{len(records)} 条")
        self.rail.update_stats(records, details)
        if not records:
            self.list_layout.addWidget(self._empty_state())
            return
        current_group = None
        for record, data in zip(records, details):
            group = self._group_label(record.get("ended_at") or 0)
            if group != current_group:
                self.list_layout.addWidget(self._group_header(group))
                current_group = group
            self.list_layout.addWidget(self._row(record, data))
        self.list_layout.addStretch(1)

    @staticmethod
    def _group_label(ts: float) -> str:
        if not ts:
            return "更早"
        day = datetime.fromtimestamp(ts).date()
        today = datetime.now().date()
        if day == today:
            return "今天"
        if day == today - timedelta(days=1):
            return "昨天"
        return day.strftime("%Y-%m-%d")

    def _group_header(self, label: str) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(2, 10, 2, 2)
        layout.setSpacing(10)
        text = QLabel(label)
        text.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px; font-weight: 600;")
        layout.addWidget(text)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.BORDER_SOFT};")
        layout.addWidget(line, 1)
        return host

    def _empty_state(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(16, 40, 16, 40)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph = IconWidget()
        glyph.setIcon(FluentIcon.HISTORY)
        glyph.setFixedSize(32, 32)
        layout.addWidget(glyph, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("还没有归档记录")
        title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {theme.TEXT};")
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        text = QLabel("任务执行结束或被人工处理后，会自动归档到这里。")
        text.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px;")
        layout.addWidget(text, 0, Qt.AlignmentFlag.AlignHCenter)
        return host

    def _row(self, record: dict, data: dict | None = None) -> QWidget:
        if data is None:
            data = self.store.get_history(record["id"]) or {}
        task = data.get("task") or {}
        frame = QFrame()
        frame.setObjectName("HistoryRow")
        frame.setFixedHeight(72)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        frame.setStyleSheet(
            f"""
            QFrame#HistoryRow {{ background: transparent; border-radius: 10px; }}
            QFrame#HistoryRow:hover {{ background: {theme.BG_SOFT}; }}
            """
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        ended = record.get("ended_at") or 0
        time = QLabel(datetime.fromtimestamp(ended).strftime("%H:%M") if ended else "—")
        time.setFixedWidth(36)
        time.setStyleSheet(
            f"color: {theme.SUBTLE}; font-size: 12px; font-family: '{theme.mono_family()}';"
        )
        layout.addWidget(time, 0, Qt.AlignmentFlag.AlignTop)
        agent = task.get("agent") or record.get("agent") or ""
        agent_icon = IconWidget()
        agent_icon.setIcon(agent_qicon(agent))
        agent_icon.setFixedSize(18, 18)
        layout.addWidget(agent_icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = ElidedLabel(record.get("task_title") or "未命名任务")
        title.setObjectName("TaskTitle")
        top.addWidget(title, 1)
        status = record.get("status") or "done"
        pill = StatusPill(status, STATUS_LABELS.get(status, status))
        top.addWidget(pill)
        text.addLayout(top)
        summary = ElidedLabel(record.get("summary") or "无摘要")
        summary.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        text.addWidget(summary)
        meta = QLabel(
            f"{adapter_label(agent)} · {len(data.get('runs') or [])} 轮执行"
        )
        meta.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        text.addWidget(meta)
        layout.addLayout(text, 1)
        view = TransparentToolButton("查看")
        view.setFixedHeight(24)
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        view.clicked.connect(lambda _=False, d=data: HistoryDetailDialog(self, d).exec())
        export = TransparentToolButton("导出")
        export.setFixedHeight(24)
        export.setCursor(Qt.CursorShape.PointingHandCursor)
        export.clicked.connect(
            lambda _=False, d=data, t=record.get("task_title") or "history": self._export_one(d, t)
        )
        layout.addWidget(view)
        layout.addWidget(export)
        return frame

    def _with_logs(self, data: dict) -> dict:
        payload = dict(data)
        logs = {}
        for run in payload.get("runs") or []:
            log_path = run.get("log_path")
            if log_path and Path(log_path).exists():
                try:
                    logs[run.get("id")] = Path(log_path).read_text(encoding="utf-8", errors="replace")
                except Exception:
                    logs[run.get("id")] = ""
        payload["logs"] = logs
        return payload

    def _export_one(self, data: dict, title: str) -> None:
        safe = "".join(ch for ch in title if ch not in '\\/:*?"<>|')[:60]
        path, _ = QFileDialog.getSaveFileName(
            self, "导出执行记录", f"{safe or 'history'}.json", "JSON 文件 (*.json)"
        )
        if path:
            Path(path).write_text(
                json.dumps(self._with_logs(data), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.notify.emit("执行记录已导出", "success")

    def _export_all(self) -> None:
        records = self.store.list_history()
        if not records:
            self.notify.emit("暂无可导出的记录", "info")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出全部执行记录",
            f"finch-history-{datetime.now().strftime('%Y%m%d-%H%M')}.json",
            "JSON 文件 (*.json)",
        )
        if not path:
            return
        payload = [self._with_logs(self.store.get_history(record["id"]) or {}) for record in records]
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.notify.emit("全部执行记录已导出", "success")

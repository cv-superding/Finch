from __future__ import annotations

import os

from PyQt6.QtCore import (
    QByteArray,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCloseEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qframelesswindow import FramelessMainWindow
from qfluentwidgets import (
    FluentWidgetTitleBar,
    ToolTipFilter,
)

from ..agents import ADAPTER_CLASSES
from ..config import AppConfig
from ..models import TaskStatus
from ..store import Store
from . import theme
from .agent_icons import agent_mono_icon, agent_qicon
from .history_page import HistoryPage
from .queue_page import QueuePage
from .settings_page import SettingsPage
from .glyphs import line_icon
from .widgets import BreathingDot, EdgeResizeHandle, NoticeDialog, Toast, make_app_icon

# 空闲 Agent 用线性图标；运行中换回真实彩色图标
AGENT_GLYPHS = {
    "claude": "spark",
    "codex": "code",
    "zcode": "command",
    "opencode": "devtools",
    "cursor": "cube",
    "mock": "bot",
}

NAV_ITEMS = (
    ("queue", "queue", "任务队列"),
    ("history", "history", "执行记录"),
    ("settings", "settings", "设置"),
)


class SideRow(QWidget):
    """Sidebar row: icon or glowing dot, label, optional count badge."""

    clicked = pyqtSignal()

    def __init__(
        self,
        text: str,
        icon_name: str = "",
        dot: str = "",
        count: int = 0,
        indent: int = 12,
        height: int = 34,
        font_size: int = 13,
        active_bar: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._text = text
        self._icon = line_icon(icon_name, theme.SIDEBAR_MUTED, 16) if icon_name else None
        self._dot = dot
        self._count = count
        self._indent = indent
        self._font_size = font_size
        self._active = False
        self._active_bar = active_bar
        self._show_text = True
        self._pressed = False
        self._pulse = 0.0
        self._pulse_anim = None
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def click(self) -> None:
        self.clicked.emit()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.update()
        if (
            was_pressed
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_active(self, value: bool) -> None:
        self._active = value
        self.update()

    def set_icon(self, icon: QIcon) -> None:
        """换成真实图标（或单色版本），并关掉圆点绘制。"""
        self._icon = icon
        self._dot = ""
        self.update()

    def set_count(self, n: int) -> None:
        self._count = n
        self.update()

    def set_dot_color(self, color: str) -> None:
        if self._dot == color:
            return
        self._dot = color
        self.update()

    def set_pulse(self, active: bool) -> None:
        """运行中的 Agent 圆点做 2s 呼吸；其余静止。"""
        if active and self._pulse_anim is None:
            anim = QVariantAnimation(self)
            anim.setDuration(2000)
            anim.setStartValue(0.0)
            anim.setKeyValueAt(0.5, 1.0)
            anim.setEndValue(0.0)
            anim.setLoopCount(-1)
            anim.valueChanged.connect(self._on_pulse)
            self._pulse_anim = anim
            anim.start()
        elif not active and self._pulse_anim is not None:
            self._pulse_anim.stop()
            self._pulse_anim.deleteLater()
            self._pulse_anim = None
            self._pulse = 0.0
            self.update()

    def _on_pulse(self, value: float) -> None:
        self._pulse = float(value)
        self.update()

    def stop_animation(self) -> None:
        if self._pulse_anim is not None:
            self._pulse_anim.stop()
            self._pulse_anim.deleteLater()
            self._pulse_anim = None

    def set_show_text(self, value: bool) -> None:
        self._show_text = value
        self.update()

    def _draw_dot(self, painter, x: float, cy: float, radius: float) -> None:
        if not self._dot:
            return
        color = QColor(self._dot)
        halo = QColor(color)
        pulse = self._pulse if self._pulse_anim is not None else 0.0
        halo.setAlphaF(0.12 + 0.26 * pulse)
        scale = 1.7 + 0.8 * pulse
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(x, cy), radius * scale, radius * scale)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(x, cy), radius, radius)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self._active or self.underMouse() or self._pressed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor(theme.BORDER_INPUT if self._pressed else theme.SURFACE_2)
            )
            painter.drawRoundedRect(QRect(0, 0, w, h), 6, 6)
        if self._active and self._active_bar:
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(QRect(0, 0, 3, h), 1.5, 1.5)

        if not self._show_text:
            if self._dot:
                self._draw_dot(painter, w / 2, h / 2, 4)
            elif self._icon is not None:
                self._icon.paint(painter, QRect((w - 16) // 2, (h - 16) // 2, 16, 16))
            return

        x = self._indent
        if self._dot:
            self._draw_dot(painter, x + 4, h / 2, 4)
            x += 17
        elif self._icon is not None:
            self._icon.paint(painter, QRect(x - 1, (h - 16) // 2, 16, 16))
            x += 24

        badge_width = 0
        if self._count:
            mono = QFont(theme.mono_family())
            mono.setPixelSize(10)
            metrics = QFontMetrics(mono)
            text = str(self._count)
            badge_width = metrics.horizontalAdvance(text) + 12
            badge_x = w - 8 - badge_width
            painter.setFont(mono)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.SURFACE_2))
            painter.drawRoundedRect(QRect(badge_x, (h - 17) // 2, badge_width, 17), 4, 4)
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(
                QRect(badge_x, (h - 17) // 2, badge_width, 17),
                Qt.AlignmentFlag.AlignCenter,
                text,
            )

        font = QFont(theme.font_family())
        font.setPixelSize(int(self._font_size))
        font.setWeight(QFont.Weight.DemiBold if self._active else QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT if self._active else theme.SIDEBAR_MUTED))
        painter.drawText(
            QRect(x, 0, max(0, w - x - badge_width - 14), h),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._text,
        )


class Sidebar(QFrame):
    nav_changed = pyqtSignal(str)
    collapsed_changed = pyqtSignal(bool)
    agent_filter_changed = pyqtSignal(str)
    help_requested = pyqtSignal()
    width_changed = pyqtSignal(int)

    EXPANDED_WIDTH = 220
    COMPACT_WIDTH = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppSidebar")
        self.setFixedWidth(self.EXPANDED_WIDTH)
        self._agent_filter = ""
        self._agent_rows: dict[str, SideRow] = {}
        self._collapsed = False
        self._expanded_width = self.EXPANDED_WIDTH
        self.resize_handle = EdgeResizeHandle("right", 180, 340, self)
        self.resize_handle.hide()
        self.resize_handle.resized.connect(self.set_expanded_width)
        self.resize_handle.finished.connect(self.width_changed.emit)
        self.resize_handle.toggled.connect(
            lambda: self.set_collapsed(not self._collapsed)
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 10)
        root.setSpacing(4)

        # 品牌与窗口控件合并进窗口标题栏，侧栏不再重复一行品牌
        root.addSpacing(10)

        self.nav_rows: dict[str, SideRow] = {}
        for key, icon_name, text in NAV_ITEMS:
            row = SideRow(text, icon_name=icon_name, active_bar=True, height=40, font_size=13.5)
            row.clicked.connect(lambda k=key: self._on_nav(k))
            root.addWidget(row)
            self.nav_rows[key] = row
        self.nav_rows["queue"].set_active(True)
        self.nav_buttons = self.nav_rows

        root.addSpacing(22)
        self.agents_head = QLabel("AGENTS")
        self.agents_head.setObjectName("SideLabel")
        self.agents_head.setFixedHeight(24)
        root.addWidget(self.agents_head)

        for cls in ADAPTER_CLASSES:
            row = SideRow(
                cls.label,
                count=0,
                indent=12,
                height=36,
                font_size=13,
            )
            row.set_icon(line_icon(AGENT_GLYPHS.get(cls.key, "bot"), theme.SUBTLE, 16))
            row.clicked.connect(lambda k=cls.key: self._on_agent_clicked(k))
            root.addWidget(row)
            self._agent_rows[cls.key] = row

        root.addStretch(1)

        self.status_box = QWidget()
        status_layout = QVBoxLayout(self.status_box)
        status_layout.setContentsMargins(8, 8, 8, 8)
        status_layout.setSpacing(4)
        state_line = QHBoxLayout()
        state_line.setSpacing(7)
        self.state_dot = BreathingDot(theme.SUBTLE, 7)
        state_line.addWidget(self.state_dot)
        self.state_label = QLabel("空闲")
        self.state_label.setObjectName("SideState")
        state_line.addWidget(self.state_label)
        state_line.addStretch(1)
        self.count_label = QLabel("0 / 0")
        self.count_label.setObjectName("SideMeta")
        state_line.addWidget(self.count_label)
        status_layout.addLayout(state_line)
        self.task_label = QLabel("暂无运行任务")
        self.task_label.setObjectName("SideMeta")
        self.task_label.setWordWrap(False)
        status_layout.addWidget(self.task_label)
        root.addWidget(self.status_box)

        self.footer = QWidget()
        footer_layout = QHBoxLayout(self.footer)
        self.footer_layout = footer_layout
        footer_layout.setContentsMargins(4, 2, 4, 0)
        footer_layout.setSpacing(4)
        self.settings_btn = self._footer_button("settings", "设置")
        self.settings_btn.clicked.connect(lambda: self._on_nav("settings"))
        footer_layout.addWidget(self.settings_btn)
        self.help_btn = self._footer_button("help", "操作提示")
        self.help_btn.clicked.connect(self.help_requested.emit)
        footer_layout.addWidget(self.help_btn)
        footer_layout.addStretch(1)
        root.addWidget(self.footer)

        self.set_state("idle")

    def _footer_button(self, icon_name: str, tip: str) -> QPushButton:
        button = QPushButton()
        button.setFixedSize(30, 28)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tip)
        button.setIcon(line_icon(icon_name, theme.SUBTLE, 16))
        button.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 6px; }"
            f"QPushButton:hover {{ background: {theme.SURFACE_2}; }}"
        )
        return button

    @staticmethod
    def _agent_color(key: str) -> str:
        return {
            "mock": theme.ACCENT,
            "claude": theme.ORANGE,
            "codex": theme.GREEN,
            "zcode": theme.VIOLET,
            "opencode": theme.BLUE,
            "cursor": theme.SUBTLE,
        }.get(key, theme.SUBTLE)

    def _on_nav(self, key: str) -> None:
        self.set_page(key)
        self.nav_changed.emit(key)

    def _on_agent_clicked(self, key: str) -> None:
        new = "" if self._agent_filter == key else key
        self.set_agent_filter(new)
        self.agent_filter_changed.emit(new)

    def set_agent_filter(self, key: str) -> None:
        self._agent_filter = key
        for agent_key, row in self._agent_rows.items():
            row.set_active(agent_key == key)

    def set_agent_counts(self, counts: dict[str, int], active: set[str] | None = None) -> None:
        active = active or set()
        for key, row in self._agent_rows.items():
            row.set_count(counts.get(key, 0))
            # 圆点表达状态而不是身份：运行中亮品牌色并呼吸，其余一律中性灰
            running = key in active
            row.set_icon(
                agent_qicon(key)
                if running
                else line_icon(AGENT_GLYPHS.get(key, "bot"), theme.SUBTLE, 16)
            )
            row.set_pulse(running)

    def set_page(self, key: str) -> None:
        for nav_key, row in self.nav_rows.items():
            row.set_active(nav_key == key)

    def set_state(self, state: str) -> None:
        labels = {
            "idle": "空闲",
            "running": "执行中",
            "paused": "已暂停",
            "stopping": "终止中",
            "awaiting": "待确认",
            "done": "已完成",
        }
        colors = {
            "idle": theme.SUBTLE,
            "running": theme.RUNNING,
            "paused": theme.ORANGE,
            "stopping": theme.RED,
            "awaiting": theme.ORANGE,
            "done": theme.GREEN,
        }
        self._last_state = state
        self.state_label.setText(labels.get(state, state))
        self.state_dot.set_color(colors.get(state, theme.SUBTLE))
        self.state_dot.set_active(state == "running")

    def set_summary(self, done: int, total: int) -> None:
        self.count_label.setText(f"{done} / {total}")
        self.nav_rows["queue"].set_count(total)
        self.nav_rows["history"].set_count(done)

    def set_active_task(self, title: str) -> None:
        text = title or "暂无运行任务"
        if len(text) > 16:
            text = text[:15] + "…"
        self.task_label.setText(text)
        self.task_label.setToolTip(title)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_expanded_width(self, width: int) -> None:
        self._expanded_width = max(180, min(340, int(width)))
        if not self._collapsed:
            self.setFixedWidth(self._expanded_width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resize_handle.setGeometry(self.width() - 4, 0, 4, self.height())
        self.resize_handle.raise_()

    def set_collapsed(self, collapsed: bool, animate: bool = True, emit: bool = True) -> None:
        self._collapsed = collapsed
        self.setFixedWidth(self.COMPACT_WIDTH if collapsed else self._expanded_width)
        self.resize_handle.setVisible(not collapsed)
        for row in list(self.nav_rows.values()) + list(self._agent_rows.values()):
            row.set_show_text(not collapsed)
        for widget in (self.agents_head, self.status_box):
            widget.setVisible(not collapsed)
        # 收起后底部只留一个设置入口，两个按钮在 60px 宽度里会叠在一起
        self.help_btn.setVisible(not collapsed)
        self.footer_layout.setAlignment(
            Qt.AlignmentFlag.AlignCenter if collapsed else Qt.AlignmentFlag.AlignLeft
        )
        if emit:
            self.collapsed_changed.emit(collapsed)


class MainWindow(FramelessMainWindow):
    def __init__(self, store: Store, engine, config: AppConfig):
        super().__init__()
        self.store = store
        self.engine = engine
        self.config = config
        self.setWindowTitle("Finch · Agent 队列")
        self.setWindowIcon(make_app_icon(64))
        self.setMinimumSize(1080, 700)
        self.resize(1200, 800)
        self._notice: NoticeDialog | None = None
        self.setObjectName("AppWindow")

        try:
            if os.environ.get("FINCH_NO_MICA") != "1":
                self.windowEffect.setMicaEffect()
        except Exception:
            pass

        title_bar = FluentWidgetTitleBar(self)
        title_bar.setObjectName("AppTitleBar")
        title_bar.setIcon(make_app_icon(64))
        title_bar.setTitle("Finch")
        title_bar.setFixedHeight(44)
        title_bar.titleLabel.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; font-weight: 600; background: transparent;"
        )
        self.setTitleBar(title_bar)
        self.installEventFilter(self)
        ToolTipFilter(self)
        self.titleBar.resize(self.width(), self.titleBar.height())

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        # The central area starts below the frameless title bar, otherwise it
        # would cover the window buttons and swallow their clicks.
        self.setContentsMargins(0, self.titleBar.height(), 0, 0)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        # 折叠按钮放进标题栏，和品牌、窗口控件同属一行
        self.collapse_btn = QPushButton()
        self.collapse_btn.setFixedSize(26, 26)
        self.collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_btn.setIcon(line_icon("chevron-down", theme.SUBTLE, 12))
        self.collapse_btn.setIconSize(QSize(12, 12))
        self.collapse_btn.setToolTip("折叠侧栏")
        self.collapse_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 6px; }"
            f"QPushButton:hover {{ background: {theme.SURFACE_2}; }}"
        )
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        title_bar.hBoxLayout.insertWidget(
            2,
            self.collapse_btn,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        self.sidebar.nav_changed.connect(self._switch_page)
        self.sidebar.agent_filter_changed.connect(self._on_agent_filter)
        self.sidebar.help_requested.connect(self._show_help)
        try:
            saved_width = int(self.store.get_setting("sidebar_width", "220") or 220)
        except ValueError:
            saved_width = 220
        self.sidebar.set_expanded_width(saved_width)
        self.sidebar.width_changed.connect(
            lambda w: self.store.set_setting("sidebar_width", str(w))
        )
        collapsed = self.store.get_setting("sidebar_collapsed", "0") == "1"
        self.sidebar.set_collapsed(collapsed, animate=False, emit=False)
        self.collapse_btn.setIcon(
            line_icon("chevron-right" if collapsed else "chevron-down", theme.SUBTLE, 12)
        )
        self.sidebar.collapsed_changed.connect(self._save_sidebar_state)
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.queue_page = QueuePage(store, engine, config)
        self.history_page = HistoryPage(store)
        self.settings_page = SettingsPage(store, engine, config)
        self.stack.addWidget(self.queue_page)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.settings_page)

        self.toast = Toast(self)
        self._connect()
        self._update_state()
        self.sidebar.set_page("queue")
        self._place_window()

    def _connect(self) -> None:
        signals = self.engine.signals
        signals.toast.connect(self._toast)
        signals.alert.connect(self._alert)
        signals.state_changed.connect(self._on_state)
        signals.task_updated.connect(self._on_task_updated)
        signals.queue_updated.connect(self._on_queue_updated)
        self.queue_page.notify.connect(self._toast)
        self.history_page.notify.connect(self._toast)
        self.settings_page.notify.connect(self._toast)
        self.settings_page.config_saved.connect(self.queue_page.reload_config)
        self.queue_page.filter_changed.connect(self.sidebar.set_agent_filter)

    def _switch_page(self, key: str) -> None:
        index = {"queue": 0, "history": 1, "settings": 2}.get(key, 0)
        self.stack.setCurrentIndex(index)
        self.sidebar.set_page(key)
        if key == "history":
            self.history_page.refresh()
        elif key == "settings":
            self.settings_page.reload()
        elif key == "queue":
            self.queue_page.refresh()

    def _on_agent_filter(self, key: str) -> None:
        self.queue_page.set_agent_filter(key)
        self._switch_page("queue")

    def _save_sidebar_state(self, collapsed: bool) -> None:
        self.store.set_setting("sidebar_collapsed", "1" if collapsed else "0")

    def _on_state(self, state: str) -> None:
        self._update_state()
        if state == "running":
            self.toast.hide()

    def _on_task_updated(self, task_id: str) -> None:
        self._update_state()

    def _on_queue_updated(self) -> None:
        self._update_state()
        if self.stack.currentIndex() == 1:
            self.history_page.refresh()

    def _update_state(self) -> None:
        tasks = self.store.list_tasks()
        task = self.store.get_task(self.engine.active_task_id) if self.engine.active_task_id else None
        state = self.engine.state
        if task and task.status == TaskStatus.awaiting.value:
            state = "awaiting"
        done = sum(1 for item in tasks if item.status == TaskStatus.done.value)
        if state == "idle" and tasks and done == len(tasks):
            state = "done"
        self.sidebar.set_state(state)
        self.sidebar.set_active_task(task.title if task else "")
        self.sidebar.set_summary(done, len(tasks))
        counts: dict[str, int] = {}
        active_agents: set[str] = set()
        for item in tasks:
            key = item.agent or self.config.agent
            counts[key] = counts.get(key, 0) + 1
            if item.status in (
                TaskStatus.running.value,
                TaskStatus.tool.value,
                TaskStatus.resuming.value,
                TaskStatus.patching.value,
                TaskStatus.validating.value,
            ):
                active_agents.add(key)
        self.sidebar.set_agent_counts(counts, active_agents)

    def _toast(self, message: str, level: str = "info", duration: int = 3200) -> None:
        self.toast.show_message(message, level, duration)

    def reload_for_theme(self, mode: str) -> None:
        """原地换肤：不重建窗口、不重启进程。"""
        from PyQt6.QtWidgets import QWidget

        from . import theme as theme_module

        from PyQt6.QtGui import QCursor

        app = QApplication.instance()
        if app is not None:
            app.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            self.config.theme_mode = mode
            self.store.save_config(self.config)
            theme_module.apply_theme(mode)
            theme_module.refresh_app_stylesheet()
            try:
                self.settings_page._sync_theme_button()
            except Exception:
                pass
            # 不重建列表：卡片是自绘的，换色后重绘即可，重建反而更慢且会丢选中态
            self.centralWidget().update()
        finally:
            if app is not None:
                app.restoreOverrideCursor()

    def _toggle_sidebar(self) -> None:
        collapsed = not self.sidebar.is_collapsed()
        self.sidebar.set_collapsed(collapsed)
        self.collapse_btn.setIcon(
            line_icon("chevron-right" if collapsed else "chevron-down", theme.SUBTLE, 12)
        )

    def _show_help(self) -> None:
        NoticeDialog.present(
            self,
            "操作提示",
            "拖动卡片左侧抓手调整队列顺序；点击卡片查看详情；"
            "粉色圆形按钮开始或暂停队列；顶部输入框回车快速添加任务。",
        )

    def _alert(self, level: str, title: str, body: str) -> None:
        """运行期提示只做轻提示，不弹模态。

        引擎在“会话丢失/无法续传”时会对每个任务发一次警告，
        以前每次都弹一个模态框，跑一批任务就会糊满屏幕。
        需要用户处理的信息已经落在任务状态与详情面板里。
        """
        duration = 5200 if level in ("warning", "error") else 3200
        self._toast(body, "error" if level == "error" else ("warning" if level == "warning" else "info"), duration)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.titleBar.resize(self.width(), self.titleBar.height())

    def eventFilter(self, obj, event) -> bool:
        # QMainWindow's resizeEvent shadows the frameless implementation, so the
        # title bar is sized through an event filter instead.
        if event.type() == QEvent.Type.Resize and obj is self:
            self.titleBar.resize(self.width(), self.titleBar.height())
        return super().eventFilter(obj, event)

    def _place_window(self) -> None:
        saved = self.store.get_setting("window_geometry", "")
        if saved:
            try:
                self.restoreGeometry(QByteArray.fromBase64(saved.encode("ascii")))
                return
            except Exception:
                pass
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - self.width()) // 2,
                geo.y() + (geo.height() - self.height()) // 2,
            )

    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            self.store.set_setting(
                "window_geometry",
                bytes(self.saveGeometry().toBase64()).decode("ascii"),
            )
        except Exception:
            pass
        self.queue_page.shutdown_ui()
        self.engine.shutdown()
        # 退出前停掉所有循环动画，避免定时器在销毁阶段回调
        try:
            self.sidebar.state_dot.set_active(False)
            for row in self.sidebar.nav_rows.values():
                row.stop_animation()
            for row in self.sidebar._agent_rows.values():
                row.stop_animation()
            # 收起所有浮层卡片，避免顶层窗口在销毁阶段回调
            from .action_popover import close_all

            close_all()
        except Exception:
            pass
        super().closeEvent(event)
        # 浮层也是顶层窗口，主窗口关闭后事件循环不会自动退出
        app = QApplication.instance()
        if app is not None:
            app.quit()
        # 浮层（Toast / Popover）也是顶层窗口，主窗口关掉后事件循环不会自动退出
        app = QApplication.instance()
        if app is not None:
            app.quit()

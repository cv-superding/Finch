from __future__ import annotations

import os

from PyQt6.QtCore import (
    QByteArray,
    QEvent,
    QPoint,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QCloseEvent,
    QGuiApplication,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qframelesswindow import FramelessMainWindow
from qfluentwidgets import (
    FluentIcon,
    FluentWidgetTitleBar,
    NavigationPanel,
    ToolTipFilter,
)

from ..agents import ADAPTER_CLASSES
from ..config import AppConfig
from ..models import TaskStatus
from ..store import Store
from . import theme
from .agent_icons import agent_qicon
from .history_page import HistoryPage
from .queue_page import QueuePage
from .settings_page import SettingsPage
from .widgets import ElidedLabel, NoticeDialog, Toast, make_app_icon

NAV_ITEMS = (
    ("queue", FluentIcon.TILES, "任务队列"),
    ("history", FluentIcon.HISTORY, "执行记录"),
    ("settings", FluentIcon.VIEW, "设置"),
)


class Sidebar(QFrame):
    """Navigation rail built on the Fluent NavigationPanel."""

    nav_changed = pyqtSignal(str)
    collapsed_changed = pyqtSignal(bool)
    agent_filter_changed = pyqtSignal(str)

    EXPANDED_WIDTH = 200
    COMPACT_WIDTH = 48

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppSidebar")
        self._agent_filter = ""
        self._agent_labels: dict[str, str] = {}
        self.agent_buttons: dict[str, object] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.panel = NavigationPanel(self)
        self.panel.setExpandWidth(self.EXPANDED_WIDTH)
        self.panel.setCollapsible(True)
        self.panel.setAcrylicEnabled(False)
        root.addWidget(self.panel, 1)

        self.nav_buttons: dict[str, object] = {}
        for key, icon, text in NAV_ITEMS:
            self.nav_buttons[key] = self.panel.addItem(
                key,
                icon,
                text,
                onClick=lambda *_, k=key: self.nav_changed.emit(k),
            )
        self.panel.addItemHeader("Agents")
        for cls in ADAPTER_CLASSES:
            widget = self.panel.addItem(
                f"agent_{cls.key}",
                agent_qicon(cls.key),
                cls.label,
                onClick=lambda *_, k=cls.key: self._on_agent_clicked(k),
            )
            self.agent_buttons[cls.key] = widget
            self._agent_labels[cls.key] = cls.label
        self.panel.setCurrentItem("queue")
        self.panel.displayModeChanged.connect(self._on_display_mode_changed)

        self.status_card = QFrame()
        self.status_card.setObjectName("SidebarStatus")
        card_layout = QVBoxLayout(self.status_card)
        card_layout.setContentsMargins(14, 8, 14, 10)
        card_layout.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(7)
        self.dot = QWidget()
        self.dot.setFixedSize(6, 6)
        top.addWidget(self.dot)
        self.state_label = QLabel("空闲")
        self.state_label.setObjectName("SidebarTitle")
        top.addWidget(self.state_label)
        top.addStretch(1)
        self.count_label = QLabel("0 / 0")
        self.count_label.setObjectName("SidebarMeta")
        top.addWidget(self.count_label)
        card_layout.addLayout(top)
        self.task_label = ElidedLabel("暂无运行任务")
        self.task_label.setObjectName("SidebarText")
        card_layout.addWidget(self.task_label)
        root.addWidget(self.status_card)

        self.set_state("idle")
        self._apply_compact(self.panel.isCollapsed())

    # -- navigation ---------------------------------------------------
    def _on_agent_clicked(self, key: str) -> None:
        new = "" if self._agent_filter == key else key
        self.set_agent_filter(new)
        self.agent_filter_changed.emit(new)

    def set_agent_filter(self, key: str) -> None:
        self._agent_filter = key

    def set_agent_counts(self, counts: dict[str, int]) -> None:
        for key, label in self._agent_labels.items():
            n = counts.get(key, 0)
            self.agent_buttons[key].setToolTip(f"{label} · {n} 条任务" if n else label)

    def set_page(self, key: str) -> None:
        if key in dict((k, 1) for k, _icon, _text in NAV_ITEMS):
            self.panel.setCurrentItem(key)

    # -- state --------------------------------------------------------
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
            "running": theme.ACCENT,
            "paused": theme.ORANGE,
            "stopping": theme.RED,
            "awaiting": theme.VIOLET,
            "done": theme.GREEN,
        }
        self._last_state = state
        color = colors.get(state, theme.SUBTLE)
        self.state_label.setText(labels.get(state, state))
        self.dot.setStyleSheet(f"background: {color}; border-radius: 3px;")

    def set_summary(self, done: int, total: int) -> None:
        self.count_label.setText(f"{done} / {total}")

    def set_active_task(self, title: str) -> None:
        self.task_label.setText(title or "暂无运行任务")
        self.task_label.setToolTip(title)

    # -- collapse -----------------------------------------------------
    def is_collapsed(self) -> bool:
        return self.panel.isCollapsed()

    def set_collapsed(self, collapsed: bool, animate: bool = True, emit: bool = True) -> None:
        if collapsed == self.panel.isCollapsed():
            return
        try:
            self.panel.displayModeChanged.disconnect(self._on_display_mode_changed)
        except TypeError:
            pass
        if collapsed:
            self.panel.collapse()
        else:
            self.panel.expand(useAni=animate)
        self._apply_compact(collapsed)
        try:
            self.panel.displayModeChanged.connect(self._on_display_mode_changed)
        except TypeError:
            pass
        if emit:
            self.collapsed_changed.emit(collapsed)

    def _on_display_mode_changed(self) -> None:
        collapsed = self.panel.isCollapsed()
        self._apply_compact(collapsed)
        self.collapsed_changed.emit(collapsed)

    def _apply_compact(self, compact: bool) -> None:
        self.status_card.setVisible(not compact)


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

        try:
            if os.environ.get("FINCH_NO_MICA") != "1":
                self.windowEffect.setMicaEffect()
        except Exception:
            pass

        title_bar = FluentWidgetTitleBar(self)
        title_bar.setIcon(make_app_icon(64))
        title_bar.setTitle("Finch · Agent 队列")
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
        self.sidebar.nav_changed.connect(self._switch_page)
        self.sidebar.agent_filter_changed.connect(self._on_agent_filter)
        collapsed = self.store.get_setting("sidebar_collapsed", "0") == "1"
        self.sidebar.set_collapsed(collapsed, animate=False, emit=False)
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
        for item in tasks:
            key = item.agent or self.config.agent
            counts[key] = counts.get(key, 0) + 1
        self.sidebar.set_agent_counts(counts)

    def _toast(self, message: str, level: str = "info") -> None:
        self.toast.show_message(message, level)

    def _alert(self, level: str, title: str, body: str) -> None:
        if level == "info":
            self._toast(body, "info")
            return
        old = self._notice
        self._notice = None
        if old is not None:
            try:
                old.finished.disconnect()
                old.close()
            except Exception:
                pass
        self._notice = NoticeDialog.present(self, title, body, level)
        dialog = self._notice
        dialog.finished.connect(lambda _=0: setattr(self, "_notice", None) if self._notice is dialog else None)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.titleBar.resize(self.width(), self.titleBar.height())
        # The panel decides between expanded and menu mode from the window
        # width, so it is re-expanded once the window is actually shown.
        if not self.sidebar.is_collapsed():
            self.sidebar.panel.expand(useAni=False)

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
        super().closeEvent(event)
        self.deleteLater()

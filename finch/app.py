from __future__ import annotations

import ctypes
import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from .config import AppConfig, data_dir
from .core.engine import QueueEngine
from .demo import add_demo_tasks
from .store import Store
from .ui.action_popover import PopoverWatcher
from .ui.main_window import MainWindow
from .ui.theme import STYLESHEET, app_font, apply_theme, font_family

SINGLE_INSTANCE_KEY = "Finch.AgentQueue.singleInstance"


def _set_app_id() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Finch.AgentQueue")
        except Exception:
            pass


def _claim_single_instance() -> QLocalServer | None:
    """Keep one instance at a time.

    Two instances would write the same library config and open a second Mica
    window at the same moment, which crashes the DWM composition.
    """
    probe = QLocalSocket()
    probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(300):
        probe.disconnectFromServer()
        return None
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(SINGLE_INSTANCE_KEY):
        return None
    return server


def _install_exception_hook(app: QApplication) -> None:
    """Never let a slot exception abort the whole app.

    PyQt6 calls ``qFatal`` for unhandled exceptions raised inside slots, which
    kills the process without any chance to report the problem. We log the
    traceback and surface it in the window instead.
    """

    def hook(exc_type, exc_value, exc_tb) -> None:
        import traceback

        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            log_dir = data_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "crash.log").write_text(text, encoding="utf-8")
        except Exception:
            pass
        sys.stderr.write(text)
        try:
            window = app.activeWindow()
            if window is not None and hasattr(window, "toast"):
                window.toast.show_message("界面出错了，详情见日志", "error", 6000)
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    _set_app_id()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    app = QApplication(sys.argv)
    app.setApplicationName("Finch")
    app.setApplicationDisplayName("Finch")
    app.setOrganizationName("Finch")
    app.setStyle("Fusion")
    app.setFont(app_font(10))
    apply_theme()
    app.setStyleSheet(STYLESHEET)

    _install_exception_hook(app)
    app.installEventFilter(PopoverWatcher(app))

    guard = _claim_single_instance()
    if guard is None:
        print("Finch 已在运行，已把焦点交回现有窗口。")
        return 0

    store = Store()
    config = store.load_config()
    store.recover_stale_tasks()
    seeded_now = False
    if not store.list_tasks() and not config.seeded_demo:
        add_demo_tasks(store)
        config.seeded_demo = True
        store.save_config(config)
        seeded_now = True
    engine = QueueEngine(store, config)
    window = MainWindow(store, engine, config)
    window.show()
    if seeded_now:
        QTimer.singleShot(
            700,
            lambda: window.toast.show_message(
                "已载入 3 条示例任务，使用内置示例 Agent。点击「开始队列」即可看完整闭环。",
                "info",
                6500,
            ),
        )
    app.aboutToQuit.connect(engine.shutdown)
    app.aboutToQuit.connect(guard.close)
    return app.exec()

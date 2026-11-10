from __future__ import annotations

import os
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / ".uihome"
if HOME.exists():
    shutil.rmtree(HOME)
HOME.mkdir()
os.environ["FINCH_HOME"] = str(HOME)
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from finch.config import AppConfig, workspaces_dir
from finch.core.engine import QueueEngine
from finch.demo import add_demo_tasks
from finch.store import Store
from finch.ui.editor_dialog import OptimizeDialog, TaskEditorDialog
from finch.ui.main_window import MainWindow
from finch.ui.theme import STYLESHEET, app_font, apply_theme
from finch.models import TaskStatus


OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
TERMINAL = {"done", "failed", "attention", "stopped", "skipped"}


def shot(widget, name):
    QTest.qWait(150)
    if hasattr(widget, "toast"):
        widget.toast.hide()
        QTest.qWait(30)
    widget.grab().save(str(OUT / name))


def main():
    app = QApplication([])
    app.setStyle("Fusion")
    app.setFont(app_font(10))
    apply_theme()
    app.setStyleSheet(STYLESHEET)
    store = Store()
    config = store.load_config()
    config.agent = "mock"
    config.auto_followup = True
    config.confirm_followup = False
    config.text_idle_timeout = 30
    config.first_output_grace = 60
    store.save_config(config)
    tasks = add_demo_tasks(store)
    engine = QueueEngine(store, config)
    window = MainWindow(store, engine, config)
    window.resize(1200, 800)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    QTest.qWait(300)
    shot(window, "01-queue.png")
    window.sidebar.nav_buttons["settings"].click()
    QTest.qWait(200)
    shot(window, "02-settings.png")
    window.sidebar.nav_buttons["queue"].click()
    QTest.qWait(200)

    editor = TaskEditorDialog(window, config, default_cwd=str(workspaces_dir()))
    editor.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    editor.show()
    QTest.qWait(250)
    shot(editor, "05-editor.png")
    editor.close()

    opt = OptimizeDialog(window, config, "帮我做一个待办清单应用，要求好看，功能完整。", "user", "示例任务")
    opt.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    opt.show()
    QTest.qWait(1500)
    shot(opt, "06-optimize.png")
    opt.close()

    engine.start()
    start = time.time()
    captured_running = False
    while time.time() - start < 45:
        QTest.qWait(120)
        current = [store.get_task(t.id) for t in tasks]
        if not captured_running and any(t.status in ("tool", "running", "resuming", "patching") for t in current):
            shot(window, "07-running.png")
            captured_running = True
        if all(t.status in TERMINAL for t in current) and engine.state in ("idle", "paused"):
            break
    QTest.qWait(500)
    shot(window, "08-done.png")
    current = [store.get_task(t.id) for t in tasks]
    for t in current:
        print("TASK", t.title, t.status, "resume", t.resume_count, "followup", t.followup_count, "tools", t.tool_count)
    second = next((t for t in current if t.followup_count), current[0])
    window.queue_page._select_task(second.id)
    QTest.qWait(250)
    shot(window, "04-detail.png")
    window.queue_page.detail._switch_tab("records")
    shot(window, "09-records.png")
    window.queue_page.detail._switch_tab("logs")
    shot(window, "10-logs.png")

    window.sidebar.nav_buttons["history"].click()
    QTest.qWait(250)
    shot(window, "03-history.png")
    window.sidebar.nav_buttons["settings"].click()
    QTest.qWait(250)
    window.settings_page.scroll.verticalScrollBar().setValue(
        window.settings_page.scroll.verticalScrollBar().maximum()
    )
    shot(window, "11-settings-bottom.png")
    print("OK")
    engine.shutdown()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise

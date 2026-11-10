from __future__ import annotations

import os
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / ".extrastates"
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

from finch.config import AppConfig
from finch.core.engine import QueueEngine
from finch.models import Task, TaskStatus
from finch.store import Store
from finch.ui.editor_dialog import OptimizeDialog
from finch.ui.main_window import MainWindow
from finch.ui.theme import STYLESHEET, app_font, apply_theme
from tests.fake_services import start_llm, start_mcp


OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
TERMINAL = {"done", "failed", "attention", "stopped", "skipped"}


def shot(widget, name, wait=200):
    QTest.qWait(wait)
    if hasattr(widget, "toast"):
        widget.toast.hide()
        QTest.qWait(30)
    widget.grab().save(str(OUT / name))


def wait_for(app, predicate, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        QTest.qWait(80)
        if predicate():
            return True
    return False


def main():
    llm_server, _, llm_url = start_llm()
    mcp_server, _, mcp_url = start_mcp()
    app = QApplication([])
    app.setStyle("Fusion")
    app.setFont(app_font(10))
    apply_theme()
    app.setStyleSheet(STYLESHEET)
    store = Store()
    config = store.load_config()
    config.agent = "mock"
    config.auto_followup = True
    config.confirm_followup = True
    config.text_idle_timeout = 3
    config.first_output_grace = 6
    config.tool_timeout = 6
    config.max_resumes = 2
    config.max_followups = 2
    config.optimize_followup = False
    config.analyzer.enabled = False
    config.optimizer.mode = "mcp"
    config.optimizer.mcp_url = mcp_url + "/mcp"
    store.save_config(config)
    cwd = HOME / "workspace"
    cwd.mkdir(parents=True, exist_ok=True)

    task = Task(title="实现待办清单核心交互", prompt="请实现一个待办清单，包含新增、完成、删除。", agent="mock", cwd=str(cwd))
    store.add_task(task)
    engine = QueueEngine(store, config)
    window = MainWindow(store, engine, config)
    window.resize(1200, 800)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    QTest.qWait(200)

    engine.start()
    wait_for(app, lambda: store.get_task(task.id).status == TaskStatus.awaiting.value)
    shot(window, "12-awaiting.png", 400)
    awaiting = store.get_task(task.id)
    print("AWAITING", awaiting.status, "promptlen", len(awaiting.followup_prompt))
    engine.resolve_followup(task.id, "approve", awaiting.followup_prompt + "\n补充：必须运行自测。")
    wait_for(app, lambda: store.get_task(task.id).status in TERMINAL)
    wait_for(app, lambda: engine.state == "idle", 5)
    shot(window, "13-confirm-done.png", 500)

    # Tool execution state + interruption record
    config.confirm_followup = False
    config.tool_timeout = 4
    store.save_config(config)
    engine.update_config(config)
    tool_task = Task(title="依赖安装与构建", prompt="STALL_TOOL 安装依赖并构建项目", agent="mock", cwd=str(cwd))
    store.add_task(tool_task)
    engine.start()
    wait_for(app, lambda: store.get_task(tool_task.id).status == TaskStatus.tool.value, 10)
    window.queue_page._select_task(tool_task.id)
    shot(window, "14-tool-running.png", 250)
    wait_for(app, lambda: store.get_task(tool_task.id).status in TERMINAL, 30)
    wait_for(app, lambda: engine.state == "idle", 5)
    window.queue_page._select_task(tool_task.id)
    window.queue_page.detail._switch_tab("records")
    shot(window, "15-interrupt-records.png", 400)

    # Optimizer through prompt-optimizer MCP
    opt = OptimizeDialog(window, config, "帮我做一个待办清单应用，要求好看，功能完整。", "user", "示例任务")
    opt.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    opt.show()
    wait_for(app, lambda: bool(opt.result_edit.toPlainText().strip()), 15)
    shot(opt, "06-optimize.png", 300)
    print("OPTIMIZED", opt.result_edit.toPlainText()[:80])
    opt.close()

    # Settings data/model section
    window.sidebar.nav_buttons["settings"].click()
    QTest.qWait(200)
    window.settings_page.scroll.verticalScrollBar().setValue(
        int(window.settings_page.scroll.verticalScrollBar().maximum() * 0.55)
    )
    shot(window, "16-settings-model.png", 300)
    print("OK")
    engine.shutdown()
    llm_server.shutdown()
    mcp_server.shutdown()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / ".uitest"
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

from finch.config import workspaces_dir
from finch.core.engine import QueueEngine
from finch.demo import add_demo_tasks
from finch.store import Store
from finch.models import Task
from finch.ui.editor_dialog import AnalysisEditDialog, TaskEditorDialog
from finch.ui.history_page import HistoryDetailDialog
from finch.ui.main_window import MainWindow
from finch.ui.theme import STYLESHEET, app_font, apply_theme
from finch.ui.widgets import ConfirmDialog, NoticeDialog


OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


def shot(widget, name, wait=200):
    QTest.qWait(wait)
    if hasattr(widget, "toast"):
        widget.toast.hide()
        QTest.qWait(30)
    widget.grab().save(str(OUT / name))


def main() -> int:
    app = QApplication([])
    app.setStyle("Fusion")
    app.setFont(app_font(10))
    apply_theme()
    app.setStyleSheet(STYLESHEET)
    store = Store()
    config = store.load_config()
    config.agent = "mock"
    store.save_config(config)
    tasks = add_demo_tasks(store)
    engine = QueueEngine(store, config)
    window = MainWindow(store, engine, config)
    window.resize(1200, 800)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    QTest.qWait(250)
    shot(window, "01-queue.png")
    window.sidebar.set_collapsed(True, animate=False)
    shot(window, "26-sidebar-collapsed.png", 200)
    window.sidebar.set_collapsed(False, animate=False)
    window.queue_page._select_task(tasks[0].id)
    shot(window, "04-detail.png")
    window.sidebar.nav_buttons["history"].click()
    shot(window, "03-history.png")
    window.sidebar.nav_buttons["settings"].click()
    shot(window, "02-settings.png")
    window.settings_page.scroll.verticalScrollBar().setValue(
        window.settings_page.scroll.verticalScrollBar().maximum()
    )
    shot(window, "11-settings-bottom.png")

    window.sidebar.nav_buttons["queue"].click()
    editor = TaskEditorDialog(window, config, default_cwd=str(workspaces_dir()))
    editor.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    editor.show()
    shot(editor, "05-editor.png", 250)
    editor.close()

    confirm = ConfirmDialog(window, "终止队列", "将结束当前 Agent 进程并停止队列。已完成的任务不受影响。", "终止", danger=True)
    confirm.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    confirm.show()
    shot(confirm, "17-confirm.png")
    confirm.close()

    notice = NoticeDialog.present(
        window,
        "需要人工处理",
        "连续中断已达到续传上限。请检查执行记录，修正提示词或工作目录后重试。",
        "warning",
    )
    notice.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    QTest.qWait(150)
    shot(notice, "18-notice.png")
    notice.close()

    history_data = {
        "task_title": "实现待办清单核心交互",
        "status": "done",
        "agent": "mock",
        "ended_at": 1761900000,
        "task": {
            "title": "实现待办清单核心交互",
            "status": "done",
            "agent": "mock",
            "summary": "已完成新增、完成切换与删除，并验证空状态与本地持久化。",
            "completed": ["新增任务", "完成切换", "删除任务", "空状态展示"],
            "pending": ["键盘快捷键"],
            "issues": ["未在移动端视口验证"],
        },
        "runs": [
            {"kind": "main", "round": 0, "status": "completed", "started_at": 1761899900, "ended_at": 1761899999, "reason": "下发主任务", "output": "已完成：新增任务\n已完成：完成切换\n未完成：键盘快捷键"},
            {"kind": "resume", "round": 1, "status": "completed", "started_at": 1761899900, "ended_at": 1761899950, "reason": "文本空闲超时后续传", "output": "继续执行剩余验收项。"},
        ],
    }
    detail = HistoryDetailDialog(window, history_data)
    detail.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    detail.show()
    shot(detail, "19-history-detail.png", 250)
    detail.close()

    analysis_task = Task(
        title="实现待办清单核心交互",
        summary="已完成新增、完成切换与删除，并验证空状态与本地持久化。",
        completed=["新增任务", "完成切换"],
        pending=["键盘快捷键"],
        issues=["未在移动端视口验证"],
    )
    analysis = AnalysisEditDialog(window, analysis_task)
    analysis.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    analysis.show()
    shot(analysis, "20-analysis-edit.png", 250)
    analysis.close()

    window.resize(1080, 700)
    window.sidebar.nav_buttons["queue"].click()
    QTest.qWait(200)
    shot(window, "21-queue-min.png", 250)
    window.sidebar.nav_buttons["settings"].click()
    window.settings_page.scroll.verticalScrollBar().setValue(0)
    QTest.qWait(200)
    shot(window, "22-settings-min.png", 250)
    window.sidebar.nav_buttons["history"].click()
    shot(window, "23-history-min.png", 250)

    window.resize(1200, 800)
    for task in store.list_tasks():
        store.delete_task(task.id)
    window._update_state()
    window.sidebar.nav_buttons["queue"].click()
    window.queue_page.refresh(force=True)
    shot(window, "24-empty-queue.png", 250)
    window.sidebar.nav_buttons["history"].click()
    shot(window, "25-empty-history.png", 250)
    engine.shutdown()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

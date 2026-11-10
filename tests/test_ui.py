from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from finch.core.engine import QueueEngine
from finch.demo import add_demo_tasks
from finch.models import Run, Task, TaskStatus
from finch.store import Store
from finch.ui.action_popover import ActionPopover
from finch.ui.editor_dialog import AnalysisEditDialog, TaskEditorDialog
from finch.ui.main_window import MainWindow
from finch.ui.theme import STYLESHEET, app_font, apply_theme


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setFont(app_font(10))
        cls.app.setStyleSheet(STYLESHEET)

    def setUp(self):
        self.old_home = os.environ.get("FINCH_HOME")
        self.home = Path(tempfile.mkdtemp(prefix="finch-ui-"))
        os.environ["FINCH_HOME"] = str(self.home)
        self.store = Store()
        self.config = self.store.load_config()
        self.config.agent = "mock"
        self.config.auto_followup = True
        self.config.confirm_followup = False
        self.store.save_config(self.config)
        self.tasks = add_demo_tasks(self.store)
        self.engine = QueueEngine(self.store, self.config)
        self.window = MainWindow(self.store, self.engine, self.config)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.show()
        QTest.qWait(80)

    def tearDown(self):
        try:
            self.window.close()
        except Exception:
            pass
        try:
            self.engine.shutdown()
        except Exception:
            pass
        QTest.qWait(30)
        if self.old_home is None:
            os.environ.pop("FINCH_HOME", None)
        else:
            os.environ["FINCH_HOME"] = self.old_home
        shutil.rmtree(self.home, ignore_errors=True)

    def test_sidebar_collapse_and_navigation(self):
        sidebar = self.window.sidebar
        QTest.qWait(400)
        self.assertEqual(sidebar.width(), sidebar.EXPANDED_WIDTH)
        sidebar.set_collapsed(True, animate=False)
        QTest.qWait(400)
        self.assertTrue(sidebar.is_collapsed())
        self.assertLess(sidebar.width(), sidebar.EXPANDED_WIDTH)
        self.assertTrue(sidebar.status_card.isHidden())
        self.assertEqual(self.store.get_setting("sidebar_collapsed"), "1")
        sidebar.set_collapsed(False, animate=False)
        QTest.qWait(400)
        self.assertFalse(sidebar.is_collapsed())
        self.assertEqual(sidebar.width(), sidebar.EXPANDED_WIDTH)
        self.assertFalse(sidebar.status_card.isHidden())
        self.assertEqual(self.store.get_setting("sidebar_collapsed"), "0")
        sidebar.nav_buttons["history"].click()
        QTest.qWait(30)
        self.assertEqual(self.window.stack.currentIndex(), 1)
        sidebar.nav_buttons["settings"].click()
        QTest.qWait(30)
        self.assertEqual(self.window.stack.currentIndex(), 2)
        sidebar.nav_buttons["queue"].click()
        QTest.qWait(30)
        self.assertEqual(self.window.stack.currentIndex(), 0)

    def test_task_detail_tabs_and_close(self):
        page = self.window.queue_page
        task = self.store.list_tasks()[1]
        page._select_task(task.id)
        self.assertEqual(page.detail.task_id, task.id)
        self.assertIs(page.rail_stack.currentWidget(), page.detail)
        self.assertFalse(page.detail.isHidden())
        page.detail._switch_tab("records")
        self.assertEqual(page.detail.stack.currentIndex(), 1)
        page.detail._switch_tab("logs")
        self.assertEqual(page.detail.stack.currentIndex(), 2)
        page.detail._switch_tab("summary")
        self.assertEqual(page.detail.stack.currentIndex(), 0)
        page._detail_closed()
        self.assertIs(page.rail_stack.currentWidget(), page.overview)

    def test_reorder_and_delete(self):
        page = self.window.queue_page
        original = self.store.list_tasks()
        page._apply_reorder(original[0].id, len(original))
        reordered = self.store.list_tasks()
        self.assertEqual(reordered[-1].id, original[0].id)
        target = original[1].id
        with patch("finch.ui.queue_page.ConfirmDialog.ask", return_value=True):
            page._delete_task(target)
        self.assertIsNone(self.store.get_task(target))
        self.assertEqual(len(self.store.list_tasks()), len(original) - 1)

    def test_settings_save(self):
        settings = self.window.settings_page
        settings.reload()
        settings.text_timeout.setValue(19)
        settings.max_followup.setValue(5)
        settings.auto_followup.setChecked(False)
        settings.save()
        saved = self.store.load_config()
        self.assertEqual(saved.text_idle_timeout, 19)
        self.assertEqual(saved.max_followups, 5)
        self.assertFalse(saved.auto_followup)
        self.assertEqual(self.engine.config.text_idle_timeout, 19)
        self.assertIn("已保存", settings.save_status.text())

    def test_editor_and_analysis_dialogs(self):
        editor = TaskEditorDialog(self.window, self.config)
        editor.prompt_edit.setPlainText("请实现一个新功能并添加测试")
        editor._save()
        self.assertIsNotNone(editor.result_task)
        self.assertEqual(editor.result_task.prompt, "请实现一个新功能并添加测试")
        self.assertTrue(editor.result_task.title.startswith("请实现一个新功能"))

        task = self.store.list_tasks()[0]
        edit = TaskEditorDialog(self.window, self.config, task=task)
        edit.prompt_edit.setPlainText("更新后的主提示词")
        edit._save()
        self.assertIsNotNone(edit.result_task)
        self.assertEqual(edit.result_task.prompt, "更新后的主提示词")

        task.summary = "旧摘要"
        analysis = AnalysisEditDialog(self.window, task)
        analysis.summary_edit.setPlainText("新摘要")
        analysis.completed_edit.setPlainText(chr(10).join(["完成 A", "完成 B"]))
        analysis.pending_edit.setPlainText("未完成 C")
        analysis.issues_edit.setPlainText("风险 D")
        result = analysis.result_data()
        self.assertEqual(result.summary, "新摘要")
        self.assertEqual(result.completed, ["完成 A", "完成 B"])
        self.assertEqual(result.pending, ["未完成 C"])
        self.assertTrue(result.needs_followup)
        self.assertTrue(analysis.use_as_feedback())

    def test_history_refresh_and_export(self):
        task = Task(
            title="历史导出",
            prompt="p",
            agent="mock",
            status=TaskStatus.done.value,
            started_at=100,
            ended_at=200,
            summary="历史摘要",
        )
        self.store.add_task(task)
        log_path = self.home / "run.log"
        log_path.write_text("完整日志内容", encoding="utf-8")
        run = Run(
            task_id=task.id,
            kind="main",
            status="completed",
            started_at=100,
            ended_at=200,
            output="输出内容",
            log_path=str(log_path),
        )
        self.store.add_run(run)
        self.store.archive_task(task)
        self.window.history_page.refresh()
        self.assertEqual(self.window.history_page.count_chip.text(), "1 条")
        data = self.store.get_history(task.id)
        target = self.home / "export.json"
        with patch(
            "finch.ui.history_page.QFileDialog.getSaveFileName",
            return_value=(str(target), ""),
        ):
            self.window.history_page._export_one(data, "历史导出")
        self.assertTrue(target.exists())
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["task"]["summary"], "历史摘要")
        self.assertIn(run.id, payload["logs"])
        self.assertIn("完整日志内容", payload["logs"][run.id])

    def test_ui_run_one_task(self):
        for task in self.store.list_tasks():
            self.store.delete_task(task.id)
        self.window.queue_page.refresh(force=True)
        task = self.store.add_task(
            Task(title="UI 启动任务", prompt="请梳理一个待办清单的验收标准。", agent="mock")
        )
        self.window.queue_page.refresh(force=True)
        self.window.queue_page._toggle_run()
        deadline = time.time() + 25
        while time.time() < deadline:
            QTest.qWait(120)
            current = self.store.get_task(task.id)
            if current and current.status in (TaskStatus.done.value, TaskStatus.failed.value, TaskStatus.attention.value):
                break
        current = self.store.get_task(task.id)
        self.assertEqual(current.status, TaskStatus.done.value)
        deadline = time.time() + 5
        while time.time() < deadline and self.engine.state != "idle":
            QTest.qWait(100)
        self.assertEqual(self.engine.state, "idle")
        deadline = time.time() + 5
        while time.time() < deadline and self.window.queue_page.run_btn.text() != "开始队列":
            QTest.qWait(50)
        self.assertEqual(self.window.queue_page.run_btn.text(), "开始队列")



    def test_action_popovers_open_without_crashing(self):
        """Every row/card action surface must open without killing the process."""
        page = self.window.queue_page
        card = next(iter(page.board.columns["todo"].cards.values()))
        row = next(iter(page.queue_list.rows.values()))
        column = page.board.columns["todo"]
        openers = (
            card._open_menu,
            row._open_menu,
            column._open_menu,
            page._open_columns_menu,
            page._choose_cwd,
        )
        for opener in openers:
            opener()
            QTest.qWait(60)
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, QWidget) and widget.parent() is self.window:
                    widget.hide()
        QTest.qWait(60)

        def popover_count() -> int:
            return len([w for w in self.window.findChildren(ActionPopover)])

        baseline = popover_count()
        for _ in range(3):
            for opener in openers:
                opener()
                QTest.qWait(40)
        self.assertEqual(popover_count(), baseline)


    def test_task_export_payload(self):
        task = self.store.list_tasks()[0]
        log_path = self.home / "detail.log"
        log_path.write_text("detail log", encoding="utf-8")
        run = Run(
            task_id=task.id,
            kind="main",
            status="completed",
            started_at=1,
            ended_at=2,
            output="detail output",
            log_path=str(log_path),
        )
        self.store.add_run(run)
        target = self.home / "task-export.json"
        from finch.ui.detail_panel import export_task

        with patch(
            "finch.ui.detail_panel.QFileDialog.getSaveFileName",
            return_value=(str(target), ""),
        ):
            export_task(self.window, self.store, task)
        self.assertTrue(target.exists())
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["app"], "Finch")
        self.assertEqual(payload["task"]["id"], task.id)
        self.assertIn(run.id, payload["logs"])
        self.assertIn("detail log", payload["logs"][run.id])


    def test_board_columns_and_filter(self):
        page = self.window.queue_page
        tasks = self.store.list_tasks()
        tasks[0].status = TaskStatus.queued.value
        tasks[1].status = TaskStatus.running.value
        tasks[2].status = TaskStatus.done.value
        for task in tasks:
            self.store.save_task(task)
        extra = self.store.add_task(
            Task(title="待确认项", prompt="p", agent="mock", status=TaskStatus.awaiting.value)
        )
        page.refresh(force=True)
        board = page.board
        self.assertEqual(board.columns["todo"].count.text(), "1")
        self.assertEqual(board.columns["progress"].count.text(), "1")
        self.assertEqual(board.columns["review"].count.text(), "1")
        self.assertEqual(board.columns["done"].count.text(), "1")
        self.assertIn(extra.id, board.columns["review"].cards)
        page._set_view(1)
        self.assertIs(page.view_stack.currentWidget(), page.scroll)
        page._set_view(0)
        self.assertIs(page.view_stack.currentWidget(), board)
        page.set_agent_filter("claude")
        self.assertTrue(page.filter_chip.isVisible())
        self.assertEqual(board.columns["todo"].count.text(), "0")
        page.set_agent_filter("")
        self.assertFalse(page.filter_chip.isVisible())
        self.assertEqual(board.columns["todo"].count.text(), "1")

    def test_autopilot_dialog_states(self):
        from finch.ui.autopilot_dialog import AutopilotDialog

        page = self.window.queue_page
        dialog = AutopilotDialog(self.window, self.config, self.engine)
        self.assertFalse(dialog.config_view.isHidden())
        self.assertFalse(dialog.start_btn.isHidden())
        self.assertTrue(dialog.run_view.isHidden())
        self.engine._autopilot.update(active=True, rounds_used=2, max_rounds=5, rounds=[])
        dialog.refresh()
        self.assertFalse(dialog.run_view.isHidden())
        self.assertFalse(dialog.stop_btn.isHidden())
        self.assertEqual(dialog.state_chip.text(), "自动 2/5")
        self.assertEqual(page.autopilot_btn.text(), "自动驾驶")
        page._update_autopilot_btn()
        self.assertEqual(page.autopilot_btn.text(), "自动 2/5")
        self.engine._autopilot.update(active=False, resumable=True)
        dialog.refresh()
        self.assertFalse(dialog.resume_btn.isHidden())
        page._update_autopilot_btn()
        self.assertEqual(page.autopilot_btn.text(), "继续自动")
        self.engine._autopilot.update(active=False, resumable=False)
        dialog.deleteLater()
        QTest.qWait(30)


if __name__ == "__main__":
    unittest.main()

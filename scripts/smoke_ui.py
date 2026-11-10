from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from finch.config import AppConfig
from finch.core.engine import QueueEngine
from finch.demo import add_demo_tasks
from finch.store import Store
from finch.ui.main_window import MainWindow
from finch.ui.theme import STYLESHEET, app_font, apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(app_font(10))
    apply_theme()
    app.setStyleSheet(STYLESHEET)
    store = Store()
    config = store.load_config()
    if not store.list_tasks():
        add_demo_tasks(store)
        config.seeded_demo = True
        store.save_config(config)
    engine = QueueEngine(store, config)
    window = MainWindow(store, engine, config)
    window.resize(1240, 840)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    app.processEvents()
    out = ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(out / "01-queue.png"))
    window.sidebar.nav_buttons["settings"].click()
    app.processEvents()
    window.grab().save(str(out / "02-settings.png"))
    window.sidebar.nav_buttons["history"].click()
    app.processEvents()
    window.grab().save(str(out / "03-history.png"))
    window.sidebar.nav_buttons["queue"].click()
    app.processEvents()
    window.queue_page._select_task(store.list_tasks()[0].id)
    app.processEvents()
    window.grab().save(str(out / "04-detail.png"))
    print("OK", window.size().width(), window.size().height())
    engine.shutdown()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise

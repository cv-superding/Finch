from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class EngineSignals(QObject):
    task_updated = pyqtSignal(str)
    queue_updated = pyqtSignal()
    run_updated = pyqtSignal(str, str)
    log_line = pyqtSignal(str, str)
    alert = pyqtSignal(str, str, str)  # level, title, body
    toast = pyqtSignal(str, str)  # message, level
    state_changed = pyqtSignal(str)
    awaiting = pyqtSignal(str)
    autopilot_updated = pyqtSignal()

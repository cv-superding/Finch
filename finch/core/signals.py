from __future__ import annotations

try:
    from PyQt6.QtCore import QObject, pyqtSignal
except ImportError:
    # Web UI / 独立打包的后端不装 Qt：提供同接口的轻量信号对象，
    # 这样 QueueEngine 不需要为了 200MB 的 PyQt6 才能起步。
    class QObject:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass

    class _Signal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def disconnect(self, slot=None):
            if slot is None:
                self._slots.clear()
            elif slot in self._slots:
                self._slots.remove(slot)

        def emit(self, *args):
            for slot in list(self._slots):
                try:
                    slot(*args)
                except Exception:
                    pass

    class pyqtSignal:  # type: ignore[no-redef]
        def __init__(self, *types, **kwargs):
            self.name = None

        def __set_name__(self, owner, name):
            self.name = name

        def __get__(self, instance, owner=None):
            if instance is None:
                return self
            store = instance.__dict__.setdefault("_finch_signals", {})
            key = self.name or id(self)
            if key not in store:
                store[key] = _Signal()
            return store[key]


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

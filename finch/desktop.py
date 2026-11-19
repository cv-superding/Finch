"""Finch 桌面端：本地服务 + WebView2 窗口（无边框，标题栏与页面融为一体）。"""
from __future__ import annotations

import ctypes
import socket
import threading
import time
import urllib.error
import urllib.request

from .webui import server as web

PREFERRED_PORT = 8766

# Win32 常量
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2
_RESIZE_CODES = {
    "left": 10,
    "right": 11,
    "top": 12,
    "topleft": 13,
    "topright": 14,
    "bottom": 15,
    "bottomleft": 16,
    "bottomright": 17,
}


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _is_finch(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=0.6) as res:
            return res.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _pick_port(start: int = PREFERRED_PORT, attempts: int = 20) -> int:
    for port in range(start, start + attempts):
        if not _port_open(port):
            return port
    raise RuntimeError("找不到可用端口")


class Api:
    """暴露给页面：原生拖拽、八向缩放、窗口按钮。"""

    def __init__(self) -> None:
        self._window = None

    def _hwnd(self) -> int:
        user32 = ctypes.windll.user32
        try:
            native = self._window.native
            handle = native.Handle
            return int(handle.ToInt64()) if hasattr(handle, "ToInt64") else int(handle)
        except Exception:
            return int(user32.FindWindowW(None, "Finch") or 0)

    def _native_move(self, code: int) -> None:
        hwnd = self._hwnd()
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        user32.ReleaseCapture()
        user32.PostMessageW(hwnd, WM_NCLBUTTONDOWN, code, 0)

    # -- 拖拽 / 缩放 -------------------------------------------------
    def start_drag(self) -> None:
        self._native_move(HTCAPTION)

    def start_resize(self, edge: str) -> None:
        self._native_move(_RESIZE_CODES.get(str(edge), 11))

    # -- 窗口按钮 -----------------------------------------------------
    def minimize(self) -> None:
        self._native_move(0)  # 占位，避免空调用
        if self._window is not None:
            self._window.minimize()

    def toggle_max(self) -> None:
        hwnd = self._hwnd()
        if hwnd:
            user32 = ctypes.windll.user32
            if user32.IsZoomed(hwnd):
                user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            else:
                user32.ShowWindow(hwnd, 3)   # SW_MAXIMIZE

    def close(self) -> None:
        if self._window is not None:
            self._window.destroy()


def main() -> int:
    import webview

    port = PREFERRED_PORT
    owned = True
    if _port_open(port) and _is_finch(port):
        owned = False
    else:
        port = _pick_port()
        web.start_server(port=port)
        deadline = time.time() + 8
        while time.time() < deadline and not _is_finch(port):
            time.sleep(0.15)

    api = Api()
    window = webview.create_window(
        "Finch",
        f"http://127.0.0.1:{port}/?shell=1",
        width=1500,
        height=940,
        min_size=(1180, 720),
        background_color="#F6F3EC",
        js_api=api,
    )
    api._window = window

    # 花笺是浅色纸张主题，系统标题栏保持系统默认，不再刷成旧界面的深色
    try:
        webview.start()
    finally:
        if owned:
            web.shutdown_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLLMHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    last_user = ""

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
        messages = payload.get("messages") or []
        system = messages[0].get("content", "") if messages else ""
        user = messages[1].get("content", "") if len(messages) > 1 else ""
        type(self).last_user = user
        if "Reply with OK" in user:
            content = "OK"
        elif "AI 编程任务验收员" in system:
            content = json.dumps(
                {
                    "summary": "实现待办清单核心交互，仍有缺漏",
                    "completed": ["实现新增与删除"],
                    "pending": ["空状态提示未实现"],
                    "issues": ["小屏布局横向溢出"],
                    "needs_followup": True,
                },
                ensure_ascii=False,
            )
        elif "提示词工程师" in system:
            content = "【优化结果】目标：实现待办清单\n验收标准：新增、完成、删除全部可用；空状态有提示；移动端不溢出。"
        else:
            content = "OK"
        body = json.dumps(
            {
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"total_tokens": 10},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FakeMCPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls: list[tuple[str, dict]] = []

    def log_message(self, *args):
        pass

    def _send(self, payload, status=200, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Mcp-Session-Id", "fake-session")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        payload = json.loads(raw)
        method = payload.get("method")
        if method == "initialize":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-prompt-optimizer", "version": "1.0"},
                    },
                }
            )
            return
        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Mcp-Session-Id", "fake-session")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "tools/list":
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {
                        "tools": [
                            {"name": "optimize-user-prompt"},
                            {"name": "optimize-system-prompt"},
                            {"name": "iterate-prompt"},
                        ]
                    },
                }
            )
            return
        if method == "tools/call":
            params = payload.get("params") or {}
            name = params.get("name", "")
            args = params.get("arguments") or {}
            type(self).calls.append((name, args))
            text = (
                "目标：交付一个可直接验证的结果，界面简洁、功能完整。\n\n"
                "原始要求：" + str(args.get("prompt", ""))[:200] + "\n\n"
                "执行要求：\n"
                "1. 明确输入、输出与边界条件；\n"
                "2. 补齐空状态、错误处理与键盘操作；\n"
                "3. 完成后自检并列出验收证据。"
            )
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": {"content": [{"type": "text", "text": text}], "isError": False},
                }
            )
            return
        self._send(
            {"jsonrpc": "2.0", "id": payload.get("id"), "error": {"code": -32601, "message": "unknown"}},
            status=200,
        )


def start_server(handler) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def start_llm() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    return start_server(FakeLLMHandler)


def start_mcp() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    return start_server(FakeMCPHandler)


class FakeMCPSseHandler(FakeMCPHandler):
    def _send(self, payload, status=200, headers=None):
        body = ("event: message\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Mcp-Session-Id", "fake-session-sse")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def start_mcp_sse() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    return start_server(FakeMCPSseHandler)

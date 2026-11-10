from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..config import ANALYZER_SYSTEM, OPTIMIZER_SYSTEM, AppConfig, LLMConfig
from .llm import LLMError, chat_completion


class OptimizerError(RuntimeError):
    pass


@dataclass
class OptimizeResult:
    text: str
    engine: str
    note: str = ""


class MCPClient:
    def __init__(self, url: str, timeout: int = 20):
        self.url = url
        self.timeout = timeout
        self.session_id = ""
        self.protocol_version = "2025-03-26"
        self._next_id = 1

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol_version,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload: dict[str, Any], expect_response: bool = True) -> dict[str, Any] | None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                session = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
                if session:
                    self.session_id = session
                body = resp.read().decode("utf-8", errors="replace")
                content_type = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            raise OptimizerError(f"prompt-optimizer MCP HTTP {exc.code}: {body}") from exc
        except Exception as exc:
            raise OptimizerError(f"无法连接 prompt-optimizer MCP：{exc}") from exc
        if not expect_response:
            return None
        if not body.strip():
            return None
        if "text/event-stream" in content_type or body.lstrip().startswith(("event:", "data:")):
            candidates = []
            for line in body.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk and chunk != "[DONE]":
                        try:
                            candidates.append(json.loads(chunk))
                        except Exception:
                            continue
            for item in reversed(candidates):
                if isinstance(item, dict) and ("result" in item or "error" in item):
                    return item
            raise OptimizerError("MCP 返回了无法解析的 SSE 数据")
        try:
            parsed = json.loads(body)
        except Exception as exc:
            raise OptimizerError(f"MCP 响应不是 JSON：{body[:300]}") from exc
        if not isinstance(parsed, dict):
            raise OptimizerError("MCP 响应格式错误")
        return parsed

    def initialize(self) -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "Finch", "version": "0.1.0"},
            },
        }
        self._next_id += 1
        response = self._post(payload)
        if not response or "error" in response:
            raise OptimizerError(f"初始化失败：{response}")
        version = (response.get("result") or {}).get("protocolVersion")
        if version:
            self.protocol_version = str(version)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": "tools/list", "params": {}}
        self._next_id += 1
        response = self._post(payload)
        if not response or "error" in response:
            raise OptimizerError(f"获取工具列表失败：{response}")
        return list((response.get("result") or {}).get("tools") or [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        self.initialize()
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        self._next_id += 1
        response = self._post(payload)
        if not response:
            raise OptimizerError("MCP 未返回结果")
        if "error" in response:
            err = response["error"]
            raise OptimizerError(f"MCP 调用失败：{err.get('message') if isinstance(err, dict) else err}")
        result = response.get("result") or {}
        if result.get("isError"):
            raise OptimizerError(_content_text(result) or "MCP 工具返回错误")
        text = _content_text(result)
        if not text:
            structured = result.get("structuredContent")
            if structured:
                text = json.dumps(structured, ensure_ascii=False)
        if not text:
            raise OptimizerError("MCP 返回了空结果")
        return text.strip()


def _content_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif "text" in item:
                    parts.append(str(item.get("text") or ""))
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, str):
        return content.strip()
    return ""


class PromptOptimizer:
    def __init__(self, config: AppConfig):
        self.config = config

    def _builtin_config(self) -> LLMConfig:
        opt = self.config.optimizer
        if opt.use_optimizer_model and opt.llm_ready:
            return LLMConfig(
                enabled=True,
                base_url=opt.base_url,
                api_key=opt.api_key,
                model=opt.model,
                temperature=0.4,
                timeout=self.config.analyzer.timeout,
            )
        analyzer = self.config.analyzer
        return LLMConfig(
            enabled=True,
            base_url=analyzer.base_url,
            api_key=analyzer.api_key,
            model=analyzer.model,
            temperature=0.4,
            timeout=analyzer.timeout,
        )

    def _optimize_mcp(self, prompt: str, kind: str) -> str:
        url = self.config.optimizer.mcp_url.strip()
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            raise OptimizerError("prompt-optimizer MCP 地址无效")
        try:
            with socket.create_connection((host, port), timeout=0.45):
                pass
        except OSError as exc:
            raise OptimizerError(f"prompt-optimizer MCP 未启动：{host}:{port}") from exc
        client = MCPClient(url, timeout=20)
        tool = "optimize-system-prompt" if kind == "system" else "optimize-user-prompt"
        args: dict[str, Any] = {"prompt": prompt}
        if self.config.optimizer.template and self.config.optimizer.template != "general":
            args["template"] = self.config.optimizer.template
        return client.call_tool(tool, args)

    def _optimize_builtin(self, prompt: str, kind: str) -> str:
        llm = self._builtin_config()
        if not llm.ready:
            raise OptimizerError("未配置优化模型，且 prompt-optimizer MCP 不可用")
        label = "系统提示词" if kind == "system" else "用户提示词"
        user = f"请优化以下{label}：\n\n{prompt}"
        try:
            return chat_completion(llm, OPTIMIZER_SYSTEM, user, temperature=0.4)
        except LLMError as exc:
            raise OptimizerError(str(exc)) from exc

    def optimize(self, prompt: str, kind: str = "user") -> OptimizeResult:
        prompt = (prompt or "").strip()
        if not prompt:
            raise OptimizerError("提示词为空")
        mode = (self.config.optimizer.mode or "auto").lower()
        if mode == "off":
            return OptimizeResult(prompt, "off", "提示词优化已关闭")
        errors: list[str] = []
        if mode in ("auto", "mcp"):
            try:
                text = self._optimize_mcp(prompt, kind)
                return OptimizeResult(text, "prompt-optimizer MCP", "已通过 prompt-optimizer MCP 优化")
            except Exception as exc:
                errors.append(str(exc))
                if mode == "mcp":
                    raise OptimizerError(errors[-1]) from exc
        if mode in ("auto", "builtin"):
            try:
                text = self._optimize_builtin(prompt, kind)
                return OptimizeResult(text, "builtin LLM", "MCP 不可用，已用内置优化器")
            except Exception as exc:
                errors.append(str(exc))
                raise OptimizerError("；".join(errors)) from exc
        raise OptimizerError("未知的优化模式")

    def test_mcp(self) -> tuple[bool, str]:
        try:
            client = MCPClient(self.config.optimizer.mcp_url.strip(), timeout=8)
            tools = client.list_tools()
            names = {tool.get("name") for tool in tools}
            needed = {"optimize-user-prompt", "optimize-system-prompt"}
            if needed & names:
                return True, f"已连接，可用工具：{', '.join(sorted(names))[:160]}"
            return False, f"已连接，但未发现优化工具：{', '.join(sorted(str(n) for n in names))[:160]}"
        except Exception as exc:
            return False, str(exc)


# Re-export so analyzer-ish callers can reuse the same system prompt constant if needed.
__all__ = ["PromptOptimizer", "OptimizeResult", "OptimizerError", "MCPClient", "ANALYZER_SYSTEM"]

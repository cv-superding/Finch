from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import LLMConfig


class LLMError(RuntimeError):
    pass


def chat_completion(
    config: LLMConfig,
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    timeout: int | None = None,
) -> str:
    if not config.base_url.strip() or not config.model.strip():
        raise LLMError("未配置解析模型（Base URL / Model）")
    base = config.base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        url = base
    else:
        url = base + "/chat/completions"
    payload = {
        "model": config.model.strip(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": config.temperature if temperature is None else temperature,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key.strip():
        headers["Authorization"] = f"Bearer {config.api_key.strip()}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout or config.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        raise LLMError(f"HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise LLMError(f"请求失败：{exc}") from exc
    try:
        parsed = json.loads(raw)
        content = parsed["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        return str(content or "").strip()
    except Exception as exc:
        raise LLMError(f"响应解析失败：{raw[:300]}") from exc


def test_llm(config: LLMConfig) -> tuple[bool, str]:
    try:
        reply = chat_completion(
            config,
            "You reply with exactly one word.",
            "Reply with OK.",
            temperature=0,
            timeout=30,
        )
        return True, reply[:80] or "连接成功"
    except Exception as exc:
        return False, str(exc)

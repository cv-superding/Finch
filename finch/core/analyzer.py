from __future__ import annotations

import json
import re
from typing import Any

from ..config import ANALYZER_SYSTEM, AppConfig
from ..models import AnalysisResult
from .llm import LLMError, chat_completion


COMPLETED_WORDS = ("已完成", "完成清单", "完成项", "完成情况", "completed", "done")
PENDING_WORDS = ("未完成", "待完成", "待办", "剩余", "遗留", "下一步", "todo", "pending", "remaining", "未实现")
ISSUE_WORDS = ("已知问题", "问题", "风险", "bug", "issue", "待优化", "注意事项", "caveat")
EMPTY_WORDS = {"无", "无。", "没有", "暂无", "none", "n/a", "na", "no", "0"}

BULLET_RE = re.compile(r"^\s*(?:[-*+•·]|\d+[.)、])\s*")
CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*")
HEADING_CLEAN_RE = re.compile(r"^[\s#>*_`]+|[\s*_`#]+$")


def clean_inline(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = text.strip(" -_*#>·•\t")
    return text


def is_heading_like(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("#"):
        return True
    raw = clean_inline(stripped)
    if not raw:
        return False
    normalized = raw.lower().replace("：", ":")
    if normalized.endswith(":"):
        return True
    if len(normalized) <= 14 and not re.search(r"[，。；！？,;!?]", normalized):
        return True
    return False


def classify_heading(line: str) -> str:
    if not is_heading_like(line):
        return ""
    raw = clean_inline(line)
    normalized = raw.lower().replace("：", ":").strip()
    if any(word in normalized for word in PENDING_WORDS):
        return "pending"
    if any(word in normalized for word in ISSUE_WORDS):
        return "issues"
    if any(word in normalized for word in COMPLETED_WORDS):
        return "completed"
    return ""


def split_heading_content(line: str) -> tuple[str, str]:
    stripped = clean_inline(line)
    for sep in ("：", ":"):
        if sep in stripped:
            left, right = stripped.split(sep, 1)
            kind = classify_heading(left + sep)
            if kind:
                return kind, right.strip()
    return classify_heading(stripped), ""


def clean_items(raw: str) -> list[str]:
    items: list[str] = []
    for line in raw.splitlines():
        original = line.strip()
        if not original:
            continue
        bullet = bool(BULLET_RE.match(original) or CHECKBOX_RE.match(original))
        line = CHECKBOX_RE.sub("", original)
        line = BULLET_RE.sub("", line)
        line = clean_inline(line)
        if not line:
            continue
        low = line.lower().strip(".。")
        if low in EMPTY_WORDS:
            continue
        if not bullet:
            if len(line) > 90:
                continue
            if line.endswith(("。", "！", "？", ".", "!", "?")):
                continue
        if len(line) > 400:
            line = line[:400].rstrip() + "…"
        items.append(line)
    return items


def extract_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"completed": [], "pending": [], "issues": []}
    current = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if current:
            for item in clean_items("\n".join(buffer)):
                if len(sections[current]) < 30:
                    sections[current].append(item)
        buffer = []

    for line in (text or "").splitlines():
        if BULLET_RE.match(line) or CHECKBOX_RE.match(line):
            if current:
                buffer.append(line)
            continue
        kind, inline = split_heading_content(line)
        if kind:
            flush()
            current = kind
            if inline:
                buffer.append(inline)
            continue
        if is_heading_like(line) and not CHECKBOX_RE.match(line) and not BULLET_RE.match(line):
            flush()
            current = ""
            continue
        if current:
            buffer.append(line)
    flush()
    return sections


def find_inline_items(text: str, keywords: tuple[str, ...]) -> list[str]:
    items: list[str] = []
    for line in (text or "").splitlines():
        stripped = clean_inline(line)
        if not stripped:
            continue
        for keyword in keywords:
            match = re.search(rf"{re.escape(keyword)}\s*[：:]\s*(.+)", stripped, re.IGNORECASE)
            if match:
                value = clean_inline(match.group(1))
                if value.lower().strip(".。") not in EMPTY_WORDS:
                    items.append(value)
                break
    return items


def make_summary(text: str, result: AnalysisResult) -> str:
    body = (text or "").strip()
    if not body:
        return "未返回内容"
    lines = []
    in_code = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        if classify_heading(stripped) and len(stripped) < 30:
            continue
        if re.fullmatch(r"[-*+•·]\s*", stripped):
            continue
        cleaned = clean_inline(stripped)
        if not cleaned or cleaned.lower().strip(".。") in EMPTY_WORDS:
            continue
        if CHECKBOX_RE.match(stripped) and cleaned.lower().strip(".。") in EMPTY_WORDS:
            continue
        lines.append(cleaned)
        if sum(len(x) for x in lines) > 150:
            break
    summary = " ".join(lines)
    summary = re.sub(r"\s+", " ", summary).strip()
    if not summary:
        summary = re.sub(r"\s+", " ", body)[:150]
    if len(summary) > 160:
        summary = summary[:160].rstrip() + "…"
    return summary


def rule_analyze(text: str) -> AnalysisResult:
    sections = extract_sections(text)
    if not sections["pending"]:
        sections["pending"] = find_inline_items(
            text, ("未完成", "待完成", "尚未完成", "遗留", "下一步", "还未", "尚未")
        )
    if not sections["issues"]:
        sections["issues"] = find_inline_items(text, ("已知问题", "存在的问题", "风险", "bug", "待优化"))
    if not sections["completed"]:
        for line in (text or "").splitlines():
            match = CHECKBOX_RE.match(line)
            if match and match.group(1).lower() == "x":
                sections["completed"].append(clean_inline(CHECKBOX_RE.sub("", line)))
    result = AnalysisResult(
        completed=sections["completed"][:30],
        pending=sections["pending"][:30],
        issues=sections["issues"][:30],
        source="rules",
    )
    result.summary = make_summary(text, result)
    result.needs_followup = bool(result.pending or result.issues)
    return result


def parse_llm_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("title") or item.get("text") or json.dumps(item, ensure_ascii=False)
        text = clean_inline(str(item))
        if text and text.lower().strip(".。") not in EMPTY_WORDS:
            out.append(text[:400])
    return out[:30]


class ResultAnalyzer:
    def __init__(self, config: AppConfig, feedback: list[dict[str, Any]] | None = None):
        self.config = config
        self.feedback = feedback or []

    def analyze(self, task_prompt: str, final_text: str) -> AnalysisResult:
        fallback = rule_analyze(final_text)
        if not final_text.strip():
            fallback.pending = ["Agent 没有返回任何可验收的内容"]
            fallback.issues = ["执行输出为空，无法确认任务是否落地"]
            fallback.needs_followup = True
            fallback.summary = "未返回内容，需要继续执行"
            return fallback
        if not self.config.analyzer.ready:
            return fallback
        try:
            result = self._llm_analyze(task_prompt, final_text)
            if not result.summary:
                result.summary = fallback.summary
            return result
        except (LLMError, Exception) as exc:
            fallback.issues = fallback.issues or []
            fallback.source = f"rules (LLM 失败: {str(exc)[:80]})"
            return fallback

    def _llm_analyze(self, task_prompt: str, final_text: str) -> AnalysisResult:
        hints = (self.config.analyzer_hints or "").strip()
        feedback_block = ""
        if self.feedback:
            examples = []
            for item in self.feedback[:3]:
                examples.append(
                    f"原始识别：{item.get('original', '')[:600]}\n人工修正：{item.get('corrected', '')[:600]}"
                )
            if examples:
                feedback_block = "\n\n历史人工修正示例（请按这些偏好修正判定）：\n" + "\n---\n".join(examples)
        user = (
            f"原始任务要求：\n{task_prompt[:8000]}\n\n"
            f"Agent 最终回复：\n{final_text[:24000]}\n\n"
            f"{hints}{feedback_block}\n\n请输出 JSON。"
        )
        raw = chat_completion(self.config.analyzer, ANALYZER_SYSTEM, user, temperature=0.1)
        data = parse_llm_json(raw)
        result = AnalysisResult(
            summary=clean_inline(str(data.get("summary") or ""))[:220],
            completed=_as_list(data.get("completed")),
            pending=_as_list(data.get("pending")),
            issues=_as_list(data.get("issues")),
            source="llm",
        )
        result.needs_followup = bool(data.get("needs_followup")) and bool(
            result.pending or result.issues
        )
        if not result.needs_followup:
            result.needs_followup = bool(result.pending or result.issues)
        return result

    def analyze_corrected(self, original: AnalysisResult, corrected: AnalysisResult) -> None:
        # Learning signal is persisted by the caller; kept here for API clarity.
        self.feedback.insert(
            0,
            {
                "original": json.dumps(original.to_dict(), ensure_ascii=False),
                "corrected": json.dumps(corrected.to_dict(), ensure_ascii=False),
            },
        )

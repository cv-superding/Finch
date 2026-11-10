from __future__ import annotations

from ..config import AppConfig


def _items_block(pending: list[str], issues: list[str]) -> str:
    lines: list[str] = []
    if pending:
        lines.append("【未完成/遗漏】")
        lines.extend(f"- {item}" for item in pending)
    if issues:
        if lines:
            lines.append("")
        lines.append("【已知问题/风险】")
        lines.extend(f"- {item}" for item in issues)
    return "\n".join(lines)


def render_followup(
    config: AppConfig,
    task_prompt: str,
    summary: str,
    pending: list[str],
    issues: list[str],
    title: str = "",
) -> str:
    template = config.followup_template or ""
    items = _items_block(pending, issues)
    rendered = (
        template.replace("{task}", task_prompt)
        .replace("{summary}", summary)
        .replace("{items}", items)
        .replace("{title}", title or "当前任务")
    )
    if "{items}" not in template:
        if rendered and not rendered.endswith("\n"):
            rendered += "\n\n"
        rendered += "需要补齐的内容：\n" + items
    return rendered.strip()


def build_followup_prompt(
    config: AppConfig,
    task_prompt: str,
    summary: str,
    pending: list[str],
    issues: list[str],
    title: str = "",
) -> str:
    return render_followup(config, task_prompt, summary, pending, issues, title)

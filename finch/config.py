from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


def app_home() -> Path:
    override = os.environ.get("FINCH_HOME")
    base = Path(override) if override else Path(os.environ.get("APPDATA", Path.home())) / "Finch"
    base.mkdir(parents=True, exist_ok=True)
    return base


def data_dir() -> Path:
    p = app_home() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = app_home() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def workspaces_dir() -> Path:
    p = app_home() / "workspaces"
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULT_CONTINUE_PROMPT = (
    "请继续执行当前未完成的任务，接着之前的进度往下输出，不要重复已完成的内容。"
    "如果已经全部完成，请给出最终收尾总结。"
)

DEFAULT_FOLLOWUP_TEMPLATE = """你刚才执行的任务是：

{task}

上一轮回复的摘要：
{summary}

根据你的回复，以下内容仍未完成或存在问题：
{items}

请直接在现有工作区中补齐上述缺漏、修复指出的问题。要求：
1. 不要重复已经完成的内容，只处理上面列出的缺漏与问题；
2. 每完成一项后自检结果，确保真实落地而不是只做说明；
3. 结束时列出本次完成项、仍然未完成项与已知问题。"""

DEFAULT_FOLLOWUP_CONFIRM_TEMPLATE = """请继续完成当前任务，以下内容仍未落地：

{items}

要求：逐项补齐、实际修改文件并验证；不要重复已完成工作。结束时汇报完成项、剩余项和已知问题。"""

ANALYZER_SYSTEM = """你是一个严谨的 AI 编程任务验收员。根据用户给出的原始任务与 Agent 最终回复，提取结构化结果。
只输出 JSON，不要输出 Markdown。JSON 结构：
{
  "summary": "不超过 120 字的执行摘要",
  "completed": ["已完成的具体事项"],
  "pending": ["明确未完成或遗漏的功能/步骤"],
  "issues": ["已知 bug、风险、待优化项；没有则为空"],
  "needs_followup": true/false
}
判定规则：
- pending 只收录回复中明确没做完、被跳过、仍待办的内容；不要臆测。
- 如果任务要求包含多个子项而回复没有交代，记为 pending。
- issues 包含测试失败、未验证、临时方案、已知风险。
- 只有 pending 和 issues 都为空时 needs_followup 才为 false。
- 回复明显被截断时，把截断造成的内容缺失记为 pending。"""

OPTIMIZER_SYSTEM = """你是世界级的提示词工程师，专门为 AI 编程 Agent 优化任务提示词。
在保持原始意图与事实不变的前提下：
1. 补足目标、范围、技术约束、验收标准与输出格式；
2. 消除歧义，把模糊动词改成可验证的动作；
3. 保留用户已有的关键细节，不编造新需求；
4. 使用清晰的层级结构，适合作为一次独立下发的任务；
5. 只输出优化后的提示词正文，不要解释、不要加代码围栏。"""


@dataclass
class LLMConfig:
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    timeout: int = 90

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.base_url.strip() and self.model.strip())


@dataclass
class OptimizerConfig:
    mode: str = "auto"  # auto | mcp | builtin | off
    mcp_url: str = "http://localhost:8081/mcp"
    template: str = "general"
    use_optimizer_model: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    @property
    def llm_ready(self) -> bool:
        return bool(self.base_url.strip() and self.model.strip())


@dataclass
class AppConfig:
    agent: str = "claude"
    cwd: str = ""
    agent_paths: dict[str, str] = field(default_factory=dict)
    agent_extra_args: dict[str, str] = field(default_factory=dict)
    text_idle_timeout: int = 30
    tool_timeout: int = 600
    first_output_grace: int = 90
    max_resumes: int = 3
    max_followups: int = 3
    auto_followup: bool = True
    confirm_followup: bool = False
    optimize_followup: bool = True
    optimize_continue: bool = False
    continue_prompt: str = DEFAULT_CONTINUE_PROMPT
    followup_template: str = DEFAULT_FOLLOWUP_TEMPLATE
    isolate_mcp: bool = False
    permission_mode: str = "acceptEdits"
    analyzer: LLMConfig = field(default_factory=LLMConfig)
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    analyzer_hints: str = ""
    seeded_demo: bool = False
    autopilot_goal: str = ""
    autopilot_rounds: int = 5
    autopilot_minutes: int = 0
    autopilot_auto_accept: bool = True
    ui_font_scale: float = 1.2
    board_layout: dict = field(default_factory=dict)
    inspector_collapsed: bool = True
    inspector_width: int = 320
    theme_mode: str = "dark"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str | None) -> "AppConfig":
        cfg = cls()
        if not text:
            return cfg
        try:
            raw = json.loads(text)
        except Exception:
            return cfg
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = raw[f.name]
            if f.name == "analyzer":
                value = LLMConfig(**{k: v for k, v in value.items() if k in LLMConfig.__dataclass_fields__})
            elif f.name == "optimizer":
                value = OptimizerConfig(**{k: v for k, v in value.items() if k in OptimizerConfig.__dataclass_fields__})
            setattr(cfg, f.name, value)
        return cfg

    def copy_dict(self) -> dict[str, Any]:
        return asdict(self)

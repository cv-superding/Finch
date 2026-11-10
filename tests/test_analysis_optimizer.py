from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finch.config import AppConfig, LLMConfig
from finch.core.analyzer import ResultAnalyzer, rule_analyze
from finch.core.optimizer import PromptOptimizer
from tests.fake_services import start_llm, start_mcp, start_mcp_sse


BUILD_DONE = """已完成：
- 补齐空状态插画与提示语
- 接入快捷键
未完成：
- 无
已知问题：
- 无
本轮补做已完成，所有验收项通过。"""


class AnalyzerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.llm_server, cls.llm_thread, cls.llm_url = start_llm()
        cls.mcp_server, cls.mcp_thread, cls.mcp_url = start_mcp()
        cls.sse_server, cls.sse_thread, cls.sse_url = start_mcp_sse()

    @classmethod
    def tearDownClass(cls):
        cls.llm_server.shutdown()
        cls.mcp_server.shutdown()
        cls.sse_server.shutdown()

    def test_rules_do_not_treat_closing_sentence_as_issue(self):
        result = rule_analyze(BUILD_DONE)
        self.assertEqual(result.pending, [])
        self.assertEqual(result.issues, [])
        self.assertFalse(result.needs_followup)
        self.assertIn("补齐空状态", result.completed[0])

    def test_rules_detect_pending_and_issues(self):
        text = """已完成：
- 完成列表
未完成：
- 空状态未实现
- 快捷键未接入
已知问题：
- 小屏横向溢出
"""
        result = rule_analyze(text)
        self.assertIn("空状态未实现", result.pending)
        self.assertIn("小屏横向溢出", result.issues)
        self.assertTrue(result.needs_followup)

    def test_llm_analysis(self):
        cfg = AppConfig()
        cfg.analyzer = LLMConfig(enabled=True, base_url=self.llm_url, model="fake", api_key="x")
        result = ResultAnalyzer(cfg).analyze("实现待办清单", "任意回复")
        self.assertEqual(result.source, "llm")
        self.assertIn("空状态提示未实现", result.pending)
        self.assertTrue(result.needs_followup)

    def test_optimizer_mcp(self):
        cfg = AppConfig()
        cfg.optimizer.mode = "mcp"
        cfg.optimizer.mcp_url = self.mcp_url + "/mcp"
        result = PromptOptimizer(cfg).optimize("帮我做待办清单", "user")
        self.assertEqual(result.engine, "prompt-optimizer MCP")
        self.assertIn("原始要求", result.text)
        system = PromptOptimizer(cfg).optimize("你是一个助手", "system")
        self.assertIn("你是一个助手", system.text)
        ok, message = PromptOptimizer(cfg).test_mcp()
        self.assertTrue(ok, message)

    def test_optimizer_mcp_sse(self):
        cfg = AppConfig()
        cfg.optimizer.mode = "mcp"
        cfg.optimizer.mcp_url = self.sse_url + "/mcp"
        result = PromptOptimizer(cfg).optimize("走 SSE 的提示词", "user")
        self.assertEqual(result.engine, "prompt-optimizer MCP")
        self.assertIn("走 SSE 的提示词", result.text)

    def test_optimizer_builtin(self):
        cfg = AppConfig()
        cfg.optimizer.mode = "builtin"
        cfg.analyzer = LLMConfig(enabled=False, base_url=self.llm_url, model="fake", api_key="x")
        result = PromptOptimizer(cfg).optimize("帮我做待办清单", "user")
        self.assertEqual(result.engine, "builtin LLM")
        self.assertIn("优化结果", result.text)


if __name__ == "__main__":
    unittest.main()

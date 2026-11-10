from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOCK_AGENT = ROOT / "finch" / "agents" / "mock_agent.py"


class MockAgentEncodingTests(unittest.TestCase):
    def test_chinese_prompt_selects_scenario(self) -> None:
        prompt = "请梳理一个待办清单应用的核心验收标准：新增、完成、删除、筛选、持久化。"
        proc = subprocess.run(
            [sys.executable, str(MOCK_AGENT), "--session-id", "encoding-test"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("梳理了待办清单的 5 条核心验收标准", proc.stdout)
        self.assertNotIn("按任务要求完成主要工作并自检", proc.stdout)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def text_delta(session: str, text: str, delay: float = 0.035) -> None:
    for index in range(0, len(text), 12):
        chunk = text[index : index + 12]
        emit(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": chunk},
                },
                "session_id": session,
            }
        )
        time.sleep(delay)


def tool(session: str, name: str, tool_input: dict, output: str, seconds: float) -> None:
    tool_id = "toolu_" + uuid.uuid4().hex[:10]
    emit(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}},
            },
            "session_id": session,
        }
    )
    emit(
        {
            "type": "assistant",
            "message": {
                "id": "msg_" + uuid.uuid4().hex[:10],
                "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}],
            },
            "session_id": session,
        }
    )
    time.sleep(seconds)
    emit(
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": tool_id, "content": output, "is_error": False}
                ]
            },
            "session_id": session,
        }
    )


def result(session: str, text: str, is_error: bool = False) -> None:
    emit(
        {
            "type": "result",
            "subtype": "success" if not is_error else "error_during_execution",
            "is_error": is_error,
            "result": text,
            "session_id": session,
            "duration_ms": 1200,
            "num_turns": 1,
            "total_cost_usd": 0.0,
        }
    )


PLAN = """已完成：
- 梳理了待办清单的 5 条核心验收标准：新增、完成、删除、筛选、持久化
- 明确了数据模型（id / title / done / createdAt）与页面结构
- 标出了空状态、错误提示和键盘操作三个交互边界

未完成：
- 无

已知问题：
- 无

下一步可以直接进入界面实现。"""

BUILD = """已完成：
- 建立任务输入框与任务列表组件
- 实现新增、完成、删除三项交互
- 使用 localStorage 保存任务数据
- 补充了基础样式与响应式布局

未完成：
- 空状态插画与提示语尚未实现
- 键盘快捷键（Enter 新增、Esc 取消）未接入

已知问题：
- 小屏幕下任务列表横向溢出，尚未适配
- 删除操作没有二次确认，存在误触风险

建议下一轮补齐空状态、快捷键与小屏适配。"""

BUILD_DONE = """已完成：
- 补齐空状态插画与提示语
- 接入 Enter 新增、Esc 取消快捷键
- 修复小屏横向溢出，增加移动端布局
- 为删除操作增加二次确认

未完成：
- 无

已知问题：
- 无

本轮补做已完成，所有验收项通过。"""

TEST = """已完成：
- 运行 12 项交互自测，全部通过
- 修复空状态初始化时列表闪烁的问题
- 校验 localStorage 读写与异常兜底
- 整理验证步骤到 README

未完成：
- 无

已知问题：
- 无

任务已完整落地。"""

FOLLOWUP_DONE = """已完成：
- 已按上一轮问题清单逐项补齐并验证
- 复跑交互自测，全部通过
- 更新任务说明与验证记录

未完成：
- 无

已知问题：
- 无"""

RESUME_DONE = """已完成：
- 从上次中断位置恢复，重新核对工作区状态
- 补齐剩余输出并完成当前步骤
- 复核关键改动，未发现新的阻塞项

未完成：
- 无

已知问题：
- 无

本次续传已完成。"""

GENERIC = """已完成：
- 按任务要求完成主要工作并自检
- 记录关键改动与验证结果

未完成：
- 无

已知问题：
- 无"""

LOOP_REPLY = """已完成：
- 完成本轮补做并复核改动

未完成：
- 仍有验收项未落地
- 仍需补齐边界条件

已知问题：
- 仍有风险待处理"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="")
    parser.add_argument("--resume", default="")
    args = parser.parse_args()
    prompt = sys.stdin.read() if not sys.stdin.isatty() else ""
    session = args.resume or args.session_id or f"mock-{uuid.uuid4().hex[:10]}"
    emit(
        {
            "type": "system",
            "subtype": "init",
            "session_id": session,
            "model": "finch-mock-1",
            "tools": ["Bash", "Read", "Edit", "Write"],
            "permissionMode": "acceptEdits",
        }
    )
    time.sleep(0.15)

    if ("STALL_TEXT" in prompt and not args.resume) or "STALL_TEXT_ALWAYS" in prompt:
        text_delta(session, "正在分析任务，先输出一段内容，然后模拟网络中断。", 0.01)
        time.sleep(600)
        return 0
    if ("STALL_TOOL" in prompt and not args.resume) or "STALL_TOOL_ALWAYS" in prompt:
        tool(session, "Bash", {"command": "npm install"}, "installing...", 600)
        return 0
    if "FAIL_AGENT" in prompt:
        emit({"type": "system", "subtype": "api_retry", "session_id": session, "attempt": 1, "error": "network"})
        result(session, "网络连接失败，无法继续。", is_error=True)
        return 0
    if "ERROR_EVENT_ONLY" in prompt:
        emit({"type": "error", "message": "Authentication Fails, Your api key is invalid (401)"})
        return 0
    if "NETWORK_STALL" in prompt and not args.resume:
        emit({"type": "system", "subtype": "api_retry", "session_id": session, "attempt": 1, "error": "connection refused"})
        text_delta(session, "网络连接异常，等待重连……", 0.01)
        time.sleep(600)
        return 0
    if "INCOMPLETE_REPLY" in prompt and not args.resume:
        text_delta(session, "我先分析一下，接下来我会")
        result(session, "我先分析一下，接下来我会")
        return 0

    resumed = bool(args.resume)
    if resumed and "LOOP_FOLLOWUP" in prompt:
        text_delta(session, LOOP_REPLY)
        result(session, LOOP_REPLY)
        return 0
    is_followup = resumed and any(
        word in prompt for word in ("补齐", "补做", "未落地", "请继续完成当前任务", "只处理上面")
    )
    if is_followup:
        text_delta(session, "收到补做要求，先检查上一轮遗留的空状态、快捷键与响应式问题。\n\n")
        tool(session, "Read", {"path": "src/App.tsx"}, "读取到 218 行组件代码。", 0.5)
        tool(
            session,
            "Bash",
            {"command": "npm test -- --run"},
            "Test Files  6 passed (6)\nTests  12 passed (12)",
            0.9,
        )
        text_delta(session, FOLLOWUP_DONE)
        result(session, FOLLOWUP_DONE)
        return 0

    if resumed:
        text_delta(session, "继续上次进度，检查工作区并补齐剩余输出。\n\n")
        tool(session, "Read", {"path": "src/App.tsx"}, "读取当前实现。", 0.3)
        text_delta(session, RESUME_DONE)
        result(session, RESUME_DONE)
        return 0

    if "验收" in prompt or "梳理" in prompt:
        text_delta(session, PLAN)
        result(session, PLAN)
        return 0
    if "自测" in prompt or "验证" in prompt:
        text_delta(session, "开始执行自测与验证。\n\n")
        tool(session, "Bash", {"command": "npm test -- --run"}, "Test Files  6 passed (6)", 0.9)
        text_delta(session, TEST)
        result(session, TEST)
        return 0
    if "实现" in prompt or "补全" in prompt:
        text_delta(session, "先检查项目结构，再实现待办清单核心交互。\n\n")
        tool(session, "Bash", {"command": "npm install"}, "added 142 packages in 2.1s", 0.8)
        tool(session, "Write", {"path": "src/App.tsx"}, "wrote 218 lines", 0.35)
        text_delta(session, BUILD)
        result(session, BUILD)
        return 0

    text_delta(session, GENERIC)
    result(session, GENERIC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from .config import workspaces_dir
from .models import Task
from .store import Store


DEMO_TASKS = [
    (
        "梳理待办清单验收标准",
        "请梳理一个待办清单应用的核心验收标准：新增、完成、删除、筛选、持久化。"
        "输出 5 条可验证的验收标准，并明确数据模型与页面结构。",
    ),
    (
        "实现待办清单核心交互",
        "请实现待办清单的核心交互：任务输入、任务列表、完成切换、删除。"
        "要求真实落地代码，并在结束时列出已完成项、未完成项和已知问题。",
    ),
    (
        "自测并整理验证记录",
        "请对刚才实现的待办清单执行自测：交互、空状态、localStorage 持久化。"
        "运行测试或给出可复现的验证步骤，并把结果整理成记录。",
    ),
]


def add_demo_tasks(store: Store) -> list[Task]:
    cwd = workspaces_dir() / "demo-todo"
    cwd.mkdir(parents=True, exist_ok=True)
    created = []
    for title, prompt in DEMO_TASKS:
        task = Task(title=title, prompt=prompt, agent="mock", cwd=str(cwd), progress="示例任务，等待执行")
        store.add_task(task)
        created.append(task)
    return created

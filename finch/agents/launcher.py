from __future__ import annotations

import os
import shutil
from pathlib import Path


def find_agent_executable(names: tuple[str, ...]) -> str:
    if os.name == "nt":
        # Prefer real Windows shims over the extensionless POSIX wrappers npm
        # installs next to them; CreateProcess cannot execute those.
        for name in names:
            base = name[:-4] if name.lower().endswith(".exe") else name
            for suffix in (".exe", ".cmd", ".bat", ""):
                found = shutil.which(base + suffix)
                if found:
                    return found
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def is_executable_file(path: str) -> bool:
    p = Path(path)
    return p.exists() or bool(shutil.which(path))

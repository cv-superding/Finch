"""打包前把最新前端与后端源码同步进自包含 backend 快照。

exe 里的 Python 后端从 backend/finch 读取代码与静态页；只同步 dist 会让
后端 .py 改动停留在旧版本，只同步 .py 又会让界面停留在旧版本——两者都要同步，
否则「改了没生效」会反复出现。
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "finch"
TARGETS = [
    ROOT / "floral-ui" / "src-tauri" / "backend" / "finch",
    ROOT / "floral-ui" / "src-tauri" / "target" / "release" / "backend" / "finch",
]

for dest in TARGETS:
    if not (dest / "webui" / "server.py").is_file():
        continue

    for item in SRC.glob("*.py"):
        shutil.copy2(item, dest / item.name)

    for sub in ("agents", "core", "webui"):
        source = SRC / sub
        target = dest / sub
        target.mkdir(parents=True, exist_ok=True)
        for item in source.glob("*.py"):
            shutil.copy2(item, target / item.name)
        for item in source.glob("*.html"):
            shutil.copy2(item, target / item.name)

    dist_target = dest / "webui" / "dist"
    dist_target.mkdir(parents=True, exist_ok=True)
    for sub in ("standalone", "webui3", "assets"):
        source = SRC / "webui" / "dist" / sub
        if not source.is_dir():
            continue
        target = dist_target / sub
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

    icons = SRC / "ui" / "assets" / "agents"
    if icons.is_dir():
        target = dest / "ui" / "assets" / "agents"
        target.mkdir(parents=True, exist_ok=True)
        for item in icons.iterdir():
            if item.is_file():
                shutil.copy2(item, target / item.name)

    print("synced", dest)

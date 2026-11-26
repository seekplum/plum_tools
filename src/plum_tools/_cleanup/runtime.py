"""将清理计划与完整实现绑定，并保护运行环境。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def implementation_paths() -> tuple[Path, ...]:
    """返回入口、公共 CLI 依赖及清理模块，供计划绑定和环境保护共用。"""
    package = Path(__file__).resolve().parent
    shared = package.parent / "utils"
    return (
        package.parent / "cli" / "pclean.py",
        *(shared / name for name in ("compat.py", "parser.py", "cli.py")),
        *sorted(package.glob("*.py")),
    )


def implementation_digest() -> str:
    """绑定完整清理实现；任一模块变化后要求重新生成计划。"""
    digest = hashlib.sha256()
    for path in implementation_paths():
        content = path.read_bytes()
        digest.update(path.name.encode())
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()

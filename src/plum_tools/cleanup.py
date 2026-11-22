"""通过显式子命令预览和清理可重建文件或工具缓存。"""

import shlex
import shutil
import subprocess
import sys

from ._cleanup.cli import parse_args
from ._cleanup.constants import PROJECT_CATEGORIES, Command
from ._cleanup.filesystem import Trash
from ._cleanup.service import run
from .utils.cli import cli_entry


@cli_entry
def main() -> int:
    """分流文件计划与原生工具流程，仅在显式执行模式下进入清理。"""
    if sys.platform not in {"darwin", "linux"}:
        print("需要 macOS/Linux。", file=sys.stderr)
        return 2

    args = parse_args()
    try:
        trash = Trash() if args.command != Command.PRUNE else None
    except ImportError as exc:
        command = shlex.join([sys.executable, "-m", "pip", "install", "trash-cli"])
        print(
            f"无法加载 trash-cli（{exc}），请在当前 Python 环境安装：{command}",
            file=sys.stderr,
        )
        return 2
    if args.categories & PROJECT_CATEGORIES and not shutil.which("git"):
        print("项目扫描需要安装 Git；不会退回不检查忽略规则的模式。", file=sys.stderr)
        return 2
    try:
        return run(args, trash)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"已停止: {exc}", file=sys.stderr)
        return 1
    except EOFError:
        print("\n已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

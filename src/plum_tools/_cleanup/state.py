"""共享单次命令的运行状态，避免组件相互持有实现。"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from rich.console import Console

from plum_tools._cleanup.constants import PlanFile
from plum_tools._cleanup.filesystem import Trash
from plum_tools._cleanup.models import Candidate, ExecutionSnapshot, Note, ToolTask
from plum_tools._cleanup.plan_io import plan_file_path, read_plan
from plum_tools._cleanup.progress import ProgressDisplay
from plum_tools._cleanup.projects import Repository
from plum_tools._cleanup.runtime import implementation_paths


class CleanupState:  # pylint: disable=too-many-instance-attributes
    """集中保存一次命令的参数、候选及复核状态。"""

    def __init__(self, args: argparse.Namespace, trash: Trash | None) -> None:
        """绑定参数、回收站和扫描快照，保护当前运行环境路径。"""

        self.args = args
        self.trash = trash
        self.console = Console(markup=False, highlight=False)
        self.error_console = Console(stderr=True, markup=False, highlight=False)
        self.progress = ProgressDisplay(self.error_console)
        self.now = time.time()
        self.home = Path.home().resolve()
        self.candidates: list[Candidate] = []
        self.candidate_paths: set[Path] = set()
        self.tasks: list[ToolTask] = []
        self.repositories: dict[Path, Repository] = {}
        self.skipped_repositories: set[Path] = set()
        self.notes: list[Note] = []
        self.errors: list[str] = []
        self.execution_digests: dict[Path, str] = {}
        self.execution_snapshots: dict[Path, ExecutionSnapshot] = {}
        protected = {
            *implementation_paths(),
            Path(__file__).parent.absolute(),
            Path(sys.executable).absolute(),
            Path(sys.prefix).absolute(),
        }
        protected.update(
            Path(os.path.abspath(os.path.expanduser(os.environ[name])))
            for name in ("VIRTUAL_ENV", "CONDA_PREFIX")
            if os.environ.get(name)
        )
        protected.update(path.resolve() for path in tuple(protected))
        self.protected_parts = {path.parts for path in protected}
        self.plan_identity: tuple[int, ...] | None = None
        self.loaded_plan_identity: tuple[int, ...] | None = None
        self.loaded_plan_checksum: str | None = None
        plan = args.save_plan or args.from_plan
        self.plan_path = plan_file_path(plan or PlanFile.DEFAULT)
        if args.save_plan and os.path.lexists(self.plan_path):
            if not args.default_plan:
                raise ValueError("清理计划文件已存在，请使用新文件名保存")
            try:
                _, self.plan_identity = read_plan(self.plan_path, check_script=False)
            except ValueError as exc:
                raise ValueError(f"默认计划无法更新: {exc}；可使用 --save-plan 指定新文件") from exc
        if args.from_plan:
            if not os.path.lexists(self.plan_path):
                raise ValueError("未找到清理计划，请先执行 pclean scan，或使用 --from-plan 指定已有计划")
            self.protected_parts.add(self.plan_path.parts)

    def add_note(self, reason: str, detail: str = "", path: Path | None = None) -> None:
        """记录带明确分组、详情和可选路径的说明。"""
        self.notes.append(Note(reason, detail, path))

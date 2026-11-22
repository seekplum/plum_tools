"""显式组合清理组件并调度单次命令。"""

from __future__ import annotations

import argparse
import sys

from .constants import Command, ExitCode, PruneAction
from .execution import CleanupExecutor
from .filesystem import FileInspector, Trash
from .plans import PlanStore
from .reporting import CleanupReporter
from .scanner import ProjectScanner
from .state import CleanupState
from .tools import ToolScanner


def run(args: argparse.Namespace, trash: Trash | None) -> int:
    """组合扫描、计划、展示与执行组件，返回当前命令的退出码。"""
    state = CleanupState(args, trash)
    inspector = FileInspector(state)
    scanner = ProjectScanner(state, inspector)
    tools = ToolScanner(state, inspector)
    plans = PlanStore(state, inspector)
    reporter = CleanupReporter(state)
    executor = CleanupExecutor(state, inspector, scanner)
    if args.command == Command.PRUNE:
        tools.discover_prune_tasks()
    elif args.command == Command.SCAN:
        scanner.scan()
        if state.errors:
            reporter.report()
            print("已停止: 扫描不完整，未保存清理计划，请处理上述错误后重新扫描。", file=sys.stderr)
            return ExitCode.FAILURE
        plans.save_plan()
    else:
        plans.load_plan()
        total = len(state.repositories) + len(state.candidates)
        with state.progress.phase("复核已保存的清理计划", total):
            executor.revalidate()
    reporter.report()
    if args.command == Command.PRUNE:
        return (
            executor.execute_prune()
            if args.prune_action == PruneAction.RUN
            else (ExitCode.FAILURE if state.errors else ExitCode.SUCCESS)
        )
    return (
        executor.execute() if args.command == Command.RUN else (ExitCode.FAILURE if state.errors else ExitCode.SUCCESS)
    )

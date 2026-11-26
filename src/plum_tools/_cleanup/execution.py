"""执行前复核完整范围，确认后按固定候选清理。"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from plum_tools._cleanup.constants import (
    PROJECT_CATEGORIES,
    QUERY_ENV,
    Category,
    Command,
    ExecutionLimits,
    ExitCode,
    SnapshotMode,
)
from plum_tools._cleanup.filesystem import Trash, directory_fd, display, human_size, remove_candidate, signature
from plum_tools._cleanup.models import Candidate, ExecutionSnapshot, ToolTask
from plum_tools._cleanup.plan_io import plan_checksum, read_plan
from plum_tools._cleanup.projects import Project, Repository, repository_at

if TYPE_CHECKING:
    from .filesystem import FileInspector
    from .scanner import ProjectScanner
    from .state import CleanupState


class CleanupExecutor:
    """在完整复核与明确确认后执行固定候选。"""

    def __init__(self, state: CleanupState, inspector: FileInspector, scanner: ProjectScanner) -> None:
        """绑定本组件使用的运行状态和协作组件。"""
        self.state = state
        self.inspector = inspector
        self.scanner = scanner

    def _trash(self) -> Trash:
        """文件计划要求已初始化回收站，原生工具流程不使用此依赖。"""
        if self.state.trash is None:
            raise ValueError("文件清理需要初始化回收站")
        return self.state.trash

    def _revalidate_snapshot(self, item: Candidate, record_limit: int) -> ExecutionSnapshot | None:
        """复核候选身份与摘要，预算足够时返回完整节点记录。"""
        if item.path.is_symlink():
            raise ValueError(f"候选已变为软链接: {display(item.path)}")
        with directory_fd(item.path.parent):
            pass
        if item.snapshot == SnapshotMode.DIRECTORY:
            current = self.inspector.directory_snapshot(item)
            if current[:3] != item.identity[:3]:
                raise ValueError(f"候选已被替换: {display(item.path)}")
            if self.state.args.command != Command.RUN:
                return None
        records: dict[Path, tuple[int, ...]] | None = {} if record_limit else None
        size, digest, _, _ = self.inspector.measure(item, records, record_limit=record_limit)
        if item.snapshot == SnapshotMode.DIRECTORY:
            # 快速计划不含内部快照，执行时首次建立并固定本次完整复核结果。
            expected = self.state.execution_digests.setdefault(item.path, digest)
        else:
            expected = item.digest
            if signature(item.path.lstat()) != item.identity:
                raise ValueError(f"候选已被替换: {display(item.path)}")
        if digest != expected:
            raise ValueError(f"候选内容已变化，请重新预览: {display(item.path)}")
        return ExecutionSnapshot(size, digest, records) if records else None

    def revalidate(self, *, capture_records: bool = False) -> None:
        """在任何删除前复核全部文件候选，变化时停止整个批次。"""
        self.state.execution_snapshots.clear()
        remaining = ExecutionLimits.CACHED_NODES if capture_records else 0
        repositories = {}
        for root in self.state.repositories:
            self.state.progress.visit(root)
            repositories[root] = Repository.load(root)
            self.state.progress.advance(root)
        ignored = {}
        for repository in repositories.values():
            ignored.update(
                repository.ignored([item.path for item in self.state.candidates if item.repository == repository.root])
            )
        contexts: dict[Path, Repository | None] = {}
        projects: dict[tuple[Path, Path], Project] = {}
        for item in self.state.candidates:
            self.state.progress.visit(item.path)
            snapshot = self._revalidate_snapshot(item, remaining)
            if snapshot is not None:
                self.state.execution_snapshots[item.path] = snapshot
                remaining -= len(snapshot.records)
            if any(signature(path.lstat()) != old for path, old in item.manifests.items()):
                raise ValueError(f"项目配置已变化: {display(item.path)}")
            if self.state.args.from_plan:
                parent = item.path.parent
                if parent not in contexts:
                    contexts[parent] = repository_at(parent)
                current = contexts[parent]
                if (current.root if current else None) != item.repository:
                    raise ValueError(f"所属 Git 仓库已变化: {display(item.path)}")
                if item.category in PROJECT_CATEGORIES:
                    project = self.scanner.resolve_project(item, projects)
                    match = self.scanner.project_match(item.path, project)
                    if project.manifests != item.manifests or match != (
                        item.category,
                        item.rebuild,
                    ):
                        raise ValueError(f"项目配置或生成物规则已变化: {display(item.path)}")
            self._revalidate_git_candidate(item, repositories, ignored)
            self.state.progress.advance(item.path)

    def _revalidate_git_candidate(
        self, item: Candidate, repositories: dict[Path, Repository], ignored: dict[Path, str]
    ) -> None:
        """再次确认候选未被 Git 跟踪，项目产物仍满足忽略规则。"""
        if not item.repository:
            return
        if repositories[item.repository].contains_tracked(item.path):
            raise ValueError(f"Git 跟踪或忽略状态已变化，已出现跟踪文件，拒绝清理: {display(item.path)}")
        if item.category in {Category.PROJECT_CACHE, Category.BUILD, Category.DEPS} and item.path not in ignored:
            raise ValueError(f"Git 跟踪或忽略状态已变化: {display(item.path)}")

    def revalidate_task(self, task: ToolTask) -> None:
        """复核工具缓存的目录身份和查询范围。"""
        if task.cache:
            if os.path.lexists(task.cache / ".git"):
                raise ValueError(f"{task.display_name}: 缓存目录已变为 Git 仓库")
            with directory_fd(task.cache):
                info = task.cache.stat()
            if (info.st_dev, info.st_ino) != task.guard:
                raise ValueError(f"{task.display_name}: 缓存目录已被替换")
            repository = repository_at(task.cache)
            if repository and repository.contains_tracked(task.cache):
                raise ValueError(f"{task.display_name}: 缓存中出现 Git 已跟踪文件")
        for verification in task.verifications:
            try:
                verification.validate()
            except ValueError as exc:
                raise ValueError(f"{task.display_name}: {exc}") from exc

    def execute(self) -> int:
        """复核后将计划中的文件候选移入回收站，逐项报告结果。"""
        if self.state.errors:
            self.state.error_console.print("扫描不完整，拒绝执行；请先处理上述错误。")
            return ExitCode.FAILURE
        if not self.state.candidates:
            self.state.console.print("没有需要清理的内容。")
            return self._finish_plan()
        if not self.state.args.yes:
            if not sys.stdin.isatty():
                self.state.error_console.print("非交互环境必须显式使用 --yes。")
                return ExitCode.USAGE
            answer = input("将清理上述内容（文件和目录移入回收站），输入 CLEAN 确认: ")
            if answer.strip().casefold() != "clean":
                self.state.console.print("已取消。")
                return ExitCode.SUCCESS
        if (
            not all(function in os.supports_dir_fd for function in (os.open, os.stat))
            or os.listdir not in os.supports_fd
        ):
            self.state.error_console.print("当前 Python 不支持安全的目录复核，拒绝执行。")
            return ExitCode.FAILURE
        total = len(self.state.repositories) + len(self.state.candidates)
        with self.state.progress.phase("复核清理范围", total):
            self.revalidate(capture_records=True)
        devices = {}
        for item in self.state.candidates:
            device = item.root.stat().st_dev
            if device not in devices:
                devices[device] = (item.root, shutil.disk_usage(item.root).free)
        try:
            with self.state.progress.phase("清理候选", len(self.state.candidates)):
                succeeded, failed, removed = self._clean_items()
        finally:
            self.state.execution_snapshots.clear()
        self.state.console.print(
            f"完成: 成功 {succeeded} 项，失败 {failed} 项；移入回收站估算占用 {human_size(removed)}。"
        )
        if failed:
            self.state.console.print("失败项可能已部分清理，未处理的文件保持原状。")
        for root, before in devices.values():
            change = shutil.disk_usage(root).free - before
            self.state.console.print(f"文件系统 {display(root)} 可用空间变化: {human_size(change)}（含并发磁盘活动）。")
        return ExitCode.FAILURE if failed else self._finish_plan()

    def execute_prune(self) -> int:
        """当次确认后复核全部工具范围，再逐项调用原生命令直接清理。"""
        if self.state.errors:
            self.state.error_console.print("工具查询不完整，拒绝执行；请先处理上述错误。")
            return ExitCode.FAILURE
        if not self.state.tasks:
            self.state.console.print("没有可执行的工具清理操作。")
            return ExitCode.SUCCESS
        if not self.state.args.yes:
            if not sys.stdin.isatty():
                self.state.error_console.print("非交互环境必须显式使用 --yes。")
                return ExitCode.USAGE
            answer = input("将调用上述工具直接清理缓存（不经过回收站），输入 CLEAN 确认: ")
            if answer.strip().casefold() != "clean":
                self.state.console.print("已取消。")
                return ExitCode.SUCCESS
        with self.state.progress.phase("复核工具清理范围", len(self.state.tasks)):
            for task in self.state.tasks:
                self.state.progress.visit(task.display_name)
                self.revalidate_task(task)
                self.state.progress.advance(task.display_name)
        with self.state.progress.phase("工具直接清理", len(self.state.tasks)):
            succeeded, failed = self._prune_tasks()
        self.state.console.print(f"工具清理完成: 成功 {succeeded} 项，失败 {failed} 项。")
        self.state.console.print("实际清理对象和释放空间以工具输出为准。")
        if any(task.category == Category.DOCKER for task in self.state.tasks):
            self.state.console.print("Docker 虚拟机磁盘文件不一定立即缩小。")
        return ExitCode.FAILURE if failed else ExitCode.SUCCESS

    def _finish_plan(self) -> int:
        """全部清理成功后回收本次加载的计划，拒绝移动被并发更新的计划。"""
        if not self.state.args.from_plan:
            return ExitCode.SUCCESS
        try:
            data, identity = read_plan(self.state.plan_path)
            if identity != self.state.loaded_plan_identity or plan_checksum(data) != self.state.loaded_plan_checksum:
                raise ValueError("清理计划在执行期间发生变化，已保留，请重新预览")
            self._trash().put(self.state.plan_path, identity)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.state.error_console.print(f"计划文件回收失败: {exc}")
            return ExitCode.FAILURE
        self.state.console.print(f"已将清理计划移入回收站: {display(self.state.plan_path)}")
        return ExitCode.SUCCESS

    def _clean_items(self) -> tuple[int, int, int]:
        """回收已复核文件候选，返回成功数、失败数和估算移除字节。"""
        succeeded, failed, removed = 0, 0, 0
        for item in self.state.candidates:
            self.state.progress.visit(item.path)
            try:
                snapshot = self.state.execution_snapshots.pop(item.path, None)
                if snapshot is None:
                    records: dict[Path, tuple[int, ...]] = {}
                    size, digest, _, _ = self.inspector.measure(item, records)
                else:
                    size, digest, records = (
                        snapshot.size,
                        snapshot.digest,
                        snapshot.records,
                    )
                expected = (
                    self.state.execution_digests.get(item.path)
                    if item.snapshot == SnapshotMode.DIRECTORY
                    else item.digest
                )
                if digest != expected:
                    raise ValueError("内容已变化，跳过")
                remove_candidate(item, records, self._trash())
                succeeded += 1
                removed += size
                self.state.console.print(f"已移入回收站: {display(item.path)}")
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                failed += 1
                self.state.error_console.print(f"清理失败 {display(item.path)}: {exc}")
                if self.state.args.from_plan:
                    self.state.error_console.print("已停止计划中的后续清理，请重新预览。")
                    break
            self.state.progress.advance(item.path)
        return succeeded, failed, removed

    def _prune_tasks(self) -> tuple[int, int]:
        """逐项复核并执行原生工具，返回成功数和失败数。"""
        succeeded, failed = 0, 0
        for task in self.state.tasks:
            self.state.progress.visit(task.display_name)
            self.state.console.print(f"执行 {task.display_name}: {shlex.join(task.command)}")
            try:
                self.revalidate_task(task)
                # 命令由工具发现阶段构造，执行前已复核缓存路径和引擎身份。
                result = subprocess.run(  # nosec B603
                    task.command,
                    cwd=self.state.home,
                    env={**os.environ, **QUERY_ENV, **task.environment},
                    check=False,
                    timeout=600,
                )
                if result.returncode:
                    failed += 1
                    self.state.error_console.print(f"{task.display_name} 失败，退出码 {result.returncode}")
                else:
                    succeeded += 1
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                failed += 1
                self.state.error_console.print(f"{task.display_name} 失败: {exc}")
            self.state.progress.advance(task.display_name)
        return succeeded, failed

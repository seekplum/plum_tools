"""保存和恢复固定文件候选，验证计划范围。"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from .cli import _build_parser, _resolve_roots, _validate_options
from .constants import PLAN_OPTIONS, PROJECT_CATEGORIES, Category, SnapshotMode
from .filesystem import display
from .models import Candidate, Note
from .plan_io import plan_checksum, plan_file_path, plan_runtime, read_plan, write_plan
from .projects import Repository

if TYPE_CHECKING:
    from .filesystem import FileInspector
    from .state import CleanupState


class PlanStore:
    """持久化文件候选，恢复时验证计划范围与扫描参数。"""

    def __init__(self, state: CleanupState, inspector: FileInspector) -> None:
        """绑定本组件使用的运行状态和协作组件。"""
        self.state = state
        self.inspector = inspector

    def save_plan(self) -> None:
        """保存当前预览快照，默认计划可刷新，自定义计划只创建新文件。"""
        if self.state.errors:
            raise ValueError("扫描不完整，不能保存清理计划")
        path = plan_file_path(self.state.args.save_plan)
        if any(item.path == path or item.path in path.parents for item in self.state.candidates):
            raise ValueError("清理计划不能存放在待清理的文件或目录中")
        data = {
            "runtime": plan_runtime(),
            "created_at": self.state.now,
            "options": {
                "root": [str(root) for root in self.state.args.roots],
                "category": sorted(self.state.args.categories),
                "exclude": self.state.args.exclude,
                "include_generated": self.state.args.include_generated,
                "older_than": self.state.args.older_than,
                "fast_deps": self.state.args.fast_deps,
            },
            "candidates": [item.plan_data() for item in self.state.candidates],
            "notes": [note.message() for note in self.state.notes],
        }
        data["checksum"] = plan_checksum(data)
        write_plan(path, data, self.state.plan_identity)
        self.state.add_note("已保存清理计划", path=path)

    def load_plan(self) -> None:
        """恢复并校验固定候选和扫描参数，供协调层整批复核。"""
        path = plan_file_path(self.state.args.from_plan)
        try:
            data, self.state.loaded_plan_identity = read_plan(path)
            self.state.loaded_plan_checksum = plan_checksum(data)
            self._restore_options(data["options"])
            if not isinstance(data["candidates"], list):
                raise ValueError("清理计划的候选清单格式无效")
            self.state.candidates = [Candidate.from_plan(item) for item in data["candidates"]]
            self._validate_plan_candidates()
            if not isinstance(data["notes"], list) or any(not isinstance(note, str) for note in data["notes"]):
                raise ValueError("清理计划的说明格式无效")
            self.state.notes = [Note.from_message(note) for note in data["notes"]]
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("清理计划格式不完整，请重新预览并保存") from exc

    def _validate_plan_candidates(self) -> None:
        """检查计划范围和候选重叠，拒绝加载原生命令或越界清理项。"""
        paths = set()
        for item in sorted(self.state.candidates, key=lambda value: len(value.path.parts)):
            # pylint: disable=too-many-boolean-expressions
            if (
                item.category not in self.state.args.categories
                or item.category in {Category.DOCKER, Category.SYSTEM_CACHE}
                or (item.category in PROJECT_CATEGORIES and item.root not in self.state.args.roots)
                or item.path in paths
                or any(parent in paths for parent in item.path.parents)
                or (item.snapshot == SnapshotMode.DIRECTORY and not self.inspector.uses_directory_snapshot(item))
            ):
                raise ValueError(f"清理计划包含越界或重叠的候选: {display(item.path)}")
            paths.add(item.path)
            if item.repository and item.repository not in self.state.repositories:
                self.state.repositories[item.repository] = Repository.load(item.repository)
        self.state.candidate_paths = paths

    def _restore_options(self, options: dict) -> None:
        """验证计划参数后恢复扫描范围，沿用 CLI 的范围限制。"""
        if set(options) != set(PLAN_OPTIONS):
            raise ValueError("清理计划的扫描参数不完整")
        for name in ("root", "category", "exclude", "include_generated"):
            values = options[name]
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError("清理计划的扫描参数格式无效")
        older_than = options["older_than"]
        if older_than is not None and (not isinstance(older_than, int) or older_than < 0):
            raise ValueError("清理计划的保留时间无效")
        if not isinstance(options["fast_deps"], bool):
            raise ValueError("清理计划的快速依赖参数无效")
        for name in PLAN_OPTIONS:
            setattr(self.state.args, name, options[name])
        self.state.args.categories = {Category(value) for value in self.state.args.category}
        if not self.state.args.categories or Category.ALL in self.state.args.categories:
            raise ValueError("清理计划的类别无效")
        parser = _build_parser()
        self.state.args.root = self.state.args.root or None
        _validate_options(self.state.args, parser)
        self.state.args.roots = _resolve_roots(self.state.args.root, parser) if self.state.args.root else []
        if self.state.args.categories & PROJECT_CATEGORIES and not shutil.which("git"):
            raise ValueError("加载项目清理计划需要安装 Git")

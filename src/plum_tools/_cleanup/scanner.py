"""发现文件候选，并应用项目与 Git 范围约束。"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import TYPE_CHECKING

from .constants import (
    BUILD_DIRS,
    DEPENDENCIES,
    MANAGED_CACHE_NAMES,
    PROJECT_CACHES,
    PROJECT_CATEGORIES,
    Category,
    ProjectKind,
    SnapshotMode,
    Tool,
)
from .filesystem import directory_fd, display, is_within, query_text, signature
from .models import Candidate, CandidateResult, Note, ProjectScope
from .projects import Project, Repository, repository_at

if TYPE_CHECKING:
    from .filesystem import FileInspector
    from .state import CleanupState


class ProjectScanner:
    """发现项目和缓存文件，统一接收候选计量结果。"""

    def __init__(self, state: CleanupState, inspector: FileInspector) -> None:
        """绑定本组件使用的运行状态和协作组件。"""
        self.state = state
        self.inspector = inspector

    def resolve_project(self, item: Candidate, projects: dict) -> Project:
        """复用父目录配置识别项目，检测预览后新增或替换的重建依据。"""
        project = Project()
        if item.repository:
            key = (item.repository, item.repository)
            if key not in projects:
                projects[key] = Project.detect(item.repository, project)
            project = projects[key]
        directories = []
        current = item.path.parent
        while current != item.root:
            directories.append(current)
            current = current.parent
        for directory in (item.root, *reversed(directories)):
            key = (item.root, directory)
            if key not in projects:
                self.state.progress.visit(directory)
                projects[key] = Project.detect(directory, project)
            project = projects[key]
        return project

    def _project_file_category(self, name: str, project: Project) -> Category | None:
        """仅按名称和项目类型筛选文件，供发现阶段在读取元数据前排除源码。"""
        if Category.PROJECT_CACHE in self.state.args.categories and (
            name in PROJECT_CACHES
            or name.endswith((".pyc", ".pyo", ".tsbuildinfo"))
            or name == ".coverage"
            or name.startswith(".coverage.")
        ):
            return Category.PROJECT_CACHE
        if (
            Category.BUILD in self.state.args.categories
            and name.endswith(".egg-info")
            and ProjectKind.PYTHON in project.kinds
        ):
            return Category.BUILD
        return None

    # pylint: disable=too-many-return-statements
    def project_match(self, path: Path, project: Project, is_dir: bool | None = None) -> tuple[Category, str] | None:
        """结合产物名称和项目配置返回类别与重建方式。"""
        name = path.name
        if is_dir is None:
            is_dir = path.is_dir()
        if name in DEPENDENCIES:
            if Category.DEPS not in self.state.args.categories:
                return None
            if name in {"node_modules", ".node_modules"} and ProjectKind.NODE in project.rebuild:
                return Category.DEPS, project.rebuild[ProjectKind.NODE]
            if name in {".venv", "venv"} and ProjectKind.PYTHON in project.rebuild and (path / "pyvenv.cfg").is_file():
                return Category.DEPS, project.rebuild[ProjectKind.PYTHON]
            if name == ".tox" and any(item.name in {"tox.ini", "pyproject.toml"} for item in project.manifests):
                return Category.DEPS, "tox"
            if name == ".nox" and any(item.name == "noxfile.py" for item in project.manifests):
                return Category.DEPS, "nox"
            return None
        category = self._project_file_category(name, project)
        if category == Category.PROJECT_CACHE or (
            Category.PROJECT_CACHE in self.state.args.categories
            and is_dir
            and name in self.state.args.include_generated
        ):
            return Category.PROJECT_CACHE, "运行对应编译、检查或测试命令时重建"
        if category == Category.BUILD or (
            Category.BUILD in self.state.args.categories
            and is_dir
            and bool(BUILD_DIRS.get(name, set()) & project.kinds)
        ):
            commands = "; ".join(project.rebuild.values())
            return Category.BUILD, commands + "；重新执行项目构建或测试命令"
        return None

    def scan_projects(self, root: Path) -> None:
        """隔离无法校验的目录和仓库，只保存安全子树中的项目候选。"""
        cache_roots = tuple(
            cache
            for cache in dict.fromkeys([self.state.home / ".cache", *self.user_cache_roots()])
            if cache.is_absolute() and cache not in {Path("/"), self.state.home}
        )

        if any(is_within(root, cache) for cache in cache_roots):
            self.state.add_note("项目扫描跳过全局缓存与日志目录", path=root)
            return
        self.state.progress.describe("发现项目与生成物", unit="个条目")
        initial_repo = None
        try:
            initial_repo = repository_at(root, load_index=False)
            if initial_repo:
                self.state.repositories[initial_repo.root] = initial_repo
            initial_project = Project.detect(initial_repo.root, Project()) if initial_repo else Project()
            root_device = root.stat().st_dev
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            if initial_repo:
                self.state.skipped_repositories.add(initial_repo.root)
            self.state.add_note("保留无法校验的项目目录", str(exc), root)
            return
        self._scan_project_tree(root, initial_repo, initial_project, root_device, cache_roots)

    def _scan_project_tree(  # pylint: disable=too-many-locals
        self,
        root: Path,
        initial_repo: Repository | None,
        initial_project: Project,
        root_device: int,
        cache_roots: tuple[Path, ...],
    ) -> None:
        """遍历独立子树，目录或仓库校验失败时撤销对应范围的候选。"""
        scope = ProjectScope(root, root_device, cache_roots)
        stack = [(root, initial_repo, initial_project)]
        pending: list[Candidate] = []
        while stack:
            current, repository, project = stack.pop()
            if self.inspector.excluded(current, root) or (
                repository and repository.root in self.state.skipped_repositories
            ):
                continue
            start = len(pending)
            children = []
            try:
                with os.scandir(current) as stream:
                    entries = sorted(stream, key=lambda entry: entry.name, reverse=True)
                if any(entry.name == ".git" for entry in entries) and (not repository or current != repository.root):
                    if repository:
                        self.state.add_note("跳过嵌套仓库", path=current)
                        continue
                    # 此处只记录边界，有候选的仓库才调用 Git 验证，失败时整仓保留。
                    repository = Repository(current)
                if repository and repository.root in self.state.skipped_repositories:
                    continue
                project = Project.detect(current, project, entries)
                children = self._scan_project_entries(entries, scope, repository, project, pending)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                # 目录失败时撤销本层发现；仓库失败时连同此前的候选一起保留。
                del pending[start:]
                failed_scope = repository.root if repository else current
                if repository:
                    self.state.skipped_repositories.add(failed_scope)
                self.state.add_note("保留无法校验的项目目录", str(exc), failed_scope)
                continue
            stack.extend(children)
        self._add_project_candidates(pending)

    def _add_project_candidates(self, pending: list[Candidate]) -> None:
        """仅验证含候选的仓库并批量查询忽略规则，失败时整仓保留。"""
        grouped: dict[Path, list[Path]] = {}
        for item in pending:
            if item.repository and item.repository not in self.state.skipped_repositories:
                grouped.setdefault(item.repository, []).append(item.path)
        ignored = {}
        self.state.progress.describe("Git 索引与忽略规则检查", unit="个仓库")
        for root, paths in grouped.items():
            self.state.progress.visit(root)
            try:
                repository = self.state.repositories.get(root)
                if repository is None:
                    repository = repository_at(root, load_index=False)
                    if repository is None or repository.root != root:
                        raise ValueError("Git 工作树与发现时的仓库边界不一致")
                    self.state.repositories[root] = repository
                repository.load_index()
                ignored.update(repository.ignored(paths))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.state.skipped_repositories.add(root)
                self.state.add_note("保留无法校验的 Git 仓库", str(exc), root)
        self.state.progress.describe(f"候选计量与安全检查 · {len(pending):,} 个候选", unit="个节点")
        eligible = []
        for item in pending:
            if item.repository:
                if item.repository in self.state.skipped_repositories:
                    continue
                repository = self.state.repositories[item.repository]
                if repository.contains_tracked(item.path) or item.path not in ignored:
                    continue
                item.reason = ignored[item.path]
            eligible.append(item)
        self._add_candidates(eligible)

    def _candidate_covered(self, item: Candidate) -> bool:
        """判断候选是否已由此前接收的路径覆盖。"""
        return item.path in self.state.candidate_paths or any(
            parent in self.state.candidate_paths for parent in item.path.parents
        )

    def _add_candidates(self, candidates: list[Candidate]) -> None:  # pylint: disable=too-many-locals
        """按候选调度有限数量的并发任务，进度与结果仅由主线程汇总。"""
        candidates = [item for item in candidates if not self._candidate_covered(item)]
        if self.state.args.workers == 1 or len(candidates) < 2:
            for item in candidates:
                self.add_candidate(item)
            return
        updates: SimpleQueue[tuple[Path, int]] = SimpleQueue()

        def visit(path: Path, count: int) -> None:
            """将分批节点计数交回主线程，避免工作线程更新终端。"""
            updates.put((path, count))

        results: dict[int, CandidateResult] = {}
        remaining = iter(enumerate(candidates))
        workers = min(self.state.args.workers, len(candidates))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            pending = {}
            for _ in range(workers):
                index, item = next(remaining)
                pending[executor.submit(self._inspect_candidate, item, visit)] = index
            while pending:
                completed, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                while True:
                    try:
                        path, count = updates.get_nowait()
                    except Empty:
                        break
                    self.state.progress.visit(path, count)
                for future in completed:
                    results[pending.pop(future)] = future.result()
                    following = next(remaining, None)
                    if following is not None:
                        index, item = following
                        future = executor.submit(self._inspect_candidate, item, visit)
                        pending[future] = index
        # 完成顺序不影响候选去重与失败说明的展示顺序。
        for index in range(len(candidates)):
            self._accept_candidate(results[index])

    def add_candidate(self, item: Candidate) -> None:
        """计量并保存完整安全的候选，跳过最近修改或已覆盖的路径。"""
        if self._candidate_covered(item):
            return
        self._accept_candidate(self._inspect_candidate(item))

    def _inspect_candidate(
        self, item: Candidate, progress: Callable[[Path, int], None] | None = None
    ) -> CandidateResult:
        """复制候选并返回计量结果及失败说明，供主线程统一接收。"""
        item = replace(item)
        try:
            if self.inspector.uses_directory_snapshot(item):
                item.identity = self.inspector.directory_snapshot(item)
                item.snapshot = SnapshotMode.DIRECTORY
                item.size = item.files = None
                return CandidateResult(candidate=item)
            item.identity = signature(item.path.lstat())
            item.size, item.digest, item.newest, item.files = self.inspector.measure(item, progress=progress)
            if signature(item.path.lstat()) != item.identity:
                raise ValueError("扫描过程中路径发生变化")
            if item.newest <= self.inspector.cutoff(item.category) and item.files:
                return CandidateResult(candidate=item)
            return CandidateResult()
        except ValueError as exc:
            return CandidateResult(note=Note("跳过", str(exc), item.path))
        except OSError as exc:
            return CandidateResult(error=f"无法读取 {display(item.path)}: {exc}")

    def _accept_candidate(self, result: CandidateResult) -> None:
        """接收计量结果并按原顺序应用候选去重、说明和错误。"""
        if result.note:
            self.state.notes.append(result.note)
        if result.error:
            self.state.errors.append(result.error)
        item = result.candidate
        if item is not None and not self._candidate_covered(item):
            self.state.candidates.append(item)
            self.state.candidate_paths.add(item.path)

    def scan_cache(self, root: Path, category: Category, reason: str) -> None:
        """只选择缓存根目录内过期的普通文件，保留目录、软链接及受保护内容。"""
        if not root.exists():
            return
        try:
            with directory_fd(root):
                pass
            if root in {Path("/"), self.state.home}:
                raise ValueError("缓存目录不能是文件系统根目录或用户主目录")
            device = root.stat().st_dev
            repository = repository_at(root)
            if repository:
                self.state.repositories[repository.root] = repository
            self._scan_cache_tree(root, category, reason, repository, device)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.state.errors.append(f"缓存扫描失败 {display(root)}: {exc}")

    def user_cache_roots(self) -> list[Path]:
        """返回平台缓存与日志根目录，供缓存扫描和项目扫描边界共用。"""
        roots = [Path(os.environ.get("XDG_CACHE_HOME", str(self.state.home / ".cache")))]
        if sys.platform == "darwin":
            roots.extend([self.state.home / "Library/Caches", self.state.home / "Library/Logs"])
        return list(dict.fromkeys(roots))

    def scan_user_cache(self) -> None:
        """根据平台选择用户缓存和 macOS 用户日志目录。"""
        for root in self.user_cache_roots():
            self.state.progress.visit(root)
            self.scan_cache(root, Category.USER_CACHE, "用户缓存或日志，按修改时间保留最近内容")

    def scan_homebrew(self) -> None:
        """枚举 Homebrew 下载缓存文件，保留已安装软件与版本。"""
        executable = shutil.which(Tool.BREW)
        if not executable:
            self.state.add_note("brew", "未安装，跳过")
            return
        self.state.protected_parts.add(Path(executable).absolute().parts)
        try:
            root = Path(query_text([executable, "--cache"]))
            self.scan_cache(root, Category.TOOLS, "Homebrew 下载缓存；保留已安装软件与版本")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.state.add_note("brew", str(exc))

    def scan(self) -> None:
        """执行已选类别的只读扫描并按文件占用排序。"""
        if self.state.args.fast_deps and self.state.args.older_than is not None:
            self.state.add_note("说明", "指定了 --older-than，依赖目录改用完整扫描。")
        stages = (
            ({Category.USER_CACHE}, "扫描用户缓存与日志", self.scan_user_cache),
            (PROJECT_CATEGORIES, "扫描项目", self._scan_project_roots),
            ({Category.TOOLS}, "扫描 Homebrew 下载缓存", self.scan_homebrew),
        )
        for categories, description, scan in stages:
            if categories & self.state.args.categories:
                with self.state.progress.phase(description):
                    scan()
        self._deduplicate_candidates()

    def _scan_project_roots(self) -> None:
        """遍历已合并的项目根目录，避免为每种项目类别重复扫描。"""
        for root in self.state.args.roots:
            self.scan_projects(root)
        self.state.candidates = [
            item for item in self.state.candidates if item.repository not in self.state.skipped_repositories
        ]
        self.state.candidate_paths = {item.path for item in self.state.candidates}

    def _deduplicate_candidates(self) -> None:
        """去除重叠文件候选，保留运行环境并按占用排序。"""
        unique = []
        kept = set()
        for item in sorted(self.state.candidates, key=lambda item: len(item.path.parts)):
            if self.inspector.excluded(item.path, item.root, deleting=True):
                self.state.add_note("保留运行环境或工具所在目录", path=item.path)
                continue
            if item.path not in kept and not any(parent in kept for parent in item.path.parents):
                unique.append(item)
                kept.add(item.path)
        self.state.candidates = unique
        self.state.candidates.sort(key=lambda item: (-(item.size or 0), str(item.path)))

    def _cache_entry_allowed(self, entry: os.DirEntry, path: Path, root: Path, category: Category) -> bool:
        """应用缓存条目的路径保护及原生工具目录排除规则。"""
        if entry.is_symlink() or self.inspector.excluded(path, root) or self.inspector.protected_name(path):
            return False
        if category == Category.USER_CACHE and path.parent == root and path.name.lower() in MANAGED_CACHE_NAMES:
            return False
        return True

    def _cache_file_eligible(
        self, path: Path, info: os.stat_result, category: Category, repository: Repository | None
    ) -> bool:
        """缓存只选择过期且未被 Git 跟踪的普通文件。"""
        return (
            stat.S_ISREG(info.st_mode)
            and info.st_mtime <= self.inspector.cutoff(category)
            and (not repository or not repository.contains_tracked(path))
        )

    def _scan_project_entries(
        self,
        entries: list[os.DirEntry],
        scope: ProjectScope,
        repository: Repository | None,
        project: Project,
        pending: list[Candidate],
    ) -> list[tuple[Path, Repository | None, Project]]:
        """记录本层候选，返回需要继续遍历的子目录。"""
        children: list[tuple[Path, Repository | None, Project]] = []
        for entry in entries:
            selected = self._project_entry(entry, scope, project)
            if selected is None:
                continue
            path, is_dir = selected
            match = self.project_match(path, project, is_dir)
            if path.name in DEPENDENCIES and Category.DEPS in self.state.args.categories and not match:
                self.state.add_note("保留无法从项目配置重建的依赖目录", path=path)
            if match and (repository or project.kinds):
                category, rebuild = match
                pending.append(
                    Candidate(
                        path,
                        scope.root,
                        category,
                        "项目标记与生成物规则",
                        rebuild,
                        repository.root if repository else None,
                        project.manifests,
                    )
                )
            elif is_dir and path.name not in DEPENDENCIES:
                children.append((path, repository, project))
        return children

    # pylint: disable=too-many-return-statements
    def _project_entry(self, entry: os.DirEntry, scope: ProjectScope, project: Project) -> tuple[Path, bool] | None:
        """筛选可检查的生成物或目录，保留挂载点、配置与保护路径。"""
        self.state.progress.visit(entry.path)
        if entry.is_symlink():
            return None
        is_dir = entry.is_dir(follow_symlinks=False)
        if not is_dir and entry.name not in DEPENDENCIES and self._project_file_category(entry.name, project) is None:
            return None
        path = Path(entry.path)
        if self.inspector.excluded(path, scope.root) or self.inspector.protected_name(path):
            return None
        if any(is_within(path, cache) for cache in scope.cache_roots):
            self.state.add_note("项目扫描跳过全局缓存与日志目录", path=path)
            return None
        if path in project.manifests:
            return None
        info = entry.stat(follow_symlinks=False)
        is_dir = stat.S_ISDIR(info.st_mode)
        if info.st_dev != scope.device or (is_dir and path.is_mount()):
            self.state.add_note("跳过挂载点", path=path)
            return None
        return path, is_dir

    def _scan_cache_tree(
        self, root: Path, category: Category, reason: str, repository: Repository | None, device: int
    ) -> None:
        """遍历缓存子树，只记录独立过期文件并跳过内部仓库。"""
        stack = [root]
        while stack:
            current = stack.pop()
            with os.scandir(current) as stream:
                entries = sorted(stream, key=lambda entry: entry.name, reverse=True)
            for entry in entries:
                path = Path(entry.path)
                self.state.progress.visit(path)
                if not self._cache_entry_allowed(entry, path, root, category):
                    continue
                info = entry.stat(follow_symlinks=False)
                if info.st_dev != device or (stat.S_ISDIR(info.st_mode) and path.is_mount()):
                    continue
                if stat.S_ISDIR(info.st_mode):
                    if os.path.lexists(path / ".git"):
                        self.state.add_note("跳过缓存内仓库", path=path)
                        continue
                    stack.append(path)
                elif self._cache_file_eligible(path, info, category, repository):
                    self.add_candidate(
                        Candidate(
                            path,
                            root,
                            category,
                            reason,
                            "工具或应用再次运行时重建",
                            repository.root if repository else None,
                        )
                    )

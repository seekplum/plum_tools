"""识别 Git 边界、忽略规则及项目重建配置。"""

from __future__ import annotations

import bisect
import fnmatch
import json
import os
import shlex
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from ..utils.compat import tomllib
from .constants import (
    BUILD_COMMANDS,
    NODE_INSTALL_COMMANDS,
    PROJECT_MARKERS,
    PYTHON_INSTALL_COMMANDS,
    PYTHON_MARKERS,
    ProjectKind,
)
from .filesystem import display, query, query_text, signature


@dataclass
class Repository:
    """保存一个仓库的跟踪文件快照并批量查询忽略规则。"""

    root: Path
    tracked: list[str] | None = None

    @classmethod
    def load(cls, root: Path) -> Repository:
        """读取仓库根目录与索引；Git 失败时拒绝推断。"""
        top = Path(query_text(["git", "-C", str(root), "rev-parse", "--show-toplevel"]))
        repository = cls(top)
        repository.load_index()
        return repository

    def load_index(self) -> list[str]:
        """按需读取并缓存索引，失败时拒绝将仓库视为无跟踪文件。"""
        if self.tracked is None:
            result = query(["git", "-C", str(self.root), "ls-files", "-z", "--cached"])
            if result.returncode:
                raise ValueError(f"无法读取 Git 索引: {display(self.root)}")
            self.tracked = sorted(os.fsdecode(item) for item in result.stdout.split(b"\0") if item)
        return self.tracked

    def contains_tracked(self, path: Path) -> bool:
        """判断路径本身或其子树中是否存在已跟踪文件。"""
        tracked = self.load_index()
        if path == self.root:
            return bool(tracked)
        relative = path.relative_to(self.root).as_posix()
        index = bisect.bisect_left(tracked, relative)
        if index < len(tracked) and tracked[index] == relative:
            return True
        prefix = relative + "/"
        index = bisect.bisect_left(tracked, prefix)
        return index < len(tracked) and tracked[index].startswith(prefix)

    def ignored(self, paths: list[Path]) -> dict[Path, str]:
        """批量查询 Git 忽略依据，保留嵌套规则、全局规则与否定规则语义。"""
        if not paths:
            return {}
        data = b"".join(os.fsencode(path.relative_to(self.root)) + b"\0" for path in paths)
        result = query(["git", "-C", str(self.root), "check-ignore", "-z", "-v", "--stdin"], data)
        if result.returncode not in (0, 1):
            raise ValueError(f"无法查询 Git 忽略规则: {display(self.root)}")
        fields = result.stdout.split(b"\0")
        ignored = {}
        for offset in range(0, len(fields) - 1, 4):
            source, line, pattern, name = map(os.fsdecode, fields[offset : offset + 4])
            if not pattern.startswith("!"):
                ignored[self.root / name] = f"{source}:{line}: {pattern}"
        directories = [path for path in paths if path not in ignored and path.is_dir()]
        if directories:
            result = query(
                [
                    "git",
                    "-C",
                    str(self.root),
                    "ls-files",
                    "-z",
                    "--others",
                    "--exclude-standard",
                    "--",
                    *(str(path.relative_to(self.root)) for path in directories),
                ]
            )
            if result.returncode:
                raise ValueError(f"无法检查目录内的非忽略文件: {display(self.root)}")
            visible = [self.root / os.fsdecode(name) for name in result.stdout.split(b"\0") if name]
            for path in directories:
                if not any(path == name or path in name.parents for name in visible):
                    ignored[path] = "生成物目录内的文件均被 Git 忽略"
        return ignored


def repository_at(path: Path, *, load_index: bool = True) -> Repository | None:
    """区分非 Git 目录与 Git 查询失败，防止失败时降级成无保护清理。"""
    marker = next(
        (parent / ".git" for parent in (path, *path.parents) if os.path.lexists(parent / ".git")),
        None,
    )
    if marker:
        info = marker.lstat()
        if stat.S_ISREG(info.st_mode) and info.st_size == 0:
            raise ValueError(f"空 .git 占位文件阻止仓库发现: {display(marker)}")
    if not shutil.which("git"):
        if marker:
            raise ValueError(f"目录位于仓库内，但 Git 命令不可用: {display(path)}")
        return None
    probe = query(
        [
            "git",
            "-C",
            str(path),
            "rev-parse",
            "--is-inside-work-tree",
            "--show-toplevel",
        ]
    )
    inside, _, top = probe.stdout.partition(b"\n")
    if inside == b"false":
        raise ValueError(f"目录不属于可清理的 Git 工作树: {display(path)}")
    if probe.returncode == 0:
        if inside != b"true" or not top.strip():
            raise ValueError(f"目录不属于可清理的 Git 工作树: {display(path)}")
        repository = Repository(Path(os.fsdecode(top).strip()))
        if load_index:
            repository.load_index()
        return repository
    if marker or inside == b"true" or os.environ.get("GIT_DIR") or os.environ.get("GIT_WORK_TREE"):
        raise ValueError(f"Git 状态查询失败，拒绝按非仓库处理: {display(path)}")
    return None


@dataclass
class Project:
    """保存项目类型、重建方式和必须保留的配置快照。"""

    kinds: set[ProjectKind] = field(default_factory=set)
    manifests: dict[Path, tuple[int, ...]] = field(default_factory=dict)
    rebuild: dict[ProjectKind, str] = field(default_factory=dict)

    @classmethod
    def detect(cls, path: Path, inherited: Project, entries: list[os.DirEntry] | None = None) -> Project:
        """复用目录条目识别项目标记，没有新标记时沿用父项目。"""
        if entries is None:
            with os.scandir(path) as stream:
                entries = list(stream)
        files = {
            item.name: item
            for item in entries
            if (
                item.name in PROJECT_MARKERS
                or item.name.endswith(".py")
                or fnmatch.fnmatchcase(item.name, "requirements*.txt")
            )
            and item.is_file(follow_symlinks=False)
        }
        if not files:
            return inherited
        names = set(files)
        markers = names & PROJECT_MARKERS
        markers.update(name for name in names if fnmatch.fnmatchcase(name, "requirements*.txt"))
        project = cls()
        project._detect_node(path, names)
        project._detect_python(path, names, markers)
        for marker, kind, command in BUILD_COMMANDS:
            if marker in names:
                project.kinds.add(kind)
                project.rebuild[kind] = command
        if not project.kinds:
            return inherited
        project.manifests = {path / name: signature(files[name].stat(follow_symlinks=False)) for name in markers}
        return project

    def _detect_node(self, path: Path, names: set[str]) -> None:
        """根据 package.json 和锁文件记录 Node 项目的依赖重建命令。"""
        if "package.json" not in names:
            return
        with (path / "package.json").open() as stream:
            config = json.load(stream)
        if not isinstance(config, dict):
            raise ValueError(f"无效的 package.json: {display(path)}")
        self.kinds.add(ProjectKind.NODE)
        if any(
            config.get(key)
            for key in (
                "dependencies",
                "devDependencies",
                "optionalDependencies",
                "peerDependencies",
                "workspaces",
            )
        ):
            self.rebuild[ProjectKind.NODE] = next(
                (command for marker, command in NODE_INSTALL_COMMANDS if marker in names),
                "npm install",
            )

    def _detect_python(self, path: Path, names: set[str], markers: set[str]) -> None:
        """识别 Python 项目，仅在依赖声明可重建时记录环境安装方式。"""
        requirements = sorted(name for name in markers if name.startswith("requirements"))
        if not (markers & PYTHON_MARKERS or requirements or any(name.endswith(".py") for name in names)):
            return
        self.kinds.add(ProjectKind.PYTHON)
        pyproject = {}
        if "pyproject.toml" in names:
            with (path / "pyproject.toml").open("rb") as stream:
                pyproject = tomllib.load(stream)
        command = self._python_rebuild(names, requirements, pyproject)
        if command:
            self.rebuild[ProjectKind.PYTHON] = command

    @staticmethod
    def _python_rebuild(names: set[str], requirements: list[str], pyproject: dict) -> str:
        """按锁文件和依赖声明的优先级返回 Python 重建命令。"""
        for marker, command in PYTHON_INSTALL_COMMANDS:
            if marker in names:
                return command
        if requirements:
            requirement = "requirements.txt" if "requirements.txt" in requirements else requirements[0]
            return f"python3 -m venv <环境目录>；<环境目录>/bin/pip install -r {shlex.quote(requirement)}"
        tools = pyproject.get("tool", {})
        if "setup.py" in names or "project" in pyproject or (isinstance(tools, dict) and tools.get("poetry")):
            return "python3 -m venv <环境目录>；<环境目录>/bin/pip install ."
        return ""

"""封装文件身份保护、候选计量及回收站操作。"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

from trashcli.lib.my_input import RealInput
from trashcli.put.clock import RealClock
from trashcli.put.fs.real_fs import RealFs
from trashcli.put.main import RandomIntGenerator, make_cmd
from trashcli.put.my_logger import StreamBackend

from plum_tools._cleanup.constants import (
    BUILD_DIRS,
    CATEGORY_PROTECTED_PATTERNS,
    DEPENDENCIES,
    PROJECT_CACHES,
    PROTECTED_NAMES,
    PROTECTED_PATTERNS,
    QUERY_ENV,
    USER_DATA_NAMES,
    Category,
    PackageChecks,
    ScanTuning,
)

if TYPE_CHECKING:
    from .models import Candidate
    from .state import CleanupState


def display(path: Path | str) -> str:
    """转义路径中的换行和控制字符，返回适合终端显示的文本。"""
    return json.dumps(str(path), ensure_ascii=False)


def is_within(path: Path, parent: Path) -> bool:
    """按路径分段判断相同或下级路径，避免构造父路径对象。"""
    return path.parts[: len(parent.parts)] == parent.parts


def signature(info: os.stat_result) -> tuple[int, ...]:
    """返回用于识别文件替换或变更的元数据。"""
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
    )


def human_size(value: int) -> str:
    """将字节数格式化为可读容量。"""
    if value == 0:
        return "0 B"
    number = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(number) < 1024 or unit == "TiB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return str(value)


def format_reason(reason: str) -> str:
    """输出依据时省略 Git 忽略规则的行号，原始计划仍保留完整来源。"""
    return re.sub(r"^(.*?):[0-9]+: (.*)$", r"\1: \2", reason, flags=re.DOTALL)


def query(command: list[str], data: bytes | None = None) -> subprocess.CompletedProcess:
    """执行有超时的只读命令，返回原始输出和退出码。"""
    # 参数列表不经过 shell，路径与 Docker 模板只作为普通参数传递。
    return subprocess.run(  # nosec B603
        command,
        input=data,
        capture_output=True,
        timeout=20,
        check=False,
        cwd=Path.home(),
        env={**os.environ, **QUERY_ENV},
    )


def query_text(command: list[str]) -> str:
    """读取成功查询的文本结果，失败时抛出明确错误。"""
    result = query(command)
    if result.returncode:
        raise ValueError(f"查询失败（退出码 {result.returncode}）: {shlex.join(command)}")
    return os.fsdecode(result.stdout).strip()


@contextmanager
def directory_fd(path: Path) -> Iterator[int]:
    """逐层打开真实目录，拒绝任何祖先软链接，最后关闭描述符。"""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        yield descriptor
    finally:
        os.close(descriptor)


class Trash:
    """封装 trash-cli 命令对象，在同一进程中复用并收集错误。"""

    def __init__(self) -> None:
        """加载当前 Python 环境的 trash-cli，创建非交互回收所需的命令对象。"""

        self.errors = StringIO()
        self.command = make_cmd(
            clock=RealClock(),
            fs=RealFs(),
            user_input=RealInput(),
            randint=RandomIntGenerator(),
            backend=StreamBackend(self.errors),
        )

    def put(self, path: Path, expected: tuple[int, ...]) -> None:
        """校验路径身份后移入回收站，失败时抛出错误供调用方停止后续清理。"""
        with directory_fd(path.parent) as parent:
            current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if signature(current) != expected:
                raise ValueError(f"文件已变化，跳过: {display(path)}")
            self.errors.seek(0)
            self.errors.truncate()
            # 库仅接受路径；保持父目录校验，但无法消除校验与移动间的并发窗口。
            code = self.command.run_put(["trash-put", "--", str(path)], os.environ, os.getuid())
            if code:
                detail = self.errors.getvalue().strip()
                raise ValueError(f"trash-cli 失败（退出码 {code}）: {detail}")
            if os.path.lexists(path):
                raise ValueError("trash-cli 返回成功，但原路径仍然存在，请检查回收结果")


def remove_candidate(candidate: Candidate, records: dict[Path, tuple[int, ...]], trash: Trash) -> None:
    """使用目录描述符复核整棵候选树，再将候选整体移入回收站。"""
    children: dict[Path, set[str]] = {}
    for path in records:
        if path != candidate.path:
            children.setdefault(path.parent, set()).add(path.name)

    def validate(parent: int, path: Path) -> None:
        expected = records[path]
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if signature(info) != expected:
            raise ValueError(f"文件已变化，跳过: {display(path)}")
        if stat.S_ISDIR(info.st_mode):
            descriptor = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                if signature(os.fstat(descriptor)) != expected:
                    raise ValueError(f"目录已被替换: {display(path)}")
                names = set(os.listdir(descriptor))
                if names != children.get(path, set()):
                    raise ValueError(f"目录内容已变化: {display(path)}")
                for name in sorted(names):
                    validate(descriptor, path / name)
                current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    raise ValueError(f"目录已被移动，保留当前位置: {display(path)}")
            finally:
                os.close(descriptor)

    with directory_fd(candidate.path.parent) as descriptor:
        validate(descriptor, candidate.path)
        trash.put(candidate.path, records[candidate.path])


class FileInspector:
    """按固定保护规则验证文件并计量候选树。"""

    def __init__(self, state: CleanupState) -> None:
        """绑定本组件使用的运行状态和协作组件。"""
        self.state = state

    def excluded(self, path: Path, root: Path, deleting: bool = False) -> bool:
        """判断显式排除规则及当前运行环境是否与候选范围相交。"""
        if not deleting and self.state.args.save_plan and path == self.state.plan_path:
            return True
        parts = path.parts
        for protected in self.state.protected_parts:
            if parts[: len(protected)] == protected or (deleting and protected[: len(parts)] == parts):
                return True
        if not self.state.args.exclude:
            return False
        root_parts = root.parts
        if parts[: len(root_parts)] != root_parts:
            raise ValueError(f"路径不在扫描根目录内: {display(path)}")
        # 根目录本身可能位于被排除的子树内，因此路径规则也检查扫描根以上的祖先。
        ancestors = (path, *path.parents)
        for value in self.state.args.exclude:
            pattern = os.path.normpath(os.path.expanduser(value))
            if "/" not in value and not value.startswith("~") and value not in {".", ".."}:
                if any(
                    fnmatch.fnmatchcase(parent.name, pattern)
                    for parent in ancestors[: len(parts) - len(root_parts) + 1]
                ):
                    return True
            else:
                pattern = os.path.normpath(os.path.join(root, pattern))
                if any(fnmatch.fnmatchcase(str(parent), pattern) for parent in ancestors):
                    return True
        return False

    @staticmethod
    def _package_marker(path: Path, checks: PackageChecks | None, *, follow_symlinks: bool = False) -> bool:
        """按包标记缓存普通文件身份，保持原有链接判断语义。"""
        key = path, follow_symlinks
        if checks is not None and key in checks:
            return checks[key] is not None
        try:
            info = path.stat(follow_symlinks=follow_symlinks)
            result = signature(info) if stat.S_ISREG(info.st_mode) else None
        except OSError:
            result = None
        if checks is not None:
            checks[key] = result
        return result is not None

    def _in_node_package(self, path: Path, candidate: Candidate, checks: PackageChecks | None = None) -> bool:
        """识别普通、作用域和嵌套 Node 包，仅接受具有真实清单的包内容。"""
        names = {"node_modules", ".node_modules"}
        parts = path.relative_to(candidate.path).parts
        offsets = [index + 1 for index, name in enumerate(parts) if name in names]
        if candidate.path.name in names:
            offsets.insert(0, 0)
        if not offsets:
            return False
        offset = offsets[-1]
        package = parts[offset:]
        if not package or package[0].startswith("."):
            return False
        depth = 2 if package[0].startswith("@") else 1
        if len(package) <= depth:
            return False
        root = candidate.path.joinpath(*parts[: offset + depth])
        return self._package_marker(root / "package.json", checks)

    def _in_dependency_package(self, path: Path, candidate: Candidate, checks: PackageChecks | None = None) -> bool:
        """限定可重建依赖包的内容边界，保留环境根目录和未确认的包。"""
        if candidate.category not in {Category.DEPS, Category.BUILD}:
            return False
        if candidate.category == Category.BUILD:
            return candidate.path.name in BUILD_DIRS and self._in_node_package(path, candidate, checks)
        if candidate.path.name in {"node_modules", ".node_modules"}:
            return self._in_node_package(path, candidate, checks)
        parts = path.relative_to(candidate.path).parts
        if candidate.path.name in {".tox", ".nox"}:
            if not parts or not self._package_marker(
                candidate.path / parts[0] / "pyvenv.cfg", checks, follow_symlinks=True
            ):
                return False
            parts = parts[1:]
        return (
            candidate.path.name in {".venv", "venv", ".tox", ".nox"}
            and len(parts) > 4
            and parts[0] in {"lib", "lib64"}
            and re.fullmatch(r"python\d+\.\d+t?", parts[1]) is not None
            and parts[2] == "site-packages"
        )

    def protected_name(
        self,
        path: Path,
        candidate: Candidate | None = None,
        checks: PackageChecks | None = None,
    ) -> bool:
        """按候选边界识别敏感数据，避免包内容和内置缓存名称误判。"""
        category = candidate.category if candidate else None
        patterns = CATEGORY_PROTECTED_PATTERNS.get(category, PROTECTED_PATTERNS) if category else PROTECTED_PATTERNS
        package_content = bool(
            candidate
            and (
                path.name in USER_DATA_NAMES
                or path.name.endswith(".key")
                or path.name == ".env"
                or path.name.startswith(".env.")
            )
            and self._in_dependency_package(path, candidate, checks)
        )
        if package_content:
            patterns = tuple(pattern for pattern in patterns if pattern not in {"*.key", ".env", ".env.*"})
        # 仅内置缓存的子树具有明确生成物语义，自定义目录仍保护同名数据。
        allow_user_data = (
            category == Category.DEPS
            or package_content
            or (
                candidate is not None
                and category == Category.PROJECT_CACHE
                and candidate.path.name in PROJECT_CACHES
                and len(path.parts) > len(candidate.path.parts)
                and is_within(path, candidate.path)
            )
        )
        return (
            path.name in PROTECTED_NAMES
            or (not allow_user_data and path.name in USER_DATA_NAMES)
            or any(fnmatch.fnmatchcase(path.name, pattern) for pattern in patterns)
        )

    def cutoff(self, category: Category) -> float:
        """计算类别的保留时间，项目产物默认不限制时间。"""
        days = self.state.args.older_than
        if days is None:
            days = 30 if category in {Category.USER_CACHE, Category.TOOLS, Category.DOCKER} else 0
        return self.state.now - days * 86400

    def uses_directory_snapshot(self, candidate: Candidate) -> bool:
        """仅无保留时间限制的依赖目录允许使用快速快照。"""
        return (
            self.state.args.fast_deps
            and self.state.args.older_than is None
            and candidate.category == Category.DEPS
            and candidate.path.name in DEPENDENCIES
        )

    def directory_snapshot(self, candidate: Candidate) -> tuple[int, ...]:
        """只检查真实目录本身的身份、挂载边界和排除条件，不遍历内部。"""
        with directory_fd(candidate.path) as descriptor:
            info = os.fstat(descriptor)
        if info.st_dev != candidate.root.stat().st_dev or candidate.path.is_mount():
            raise ValueError(f"包含挂载点或跨文件系统路径: {display(candidate.path)}")
        if self.excluded(candidate.path, candidate.root, deleting=True) or self.protected_name(
            candidate.path, candidate
        ):
            raise ValueError(f"包含受保护或排除路径: {display(candidate.path)}")
        return signature(info)

    def measure(  # pylint: disable=too-many-locals
        self,
        candidate: Candidate,
        records: dict | None = None,
        *,
        record_limit: int | None = None,
        progress: Callable[[Path, int], None] | None = None,
    ) -> tuple[int, str, float, int]:
        """不跟随软链接地计量候选，遇到保护项或跨文件系统时拒绝整项。"""
        digest = hashlib.blake2b()
        device = candidate.root.stat().st_dev
        inodes, size, newest, files = set(), 0, 0.0, 0
        package_checks: PackageChecks = {}
        visit = progress or self.state.progress.visit
        nodes = 0
        stack: list[tuple[Path | os.DirEntry, str]] = [(candidate.path, candidate.path.name)]
        try:
            while stack:
                entry, relative = stack.pop()
                path = entry if isinstance(entry, Path) else Path(entry.path)
                nodes += 1
                if nodes >= ScanTuning.PROGRESS_BATCH:
                    visit(path, nodes)
                    nodes = 0
                info = path.lstat() if isinstance(entry, Path) else entry.stat(follow_symlinks=False)
                self._validate_node(path, info, candidate, package_checks, device)
                current = signature(info)
                digest.update(os.fsencode(relative))
                digest.update(repr(current).encode())
                if records is not None:
                    if record_limit is not None and len(records) >= record_limit:
                        # 不缓存截断快照；超限候选在执行到该项时重新收集完整记录。
                        records.clear()
                        records = None
                    else:
                        records[path] = current
                newest = max(newest, info.st_mtime)
                identity = info.st_dev, info.st_ino
                if identity not in inodes:
                    inodes.add(identity)
                    size += info.st_blocks * 512
                if stat.S_ISDIR(info.st_mode):
                    # 摘要依赖遍历顺序，排序确保独立 scan/show/run 的结果一致。
                    with os.scandir(path) as stream:
                        stack.extend(
                            (item, relative + "/" + item.name)
                            for item in sorted(stream, key=lambda item: item.name, reverse=True)
                        )
                else:
                    files += 1
        finally:
            if nodes:
                visit(path, nodes)
        for (marker, follow_symlinks), expected in package_checks.items():
            if expected is not None and signature(marker.stat(follow_symlinks=follow_symlinks)) != expected:
                raise ValueError(f"依赖包标记在扫描期间发生变化: {display(marker)}")
        return size, digest.hexdigest(), newest, files

    def _validate_node(
        self,
        path: Path,
        info: os.stat_result,
        candidate: Candidate,
        package_checks: PackageChecks,
        device: int,
    ) -> None:
        """在计量前验证节点的设备边界、保护规则与文件类型。"""
        if info.st_dev != device or (stat.S_ISDIR(info.st_mode) and path.is_mount()):
            raise ValueError(f"包含挂载点或跨文件系统路径: {display(path)}")
        if self.excluded(path, candidate.root, deleting=True) or self.protected_name(path, candidate, package_checks):
            raise ValueError(f"包含受保护或排除路径: {display(path)}")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise ValueError(f"包含特殊文件: {display(path)}")

"""提供本地及 SSH 远端共用的扫描逻辑，可仅依赖标准库独立执行。"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path

# 分块读取文件，避免大文件占用过多内存。
CHUNK_SIZE = 1024 * 1024

# 默认跳过系统、编辑器及依赖环境生成的子项。
DEFAULT_EXCLUDE_NAMES = (
    ".DS_Store",
    ".idea",
    ".node_modules",
    "node_modules",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
)


@dataclass(frozen=True)
class Entry:
    """保存条目的路径、类型、大小、链接目标及可选的远端摘要。"""

    path: Path
    kind: str
    size: int = 0
    target: str = ""
    digest: str | None = None


def read_entry(path: Path) -> Entry:
    """读取路径的类型及元信息，返回条目；符号链接不跟随目标。"""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return Entry(path, "链接", target=os.readlink(path))
    if stat.S_ISDIR(info.st_mode):
        return Entry(path, "目录")
    if stat.S_ISREG(info.st_mode):
        return Entry(path, "文件", size=info.st_size)
    raise ValueError(f"不支持的文件类型：{path}")


def file_md5(entry: Entry, chunk_size: int = CHUNK_SIZE) -> str:
    """分块计算文件的完整 MD5；读取期间文件变化时抛出异常。"""
    digest = hashlib.md5(usedforsecurity=False)
    with entry.path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if before.st_size != entry.size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise OSError(f"比较期间文件发生变化：{entry.path}")
    return digest.hexdigest()


def exclusion_rules(exclude_names: Sequence[str], exclude_paths: Sequence[str]) -> tuple[set[str], set[Path]]:
    """校验普通名称及相对路径规则，返回保留通配符的规范化集合。"""
    names = set(exclude_names)
    for name in names:
        if not name or name in (".", "..") or "/" in name or "\x00" in name:
            raise ValueError(f"排除名称必须是单个目录名或文件名：{name!r}")
    paths = set()
    for value in exclude_paths:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts or path == Path(".") or "\x00" in value:
            raise ValueError(f"排除路径必须是输入根目录内的相对路径：{value!r}")
        paths.add(path)
    return names, paths


def _exclusion_regex(value: str) -> re.Pattern[str]:
    if not value[3:] or "\x00" in value:
        raise ValueError(f"无效的排除正则：{value!r}")
    try:
        return re.compile(value[3:])
    except re.error as exc:
        raise ValueError(f"无效的排除正则 {value!r}：{exc}") from exc


def _path_glob_matches(path: Path, pattern: Path) -> bool:
    # 按路径分段推进匹配位置，确保 * 不跨目录，** 可匹配零层或多层，避免递归回溯。
    positions = {0}
    for part in pattern.parts:
        if part == "**":
            positions = set(range(min(positions), len(path.parts) + 1))
        else:
            positions = {
                index + 1
                for index in positions
                if index < len(path.parts) and fnmatch.fnmatchcase(path.parts[index], part)
            }
        if not positions:
            return False
    return len(path.parts) in positions


def exclusion_matcher(exclude_names: Sequence[str], exclude_paths: Sequence[str]) -> Callable[[Path], bool]:
    """校验并预处理通配符和 re: 正则规则，返回判断相对子项是否排除的函数。"""
    names, paths = exclusion_rules(
        [value for value in exclude_names if not value.startswith("re:")],
        [value for value in exclude_paths if not value.startswith("re:")],
    )
    name_regexes = tuple(_exclusion_regex(value) for value in exclude_names if value.startswith("re:"))
    path_regexes = tuple(_exclusion_regex(value) for value in exclude_paths if value.startswith("re:"))
    name_globs = tuple(value for value in names if any(char in value for char in "*?["))
    path_globs = tuple(value for value in paths if any(char in str(value) for char in "*?["))
    names.difference_update(name_globs)
    paths.difference_update(path_globs)

    def matches(path: Path) -> bool:
        if path.name in names or path in paths:
            return True
        return (
            any(fnmatch.fnmatchcase(path.name, pattern) for pattern in name_globs)
            or any(_path_glob_matches(path, pattern) for pattern in path_globs)
            or any(pattern.fullmatch(path.name) is not None for pattern in name_regexes)
            or any(pattern.fullmatch(path.as_posix()) is not None for pattern in path_regexes)
        )

    return matches


def scan(
    root: Entry,
    hash_files: bool = False,
    *,
    exclude_names: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
    default_excludes: bool = True,
    max_depth: int | None = None,
) -> dict[Path, Entry]:
    """按排除规则及可选深度扫描，返回条目映射，可同时计算文件摘要；根目录为第 0 层。"""
    if max_depth is not None and (isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 1):
        raise ValueError("比较深度必须是大于等于 1 的整数")
    names = (*exclude_names, *(DEFAULT_EXCLUDE_NAMES if default_excludes else ()))
    is_excluded = exclusion_matcher(names, exclude_paths)
    entries = {Path("."): root}
    pending = [Path(".")] if root.kind == "目录" else []
    while pending:
        relative = pending.pop()
        for child in entries[relative].path.iterdir():
            key = relative / child.name
            # 在读取元信息前排除，避免进入依赖目录或读取其中无法访问的文件。
            if is_excluded(key):
                continue
            entries[key] = read_entry(child)
            if entries[key].kind == "目录" and (max_depth is None or len(key.parts) < max_depth):
                pending.append(key)
    if hash_files:
        for relative, entry in entries.items():
            if entry.kind == "文件":
                entries[relative] = replace(entry, digest=file_md5(entry))
    return entries


def main() -> None:
    """扫描参数指定的远端路径，将清单和摘要以 JSON 写入标准输出。"""
    try:
        if sys.version_info < (3, 9):
            raise ValueError(f"远端需要 Python 3.9+，当前版本为 {sys.version.split()[0]}")
        exclusions = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        root = read_entry(Path(sys.argv[1]).expanduser().absolute())
        entries = scan(root, hash_files=True, **exclusions)
        print(json.dumps({str(key): {**asdict(entry), "path": str(entry.path)} for key, entry in entries.items()}))
    except (OSError, ValueError) as exc:
        print(f"远端扫描失败：{exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

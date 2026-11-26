"""读取多个输入并计算各路径的内容差异。"""

import json
import os
import re
import shlex
import shutil
import subprocess
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from plum_tools._compare import remote
from plum_tools._compare.models import CompareResult, Comparison
from plum_tools._compare.remote import CHUNK_SIZE as _CHUNK_SIZE
from plum_tools._compare.remote import Entry, EntryKind
from plum_tools.utils.cli import run_process


def _file_md5(entry: Entry) -> str:
    return entry.digest if entry.digest is not None else remote.file_md5(entry, _CHUNK_SIZE)


def _split_remote(path: str | Path) -> tuple[str, str] | None:
    value = os.fspath(path)
    match = re.match(r"^((?:[^/@:\s]+@)?(?:\[[^\]\s]+\]|[^/@:\s]+)):(.*)$", value, re.DOTALL)
    if match is None:
        return None
    host, remote_path = match.groups()
    if host.startswith("-") or not remote_path or "\x00" in value:
        raise ValueError(f"无效的远端路径：{value}")
    return re.sub(r"\[([^\]]+)\]$", r"\1", host), remote_path


def _decode_remote_tree(output: str) -> dict[Path, Entry]:
    data = json.loads(output)
    if not isinstance(data, dict) or "." not in data:
        raise ValueError("缺少根条目")
    entries = {}
    for relative, row in data.items():
        key = Path(relative)
        if key.is_absolute() or ".." in key.parts or str(key) != relative:
            raise ValueError("无效的相对路径")
        entry = Entry(**{**row, "path": Path(row["path"])})
        if entry.kind not in tuple(EntryKind) or not isinstance(entry.target, str):
            raise ValueError("无效的条目类型或链接目标")
        if not isinstance(entry.size, int) or isinstance(entry.size, bool) or entry.size < 0:
            raise ValueError("无效的文件大小")
        if entry.kind == EntryKind.FILE and (
            not isinstance(entry.digest, str) or not re.fullmatch("[0-9a-f]{32}", entry.digest)
        ):
            raise ValueError("缺少有效的 MD5 摘要")
        entries[key] = entry
    for key in entries:
        if key != Path(".") and (key.parent not in entries or entries[key.parent].kind != EntryKind.DIRECTORY):
            raise ValueError("缺少父目录条目")
    return entries


def _scan_remote(
    host: str,
    path: str,
    exclude_names: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
    default_excludes: bool = True,
    max_depth: int | None = None,
) -> dict[Path, Entry]:
    # 复用同一份标准库扫描代码，避免远端依赖安装及两端比较规则漂移。
    script = Path(remote.__file__).read_text(encoding="utf-8")
    ssh = shutil.which("ssh")
    if ssh is None:
        raise OSError("找不到 ssh 命令，请先安装 OpenSSH 客户端")
    options = json.dumps(
        {
            "exclude_names": list(exclude_names),
            "exclude_paths": list(exclude_paths),
            "default_excludes": default_excludes,
            "max_depth": max_depth,
        }
    )
    # 本地按参数列表调用，远端路径单独转义，避免路径中的 shell 字符被执行。
    process: subprocess.CompletedProcess[str] = run_process(
        [ssh, "-T", "-o", "ConnectTimeout=10", "--", host, shlex.join(["python3", "-", path, options])],
        input=script,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode:
        detail = process.stderr.strip() or f"退出码 {process.returncode}"
        raise OSError(f"远端读取失败（{host}:{path}）：{detail}")
    try:
        return _decode_remote_tree(process.stdout)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"远端返回的文件清单无效（{host}:{path}）：{exc}") from exc


def _signatures(entries: tuple[Entry | None, ...]) -> list[tuple[object, ...] | None]:
    sizes = Counter(entry.size for entry in entries if entry is not None and entry.kind == EntryKind.FILE)
    signatures: list[tuple[object, ...] | None] = []
    for entry in entries:
        if entry is None:
            signatures.append(None)
        elif entry.kind == EntryKind.FILE:
            digest = _file_md5(entry) if sizes[entry.size] > 1 else ""
            signatures.append((entry.kind, entry.size, digest))
        else:
            signatures.append((entry.kind, entry.target))
    return signatures


def _result(entries: tuple[Entry | None, ...], groups: tuple[int, ...]) -> CompareResult:
    present = [entry for entry in entries if entry is not None]
    if len(present) != len(entries):
        return CompareResult.MISSING
    if len({entry.kind for entry in present}) > 1:
        return CompareResult.TYPE_DIFFERENT
    if len(set(groups)) == 1:
        return CompareResult.IDENTICAL
    if present[0].kind == EntryKind.DIRECTORY:
        return CompareResult.CHILDREN_DIFFERENT
    if present[0].kind == EntryKind.LINK:
        return CompareResult.LINK_TARGET_DIFFERENT
    return (
        CompareResult.SIZE_DIFFERENT if len({entry.size for entry in present}) > 1 else CompareResult.CONTENT_DIFFERENT
    )


def _load_trees(
    paths: Sequence[str | Path],
    exclude_names: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
    default_excludes: bool = True,
    max_depth: int | None = None,
) -> list[dict[Path, Entry]]:
    if len(paths) < 2:
        raise ValueError("至少需要两个路径")
    if max_depth is not None and (isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 1):
        raise ValueError("比较深度必须是大于等于 1 的整数")
    remote.exclusion_matcher(exclude_names, exclude_paths)
    trees = []
    for path in paths:
        remote_path = _split_remote(path)
        if remote_path is not None:
            trees.append(_scan_remote(*remote_path, exclude_names, exclude_paths, default_excludes, max_depth))
        else:
            root = remote.read_entry(Path(path).expanduser().absolute())
            trees.append(
                remote.scan(
                    root,
                    exclude_names=exclude_names,
                    exclude_paths=exclude_paths,
                    default_excludes=default_excludes,
                    max_depth=max_depth,
                )
            )
    if len({tree[Path(".")].kind == EntryKind.DIRECTORY for tree in trees}) > 1:
        raise ValueError("不能混合比较目录和文件（符号链接按链接本身比较）")
    return trees


def compare_paths(
    paths: Sequence[str | Path],
    *,
    exclude_names: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
    default_excludes: bool = True,
    max_depth: int | None = None,
    ignore_case: bool = False,
) -> list[Comparison]:
    """按排除规则及可选深度比较路径并返回结果；ignore_case 忽略相对路径大小写，重名时报错。"""
    trees = _load_trees(paths, exclude_names, exclude_paths, default_excludes, max_depth)
    if not ignore_case:
        return _compare_trees(trees)
    folded, original_paths = _casefold_trees(trees)
    comparisons = [replace(item, path=original_paths[item.path]) for item in _compare_trees(folded)]
    return sorted(comparisons, key=lambda item: item.path)


def _casefold_trees(trees: Sequence[dict[Path, Entry]]) -> tuple[list[dict[Path, Entry]], dict[Path, Path]]:
    """折叠相对路径的大小写，校验单个输入内重名，并保留最先出现的原始路径用于展示。"""
    folded = []
    original_paths: dict[Path, Path] = {}
    for index, tree in enumerate(trees, start=1):
        entries: dict[Path, Entry] = {}
        for relative, entry in tree.items():
            key = Path(str(relative).casefold())
            if key in entries:
                raise ValueError(f"输入 [{index}] 存在大小写路径冲突：{entries[key].path} 与 {entry.path}")
            entries[key] = entry
            original_paths.setdefault(key, relative)
        folded.append(entries)
    return folded, original_paths


def _compare_trees(trees: Sequence[dict[Path, Entry]]) -> list[Comparison]:
    """自底向上比较已扫描的条目，将子项差异传递到父目录。"""
    relative_paths = set().union(*(tree.keys() for tree in trees))
    children: dict[Path, list[Path]] = defaultdict(list)
    for relative in sorted(relative_paths):
        if relative != Path("."):
            children[relative.parent].append(relative)
    identities: list[dict[Path, int]] = [{} for _ in trees]
    interned: dict[tuple[object, ...], int] = {}
    comparisons = []
    # 先处理子项，再复用其身份判断目录，确保任意深度的差异都能传递到父目录。
    for relative in sorted(relative_paths, key=lambda path: (-len(path.parts), path)):
        entries = tuple(tree.get(relative) for tree in trees)
        groups = []
        for index, (entry, signature) in enumerate(zip(entries, _signatures(entries), strict=True)):
            if entry is not None and entry.kind == EntryKind.DIRECTORY:
                signature = (
                    entry.kind,
                    tuple(
                        (child.name, identities[index][child]) for child in children[relative] if child in trees[index]
                    ),
                )
            identities[index][relative] = 0 if signature is None else interned.setdefault(signature, len(interned) + 1)
            groups.append(identities[index][relative])
        comparisons.append(Comparison(relative, entries, tuple(groups), _result(entries, tuple(groups))))
    return sorted(comparisons, key=lambda item: item.path)

"""递归比较多个目录或文件，使用 Rich 分开展示一致和不一致的条目。"""

import hashlib
import os
import stat
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .utils.parser import get_base_parser

# 分块读取文件，避免大文件占用过多内存。
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class Entry:
    """保存条目的实际路径、类型、大小及符号链接目标。"""

    path: Path
    kind: str
    size: int = 0
    target: str = ""


@dataclass(frozen=True)
class Comparison:
    """保存一个相对路径在所有输入中的条目、内容分组及比较结果。"""

    path: Path
    entries: tuple[Entry | None, ...]
    groups: tuple[int, ...]
    result: str


def _read_entry(path: Path) -> Entry:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        return Entry(path, "链接", target=os.readlink(path))
    if stat.S_ISDIR(info.st_mode):
        return Entry(path, "目录")
    if stat.S_ISREG(info.st_mode):
        return Entry(path, "文件", size=info.st_size)
    raise ValueError(f"不支持的文件类型：{path}")


def _scan(root: Entry) -> dict[Path, Entry]:
    entries = {Path("."): root}
    pending = [Path(".")] if root.kind == "目录" else []
    while pending:
        relative = pending.pop()
        for child in entries[relative].path.iterdir():
            key = relative / child.name
            entries[key] = _read_entry(child)
            if entries[key].kind == "目录":
                pending.append(key)
    return entries


def _file_md5(entry: Entry) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with entry.path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    if before.st_size != entry.size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise OSError(f"比较期间文件发生变化：{entry.path}")
    return digest.hexdigest()


def _signatures(entries: tuple[Entry | None, ...]) -> list[tuple[object, ...] | None]:
    sizes = Counter(entry.size for entry in entries if entry is not None and entry.kind == "文件")
    signatures: list[tuple[object, ...] | None] = []
    for entry in entries:
        if entry is None:
            signatures.append(None)
        elif entry.kind == "文件":
            digest = _file_md5(entry) if sizes[entry.size] > 1 else ""
            signatures.append((entry.kind, entry.size, digest))
        else:
            signatures.append((entry.kind, entry.target))
    return signatures


def _result(entries: tuple[Entry | None, ...], groups: tuple[int, ...]) -> str:
    present = [entry for entry in entries if entry is not None]
    if len(present) != len(entries):
        return "缺失"
    if len({entry.kind for entry in present}) > 1:
        return "类型不同"
    if len(set(groups)) == 1:
        return "一致"
    if present[0].kind == "目录":
        return "子项不同"
    if present[0].kind == "链接":
        return "链接目标不同"
    return "大小不同" if len({entry.size for entry in present}) > 1 else "内容不同"


def _load_trees(paths: Sequence[Path]) -> list[dict[Path, Entry]]:
    if len(paths) < 2:
        raise ValueError("至少需要两个路径")
    roots = [_read_entry(path.expanduser().absolute()) for path in paths]
    if len({entry.kind == "目录" for entry in roots}) > 1:
        raise ValueError("不能混合比较目录和文件（符号链接按链接本身比较）")
    return [_scan(root) for root in roots]


def compare_paths(paths: Sequence[Path]) -> list[Comparison]:
    """比较至少两个同类路径，返回按相对路径排序的结果；输入或读取失败时抛出异常。"""
    trees = _load_trees(paths)
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
        signatures = _signatures(entries)
        groups = []
        for index, (entry, signature) in enumerate(zip(entries, signatures, strict=True)):
            if entry is not None and entry.kind == "目录":
                signature = (
                    entry.kind,
                    tuple(
                        (child.name, identities[index][child]) for child in children[relative] if child in trees[index]
                    ),
                )
            identity = 0 if signature is None else interned.setdefault(signature, len(interned) + 1)
            identities[index][relative] = identity
            groups.append(identity)
        comparisons.append(Comparison(relative, entries, tuple(groups), _result(entries, tuple(groups))))
    return sorted(comparisons, key=lambda item: item.path)


def _report_table(rows: Sequence[Comparison], path_count: int, identical: bool) -> Table:
    style = "green" if identical else "red"
    title = "一致的目录 / 文件" if identical else "不一致的目录 / 文件"
    table = Table(title=f"{title}（{len(rows)}）", header_style="bold", border_style=style)
    table.add_column("相对路径", overflow="fold")
    for index in range(1, path_count + 1):
        table.add_column(f"[{index}]", overflow="fold")
    table.add_column("结果", style=style)
    for item in rows:
        labels = []
        row_groups: dict[int, int] = {}
        for entry, identity in zip(item.entries, item.groups, strict=True):
            if entry is None:
                labels.append(Text("缺失", style="yellow"))
                continue
            group = row_groups.setdefault(identity, len(row_groups) + 1)
            label = f"{entry.kind} · 组{group}"
            if entry.kind == "链接":
                label += f" → {entry.target}"
            labels.append(Text(label))
        table.add_row(Text(str(item.path)), *labels, item.result)
    return table


def print_report(paths: Sequence[Path], comparisons: Sequence[Comparison], console: Console) -> None:
    """将比较结果分为一致和不一致两张表，输出到指定控制台并汇总数量。"""
    for index, path in enumerate(paths, start=1):
        console.print(Text(f"[{index}] {path.expanduser().absolute()}"))
    console.print("同一行中组号相同表示内容一致；目录包含全部子项，. 表示根条目。")
    for identical in (True, False):
        rows = [item for item in comparisons if (item.result == "一致") == identical]
        console.print(_report_table(rows, len(paths), identical))
    same = sum(item.result == "一致" for item in comparisons)
    different = len(comparisons) - same
    console.print(f"整体{'一致' if not different else '不一致'}：一致 {same} 项，不一致 {different} 项。")


def main() -> None:
    """解析路径参数并展示结果；退出码 0 表示一致，1 表示差异，2 表示错误。"""
    parser = get_base_parser()
    parser.description = "比较两个及以上目录或文件，使用 Rich 表格分开展示一致和不一致的条目。"  # noqa
    parser.epilog = (
        "示例：\n"
        "  pcompare ./old ./new\n"
        "  pcompare ./a.txt ./b.txt ./c.txt\n\n"
        "目录递归比较，文件按内容比较，符号链接仅比较链接目标。\n"
        "退出码：0 内容一致，1 存在差异，2 输入或读取失败。"
    )
    parser.add_argument("paths", nargs="+", type=Path, metavar="路径", help="要比较的目录或文件，至少两个")
    args = parser.parse_args()
    try:
        comparisons = compare_paths(args.paths)
        print_report(args.paths, comparisons, Console())
    except (OSError, ValueError) as exc:
        Console(stderr=True).print(Text(f"比较失败：{exc}", style="red"))
        raise SystemExit(2) from exc
    raise SystemExit(int(any(item.result != "一致" for item in comparisons)))


if __name__ == "__main__":
    main()

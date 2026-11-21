"""递归比较多个目录或文件，使用 Rich 分开展示一致和不一致的条目。"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import _compare_remote
from ._compare_remote import CHUNK_SIZE as _CHUNK_SIZE
from ._compare_remote import Entry
from .utils.parser import add_compact_argument, get_base_parser
from .utils.printer import compact_table


@dataclass(frozen=True)
class Comparison:
    """保存一个相对路径在所有输入中的条目、内容分组及比较结果。"""

    path: Path
    entries: tuple[Entry | None, ...]
    groups: tuple[int, ...]
    result: str


def _file_md5(entry: Entry) -> str:
    return entry.digest if entry.digest is not None else _compare_remote.file_md5(entry, _CHUNK_SIZE)


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
        if entry.kind not in ("目录", "文件", "链接") or not isinstance(entry.target, str):
            raise ValueError("无效的条目类型或链接目标")
        if not isinstance(entry.size, int) or isinstance(entry.size, bool) or entry.size < 0:
            raise ValueError("无效的文件大小")
        if entry.kind == "文件" and (
            not isinstance(entry.digest, str) or not re.fullmatch("[0-9a-f]{32}", entry.digest)
        ):
            raise ValueError("缺少有效的 MD5 摘要")
        entries[key] = entry
    for key in entries:
        if key != Path(".") and (key.parent not in entries or entries[key.parent].kind != "目录"):
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
    script = Path(_compare_remote.__file__).read_text(encoding="utf-8")
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
    process = subprocess.run(  # nosec B603
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
    _compare_remote.exclusion_rules(exclude_names, exclude_paths)
    trees = []
    for path in paths:
        remote = _split_remote(path)
        if remote is not None:
            trees.append(_scan_remote(*remote, exclude_names, exclude_paths, default_excludes, max_depth))
        else:
            root = _compare_remote.read_entry(Path(path).expanduser().absolute())
            trees.append(
                _compare_remote.scan(
                    root,
                    exclude_names=exclude_names,
                    exclude_paths=exclude_paths,
                    default_excludes=default_excludes,
                    max_depth=max_depth,
                )
            )
    if len({tree[Path(".")].kind == "目录" for tree in trees}) > 1:
        raise ValueError("不能混合比较目录和文件（符号链接按链接本身比较）")
    return trees


def compare_paths(
    paths: Sequence[str | Path],
    *,
    exclude_names: Sequence[str] = (),
    exclude_paths: Sequence[str] = (),
    default_excludes: bool = True,
    max_depth: int | None = None,
) -> list[Comparison]:
    """按排除规则及可选深度比较本地或 host:path 路径，返回排序后的范围内结果。"""
    return _compare_trees(_load_trees(paths, exclude_names, exclude_paths, default_excludes, max_depth))


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
            if entry is not None and entry.kind == "目录":
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


def _report_table(rows: Sequence[Comparison], path_count: int, identical: bool, *, compact: bool = False) -> Table:
    style = "green" if identical else "red"
    title = "一致的目录 / 文件" if identical else "不一致的目录 / 文件"
    table = Table(title=f"{title}（{len(rows)}）", header_style="bold", border_style=style)
    if compact:
        compact_table(table)
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
            label = f"{entry.kind}/组{group}" if compact else f"{entry.kind} · 组{group}"
            if entry.kind == "链接":
                label += f" → {entry.target}"
            labels.append(Text(label))
        table.add_row(Text(str(item.path)), *labels, item.result)
    return table


def print_report(
    paths: Sequence[str | Path],
    comparisons: Sequence[Comparison],
    console: Console,
    *,
    hide_identical: bool = False,
    compact: bool = False,
    max_depth: int | None = None,
) -> None:
    """向 console 输出比较表格及范围汇总，可隐藏一致项或精简布局；max_depth 标明扫描深度。"""
    for index, path in enumerate(paths, start=1):
        label = str(path) if _split_remote(path) is not None else str(Path(path).expanduser().absolute())
        console.print(Text(f"[{index}] {label}"))
    if max_depth is None:
        console.print("同一行中组号相同表示内容一致；目录包含全部子项，. 表示根条目。")
    else:
        console.print(f"比较范围：最多 {max_depth} 层（根目录为第 0 层），未检查更深层内容。")
        console.print("同一行中组号相同表示当前深度内一致；目录仅包含范围内子项，. 表示根条目。")
    for identical in (True, False):
        if identical and hide_identical:
            continue
        rows = [item for item in comparisons if (item.result == "一致") == identical]
        console.print(_report_table(rows, len(paths), identical, compact=compact))
    same = sum(item.result == "一致" for item in comparisons)
    different = len(comparisons) - same
    scope = "整体" if max_depth is None else "当前深度内"
    console.print(f"{scope}{'一致' if not different else '不一致'}：一致 {same} 项，不一致 {different} 项。")


def main() -> None:
    """解析路径参数并展示结果；退出码 0 表示一致，1 表示差异，2 表示错误。"""
    parser = get_base_parser()
    add_compact_argument(parser)
    parser.description = "比较两个及以上目录或文件，默认仅展示不一致的条目。"  # noqa
    parser.epilog = (
        "示例：\n"
        "  pcompare ./old ./new\n"
        "  pcompare 'seekplum:~/Downloads' ~/Downloads\n"
        "  pcompare ./a.txt ./b.txt ./c.txt\n"
        "  pcompare ./old ./new --exclude-name node_modules --exclude-name .venv\n"
        "  pcompare ./old ./new --exclude-path packages/web/dist --no-hide-identical\n\n"
        "  pcompare ./old ./new --quick\n"
        "  pcompare ./old ./new -L 3 --no-default-excludes\n\n"
        "目录递归比较，文件按内容比较，符号链接仅比较链接目标。\n"
        "远端路径使用 [user@]host:path，支持 SSH 别名；远端需要 Python 3.9+。\n"
        "退出码：0 内容一致，1 存在差异，2 输入或读取失败。"
    )
    parser.add_argument("paths", nargs="+", metavar="路径", help="要比较的本地或 host:path 路径，至少两个")
    parser.add_argument(
        "--hide-identical",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="隐藏一致的目录、文件和链接条目（默认开启）",
    )
    parser.add_argument(
        "--exclude-name",
        action="append",
        default=[],
        metavar="名称",
        help="按目录名或文件名精确排除任意层级的条目，可重复传入",
    )
    parser.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        metavar="相对路径",
        help="按相对于各输入根目录的路径精确排除条目，可重复传入",
    )
    parser.add_argument(
        "--no-default-excludes",
        dest="default_excludes",
        action="store_false",
        help="关闭默认名称排除：" + "、".join(_compare_remote.DEFAULT_EXCLUDE_NAMES),
    )
    parser.add_argument("--quick", action="store_true", help="快速比较，默认只扫描 2 层；可用 --max-depth 覆盖")
    parser.add_argument("--max-depth", "-L", type=int, metavar="层数", help="限制扫描深度，至少为 1，根目录为第 0 层")
    args = parser.parse_args()
    max_depth = args.max_depth if args.max_depth is not None else (2 if args.quick else None)
    console = Console()
    try:
        with console.status("正在扫描并比较…", spinner="dots"):
            comparisons = compare_paths(
                args.paths,
                exclude_names=args.exclude_name,
                exclude_paths=args.exclude_path,
                default_excludes=args.default_excludes,
                max_depth=max_depth,
            )
        print_report(
            args.paths,
            comparisons,
            console,
            hide_identical=args.hide_identical,
            compact=args.compact,
            max_depth=max_depth,
        )
    except (OSError, ValueError) as exc:
        Console(stderr=True).print(Text(f"比较失败：{exc}", style="red"))
        raise SystemExit(2) from exc
    raise SystemExit(int(any(item.result != "一致" for item in comparisons)))


if __name__ == "__main__":
    main()

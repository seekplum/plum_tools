"""检查命令行或文件中的 fork / 父仓库对在指定本地目录下的存在状态。"""

import argparse
import json
import stat
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from plum_tools.utils.cli import cli_entry
from plum_tools.utils.parser import add_compact_argument, get_base_parser
from plum_tools.utils.printer import compact_table
from plum_tools.utils.sorting import add_sort_argument, sort_items


class RepoStatus(StrEnum):
    """表示仓库对的四种目录存在状态。"""

    BOTH = "fork 与父仓库均存在"
    FORK_ONLY = "仅 fork 存在"
    PARENT_ONLY = "仅父仓库存在"
    NONE = "均不存在"


# 状态颜色供表格和全量统计复用，文字仍保留完整含义。
_STATUS_STYLES = {
    RepoStatus.BOTH: "green",
    RepoStatus.FORK_ONLY: "yellow",
    RepoStatus.PARENT_ONLY: "cyan",
    RepoStatus.NONE: "red",
}


@dataclass(frozen=True)
class RepoRow:
    """保存来源编号、仓库对及各自命中的目标标签。"""

    index: int
    fork: str
    parent: str
    fork_hits: tuple[str, ...]
    parent_hits: tuple[str, ...]

    @property
    def status(self) -> RepoStatus:
        """根据当前行的 fork 与父仓库命中标签返回存在状态。"""
        if self.fork_hits and self.parent_hits:
            return RepoStatus.BOTH
        if self.fork_hits:
            return RepoStatus.FORK_ONLY
        if self.parent_hits:
            return RepoStatus.PARENT_ONLY
        return RepoStatus.NONE


def _repo_reference(value: str) -> str:
    parts = value.split("/")
    if (
        len(parts) != 2
        or any(part in ("", ".", "..") for part in parts)
        or any(char.isspace() or char in "\\\x00" for char in value)
    ):
        raise argparse.ArgumentTypeError(f"仓库格式无效：{value!r}，应为 owner/repo")
    return value


def build_parser() -> argparse.ArgumentParser:
    """创建文件或仓库对互斥输入、目标目录及状态筛选的参数解析器。"""
    parser = get_base_parser()
    add_sort_argument(
        parser,
        {
            "index": "原始编号",
            "fork": "fork",
            "parent": "父仓库",
            "status": "状态代码",
            "fork_hits": "fork 命中目录数",
            "parent_hits": "父仓库命中目录数",
            "hits": "命中目录数合计",
        },
    )
    parser.description = "检查 fork / 父仓库在指定本地目录下的存在状态。"
    parser.epilog = (
        "示例：\n"
        "  pforkcheck --data ./repos.txt --target ~/projects\n"
        "  pforkcheck --pair alice/project upstream/project --target ~/projects\n"
        "  pforkcheck --data ./repos.txt --target ~/projects/python --target ~/projects/web --status FORK_ONLY\n"
        "  pforkcheck --data ./repos.txt --target ~/projects --json\n\n"
        "文件每行格式：<fork owner/repo> <父仓库 owner/repo>。\n"
        "目录匹配：目标目录/owner/repo 或目标目录/repo；不递归扫描或校验 Git 元数据。\n\n"
        "状态：\n" + "\n".join(f"  {status.name:<12} {status.value}" for status in RepoStatus)
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", metavar="FILE", help="UTF-8 仓库对文件路径，与 --pair 二选一，无默认文件")
    source.add_argument(
        "--pair",
        nargs=2,
        action="append",
        type=_repo_reference,
        metavar=("FORK", "PARENT"),
        help="指定 fork 和父仓库，均为 owner/repo；可重复指定，与 --data 二选一",
    )
    parser.add_argument(
        "--target", required=True, action="append", metavar="PATH", help="本地目标目录，必填且可重复指定，无默认目录"
    )
    parser.add_argument(
        "--status",
        action="append",
        type=str.upper,
        choices=tuple(status.name for status in RepoStatus),
        metavar="STATUS",
        help="按状态筛选，可重复指定、大小写不敏感；默认显示全部，可用值见下方说明",
    )
    add_compact_argument(parser)
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="以 JSON 输出结果，忽略 --compact；默认使用表格"
    )
    return parser


def _is_directory(path: Path) -> bool:
    # 只有路径缺失属于未命中，权限等读取错误必须继续上报，避免误判为仓库不存在。
    try:
        return stat.S_ISDIR(path.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


def _resolve_targets(paths: list[str]) -> dict[str, Path]:
    targets: dict[str, Path] = {}
    for index, value in enumerate(paths, 1):
        if not value:
            raise ValueError("目标路径不能为空")
        path = Path(value).expanduser().resolve()
        if not _is_directory(path):
            raise ValueError(f"目标路径不是已存在的目录：{path}")
        targets[f"T{index}"] = path
    return targets


def _load_pairs(path: Path) -> tuple[list[tuple[int, str, str]], int]:
    pairs: list[tuple[int, str, str]] = []
    skipped = 0
    with path.open(encoding="utf-8-sig") as source:
        for line_no, line in enumerate(source, 1):
            parts = line.split()
            if not parts:
                continue
            if len(parts) < 2:
                skipped += 1
                continue
            try:
                fork, parent = (_repo_reference(value) for value in parts[:2])
            except argparse.ArgumentTypeError:
                skipped += 1
                continue
            pairs.append((line_no, fork, parent))
    return pairs, skipped


def _find_repo(repo: str, targets: dict[str, Path]) -> tuple[str, ...]:
    owner, name = repo.split("/")
    return tuple(
        label for label, root in targets.items() if _is_directory(root / owner / name) or _is_directory(root / name)
    )


def _select_rows(rows: list[RepoRow], statuses: set[RepoStatus]) -> tuple[list[RepoRow], dict[RepoStatus, int]]:
    counts = dict.fromkeys(RepoStatus, 0)
    selected: list[RepoRow] = []
    for row in rows:
        status = row.status
        counts[status] += 1
        if not statuses or status in statuses:
            selected.append(row)
    return selected, counts


def _repository_cell(repo: str, hits: tuple[str, ...]) -> Text:
    cell = Text(repo)
    cell.append("\n")
    cell.append("存在：" + ", ".join(hits) if hits else "未找到", style="green" if hits else "dim")
    return cell


def _result_table(rows: list[RepoRow], *, from_file: bool, compact: bool) -> Table:
    table = Table(title="仓库对检查", expand=True)
    if compact:
        compact_table(table)
    table.add_column("行号" if from_file else "序号", justify="right", no_wrap=True)
    table.add_column("状态", overflow="fold")
    table.add_column("fork 仓库", ratio=1, overflow="fold")
    table.add_column("父仓库", ratio=1, overflow="fold")
    for row in rows:
        table.add_row(
            Text(str(row.index)),
            Text(row.status.value, style=_STATUS_STYLES[row.status]),
            _repository_cell(row.fork, row.fork_hits),
            _repository_cell(row.parent, row.parent_hits),
            end_section=not compact,
        )
    return table


def _print_results(
    rows: list[RepoRow],
    targets: dict[str, Path],
    statuses: set[RepoStatus],
    skipped: int,
    *,
    from_file: bool,
    compact: bool = False,
) -> None:
    console = Console()
    console.print(Text("目标目录：", style="bold"))
    for label, path in targets.items():
        console.print(Text.assemble((f"  {label}", "cyan"), f"  {path}"))
    if statuses:
        console.print(Text("筛选状态：" + ", ".join(status.value for status in RepoStatus if status in statuses)))
    selected, counts = _select_rows(rows, statuses)
    if selected:
        console.print(_result_table(selected, from_file=from_file, compact=compact))
    else:
        console.print(Text("没有符合筛选条件的仓库对。" if rows else "没有有效的仓库对。", style="yellow"))
    console.print(Text(f"检查 {len(rows)} 对 · 展示 {len(selected)} 对 · 跳过 {skipped} 行"))
    summary = Text()
    for status in RepoStatus:
        if summary:
            summary.append(" · ")
        summary.append(f"{status.value} {counts[status]}", style=_STATUS_STYLES[status])
    console.print(summary)
    if statuses:
        console.print(Text("全量统计，表格按筛选显示", style="dim"))


def _print_json_results(
    rows: list[RepoRow], targets: dict[str, Path], statuses: set[RepoStatus], skipped: int, *, data_path: Path | None
) -> None:
    selected, counts = _select_rows(rows, statuses)
    json.dump(
        {
            "schema_version": 1,
            "command": "pforkcheck",
            "options": {
                "source": "file" if data_path is not None else "pairs",
                "data_path": str(data_path) if data_path is not None else None,
                "statuses": [status.name for status in RepoStatus if status in statuses],
            },
            "targets": {label: str(path) for label, path in targets.items()},
            "summary": {
                "pair_count": len(rows),
                "shown_pair_count": len(selected),
                "skipped_count": skipped,
                "status_counts": {status.name: count for status, count in counts.items()},
            },
            "pairs": [
                {
                    "index": row.index,
                    "status": row.status.name,
                    "status_label": row.status.value,
                    "fork": row.fork,
                    "parent": row.parent,
                    "fork_hits": list(row.fork_hits),
                    "parent_hits": list(row.parent_hits),
                }
                for row in selected
            ],
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")


@cli_entry
def main() -> None:
    """解析 CLI 参数，检查仓库对并展示结果；输入或读取错误以状态码 2 退出。"""
    parser = build_parser()
    args = parser.parse_args()
    try:
        targets = _resolve_targets(args.target)
        data_path = Path(args.data).expanduser().resolve() if args.data is not None else None
        if data_path is not None:
            pairs, skipped = _load_pairs(data_path)
        else:
            pairs = [(index, fork, parent) for index, (fork, parent) in enumerate(args.pair, 1)]
            skipped = 0
        rows = [
            RepoRow(index, fork, parent, _find_repo(fork, targets), _find_repo(parent, targets))
            for index, fork, parent in pairs
        ]
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(f"无法检查仓库：{exc}")
    statuses = {RepoStatus[name] for name in args.status or ()}
    rows = sort_items(
        rows,
        args.sort,
        {
            "index": lambda row: row.index,
            "fork": lambda row: row.fork,
            "parent": lambda row: row.parent,
            "status": lambda row: row.status.name,
            "fork_hits": lambda row: len(row.fork_hits),
            "parent_hits": lambda row: len(row.parent_hits),
            "hits": lambda row: len(row.fork_hits) + len(row.parent_hits),
        },
    )
    if args.json_output:
        _print_json_results(rows, targets, statuses, skipped, data_path=data_path)
        return
    _print_results(rows, targets, statuses, skipped, from_file=data_path is not None, compact=args.compact)


if __name__ == "__main__":
    main()

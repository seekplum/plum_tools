"""生成终端表格和 JSON 报告。"""

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from plum_tools._compare.comparison import _split_remote
from plum_tools._compare.history import GitComparison
from plum_tools._compare.models import CompareResult, Comparison, ShowMode
from plum_tools._compare.remote import EntryKind
from plum_tools.utils.printer import compact_table, display_path


def _report_table(rows: Sequence[Comparison], path_count: int, identical: bool, *, compact: bool = False) -> Table:
    style = "green" if identical else "red"
    title = f"{CompareResult.IDENTICAL if identical else CompareResult.DIFFERENT}的目录 / 文件"
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
                labels.append(Text(CompareResult.MISSING, style="yellow"))
                continue
            group = row_groups.setdefault(identity, len(row_groups) + 1)
            label = f"{entry.kind}/组{group}" if compact else f"{entry.kind} · 组{group}"
            if entry.kind == EntryKind.LINK:
                label += f" → {display_path(entry.target)}"
            labels.append(Text(label))
        table.add_row(Text(str(item.path)), *labels, item.result)
    return table


def _print_inputs(paths: Sequence[str | Path], console: Console, git: GitComparison | None) -> None:
    for index, path in enumerate(paths, start=1):
        label = str(path) if _split_remote(path) is not None else display_path(Path(path).expanduser().absolute())
        head = git.heads[index - 1] if git else None
        if head:
            label += f" · {head.branch or 'HEAD'} · {head.commit[:12] or '无可用提交'}"
        console.print(Text(f"[{index}] {label}"))
    if git:
        for relation in git.relations:
            console.print(Text(relation.label(), style=relation.status.style))


def print_report(  # pylint: disable=too-many-arguments,too-many-locals
    paths: Sequence[str | Path],
    comparisons: Sequence[Comparison],
    console: Console,
    *,
    show: ShowMode | str = ShowMode.ALL,
    compact: bool = False,
    max_depth: int | None = None,
    ignore_case: bool = False,
    display_depth: int | None = None,
    git: GitComparison | None = None,
) -> None:
    """按 show 类型及可选展示深度输出表格，汇总始终包含全部已比较条目。"""
    if show not in tuple(ShowMode):
        raise ValueError(f"展示类型必须是 {ShowMode.ALL}、{ShowMode.IDENTICAL} 或 {ShowMode.DIFFERENT}")
    if display_depth is not None and (
        isinstance(display_depth, bool) or not isinstance(display_depth, int) or display_depth < 0
    ):
        raise ValueError("展示深度必须是大于等于 0 的整数")
    _print_inputs(paths, console, git)
    if ignore_case:
        console.print("忽略相对路径大小写，仍比较条目类型、文件内容和链接目标。")
    if max_depth is None:
        console.print("同一行中组号相同表示内容一致；目录包含全部子项，. 表示根条目。")
    else:
        console.print(f"比较范围：最多 {max_depth} 层（根目录为第 0 层），未检查更深层内容。")
        console.print("同一行中组号相同表示当前深度内一致；目录仅包含范围内子项，. 表示根条目。")
    if display_depth is not None:
        console.print(f"展示范围：最多 {display_depth} 层（根目录为第 0 层），汇总包含全部已比较条目。")
    for identical in (True, False):
        if show not in (ShowMode.ALL, ShowMode.IDENTICAL if identical else ShowMode.DIFFERENT):
            continue
        rows = [
            item
            for item in comparisons
            if (item.result == CompareResult.IDENTICAL) == identical
            and (display_depth is None or len(item.path.parts) <= display_depth)
        ]
        if rows:
            console.print(_report_table(rows, len(paths), identical, compact=compact))
    same = sum(item.result == CompareResult.IDENTICAL for item in comparisons)
    different = len(comparisons) - same
    scope = "整体" if max_depth is None else "当前深度内"
    result = CompareResult.DIFFERENT if different else CompareResult.IDENTICAL
    console.print(f"{scope}{result}：{CompareResult.IDENTICAL} {same} 项，{CompareResult.DIFFERENT} {different} 项。")


def _print_json_report(
    paths: Sequence[str | Path],
    comparisons: Sequence[Comparison],
    options: dict[str, object],
    *,
    display_depth: int | None = None,
    git: GitComparison | None = None,
) -> None:
    """按 display_depth 输出 comparisons 的 JSON 条目，汇总保留全部比较结果及 options。"""
    same = sum(item.result == CompareResult.IDENTICAL for item in comparisons)
    print(
        json.dumps(
            {
                "schema_version": 1,
                "command": "pcompare",
                "paths": [
                    str(path) if _split_remote(path) is not None else str(Path(path).expanduser().absolute())
                    for path in paths
                ],
                "options": options,
                **({"git": asdict(git)} if git else {}),
                "summary": {
                    "entry_count": len(comparisons),
                    "identical_count": same,
                    "different_count": len(comparisons) - same,
                    "identical": same == len(comparisons),
                },
                "entries": [
                    {
                        "path": str(item.path),
                        "identical": item.result == CompareResult.IDENTICAL,
                        "result": item.result,
                        "groups": item.groups,
                        "entries": [
                            (
                                {
                                    "path": str(entry.path),
                                    "kind": entry.kind,
                                    "size": entry.size,
                                    "target": entry.target,
                                }
                                if entry is not None
                                else None
                            )
                            for entry in item.entries
                        ],
                    }
                    for item in comparisons
                    if display_depth is None or len(item.path.parts) <= display_depth
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

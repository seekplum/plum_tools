"""展示仓库对检查结果。"""

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from plum_tools._fork_check.repositories import RepoRow, RepoStatus
from plum_tools.utils.printer import compact_table

# 状态颜色供表格和全量统计复用，文字仍保留完整含义。
_STATUS_STYLES = {
    RepoStatus.BOTH: "green",
    RepoStatus.FORK_ONLY: "yellow",
    RepoStatus.PARENT_ONLY: "cyan",
    RepoStatus.NONE: "red",
}


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

"""生成终端表格和 JSON 报告。"""

import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from threading import Lock

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from plum_tools._gitrepo.grouping import _build_scan_report, _remote_host, _repository_statuses
from plum_tools._gitrepo.models import DirectoryScanError, Repository, _ScanReport
from plum_tools.utils.printer import compact_table
from plum_tools.utils.sorting import SortField


class RepositoryProgress(Progress):
    """展示目录发现和仓库检查进度；重定向输出时关闭动态展示。"""

    def __init__(self, console: Console) -> None:
        super().__init__(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.fields[summary]}"),
            TimeElapsedColumn(),
            console=console,
            disable=not console.is_terminal,
            auto_refresh=console.is_terminal,
            refresh_per_second=4,
            transient=True,
        )
        self.directories = 0
        self.found = 0
        self.failed = 0
        self.completed = 0
        self.counter_lock = Lock()
        self.discovery = self.add_task("发现目录", total=None, summary="遍历 0 · 仓库 0")
        self.checking = self.add_task("检查仓库", total=None, summary="完成 0/0 · 失败 0")

    def discovered(self, found: bool) -> None:
        """累计一个已遍历目录，以 found 标记是否发现仓库并批量刷新。"""
        with self.counter_lock:
            self.directories += 1
            self.found += found
            if found or self.directories % 128 == 0:
                self.update(self.discovery, summary=f"遍历 {self.directories} · 仓库 {self.found}")
            if found:
                self.update(self.checking, summary=f"完成 {self.completed}/{self.found} · 失败 {self.failed}")

    def finish_discovery(self) -> None:
        """发现结束后固定检查总数，显示实际完成比例。"""
        with self.counter_lock:
            self.update(
                self.discovery,
                total=self.directories,
                completed=self.directories,
                summary=f"遍历 {self.directories} · 仓库 {self.found}",
            )
            self.stop_task(self.discovery)
            self.update(
                self.checking, total=self.found, summary=f"完成 {self.completed}/{self.found} · 失败 {self.failed}"
            )

    def checked(self, failed: bool) -> None:
        """按任务完成顺序累计检查数量及失败数。"""
        with self.counter_lock:
            self.failed += failed
            self.completed += 1
            self.update(self.checking, advance=1, summary=f"完成 {self.completed}/{self.found} · 失败 {self.failed}")


def write_json_result(
    command: str,
    summary: dict[str, int],
    repositories: list[dict],
    errors: list[DirectoryScanError],
    options: dict[str, object],
    *,
    schema_version: int = 1,
) -> None:
    """将 command 的仓库、目录错误、统计及选项以版本化 JSON 写入 stdout。"""
    json.dump(
        {
            "schema_version": schema_version,
            "command": command,
            "options": options,
            "summary": summary,
            "repositories": repositories,
            "directory_errors": [asdict(error) for error in errors],
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")


def print_directory_errors(console: Console, errors: list[DirectoryScanError], *, compact: bool = False) -> None:
    """将 errors 按原因分组展示到 console，compact 精简边框；无错误时不输出。"""
    if not errors:
        return
    grouped: dict[str, list[str]] = defaultdict(list)
    for error in errors:
        grouped[error.reason].append(error.path)
    table = Table(
        title=Text("目录扫描错误", style="bold red"),
        caption=Text(f"{len(grouped)} 种原因 · {len(errors)} 个目录"),
        expand=True,
    )
    table.add_column("出错原因", ratio=1, overflow="fold", style="red")
    table.add_column("目录", ratio=3, overflow="fold")
    if compact:
        compact_table(table)
    for reason, paths in sorted(grouped.items()):
        for index, path in enumerate(sorted(paths)):
            table.add_row(
                Text(reason if index == 0 else ""), Text(path), end_section=not compact and index == len(paths) - 1
            )
    console.print(table)


def _group_label(
    key: str, repos: list[Repository], group_by: str, duplicates: set[str], *, compact: bool = False
) -> Text:
    if group_by == "remote":
        key = key.removeprefix(f"{_remote_host(key)}/") if any(repo.remote_urls for repo in repos) else Path(key).name
    label = Text(key, style="bold cyan")
    if any(repo.path in duplicates for repo in repos):
        label.append(" · 重复克隆" if compact else "\n重复克隆", style="yellow")
    if group_by == "name" and len({repo.remote_url for repo in repos if repo.remote_url}) > 1:
        label.append(" · 同名仓库（远程不同）" if compact else "\n同名仓库（远程不同）", style="yellow")
    return label


def _repository_cells(  # noqa: C901
    repo: Repository, group_by: str, *, compact: bool = False, detail: bool = False, clean_label: str = ""
) -> tuple[Text, Text, Text, Text]:
    kind = "（裸仓库）" if repo.bare else "（worktree）" if repo.worktree else ""
    remote = repo.remote_name or "—"
    if repo.remotes:
        remote = (" · " if compact else "\n").join(
            f"{name}：{url}" for name, urls in repo.remotes.items() for url in urls
        )
    elif group_by == "name" and repo.remote_url:
        separator = " · " if compact else "\n"
        remote = f"{remote}{separator}{repo.remote_url}"
    status = Text((" · " if compact else "\n").join(repo.issues), style="yellow")
    if detail:
        details = []
        for change in repo.changes:
            path = repr(change["path"])
            if "original_path" in change:
                path = f"{repr(change['original_path'])} → {path}"
            if "submodule" in change:
                path = f"{path} {change['submodule']}"
            details.append(f"{change['status']} {path}")
        details.extend(repo.stashes)
        for line in details:
            if status:
                status.append("\n")
            status.append(line)
    for error in repo.errors:
        if status:
            status.append("\n")
        status.append(f"检查失败：{error}", style="red")
    if not repo.issues and not repo.errors:
        clean = "工作区干净，与跟踪引用一致" if not repo.bare else "与跟踪引用一致"
        if compact:
            clean = "干净 / 跟踪一致" if not repo.bare else "跟踪一致"
        status.append(clean_label or clean, style="green")
    return Text(f"{repo.path}{kind}"), Text(repo.branch or "—"), Text(remote), status


def _print_host_table(  # pylint: disable=too-many-arguments
    console: Console,
    host: str,
    groups: dict[str, list[Repository]],
    group_by: str,
    duplicates: set[str],
    *,
    compact: bool = False,
    detail: bool = False,
    clean_label: str = "",
) -> None:
    repos = [repo for group in groups.values() for repo in group]
    table = Table(
        title=Text(host, style="bold cyan"),
        caption=Text(
            f"{len(groups)} 个仓库组 · {len(repos)} 个目录 · "
            f"{len({repo.common_dir for repo in repos if repo.common_dir})} 个独立仓库"
        ),
        expand=True,
    )
    if compact:
        compact_table(table)
    table.add_column("仓库", ratio=2, overflow="fold")
    table.add_column("目录", ratio=3, overflow="fold")
    if detail:
        table.add_column("当前分支", min_width=8, max_width=20, overflow="fold")
        table.add_column("远程", ratio=2, overflow="fold")
    table.add_column("本地 / 跟踪状态", ratio=3, overflow="fold")
    for key, group in groups.items():
        for index, repo in enumerate(group):
            cells: tuple[Text, ...] = _repository_cells(
                repo, group_by, compact=compact, detail=detail, clean_label=clean_label
            )
            if not detail:
                cells = (cells[0], cells[-1])
            # 组内留空仓库列形成纵向合并，紧凑模式取消组间横线以节省行数。
            table.add_row(
                _group_label(key, group, group_by, duplicates, compact=compact) if index == 0 else Text(""),
                *cells,
                end_section=not compact and index == len(group) - 1,
            )
    console.print(table)


def _scan_json_repositories(report: _ScanReport) -> list[dict]:
    return [
        {
            **asdict(repo),
            "statuses": sorted(_repository_statuses(repo, report.duplicates)),
            "host": host,
            "group_key": key,
            "kind": "bare" if repo.bare else "worktree" if repo.worktree else "normal",
            "duplicate_clone": repo.path in report.duplicates,
            "has_issues": bool(repo.issues or repo.errors),
            "failed": bool(repo.errors),
        }
        for host, groups in report.groups.items()
        for key, group in groups.items()
        for repo in group
    ]


def _print_scan_results(  # pylint: disable=too-many-arguments
    console: Console,
    repos: list[Repository],
    errors: list[DirectoryScanError],
    group_by: str,
    statuses: tuple[str, ...],
    fetch: bool,
    host_filter: re.Pattern[str] | None = None,
    *,
    compact: bool = False,
    detail: bool = False,
    sort: list[SortField] | None = None,
    ignored_statuses: tuple[str, ...] = (),
) -> None:
    report = _build_scan_report(repos, errors, group_by, statuses, host_filter, sort)
    console.print(
        "已启用远程更新；更新失败的仓库按缓存检查。" if fetch else "远程差异依据本地缓存引用；使用 --fetch 可先更新。"
    )
    for host, groups in report.groups.items():
        _print_host_table(
            console,
            host,
            groups,
            group_by,
            report.duplicates,
            compact=compact,
            detail=detail,
            clean_label="其余检查正常" if ignored_statuses else "",
        )
    print_directory_errors(console, errors, compact=compact)
    summary = report.summary
    console.print(
        f"扫描 {summary['repository_count']} 个目录，{summary['independent_repository_count']} 个独立仓库；"
        f"展示 {summary['shown_group_count']}/{summary['group_count']} 个仓库组，"
        f"重复仓库 {summary['duplicate_group_count']} 组，异常仓库目录 {summary['issue_repository_count']} 个，"
        f"检查失败 {summary['failed_repository_count']} 个，扫描错误 {summary['directory_error_count']} 个。"
    )

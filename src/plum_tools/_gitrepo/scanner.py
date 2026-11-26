"""遍历仓库，并发检查并输出扫描结果。"""

import os
import re
from collections.abc import Generator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextvars import copy_context
from functools import partial
from pathlib import Path
from threading import Lock

from rich.console import Console

from plum_tools._gitrepo.grouping import _build_scan_report
from plum_tools._gitrepo.models import DirectoryScanError, Repository
from plum_tools._gitrepo.reporting import (
    RepositoryProgress,
    _print_scan_results,
    _scan_json_repositories,
    write_json_result,
)
from plum_tools._gitrepo.repository import _scan_repository
from plum_tools.utils.cli import cancel_current
from plum_tools.utils.sorting import SortField

# 限制并发外部进程数，避免大型目录扫描耗尽系统资源。
_MAX_WORKERS = 16


def walk_directories(
    paths: list[str], errors: list[DirectoryScanError], exclude: tuple[str, ...] = ()
) -> Generator[tuple[str, list[str], list[str]], None, None]:
    """遍历 paths 中不重复的目录并剪枝；按目录名排除 exclude，错误追加至 errors。"""
    visited: set[str] = set()

    def record_error(exc: OSError) -> None:
        errors.append(DirectoryScanError(str(exc.filename or "未知目录"), exc.strerror or str(exc)))

    for path in paths:
        try:
            base = Path(path).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            reason = (exc.strerror if isinstance(exc, OSError) else None) or str(exc)
            errors.append(DirectoryScanError(path, reason))
            continue
        if not base.is_dir():
            errors.append(DirectoryScanError(str(base), "扫描路径不是目录"))
            continue
        for root, dirs, files in os.walk(base, onerror=record_error):
            if root in visited:
                dirs.clear()
                continue
            visited.add(root)
            yield root, dirs, files
            dirs[:] = [name for name in dirs if name != ".git" and name not in exclude]


def iter_repositories(
    paths: list[str],
    errors: list[DirectoryScanError],
    exclude: tuple[str, ...] = (),
    progress: RepositoryProgress | None = None,
) -> Generator[str, None, None]:
    """遍历 paths，按目录名排除 exclude，逐个返回仓库路径。
    遍历错误追加至 errors，通过 progress 更新发现数量。
    """
    for root, dirs, files in walk_directories(paths, errors, exclude):
        found = ".git" in dirs or ".git" in files
        if not found and "HEAD" in files and "config" in files and "objects" in dirs:
            found = True
            dirs.clear()
        if progress is not None:
            progress.discovered(found)
        if found:
            yield root


def _collect_repositories(  # pylint: disable=too-many-locals
    paths: list[str],
    errors: list[DirectoryScanError],
    fetch: bool,
    exclude: tuple[str, ...] = (),
    progress: RepositoryProgress | None = None,
    stash: bool = True,
    detail: bool = False,
    *,
    ignored_statuses: tuple[str, ...] = (),
) -> list[Repository]:
    repos: list[Repository] = []
    scan_repository = partial(
        _scan_repository,
        fetch=fetch,
        shared={},
        lock=Lock(),
        stash=stash,
        detail=detail,
        ignored_statuses=ignored_statuses,
    )

    def report(future: Future[Repository]) -> None:
        if progress is not None and not future.cancelled():
            progress.checked(future.exception() is not None or bool(future.result().errors))

    def collect(done: set[Future[Repository]]) -> None:
        repos.extend(future.result() for future in done)

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        pending: set[Future[Repository]] = set()
        try:
            for path in iter_repositories(paths, errors, exclude, progress):
                future = pool.submit(copy_context().run, scan_repository, path)
                future.add_done_callback(report)
                pending.add(future)
                done = {future for future in pending if future.done()}
                collect(done)
                pending.difference_update(done)
                # 对未完成任务施加上限，避免仓库很多时占用无界内存。
                if len(pending) >= _MAX_WORKERS * 2:
                    done, pending = wait(pending, return_when=FIRST_COMPLETED)
                    collect(done)
            if progress is not None:
                progress.finish_discovery()
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                collect(done)
        except KeyboardInterrupt:
            cancel_current()
            for future in pending:
                future.cancel()
            raise
    return sorted(repos, key=lambda repo: repo.path)


def scan_projects(  # pylint: disable=too-many-arguments
    paths: list[str],
    group_by: str = "remote",
    statuses: tuple[str, ...] = ("all",),
    fetch: bool = False,
    exclude: tuple[str, ...] = (),
    stash: bool = True,
    host_filter: re.Pattern[str] | None = None,
    *,
    json_output: bool = False,
    compact: bool = False,
    detail: bool = False,
    sort: list[SortField] | None = None,
    ignored_statuses: tuple[str, ...] = (),
) -> None:
    """扫描 paths，按 group_by 合并，用 statuses 和 host_filter 筛选结果。
    detail 展示文件及 stash 详情；JSON 始终包含详情，compact 仅精简表格。
    """
    errors: list[DirectoryScanError] = []
    with RepositoryProgress(Console(stderr=json_output)) as progress:
        repos = _collect_repositories(
            paths,
            errors,
            fetch,
            exclude,
            progress,
            stash,
            detail or json_output,
            **({"ignored_statuses": ignored_statuses} if ignored_statuses else {}),
        )
    if json_output:
        report = _build_scan_report(repos, errors, group_by, statuses, host_filter, sort)
        write_json_result(
            "scan",
            report.summary,
            _scan_json_repositories(report),
            errors,
            {
                "group_by": group_by,
                "statuses": list(statuses),
                **({"ignored_statuses": list(ignored_statuses)} if ignored_statuses else {}),
                "fetch": fetch,
                "stash_checked": stash,
            },
            schema_version=2,
        )
        return
    _print_scan_results(
        Console(),
        repos,
        errors,
        group_by,
        statuses,
        fetch,
        host_filter,
        compact=compact,
        detail=detail,
        sort=sort,
        ignored_statuses=ignored_statuses,
    )

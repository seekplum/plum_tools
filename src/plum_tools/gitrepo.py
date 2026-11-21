"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: exceptions
#         Desc: 查找指定路径下所有被改动的git仓库
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-05 22:02
#=============================================================================
"""

import functools
import os
from collections.abc import Generator

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .conf import PROCESSES_NUMBER
from .exceptions import RunCmdError, RunCmdTimeout
from .git_scan import (
    DirectoryScanError,
    RepositoryProgress,
    add_scan_parser,
    print_directory_errors,
    scan_projects,
    walk_directories,
    write_json_result,
)
from .utils.cli import cli_entry
from .utils.cli import process_pool as Pool
from .utils.git import check_is_git_repository, check_repository_modify_status, check_repository_stash
from .utils.parser import get_base_parser
from .utils.printer import compact_table


def find_git_project_for_python(path: str) -> Generator[str, None, None]:
    """返回 path 下的普通 Git 仓库路径，遍历时跳过 .git 内部。"""
    for root, _, _ in walk_directories([path], []):
        if check_is_git_repository(root):
            yield root


def check_project(path: str, stash: bool = True) -> dict:
    """检查 path 的改动及可选 stash，返回路径、异常状态和详细输出。"""
    result = {
        "path": path,
        "status": False,
    }
    outputs = []
    try:
        status_result, status_out = check_repository_modify_status(path)
        if status_result:
            outputs.append(status_out)
        if stash:
            stash_result, stash_out = check_repository_stash(path)
            if stash_result:
                outputs.append(stash_out)
    except (RunCmdError, RunCmdTimeout, OSError) as exc:
        result["error"] = True
        outputs.append(f"检查失败：{exc}")
    if outputs:
        result.update(status=True, output="\n".join(outputs))
    return result


def _collect_check_results(
    projects: list[str], stash: bool, exclude: tuple[str, ...], progress: RepositoryProgress
) -> tuple[list[dict], list[DirectoryScanError]]:
    errors: list[DirectoryScanError] = []
    result: list[dict] = []
    targets = []
    for root, _, _ in walk_directories(projects, errors, exclude):
        found = check_is_git_repository(root)
        progress.discovered(found)
        if found:
            targets.append(root)
    progress.finish_discovery()
    if targets:
        # 检查函数通过 cd 改变工作目录，需要进程隔离，并限制少量仓库的启动开销。
        workers = min(PROCESSES_NUMBER, 16, os.cpu_count() or 2, len(targets))
        with Pool(processes=workers) as pool:
            for item in pool.imap_unordered(functools.partial(check_project, stash=stash), targets):
                result.append(item)
                progress.checked(bool(item.get("error")))
    result.sort(key=lambda item: item["path"])
    return result, errors


def _print_check_results(
    console: Console, result: list[dict], errors: list[DirectoryScanError], detail: bool, *, compact: bool = False
) -> None:
    affected = [item for item in result if item["status"]]
    if affected:
        failures = sum(bool(item.get("error")) for item in affected)
        table = Table(
            title=Text("仓库检查结果", style="bold cyan"),
            caption=Text(f"检查 {len(result)} 个仓库 · 异常 {len(affected)} 个 · 检查失败 {failures} 个"),
            expand=True,
        )
        table.add_column("目录", ratio=2, overflow="fold")
        if compact:
            compact_table(table)
        table.add_column("状态", min_width=8)
        if detail or failures:
            table.add_column("详细信息", ratio=3, overflow="fold")
        for item in affected:
            failed = bool(item.get("error"))
            cells = [
                Text(item["path"]),
                Text("检查失败" if failed else "存在差异", style="red" if failed else "yellow"),
            ]
            if detail or failures:
                output = item.get("output", "") if detail or failed else ""
                if compact and not failed:
                    output = "\n".join(line for line in output.splitlines() if line.strip())
                cells.append(Text(output))
            table.add_row(*cells)
        console.print(table)
    print_directory_errors(console, errors, compact=compact)


def check_projects(
    projects: list[str],
    detail: bool,
    stash: bool = True,
    exclude: tuple[str, ...] = (),
    *,
    json_output: bool = False,
    compact: bool = False,
) -> None:
    """检查 projects 下的普通仓库，按 detail、stash 和 exclude 控制检查与展示。
    compact 精简展示；json_output 输出全部仓库的 JSON 时忽略展示选项。
    """
    console = Console()
    with RepositoryProgress(Console(stderr=True) if json_output else console) as progress:
        result, errors = _collect_check_results(projects, stash, exclude, progress)
    if json_output:
        repositories = [
            {
                "path": item["path"],
                "has_issues": bool(item["status"]),
                "failed": bool(item.get("error")),
                "output": item.get("output", ""),
            }
            for item in result
        ]
        write_json_result(
            "check",
            {
                "repository_count": len(result),
                "shown_repository_count": len(result),
                "issue_repository_count": sum(bool(item["status"]) for item in result),
                "failed_repository_count": sum(bool(item.get("error")) for item in result),
                "directory_error_count": len(errors),
            },
            repositories,
            errors,
            {"stash_checked": stash},
        )
        return
    _print_check_results(console, result, errors, detail, compact=compact)


@cli_entry
def main() -> None:
    """程序主入口"""
    parser = get_base_parser()
    add_scan_parser(parser)
    args = parser.parse_args()
    display_options = {"compact": True} if args.compact else {}
    if args.command == "scan":
        scan_projects(
            args.path,
            args.group_by,
            args.duplicates,
            args.fetch,
            tuple(args.exclude),
            stash=args.stash,
            host_filter=args.host_filter,
            json_output=args.json_output,
            **display_options,
        )
        return
    check_projects(
        args.path, args.detail, args.stash, tuple(args.exclude), json_output=args.json_output, **display_options
    )

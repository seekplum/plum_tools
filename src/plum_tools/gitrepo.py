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
from multiprocessing import Pool

from rich.console import Console
from rich.text import Text

from .conf import PROCESSES_NUMBER
from .exceptions import RunCmdError, RunCmdTimeout
from .git_scan import RepositoryProgress, add_scan_parser, scan_projects, walk_directories
from .utils.git import check_is_git_repository, check_repository_modify_status, check_repository_stash
from .utils.parser import get_base_parser
from .utils.printer import print_error, print_warn


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
    try:
        status_result, status_out = check_repository_modify_status(path)
        if status_result:
            result["status"] = True
            result["output"] = status_out
            return result
        if stash:
            stash_result, stash_out = check_repository_stash(path)
            if stash_result:
                result["status"] = True
                result["output"] = stash_out
    except (RunCmdError, RunCmdTimeout, OSError) as exc:
        result.update(status=True, output=f"检查失败：{exc}", error=True)
    return result


def check_projects(projects: list[str], detail: bool, stash: bool = True, exclude: tuple[str, ...] = ()) -> None:
    """检查 projects 下的普通仓库，可排除目录；按 detail、stash 控制详细输出与储藏检查。"""
    console = Console()
    errors: list[str] = []
    result: list[dict] = []
    with RepositoryProgress(console) as progress:
        targets = []
        for root, _, _ in walk_directories(projects, errors, exclude):
            found = check_is_git_repository(root)
            progress.discovered(found)
            if found:
                targets.append(root)
        progress.finish_discovery()
        if targets:
            # 旧检查通过 cd 改变进程工作目录，需要进程隔离，且不应为少量仓库启动百个进程。
            workers = min(PROCESSES_NUMBER, 16, os.cpu_count() or 2, len(targets))
            with Pool(processes=workers) as pool:
                for item in pool.imap_unordered(functools.partial(check_project, stash=stash), targets):
                    result.append(item)
                    progress.checked(bool(item.get("error")))
    result.sort(key=lambda item: item["path"])
    for item in result:
        # 仓库中文件没有被改动而且没有文件被储藏了
        if not item["status"]:
            continue
        print_warn(item["path"])

        # 打印详细错误信息
        if not detail and not item.get("error"):
            continue
        print_error(item["output"])
    for error in errors:
        console.print(Text(error, style="red"))


def main() -> None:
    """程序主入口"""
    parser = get_base_parser()
    parser.add_argument(
        "-p",
        "--path",
        action="store",
        required=False,
        dest="path",
        nargs="+",
        default=[os.environ["HOME"]],
        help="The directory path to check",
    )
    parser.add_argument(
        "-d",
        "--detail",
        action="store_true",
        required=False,
        dest="detail",
        default=False,
        help="display staged details",
    )
    parser.add_argument(
        "-s",
        "--stash",
        action="store_true",
        required=False,
        dest="stash",
        default=False,
        help="display stash details",
    )
    parser.add_argument("--exclude", nargs="+", default=[], help="按目录名跳过子目录，例如 node_modules .venv")
    add_scan_parser(parser)
    args = parser.parse_args()
    if args.command == "scan":
        scan_projects(args.path, args.group_by, args.duplicates, args.fetch, tuple(args.exclude))
        return
    if args.exclude:
        check_projects(args.path, args.detail, args.stash, tuple(args.exclude))
        return
    check_projects(args.path, args.detail, args.stash)

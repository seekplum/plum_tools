"""Git 仓库扫描的命令行参数和状态筛选说明。"""

import argparse
import fnmatch
import re
from pathlib import Path

from plum_tools._gitrepo.constants import RepositorySortField, Status
from plum_tools.utils.parser import add_compact_argument
from plum_tools.utils.sorting import add_sort_argument


def compile_host_glob(value: str) -> re.Pattern[str]:
    """将主机通配符编译为忽略大小写的匹配表达式。"""
    return re.compile("|".join(fnmatch.translate(pattern) for pattern in value.split("|")), re.IGNORECASE)


def compile_host_regex(value: str) -> re.Pattern[str]:
    """编译主机正则表达式，格式错误时报告命令行参数错误。"""
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error as exc:
        raise argparse.ArgumentTypeError(f"无效的主机正则表达式：{exc}") from exc


def add_scan_parser(parser: argparse.ArgumentParser) -> None:
    """为 parser 添加必选的 scan 子命令及筛选、详情参数，默认检查 stash。"""
    parser.description = "递归检查 Git 仓库状态，查找重复克隆和本地差异。"  # noqa
    parser.epilog = (
        "示例：\n  gitrepo scan -p ~/PythonProjects --status issues -d\n"
        "  gitrepo scan -p ~/PythonProjects --status duplicate"
    )
    subparsers = parser.add_subparsers(dest="command", required=True, title="子命令", metavar="{scan}")
    scan = subparsers.add_parser(
        "scan",
        help="扫描 Git 仓库，按远程主机分表并合并展示",
        description="扫描 Git 仓库，按远程主机分表，合并展示同一仓库的多个本地克隆。",
        epilog=(
            "示例：\n"
            "  gitrepo scan -p ~/PythonProjects --status duplicate\n"
            "  gitrepo scan -p . --status ahead stash\n"
            "  gitrepo scan -p . --status issues -d\n"
            "  gitrepo scan -p . --group-by name\n"
            "  gitrepo scan -p . --host '*.xxx.net|github.com'\n"
            "  gitrepo scan -p . --host-regex '.*\\.xxx\\.net|github\\.com' --json\n\n"
            "远程分组依据全部远程地址的直接或间接关联。\n"
            "默认只与本地缓存的远程跟踪引用比较，可用 --fetch 更新引用。\n\n"
            "子模块检查本地改动，重复仓库统计和提交对比仅包含独立克隆及其普通 worktree。\n\n"
            "状态（默认 all，多个值匹配任一）：\n" + "\n".join(f"  {status:<16} {status.desc}" for status in Status)
        ),
    )
    add_compact_argument(scan)
    add_sort_argument(
        scan,
        {field.value: field.desc for field in RepositorySortField},
        default_order="按远程主机、仓库组键、组内路径依次升序",
    )
    scan.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="以 JSON 输出结果，默认使用表格；进度条写入标准错误",
    )
    scan.add_argument(
        "--ignore-stash",
        dest="stash",
        action="store_false",
        default=True,
        help="跳过已储藏记录的检查，默认检查",
    )
    scan.add_argument(
        "-p", "--path", nargs="+", default=[str(Path.home())], help="扫描目录，可指定多个；默认用户主目录"
    )
    scan.add_argument(
        "--exclude",
        nargs="+",
        default=[],
        help="按目录名或具体路径排除整个子树，路径支持绝对路径、相对当前目录的路径及 ~；默认无额外排除",
    )
    scan.add_argument(
        "-d",
        "--detail",
        action="store_true",
        help="显示工作区、分支差异、已储藏记录及重复仓库提交关系的详细信息，默认仅展示摘要",
    )
    scan.add_argument(
        "--group-by",
        choices=("remote", "name"),
        default="remote",
        help="表内仓库合并依据：remote 全部远程地址的关联组、name 目录名；默认 remote",
    )
    scan.add_argument(
        "--status",
        nargs="+",
        choices=tuple(Status),
        default=None,
        metavar="STATUS",
        help="按状态筛选目录，多个值用空格分隔，匹配任一；默认 all，可用值见下方状态说明",
    )
    scan.add_argument(
        "--ignore-status",
        nargs="+",
        choices=("submodule-pointer", "ahead", "behind", "detached"),
        help="筛选前忽略指定状态，多个值用空格分隔。submodule-pointer 仅忽略子模块未暂存的提交指针变化",
    )
    scan.add_argument("--fetch", action="store_true", help="先更新所有已配置远程的引用，再检查状态；默认不更新引用")
    hosts = scan.add_mutually_exclusive_group()
    hosts.add_argument(
        "--host",
        dest="host_filter",
        type=compile_host_glob,
        help="按通配符筛选展示主机，多个模式用 | 分隔，例如 '*.xxx.net|github.com'；默认不筛选",
    )
    hosts.add_argument(
        "--host-regex",
        dest="host_filter",
        type=compile_host_regex,
        help="按正则完整匹配展示主机，默认不筛选，与 --host 互斥；两种匹配均不区分大小写",
    )

"""pforkcheck 命令行入口。"""

import argparse
from pathlib import Path

from plum_tools._fork_check.reporting import _print_json_results, _print_results
from plum_tools._fork_check.repositories import (
    RepoRow,
    RepoStatus,
    _find_repo,
    _load_pairs,
    _repo_reference,
    _resolve_targets,
)
from plum_tools.utils.cli import cli_entry
from plum_tools.utils.parser import add_compact_argument, get_base_parser
from plum_tools.utils.sorting import add_sort_argument, sort_items


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
    raise SystemExit(main())

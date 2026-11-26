"""Git 仓库扫描命令入口。"""

from typing import Any

from plum_tools._gitrepo.cli import add_scan_parser
from plum_tools._gitrepo.scanner import scan_projects
from plum_tools.utils.cli import cli_entry
from plum_tools.utils.parser import get_base_parser


@cli_entry
def main() -> None:
    """解析扫描参数并展示仓库检查结果。"""
    parser = get_base_parser()
    add_scan_parser(parser)
    args = parser.parse_args()
    display_options: dict[str, Any] = {}
    if args.compact:
        display_options["compact"] = True
    if args.sort:
        display_options["sort"] = args.sort
    if args.ignore_status:
        display_options["ignored_statuses"] = tuple(dict.fromkeys(args.ignore_status))
    scan_projects(
        args.path,
        args.group_by,
        tuple(dict.fromkeys(args.status or ("all",))),
        args.fetch,
        tuple(args.exclude),
        stash=args.stash,
        host_filter=args.host_filter,
        json_output=args.json_output,
        detail=args.detail,
        **display_options,
    )


if __name__ == "__main__":
    raise SystemExit(main())

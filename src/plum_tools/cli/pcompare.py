"""解析比较参数并运行命令。"""

from rich.console import Console
from rich.text import Text

from plum_tools._compare import remote
from plum_tools._compare.comparison import compare_paths
from plum_tools._compare.history import compare_heads
from plum_tools._compare.models import CompareExitCode, CompareResult, ShowMode
from plum_tools._compare.reporting import _print_json_report, print_report
from plum_tools.utils.cli import cli_entry
from plum_tools.utils.parser import add_compact_argument, get_base_parser
from plum_tools.utils.sorting import add_sort_argument, sort_items


@cli_entry
def main() -> None:
    """解析路径参数并展示结果；退出码 0 表示一致，1 表示差异，2 表示错误。"""
    parser = get_base_parser()
    add_sort_argument(
        parser,
        {
            "path": "相对路径",
            "name": "名称",
            "result": "比较结果",
            "kind": "各输入中首个存在条目的类型",
            "size": "各输入对应条目的最大大小",
        },
        default_order="按相对路径升序，表格按一致与不一致分组展示",
    )
    add_compact_argument(parser)
    parser.description = "比较两个及以上目录或文件，默认仅展示不一致的条目。"  # noqa
    parser.epilog = (
        "示例：\n"
        "  pcompare ./old ./new\n"
        "  pcompare 'seekplum:~/Downloads' ~/Downloads\n"
        "  pcompare 'seekplum:~/Downloads' ~/Downloads --ignore-case\n"
        "  pcompare ./a.txt ./b.txt ./c.txt\n"
        "  pcompare ./old ./new --exclude-name node_modules .venv\n"
        "  pcompare ./old ./new --exclude-name '*.log*'\n"
        f"  pcompare ./old ./new --exclude-path packages/web/dist --show {ShowMode.ALL}\n"
        f"  pcompare ./old ./new --show {ShowMode.IDENTICAL}\n"
        "  pcompare ./old ./new --json | jq -r '.entries[] | select(.identical) | .path'\n"
        f"  pcompare ./old ./new --show {ShowMode.ALL} --display-depth 2\n"
        "  pcompare ./old ./new --quick\n"
        "  pcompare ./old ./new -L 3 --no-default-excludes\n\n"
        "Git 仓库根目录另显示当前提交关系。\n"
        "待比较路径放在 --exclude-name、--exclude-path 和 --sort 等列表型选项之前。\n"
        "目录递归比较，文件按内容比较，符号链接仅比较链接目标。\n"
        "远端路径使用 [user@]host:path，支持 SSH 别名；远端需要 Python 3.9+。\n"
        "退出码：" + "，".join(f"{code} {code.desc}" for code in CompareExitCode) + "。"
    )
    parser.add_argument("paths", nargs="+", metavar="路径", help="要比较的本地或 host:path 路径，至少两个")
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="以 JSON 输出比较结果，支持 --display-depth，忽略 --show 和 --compact；加载动画写入标准错误",
    )
    parser.add_argument(
        "--ignore-case",
        action="store_true",
        help="忽略相对路径大小写，单个输入内出现大小写重名时报错（默认区分大小写）",
    )
    parser.add_argument(
        "--show",
        choices=[mode.value for mode in ShowMode],
        default=ShowMode.DIFFERENT,
        help="选择展示类型：" + "、".join(f"{mode} {mode.desc}" for mode in ShowMode) + "（默认）",
    )
    parser.add_argument(
        "--display-depth",
        type=int,
        metavar="层数",
        help="限制表格及 JSON 条目的展示深度，至少为 0，根目录为第 0 层；默认不限，不影响比较范围及汇总",
    )
    parser.add_argument(
        "--exclude-name",
        nargs="+",
        default=[],
        metavar="名称",
        help="按名称排除任意层级的条目，支持通配符或 re: 正则完整匹配，多个规则用空格分隔",
    )
    parser.add_argument(
        "--exclude-path",
        nargs="+",
        default=[],
        metavar="相对路径",
        help="按根目录内相对路径排除，支持通配符（** 跨层）或 re: 正则完整匹配，多个规则用空格分隔",
    )
    parser.add_argument(
        "--no-default-excludes",
        dest="default_excludes",
        action="store_false",
        help="关闭默认名称排除：" + "、".join(remote.DEFAULT_EXCLUDE_NAMES),
    )
    parser.add_argument("--quick", action="store_true", help="快速比较，默认只扫描 2 层；可用 --max-depth 覆盖")
    parser.add_argument("--max-depth", "-L", type=int, metavar="层数", help="限制扫描深度，至少为 1，根目录为第 0 层")
    args = parser.parse_args()
    if args.display_depth is not None and args.display_depth < 0:
        parser.error("展示深度必须是大于等于 0 的整数")
    max_depth = args.max_depth if args.max_depth is not None else (2 if args.quick else None)
    console = Console(stderr=args.json_output)
    try:
        with console.status("正在扫描并比较…", spinner="dots"):
            comparisons = compare_paths(
                args.paths,
                exclude_names=args.exclude_name,
                exclude_paths=args.exclude_path,
                default_excludes=args.default_excludes,
                max_depth=max_depth,
                ignore_case=args.ignore_case,
            )
            git = compare_heads(args.paths, comparisons)
        comparisons = sort_items(
            comparisons,
            args.sort,
            {
                "path": lambda item: str(item.path),
                "name": lambda item: item.path.name,
                "result": lambda item: item.result,
                "kind": lambda item: next((entry.kind for entry in item.entries if entry is not None), None),
                "size": lambda item: max((entry.size for entry in item.entries if entry is not None), default=None),
            },
        )
        if args.json_output:
            _print_json_report(
                args.paths,
                comparisons,
                {
                    "exclude_names": args.exclude_name,
                    "exclude_paths": args.exclude_path,
                    "default_excludes": args.default_excludes,
                    "max_depth": max_depth,
                    "ignore_case": args.ignore_case,
                    "display_depth": args.display_depth,
                },
                display_depth=args.display_depth,
                git=git,
            )
        else:
            print_report(
                args.paths,
                comparisons,
                console,
                show=args.show,
                compact=args.compact,
                max_depth=max_depth,
                ignore_case=args.ignore_case,
                display_depth=args.display_depth,
                git=git,
            )
    except (OSError, ValueError) as exc:
        Console(stderr=True).print(Text(f"比较失败：{exc}", style="red"))
        raise SystemExit(CompareExitCode.ERROR) from exc
    raise SystemExit(
        CompareExitCode.DIFFERENT
        if any(item.result != CompareResult.IDENTICAL for item in comparisons)
        else CompareExitCode.IDENTICAL
    )


if __name__ == "__main__":
    raise SystemExit(main())

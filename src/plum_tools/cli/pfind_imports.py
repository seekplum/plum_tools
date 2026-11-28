"""pfind_imports 命令行入口。"""

import json
import sys
from operator import itemgetter
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from plum_tools._find_imports.reporting import _map_modules, _print_results
from plum_tools._find_imports.scanner import FindMode, ImportScanReport, find_imports
from plum_tools.utils.cli import cli_entry
from plum_tools.utils.parser import add_compact_argument, add_extra_argument, get_base_parser
from plum_tools.utils.sorting import add_sort_argument, sort_items


@cli_entry
def main() -> None:
    """解析命令行参数，扫描导入并输出 Rich 表格或 JSON，进度写入 stderr。"""
    parser = get_base_parser()
    add_sort_argument(
        parser,
        {"name": "导入名", "package_name": "包名", "mode": "分类"},
        default_order="按 mode、name 依次升序",
    )
    add_compact_argument(parser)
    parser.description = "扫描 Python 项目的导入语句，按模块分类输出包名及扫描错误。"  # noqa
    parser.epilog = (
        "示例：\n"
        "  pfind_imports -p ./src\n"
        "  pfind_imports -p . -m all --json\n"
        "  pfind_imports -p . -i ./setup.py -e yaml=PyYAML\n\n"
        "默认跳过 .venv、__pycache__ 目录和项目本地模块。"
    )
    parser.add_argument(
        "--mode",
        "-m",
        type=FindMode,
        choices=list(FindMode),
        default=FindMode.THIRD_PARTY,
        help="模块分类：std 标准库、3rd-party 第三方库、all 全部；默认 3rd-party",
    )
    parser.add_argument(
        "--project-dir",
        "-p",
        type=str,
        dest="project_dir",
        default=".",
        help="项目目录，默认为当前目录",
    )
    parser.add_argument(
        "--ignore-path",
        "-i",
        required=False,
        action="store",
        dest="ignore_paths",
        nargs="+",
        help="忽略指定 Python 文件路径，可指定多个；默认无额外忽略文件",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true", help="以 JSON 输出结果，默认使用表格；进度条写入标准错误"
    )
    add_extra_argument(parser)
    args = parser.parse_args()
    report = ImportScanReport()
    progress_console = Console(stderr=True)
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.fields[summary]}"),
        TimeElapsedColumn(),
        console=progress_console,
        disable=not progress_console.is_terminal,
        transient=True,
        refresh_per_second=4,
        redirect_stdout=False,
        redirect_stderr=False,
    ) as progress:
        modules = _map_modules(
            sorted(
                find_imports(
                    args.project_dir, mode=args.mode, ignore_paths=args.ignore_paths, report=report, progress=progress
                ),
                key=lambda module: (module["mode"], module["name"]),
            ),
            args.extra,
        )
    modules = sort_items(modules, args.sort, {name: itemgetter(name) for name in ("name", "package_name", "mode")})
    if args.json_output:
        json.dump(
            {
                "schema_version": 1,
                "project_dir": str(Path(args.project_dir).absolute()),
                "mode": args.mode,
                "summary": {
                    "file_count": report.file_count,
                    "scanned_file_count": report.scanned_file_count,
                    "module_count": len(modules),
                    "error_count": len(report.errors),
                },
                "modules": modules,
                "errors": report.errors,
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return
    _print_results(Console(), modules, report, compact=args.compact is True)


if __name__ == "__main__":
    raise SystemExit(main())

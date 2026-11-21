import ast
import json
import os
import sys
import typing as t
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from .utils.parser import add_compact_argument, add_extra_argument, get_base_parser
from .utils.printer import compact_table, print_columns

# 使用当前 Python 解释器提供的标准库模块集合。
STD_LIB_MODULE_NAMES = sys.stdlib_module_names
# 补全导入名与安装包名不一致的常用依赖。
MODULE_NAME_PAIRS = {
    "PIL": "pillow",
    "grpc": "grpcio",
}


class FindMode(StrEnum):
    STD = "std"  # 标准库
    ALL = "all"  # 所有库
    THIRD_PARTY = "3rd-party"  # 第三方库。这个会把项目本身的包也包含进来


# 保存去重前的导入语句信息及模块分类。
ModuleDict = t.TypedDict(
    "ModuleDict",
    {
        "name": str,
        "type": t.Literal["import", "from"],
        "origin_name": str,
        "mode": t.Literal[FindMode.STD, FindMode.THIRD_PARTY],
    },
)
# 扫描接口逐项返回模块，避免依赖展示层。
GeneratorModuleDict = t.Generator[ModuleDict, None, None]


@dataclass
class ImportScanReport:
    """保存扫描文件数、已处理文件数及包含 path、reason 的错误记录。"""

    file_count: int = 0
    scanned_file_count: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


def calc_mode(name: str) -> t.Literal[FindMode.STD, FindMode.THIRD_PARTY]:
    """根据顶层导入名 name 返回标准库或第三方库分类。"""
    if name in STD_LIB_MODULE_NAMES:
        return FindMode.STD
    return FindMode.THIRD_PARTY


def parse_imports(source: str) -> GeneratorModuleDict:
    """解析 source 中的绝对导入，逐项返回模块名、语句类型及分类。"""
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                first_name = name.name.split(".")[0]
                yield ModuleDict(
                    type="import",
                    origin_name=name.name,
                    name=first_name,
                    mode=calc_mode(first_name),
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                if node.level > 0:  # 不考虑相对导入
                    continue
                first_name = node.module.split(".")[0]
                yield ModuleDict(
                    type="from",
                    origin_name=node.module,
                    name=first_name,
                    mode=calc_mode(first_name),
                )


def find_imports_by_file(file_path: str) -> GeneratorModuleDict:
    """读取 file_path 的 UTF-8 源码，逐项返回绝对导入信息。"""
    with open(file_path, encoding="utf-8") as f:
        yield from parse_imports(f.read())


def _collect_python_files(
    project_path: Path, ignore_paths: list[str] | None, report: ImportScanReport, progress: Progress | None
) -> list[Path]:
    ignore_path_set = {str(Path(path)) for path in ignore_paths or []}
    task = progress.add_task("发现文件", total=None, summary="文件 0 · 错误 0") if progress is not None else None
    files = []
    scan_file = Path(__file__).absolute()

    def record_error(exc: OSError) -> None:
        report.errors.append({"path": str(exc.filename or project_path), "reason": str(exc)})

    for root, dirs, filenames in os.walk(project_path, onerror=record_error):
        # 在遍历阶段剪枝，避免进入不参与解析的虚拟环境和缓存目录。
        dirs[:] = [name for name in dirs if name not in (".venv", "__pycache__")]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            file = Path(root) / name
            if str(file) not in ignore_path_set and file.absolute() != scan_file:
                files.append(file)
        if progress is not None and task is not None:
            progress.update(task, summary=f"文件 {len(files)} · 错误 {len(report.errors)}")
    report.file_count = len(files)
    if progress is not None and task is not None:
        progress.update(
            task, total=len(files), completed=len(files), summary=f"文件 {len(files)} · 错误 {len(report.errors)}"
        )
        progress.stop_task(task)
    return files


def find_imports(
    project_dir: str,
    *,
    mode: FindMode = FindMode.ALL,
    ignore_paths: list[str] | None = None,
    report: ImportScanReport | None = None,
    progress: Progress | None = None,
) -> GeneratorModuleDict:
    """扫描 project_dir，按 mode、ignore_paths 排除并去重后返回模块。
    可通过 report 收集统计与错误，通过 progress 展示文件发现和解析进度。
    """
    report = report if report is not None else ImportScanReport()
    exists = set()
    project_path = Path(project_dir)
    try:
        my_module_names = {path.name for path in project_path.iterdir()}
    except OSError as exc:
        report.errors.append({"path": str(project_path), "reason": str(exc)})
        return
    src_path = project_path / "src"
    try:
        if src_path.is_dir():
            my_module_names.update(path.name for path in src_path.iterdir())
    except OSError as exc:
        report.errors.append({"path": str(src_path), "reason": str(exc)})
    files = _collect_python_files(project_path, ignore_paths, report, progress)
    task = (
        progress.add_task("解析文件", total=len(files), summary=f"完成 0/{len(files)} · 错误 {len(report.errors)}")
        if progress is not None
        else None
    )
    for file in files:
        try:
            for module in find_imports_by_file(str(file)):
                if module["name"] in exists or module["name"] in my_module_names:
                    continue
                exists.add(module["name"])
                if mode in (FindMode.ALL, module["mode"]):
                    yield module
        except Exception as exc:
            report.errors.append({"path": str(file), "reason": str(exc)})
        finally:
            report.scanned_file_count += 1
            if progress is not None and task is not None:
                progress.update(
                    task,
                    advance=1,
                    summary=f"完成 {report.scanned_file_count}/{len(files)} · 错误 {len(report.errors)}",
                )


def _map_modules(modules: list[ModuleDict], extra: dict[str, str]) -> list[dict[str, str]]:
    return [
        {
            "name": module["name"],
            "origin_name": module["origin_name"],
            "type": module["type"],
            "mode": module["mode"],
            "package_name": MODULE_NAME_PAIRS.get(module["name"], extra.get(module["name"], module["name"])),
        }
        for module in modules
    ]


def _print_compact_modules(console: Console, modules: list[dict[str, str]]) -> None:
    console.print(Text("导入模块", style="bold"))
    for mode, label in ((FindMode.STD, "标准库"), (FindMode.THIRD_PARTY, "第三方库")):
        group = [module for module in modules if module["mode"] == mode]
        if not group:
            continue
        console.print(Text(f"{label}（{len(group)}）", style="bold cyan"))
        print_columns(
            console,
            [
                Text(
                    (
                        module["name"]
                        if module["name"] == module["package_name"]
                        else f"{module['name']}→{module['package_name']}"
                    ),
                    overflow="fold",
                )
                for module in group
            ],
        )


def _print_results(
    console: Console, modules: list[dict[str, str]], report: ImportScanReport, *, compact: bool = False
) -> None:
    if compact:
        _print_compact_modules(console, modules)
    else:
        table = Table(title="导入模块", expand=True)
        table.add_column("导入名", overflow="fold")
        table.add_column("包名", overflow="fold")
        table.add_column("分类")
        for module in modules:
            table.add_row(
                Text(module["name"]),
                Text(module["package_name"]),
                Text("标准库" if module["mode"] == FindMode.STD else "第三方库"),
            )
        console.print(table)
    if report.errors:
        errors = Table(title="扫描错误", expand=True)
        if compact:
            compact_table(errors)
        errors.add_column("路径", overflow="fold", ratio=2)
        errors.add_column("原因", overflow="fold", ratio=3, style="red")
        for error in report.errors:
            errors.add_row(Text(error["path"]), Text(error["reason"]))
        console.print(errors)
    console.print(
        f"扫描 {report.scanned_file_count}/{report.file_count} 个文件，展示 {len(modules)} 个模块，"
        f"错误 {len(report.errors)} 个。"
    )


def main() -> None:
    """解析命令行参数，扫描导入并输出 Rich 表格或 JSON，进度写入 stderr。"""
    parser = get_base_parser()
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

"""映射包名并展示扫描结果。"""

from rich.console import Console
from rich.table import Table
from rich.text import Text

from plum_tools._find_imports.scanner import FindMode, ImportScanReport, ModuleDict
from plum_tools.utils.printer import compact_table, print_columns

# 补全导入名与安装包名不一致的常用依赖。
MODULE_NAME_PAIRS = {
    "PIL": "pillow",
    "grpc": "grpcio",
}


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

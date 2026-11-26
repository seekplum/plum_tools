"""收集 Python 文件并解析导入。"""

import ast
import os
import sys
import typing as t
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from rich.progress import Progress

# 使用当前 Python 解释器提供的标准库模块集合。
STD_LIB_MODULE_NAMES = sys.stdlib_module_names


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

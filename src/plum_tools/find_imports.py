import ast
import sys
import typing as t
from enum import StrEnum
from pathlib import Path

from .utils.parser import add_extra_argument, get_base_parser

STD_LIB_MODULE_NAMES = sys.stdlib_module_names
MODULE_NAME_PAIRS = {
    "PIL": "pillow",
    "grpc": "grpcio",
}


class FindMode(StrEnum):
    STD = "std"  # 标准库
    ALL = "all"  # 所有库
    THIRD_PARTY = "3rd-party"  # 第三方库。这个会把项目本身的包也包含进来


ModuleDict = t.TypedDict(
    "ModuleDict",
    {
        "name": str,
        "type": t.Literal["import", "from"],
        "origin_name": str,
        "mode": t.Literal[FindMode.STD, FindMode.THIRD_PARTY],
    },
)
GeneratorModuleDict = t.Generator[ModuleDict, None, None]


def calc_mode(name: str) -> t.Literal[FindMode.STD, FindMode.THIRD_PARTY]:
    if name in STD_LIB_MODULE_NAMES:
        return FindMode.STD
    return FindMode.THIRD_PARTY


def parse_imports(source: str) -> GeneratorModuleDict:
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
    with open(file_path, encoding="utf-8") as f:
        yield from parse_imports(f.read())


def find_imports(
    project_dir: str, *, mode: FindMode = FindMode.ALL, ignore_paths: t.List[str] | None = None
) -> GeneratorModuleDict:
    exists = set()
    project_path = Path(project_dir)
    ignore_path_set = {str(Path(path)) for path in ignore_paths or []}
    ignore_dir_parts = {".venv", "__pycache__"}
    my_module_names = {path.name for path in project_path.iterdir()}
    src_path = project_path / "src"
    if src_path.is_dir():
        my_module_names.update(path.name for path in src_path.iterdir())

    for file in project_path.rglob("*.py"):
        file_path = str(file)
        relative_parts = file.relative_to(project_path).parts
        # 遍历目录中的所有文件，除了.venv和__pycache__目录
        if file_path in ignore_path_set or any(part in ignore_dir_parts for part in relative_parts):
            continue
        if file.absolute() == Path(__file__).absolute():
            continue
        try:
            for module in find_imports_by_file(file_path):
                if module["name"] in exists or module["name"] in my_module_names:
                    continue
                exists.add(module["name"])
                if mode in (FindMode.ALL, module["mode"]):
                    yield module
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")


def main():
    parser = get_base_parser()
    parser.add_argument(
        "--mode",
        "-m",
        type=FindMode,
        choices=list(FindMode),
        default=FindMode.THIRD_PARTY,
        help="Find mode",
    )
    parser.add_argument(
        "--project-dir",
        "-p",
        type=str,
        dest="project_dir",
        default=".",
        help="Project directory",
    )
    parser.add_argument(
        "--ignore-path",
        "-i",
        required=False,
        action="store",
        dest="ignore_paths",
        nargs="+",
        help="Ignore paths",
    )
    add_extra_argument(parser)
    args = parser.parse_args()
    modules = sorted(
        find_imports(args.project_dir, mode=args.mode, ignore_paths=args.ignore_paths),
        key=lambda x: (x["mode"], x["name"]),
    )
    extra_modules = args.extra
    for module in modules:
        name = module["name"]
        if name in MODULE_NAME_PAIRS:
            name = MODULE_NAME_PAIRS[name]
        elif name in extra_modules:
            name = extra_modules[name]
        print(name)

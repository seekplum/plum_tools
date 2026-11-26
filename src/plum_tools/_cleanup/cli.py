"""解析并验证文件计划和原生工具子命令。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from plum_tools._cleanup.constants import (
    CATEGORY_LABELS,
    DEPENDENCIES,
    PROJECT_CATEGORIES,
    PROTECTED_NAMES,
    PRUNE_CATEGORIES,
    PRUNE_TOOLS,
    Category,
    Command,
    PlanFile,
    PruneAction,
    ScanTuning,
    Tool,
)
from plum_tools._cleanup.filesystem import directory_fd, display
from plum_tools.utils.parser import get_base_parser
from plum_tools.utils.sorting import add_sort_argument

# 帮助文字集中说明默认扫描范围、重建条件和原生工具限制。
HELP_EPILOG = """示例:
  pclean scan
  pclean scan --category user-cache
  pclean scan --root ~/PythonProjects --root ~/WebProjects --category project-cache,build,deps
  pclean scan --root ~/PythonProjects --fast-deps
  pclean scan --root ~/PythonProjects --workers 4
  pclean scan --root ~/GolangProjects --category project-cache,build,deps
  pclean scan --category tools --tool brew
  pclean scan --root ~/PythonProjects --category project-cache --include-generated .mycache
  pclean scan --root . --save-plan /tmp/pclean-plan.json
  pclean show
  pclean show --from-plan /tmp/pclean-plan.json --json
  pclean run
  pclean run --from-plan /tmp/pclean-plan.json
  pclean prune show
  pclean prune show --category tools --tool uv --tool pnpm
  pclean prune show --category tools --tool go
  pclean prune run --category docker --older-than 30
  pclean prune run --category tools --tool pip --yes

规则:
  必须显式指定子命令；scan 预览并保存或刷新 .pclean-plan.json。
  show 复核并预览已有计划；run 复核并执行，两者默认加载当前目录的计划。
  没有计划时需先 scan；show 和 run 不会重新扫描或添加候选。
  all 包含目录内的 project-cache、build、deps。
  scan 的全局缓存通过 --category user-cache、tools 显式选择；tools 仅枚举 Homebrew 下载缓存。
  显式 --root 仅支持项目类别，不扫描全局缓存。
  run 才执行清理，文件和目录通过 trash-cli 移入回收站，清空后才释放空间。
  --yes 跳过输入 CLEAN 的确认；确认输入忽略大小写。
  run 全部成功后，计划文件也移入回收站；取消或失败时保留。
  scan --save-plan 指定保存位置；show/run --from-plan 指定已有计划。
  默认完整扫描；加载计划时整批复核文件、配置和 Git 状态，变化时要求重新预览。
  --fast-deps 仅快速识别依赖目录，scan/show 不遍历内部，文件数与占用显示未统计。
  快速计划只固定目录身份与项目配置，允许内部文件变化；run 完整检查保护项和排除规则。
  快速模式遇到内部保护项或排除路径时，run 拒绝整批清理；指定 --older-than 时恢复完整扫描。
  计划绑定当前用户、主机和脚本版本；显式指定的计划不覆盖已有文件。
  prune 必须指定 show 或 run；show 仅查询预览，run 当次查询、展示并确认后调用工具直接清理。
  prune 默认 all，包含 tools、system-cache、docker，不读写文件计划，不经过回收站。
  prune 不支持 --root、--exclude、--save-plan 或 --from-plan，实际对象由工具执行时决定。
  user-cache 和 Homebrew 默认保留最近 30 天；项目默认不限制时间。
  Docker 默认保留最近 30 天的构建缓存和新建镜像；不清理容器、卷或带标签镜像。
  Docker 执行前复核引擎 ID、上下文端点及构建器节点；查询失败时停止清理。
  原生工具不支持按时间或排除路径清理时，会明确跳过相应操作。
  prune tools: npm/pip/Yarn Classic 全局缓存；pnpm/uv 无用缓存；Go 构建、测试结果、模糊测试与模块下载缓存。
  Go 模块按 go.mod/go.sum 识别；deps 支持模块根目录带 modules.txt 的 vendor，重建使用 go mod vendor。
  Go 项目缓存支持校验格式的覆盖率报告；build 支持经 go version 确认的 *.test、*.test.exe。
  Go 模块缓存由多个项目共享，清理后依赖需重新下载；模糊测试缓存需重新积累，不清理 testdata 语料。
  prune system-cache: Linux 的 APT/DNF/YUM 下载缓存，需要已有 root 权限，不自动提权。
  all 包含 deps；移除依赖后需要重新安装，精确恢复版本取决于锁文件。
  deps 按项目声明重建，未记录的手工安装或环境内本地修改无法恢复。
  项目在 Git 内时必须被忽略且不含已跟踪文件；Git 外必须识别到项目标记。
  所有文件候选（包括 .venv、.node_modules 等目录）含 Git 已跟踪文件时保留并提示。
  --sort 仅调整预览顺序，不改变已保存计划或清理执行顺序。
  用户缓存按修改时间筛选，不代表文件一定未被使用；建议先退出相关应用。
  不读取 .chezmoiignore 作为清理规则，不跟随软链接，不自动提权或安装工具。
"""


def _build_parser() -> argparse.ArgumentParser:
    """按扫描、查看和执行职责绑定参数，避免无效的跨阶段参数组合。"""
    parser = get_base_parser()
    parser.prog = "pclean"
    parser.description = "预览并清理可重建文件或工具缓存；文件计划需要 trash-cli，项目扫描需要 Git。"
    parser.epilog = HELP_EPILOG
    parser.set_defaults(
        root=None,
        category=None,
        exclude=[],
        include_generated=[],
        older_than=None,
        fast_deps=False,
        workers=ScanTuning.WORKERS,
        tool=None,
        docker_context=None,
        docker_builder=None,
        save_plan=None,
        from_plan=None,
        yes=False,
        json=False,
        prune_action=None,
        sort=None,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        title="子命令",
        metavar="{" + ",".join(Command) + "}",
        required=True,
    )
    commands = {}
    for command, description in (
        (Command.SCAN, "扫描、预览并保存清理计划"),
        (Command.SHOW, "加载并复核已有计划，仅预览"),
        (Command.RUN, "加载、复核并执行已有计划"),
        (Command.PRUNE, "独立查询或执行原生工具缓存清理，必须指定 show/run，不使用文件计划"),
    ):
        child = subparsers.add_parser(command, help=description, description=description)
        commands[command] = child
    _add_scan_arguments(commands[Command.SCAN])
    _add_plan_arguments(commands)
    _add_prune_arguments(commands[Command.PRUNE])
    return parser


def _validate_options(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """校验参数组合与自定义生成物名称，拒绝无法遵守的清理范围。"""
    if args.older_than is not None and args.older_than < 0:
        parser.error("--older-than 不能小于 0")
    if args.workers < 1:
        parser.error("--workers 不能小于 1")
    if args.fast_deps and Category.DEPS not in args.categories:
        parser.error("--fast-deps 需要选择 deps 类别")
    if args.tool and Category.TOOLS not in args.categories:
        parser.error("--tool 需要选择 tools 类别")
    if (args.docker_context or args.docker_builder) and Category.DOCKER not in args.categories:
        parser.error("Docker 参数需要选择 docker 类别")
    project_categories = args.categories & PROJECT_CATEGORIES
    if args.root and not project_categories:
        parser.error("--root 需要选择项目类别")
    if args.include_generated and Category.PROJECT_CACHE not in args.categories:
        parser.error("--include-generated 需要选择 project-cache 类别")
    for name in args.include_generated:
        if name in {".", "..", "*", "**"} | PROTECTED_NAMES | DEPENDENCIES or "/" in name or not name:
            parser.error(f"不允许的生成物名称: {display(name)}")


def _resolve_roots(values: list[str], parser: argparse.ArgumentParser) -> list[Path]:
    """校验真实根目录并合并父子重叠，返回一次遍历所需的路径。"""
    roots: list[Path] = []
    for value in values:
        root = Path(os.path.abspath(os.path.expanduser(value)))
        if not root.is_dir() or root in {
            Path("/"),
            Path("/Users"),
            Path("/home"),
            Path("/var"),
            Path("/usr"),
            Path("/etc"),
        }:
            parser.error(f"无效或过宽的项目根目录: {display(root)}")
        try:
            with directory_fd(root):
                pass
        except OSError as exc:
            parser.error(f"项目根目录包含软链接或不可访问: {display(root)}: {exc}")
        if not any(root == old or old in root.parents for old in roots):
            roots = [old for old in roots if root not in old.parents]
            roots.append(root)
    return roots


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析显式子命令，计划路径默认位于当前目录。"""
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.command = Command(args.command)
    args.default_plan = not args.save_plan and not args.from_plan
    if args.command in {Command.SHOW, Command.RUN}:
        args.from_plan = args.from_plan or PlanFile.DEFAULT
        args.categories = set()
        args.roots = []
        return args
    if args.command == Command.PRUNE:
        args.prune_action = PruneAction(args.prune_action)
    else:
        args.save_plan = args.save_plan or PlanFile.DEFAULT
    _resolve_categories(args, parser)
    _validate_options(args, parser)
    if args.command == Command.PRUNE:
        args.roots = []
        return args
    args.root = args.root or [str(Path.cwd())]
    args.roots = _resolve_roots(args.root, parser) if args.categories & PROJECT_CATEGORIES else []
    return args


def _add_scan_arguments(scan: argparse.ArgumentParser) -> None:
    """绑定文件扫描与计量参数。"""
    scan.add_argument(
        "--category",
        action="append",
        metavar="类别,...",
        help="默认 all（项目缓存、构建产物、依赖）；另支持 user-cache、tools（仅 Homebrew）；原生工具用 prune",
    )
    scan.add_argument(
        "--root",
        action="append",
        metavar="目录",
        help="限定项目扫描目录，默认当前工作目录；显式指定时仅支持项目类别，可重复指定",
    )
    scan.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="规则",
        help="排除绝对路径、相对路径或名称，支持通配符",
    )
    scan.add_argument(
        "--include-generated",
        action="append",
        default=[],
        metavar="目录名",
        help="额外生成物目录的准确名称，仍需通过项目与 Git 检查",
    )
    scan.add_argument(
        "--older-than",
        type=int,
        metavar="天",
        help="只清理此前修改的文件，0 表示不保留",
    )
    scan.add_argument(
        "--fast-deps",
        action="store_true",
        help="跳过依赖目录内部扫描和计量；run 前完整检查，指定 --older-than 时恢复完整扫描",
    )
    scan.add_argument(
        "--workers",
        type=int,
        default=ScanTuning.WORKERS,
        metavar="线程数",
        help=f"项目候选详细统计的线程数，默认 {ScanTuning.WORKERS}；1 为串行",
    )
    scan.add_argument(
        "--tool",
        action="append",
        choices=tuple(Tool),
        type=Tool,
        help="文件计划仅支持 brew；其他工具请使用 prune show/run --tool，需要 tools 类别",
    )
    scan.add_argument(
        "--save-plan",
        metavar="文件",
        help=f"保存计划，默认 {PlanFile.DEFAULT}；显式指定时不覆盖",
    )


def _add_plan_arguments(commands: dict[Command, argparse.ArgumentParser]) -> None:
    """绑定已有计划的展示与执行参数。"""
    for command in (Command.SHOW, Command.RUN):
        commands[command].add_argument("--from-plan", metavar="文件", help=f"加载已有计划，默认 {PlanFile.DEFAULT}")
    for command in (Command.SCAN, Command.SHOW, Command.RUN):
        add_sort_argument(
            commands[command],
            {
                "path": "路径",
                "category": "类别",
                "size": "占用字节数",
                "files": "文件数",
                "reason": "清理依据",
            },
        )
    for command in (Command.SCAN, Command.SHOW):
        commands[command].add_argument("--json", action="store_true", help="以 JSON 输出预览")
    commands[Command.RUN].add_argument("--yes", action="store_true", help="跳过交互确认")


def _add_prune_arguments(parser: argparse.ArgumentParser) -> None:
    """绑定独立原生工具操作参数。"""
    actions = parser.add_subparsers(
        dest="prune_action",
        title="子命令",
        metavar="{" + ",".join(PruneAction) + "}",
        required=True,
    )
    for action, description in (
        (PruneAction.SHOW, "查询并预览工具清理操作"),
        (PruneAction.RUN, "当次查询并确认后直接清理工具缓存"),
    ):
        child = actions.add_parser(action, help=description, description=description)
        child.add_argument(
            "--category",
            action="append",
            metavar="类别,...",
            help="默认 all；支持 tools、system-cache、docker，可重复指定",
        )
        child.add_argument(
            "--tool",
            action="append",
            choices=PRUNE_TOOLS,
            type=Tool,
            help="选择 tools 中的工具，可重复；Homebrew 下载缓存请用 scan --category tools",
        )
        child.add_argument(
            "--older-than",
            type=int,
            metavar="天",
            help="Docker 默认保留最近 30 天，0 表示不保留；其他工具不支持时跳过",
        )
        child.add_argument("--docker-context", metavar="上下文", help="明确选择本地 Docker 上下文")
        child.add_argument("--docker-builder", metavar="构建器", help="选择该本地引擎上的 Buildx 构建器")
        if action == PruneAction.SHOW:
            child.add_argument("--json", action="store_true", help="以 JSON 输出预览")
        else:
            child.add_argument("--yes", action="store_true", help="跳过交互确认")


def _resolve_categories(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """解析类别名称并按命令展开 all。"""
    args.category = args.category or [Category.ALL]
    requested = {part for value in args.category for part in value.split(",")}
    unknown = requested - set(Category)
    if unknown:
        parser.error(f"未知类别: {', '.join(sorted(unknown))}")
    _validate_category_scope(args, requested, parser)
    args.categories = {Category(value) for value in requested - {Category.ALL}}
    if Category.ALL in requested:
        args.categories.update(PRUNE_CATEGORIES if args.command == Command.PRUNE else PROJECT_CATEGORIES)


def _validate_category_scope(args: argparse.Namespace, requested: set[str], parser: argparse.ArgumentParser) -> None:
    """限制文件扫描与原生工具的类别范围及工具选择。"""
    if args.command == Command.SCAN:
        native = requested & {Category.DOCKER, Category.SYSTEM_CACHE}
        if native:
            parser.error(f"{', '.join(sorted(native))} 请使用 pclean prune show/run --category 指定")
        if args.tool and set(args.tool) != {Tool.BREW}:
            parser.error("scan --tool 仅支持 brew；其他工具请使用 pclean prune show/run --category tools --tool 工具名")
    if args.command == Command.PRUNE:
        available = PRUNE_CATEGORIES
    else:
        available = PROJECT_CATEGORIES if args.root else set(CATEGORY_LABELS)
    outside_scope = requested - available - {Category.ALL}
    if outside_scope:
        if args.command == Command.PRUNE:
            parser.error("prune 仅支持 tools、system-cache、docker 类别；文件类别请使用 scan")
        parser.error(f"--root 仅支持项目类别，不能扫描全局类别: {', '.join(sorted(outside_scope))}")

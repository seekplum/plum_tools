"""展示文件候选、原生操作及计划执行方式。"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .constants import CATEGORY_LABELS, Command, PruneAction, SnapshotMode
from .filesystem import display, format_reason, human_size, is_within
from .models import Candidate, ToolTask

if TYPE_CHECKING:
    from .state import CleanupState


class CleanupReporter:
    """基于运行快照输出 JSON 或终端预览。"""

    def __init__(self, state: CleanupState) -> None:
        """绑定本组件使用的运行状态和协作组件。"""
        self.state = state

    def report_data(self) -> dict:
        """返回候选与工具详情，未计量的数量和占用在 JSON 中使用 null。"""
        return {
            "mode": self.state.args.command,
            "action": self.state.args.prune_action,
            "estimated_bytes": (
                None
                if any(item.size is None for item in self.state.candidates)
                else sum(item.size for item in self.state.candidates)
            ),
            "measured_bytes": sum(item.size or 0 for item in self.state.candidates),
            "unmeasured_candidates": sum(item.size is None for item in self.state.candidates),
            "candidates": [
                {
                    "path": str(item.path),
                    "category": item.category,
                    "bytes": item.size,
                    "files": item.files,
                    "reason": format_reason(item.reason),
                    "rebuild": item.rebuild,
                    "snapshot": item.snapshot,
                }
                for item in self.state.candidates
            ],
            "tools": [
                {
                    "name": item.name,
                    "category": item.category,
                    "command": item.command,
                    "scope": item.scope,
                    "preview": item.preview,
                    "environment": item.environment,
                }
                for item in self.state.tasks
            ],
            "notes": [note.message() for note in self.state.notes],
            "errors": self.state.errors,
        }

    def report(self) -> None:
        """按类别与清理依据展示汇总及路径，JSON 模式仅输出原始数据。"""
        if self.state.args.json:
            print(json.dumps(self.report_data(), ensure_ascii=False, indent=2))
            return
        self._report_summary()
        for category, label in CATEGORY_LABELS.items():
            candidates = [item for item in self.state.candidates if item.category == category]
            tasks = [task for task in self.state.tasks if task.category == category]
            if not candidates and not tasks:
                continue
            self.state.console.rule(label, style="cyan")
            if candidates:
                self._report_candidates(candidates)
            if tasks:
                self._report_tasks(tasks)
        self._report_notes()
        if not self.state.errors and self.state.args.command in {Command.SCAN, Command.SHOW}:
            self._report_plan()

    def _report_summary(self) -> None:
        """先展示候选总量、扫描范围和类别占用，避免在长清单中寻找结论。"""

        if self.state.args.command == Command.PRUNE:
            self._report_prune_summary()
            return
        files, size = self._candidate_totals(self.state.candidates)
        summary = Text(f"{len(self.state.candidates):,} 个候选  ·  估算 {size}", style="bold green")
        if self.state.tasks:
            summary.append(f"  ·  {len(self.state.tasks):,} 项工具操作")
        if self.state.errors:
            title, style = "扫描不完整 · 未保存本次计划", "red"
        elif self.state.args.command == Command.RUN:
            title, style = "执行前预览", "cyan"
        else:
            title, style = "清理预览", "cyan"
        for root in self.state.args.roots:
            summary.append(f"\n范围: {self._display_path(root)}", style="bright_white")
        if any(item.snapshot == SnapshotMode.DIRECTORY for item in self.state.candidates):
            summary.append(
                "\n快速依赖：仅固定目录；内部变化不比对，保护项和排除规则在 run 时完整检查。",
                style="bright_yellow",
            )
        self.state.console.print(Panel(summary, title=title, border_style=style))
        table = Table(header_style="bold cyan", show_footer=True)
        table.add_column("类别", footer="合计")
        table.add_column("候选", justify="right", footer=f"{len(self.state.candidates):,}")
        table.add_column(
            "文件数",
            justify="right",
            footer=files,
        )
        table.add_column("估算占用", justify="right", footer=size)
        if self.state.tasks:
            table.add_column("工具操作", justify="right", footer=str(len(self.state.tasks)))
        for category, label in CATEGORY_LABELS.items():
            candidates = [item for item in self.state.candidates if item.category == category]
            tasks = [task for task in self.state.tasks if task.category == category]
            if not candidates and not tasks:
                continue
            category_files, category_size = self._candidate_totals(candidates)
            row = [
                label,
                f"{len(candidates):,}",
                category_files,
                category_size,
            ]
            if self.state.tasks:
                row.append(str(len(tasks)))
            table.add_row(*row)
        table.footer_style = "bold green"  # noqa
        self.state.console.print(table)
        self.state.console.print("移入 trash-cli 回收站；清空回收站后才释放空间。", style="bright_yellow")

    def _report_prune_summary(self) -> None:
        """突出原生操作数量与执行语义，避免混入文件计划统计。"""

        title = "工具清理 · 执行前预览" if self.state.args.prune_action == PruneAction.RUN else "工具清理预览"
        self.state.console.print(Panel(f"{len(self.state.tasks):,} 项原生工具操作", title=title, border_style="cyan"))
        table = Table(header_style="bold cyan")
        table.add_column("类别")
        table.add_column("工具操作", justify="right")
        for category, label in CATEGORY_LABELS.items():
            count = sum(task.category == category for task in self.state.tasks)
            if count:
                table.add_row(label, str(count))
        if self.state.tasks:
            self.state.console.print(table)
        self.state.console.print(
            "工具直接清理，不经过回收站；实际对象由执行时的工具状态决定，不使用文件计划。",
            style="bright_yellow",
        )

    def _candidate_totals(self, candidates: list[Candidate]) -> tuple[str, str]:
        """汇总已计量项，并明确区分快速模式中未统计的文件数与占用。"""
        measured = [item for item in candidates if item.size is not None]
        unknown = len(measured) != len(candidates)
        if unknown and not measured:
            return "未统计", "未统计"
        suffix = " + 未统计" if unknown else ""
        files = sum(item.files or 0 for item in measured)
        size = sum(item.size or 0 for item in measured)
        return f"{files:,}{suffix}", human_size(size) + suffix

    def _display_path(self, path: Path) -> str:
        """缩短 Home 前缀并转义控制字符，保持路径展示可辨认。"""
        if is_within(path, self.state.home):
            relative = path.relative_to(self.state.home).as_posix()
            return display("~" if relative == "." else "~/" + relative)
        return display(path)

    def _report_notes(self) -> None:
        """按相同原因归组说明，保留全部路径与错误详情。"""

        groups: dict[str, list[str]] = {}
        for note in dict.fromkeys(self.state.notes):
            if note.reason == "已保存清理计划":
                continue
            label = next((label for category, label in CATEGORY_LABELS.items() if note.reason == category), note.reason)
            groups.setdefault(label, []).append(note.description())
        if groups:
            self.state.console.rule("跳过与说明", style="yellow")
            for label, details in groups.items():
                tree = Tree(Text(f"{label} · {len(details):,} 项", style="bold bright_yellow"))
                for detail in details:
                    tree.add(Text(detail, style="bright_yellow"))
                self.state.console.print(tree)
        if self.state.errors:
            self.state.error_console.rule(
                "错误 · 请处理后重新查询" if self.state.args.command == Command.PRUNE else "错误 · 请处理后重新扫描",
                style="red",
            )
            for message in self.state.errors:
                self.state.error_console.print(Text(message, style="bold red"))

    def _report_plan(self) -> None:
        """集中展示实际计划路径和对应执行命令。"""

        command = ["pclean", Command.RUN]
        if not self.state.args.default_plan:
            command.extend(["--from-plan", str(self.state.plan_path)])
        text = Text(f"计划: {self._display_path(self.state.plan_path)}\n", style="bright_white")
        text.append(shlex.join(command), style="bold green")
        self.state.console.print(Panel(text, title="执行此计划", border_style="green"))

    def _report_candidates(self, candidates: list[Candidate]) -> None:
        """将共用依据合并在组顶部，为路径与容量表格保留完整宽度。"""

        groups: dict[tuple[str, str], list[Candidate]] = {}
        for item in candidates:
            key = format_reason(item.reason), item.rebuild
            groups.setdefault(key, []).append(item)
        for (reason, rebuild), items in sorted(
            groups.items(),
            key=lambda group: -sum(item.size or 0 for item in group[1]),
        ):
            files, size = self._candidate_totals(items)
            paths = Table(
                box=box.SIMPLE,
                expand=True,
                show_edge=False,
                show_footer=True,
                padding=(0, 1),
                header_style="bold cyan",
                footer_style="bold green",
            )
            paths.add_column("路径", ratio=1, overflow="fold", footer=f"{len(items):,} 个候选")
            paths.add_column(
                "文件数",
                justify="right",
                no_wrap=True,
                footer=files,
            )
            paths.add_column(
                "估算占用",
                justify="right",
                no_wrap=True,
                footer=size,
            )
            for item in items:
                paths.add_row(
                    Text(self._display_path(item.path)),
                    f"{item.files:,}" if item.files is not None else "未统计",
                    human_size(item.size) if item.size is not None else "未统计",
                )
            details = Group(
                Text("依据: " + display(reason)[1:-1], style="bold cyan"),
                Text("重建: " + rebuild, style="bright_white"),
                paths,
            )
            self.state.console.print(Panel(details, border_style="cyan"))

    def _report_tasks(self, tasks: list[ToolTask]) -> None:
        """展示原生命令、固定清理范围及工具提供的占用说明。"""

        table = Table("工具", "依据与范围", "命令与预览", header_style="bold cyan")
        for task in tasks:
            details = [shlex.join(task.command)]
            if task.environment:
                details.append(f"环境: {task.environment}")
            details.append(task.preview)
            table.add_row(Text(task.display_name), Text(display(task.scope)), Text("\n".join(details)))
        self.state.console.print(table)

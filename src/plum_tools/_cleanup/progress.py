"""将扫描和复核进度独立输出至 stderr。"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Column

from .filesystem import display


class ProgressDisplay:  # pylint: disable=too-many-instance-attributes
    """在 stderr 展示阶段进度，未知总量时持续显示扫描数量和耗时。"""

    def __init__(self, console: Console) -> None:
        """绑定终端，非交互环境只输出阶段开始与结束信息。"""

        self.console = console
        self.interactive = console.is_terminal and not console.is_dumb_terminal
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}", markup=False),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("已检查 {task.fields[nodes]:,} 项", markup=False),
            TextColumn("{task.fields[rate]:,.0f} 项/秒", markup=False),
            TimeElapsedColumn(),
            TextColumn(
                "{task.fields[path]}",
                markup=False,
                table_column=Column(ratio=1, no_wrap=True, overflow="ellipsis"),
            ),
            console=console,
            transient=True,
            refresh_per_second=4,
            redirect_stdout=False,
            redirect_stderr=False,
            disable=not self.interactive,
        )
        self.task: TaskID | None = None
        self.total: int | None = None
        self.nodes = 0
        self.completed = 0
        self.last_update = 0.0
        self.started = 0.0
        self.step_description: str | None = None
        self.step_started = 0.0
        self.step_start_nodes = 0
        self.step_unit = "项"
        self.steps: list[tuple[str, int, float]] = []

    @contextmanager
    def phase(self, description: str, total: int | None = None) -> Iterator[None]:
        """管理一个阶段的进度生命周期，异常退出时标记未完成。"""
        self.nodes = self.completed = 0
        self.total = total
        self.last_update = 0.0
        self.started = time.monotonic()
        self.steps.clear()
        self.task = self.progress.add_task(description, total=total, nodes=0, rate=0.0, path="")
        if not self.interactive:
            self.console.print(f"{description}……")
        finished = False
        try:
            with self.progress:
                yield
                finished = True
        finally:
            self._finish_step(finished)
            self.progress.remove_task(self.task)
            self.task = None
            self.total = None
            state = "完成" if finished else "未完成"
            count = "" if self.steps else f"检查 {self.nodes:,} 项 · "
            self.console.print(
                f"{description}{state} · {count}{time.monotonic() - self.started:.1f} 秒",
                style="green" if finished else "bright_yellow",
            )

    def describe(self, description: str, unit: str = "项") -> None:
        """结束上一步并单独统计新步骤的检查数量、速度与耗时。"""
        if self.task is None:
            return
        self._finish_step()
        self.step_description = description
        self.step_started = time.monotonic()
        self.step_start_nodes = self.nodes
        self.step_unit = unit
        self.last_update = 0.0
        self.progress.update(self.task, description=description, nodes=0, rate=0.0)
        if not self.interactive:
            self.console.print(f"  {description}", style="cyan")

    def _finish_step(self, finished: bool = True) -> None:
        """保留各步骤独立的数量和耗时，避免将重复遍历合并为文件总数。"""
        if self.step_description is None:
            return
        nodes = self.nodes - self.step_start_nodes
        elapsed = time.monotonic() - self.step_started
        self.steps.append((self.step_description, nodes, elapsed))
        state = "完成" if finished else "未完成"
        self.console.print(
            f"  {self.step_description}{state} · 检查 {nodes:,} {self.step_unit} · {elapsed:.2f} 秒",
            style="cyan" if finished else "bright_yellow",
        )
        self.step_description = None

    def visit(self, path: Path | str, count: int = 1) -> None:
        """记录扫描节点，限制刷新频率以避免进度更新拖慢遍历。"""
        if self.task is None:
            return
        self.nodes += count
        self._update(path)

    def advance(self, path: Path | str) -> None:
        """完成一个已知总量的工作项，并刷新其所在位置。"""
        self.completed += 1
        self._update(path, force=True)

    def _update(self, path: Path | str, force: bool = False) -> None:
        """更新终端显示，普通扫描每秒最多更新十次。"""
        if self.task is None or not self.interactive:
            return
        now = time.monotonic()
        if not force and now - self.last_update < 0.1:
            return
        self.last_update = now
        nodes = self.nodes
        started = self.started
        if self.step_description is not None:
            nodes -= self.step_start_nodes
            started = self.step_started
        self.progress.update(
            self.task,
            completed=nodes if self.total is None else self.completed,
            nodes=nodes,
            rate=nodes / max(now - started, 0.001),
            path=display(path),
        )

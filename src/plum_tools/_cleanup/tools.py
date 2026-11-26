"""查询本机工具、系统和 Docker 的原生清理范围。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from plum_tools._cleanup.constants import PRUNE_TOOLS, Category, DockerTask, Tool
from plum_tools._cleanup.filesystem import directory_fd, query_text
from plum_tools._cleanup.models import BuilderSnapshot, ToolTask, ToolVerification
from plum_tools._cleanup.projects import repository_at

if TYPE_CHECKING:
    from .filesystem import FileInspector
    from .state import CleanupState


class ToolScanner:
    """查询并固定原生工具的清理范围。"""

    def __init__(self, state: CleanupState, inspector: FileInspector) -> None:
        """绑定本组件使用的运行状态和协作组件。"""
        self.state = state
        self.inspector = inspector

    def add_cache_task(self, name: str, probe: list[str], command: list[str]) -> ToolTask | None:
        """从原生查询固定缓存路径，显式排除项存在时拒绝整库清理。"""
        cache = Path(query_text(probe)).expanduser()
        if not cache.is_absolute() or cache in {Path("/"), self.state.home}:
            raise ValueError("工具返回了过宽或无效的缓存路径")
        if not cache.exists():
            self.state.add_note(name, "缓存目录不存在")
            return None
        with directory_fd(cache):
            pass
        guard = cache.stat()
        if os.path.lexists(cache / ".git") or self.inspector.excluded(cache, cache, deleting=True):
            raise ValueError("缓存路径与仓库、运行环境或排除规则冲突")
        repository = repository_at(cache)
        if repository and repository.contains_tracked(cache):
            raise ValueError("缓存目录包含 Git 已跟踪文件，拒绝整库清理")
        if self.state.args.exclude:
            raise ValueError("原生命令不能逐文件遵守 --exclude，已跳过该工具")
        if self.state.args.older_than is not None:
            raise ValueError("原生命令不支持 --older-than，已跳过该工具")
        task = ToolTask(
            name,
            Category.TOOLS,
            [*command, str(cache)],
            str(cache),
            "原生工具决定可清理项；容量未知，不计入文件估算；后续安装可能重新下载",
            cache,
            (guard.st_dev, guard.st_ino),
            [ToolVerification(probe, str(cache))],
        )
        self.state.tasks.append(task)
        return task

    def scan_tools(self) -> None:
        """只查询已安装工具，不自动下载工具或依赖。"""
        selected = tuple(dict.fromkeys(self.state.args.tool or PRUNE_TOOLS))
        for name in selected:
            self.state.progress.visit(name)
            executable = shutil.which(name) if name != Tool.PIP else sys.executable
            if not executable:
                self.state.add_note(name, "未安装，跳过")
                continue
            self.state.protected_parts.add(Path(executable).absolute().parts)
            try:
                if name == Tool.NPM:
                    self.add_cache_task(
                        name,
                        [executable, "config", "get", "cache", "--logs-max=0"],
                        [
                            executable,
                            "cache",
                            "clean",
                            "--force",
                            "--logs-max=0",
                            "--cache",
                        ],
                    )
                elif name == Tool.PNPM:
                    self._scan_pnpm(executable)
                elif name == Tool.YARN:
                    self._scan_yarn(executable)
                elif name == Tool.PIP:
                    self.add_cache_task(
                        name,
                        [executable, "-m", "pip", "cache", "dir"],
                        [executable, "-m", "pip", "cache", "purge", "--cache-dir"],
                    )
                elif name == Tool.UV:
                    self.add_cache_task(
                        name,
                        [executable, "cache", "dir"],
                        [
                            executable,
                            "--no-config",
                            "--offline",
                            "cache",
                            "prune",
                            "--cache-dir",
                        ],
                    )
                elif name == Tool.GO:
                    self._scan_go(executable)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.state.add_note(name, str(exc))

    def _scan_go(self, executable: str) -> None:
        """分别固定 Go 构建与模块缓存，单个范围不可用时仍检查另一范围。"""
        for name, variable, flags, description in (
            ("go", "GOCACHE", ["-cache", "-testcache", "-fuzzcache"], "Go 构建、测试结果与模糊测试语料缓存"),
            ("go-modcache", "GOMODCACHE", ["-modcache"], "Go 共享模块下载缓存（含解压的依赖源码）"),
        ):
            try:
                task = self.add_cache_task(name, [executable, "env", variable], [executable, "clean", *flags])
                if task:
                    # Go 通过环境变量限定清理范围，不接受缓存目录作为位置参数。
                    task.command.pop()
                    task.environment[variable] = str(task.cache)
                    task.scope = f"{description}: {task.cache}"
                    task.preview += (
                        "；模糊测试缓存移除后需重新积累语料" if variable == "GOCACHE" else "；影响共享缓存的所有项目"
                    )
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                self.state.add_note(f"go {variable}", str(exc))

    def scan_system_cache(self) -> None:
        """为 Linux 软件包下载缓存生成原生命令，保留软件和系统状态。"""
        if sys.platform != "linux":
            self.state.add_note(Category.SYSTEM_CACHE, "仅支持 Linux，当前系统跳过")
            return
        if os.geteuid() != 0:
            self.state.add_note(Category.SYSTEM_CACHE, "需要 root 权限，未自动提权，已跳过")
            return
        if self.state.args.exclude or self.state.args.older_than is not None:
            self.state.add_note(Category.SYSTEM_CACHE, "原生命令不能遵守时间或路径筛选，已跳过")
            return
        for name, arguments in (
            ("apt-get", ["clean"]),
            ("dnf", ["clean", "packages"]),
            ("yum", ["clean", "packages"]),
        ):
            self.state.progress.visit(name)
            executable = shutil.which(name)
            if executable:
                self.state.tasks.append(
                    ToolTask(
                        name,
                        Category.SYSTEM_CACHE,
                        [executable, *arguments],
                        "Linux 软件包下载缓存",
                        "原生命令决定范围；不卸载软件、不清日志、不修改软件源",
                    )
                )
                break
        else:
            self.state.add_note(Category.SYSTEM_CACHE, "未找到受支持的 APT/DNF/YUM")

    def scan_docker(self) -> None:
        """固定本地 Docker 引擎身份，预览悬空镜像与选定 builder 的旧缓存。"""
        executable = shutil.which("docker")
        if not executable:
            self.state.add_note(Category.DOCKER, "未安装，跳过")
            return
        if self.state.args.exclude:
            self.state.add_note(Category.DOCKER, "原生命令不能逐路径遵守 --exclude，已跳过")
            return
        try:
            self.state.progress.visit("Docker 上下文")
            base, context, endpoint, verifications = self._resolve_docker_engine(executable)
            if not endpoint.startswith("unix://"):
                self.state.add_note(Category.DOCKER, "当前连接不是本地 Unix 套接字，已跳过远程引擎")
                return
            self.state.progress.visit(f"Docker 引擎 {context}")
            identity_command = [*base, "info", "--format", "{{.ID}}"]
            identity = query_text(identity_command)
            if not identity or identity == "<no value>":
                raise ValueError("无法读取 Docker 引擎 ID，拒绝添加清理任务")
            verifications.append(ToolVerification(identity_command, identity))
            preview = query_text([*base, "system", "df"])
            days = 30 if self.state.args.older_than is None else self.state.args.older_than
            filters = ["--filter", f"until={days * 24}h"] if days else []
            images = ToolTask(
                DockerTask.IMAGES,
                Category.DOCKER,
                [*base, "image", "prune", "--force", *filters],
                f"本地引擎 {context} 的悬空镜像；创建超过 {days} 天",
                preview + "\n上表为引擎整体占用，并非本次精确可回收容量；保留所有容器及数据卷",
                verifications=list(verifications),
            )
            self.state.tasks.append(images)
            self._add_docker_builder(base, context, endpoint, days, filters, verifications)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            self.state.errors.append(f"Docker：{exc}")

    def _resolve_docker_engine(self, executable: str) -> tuple[list[str], str, str, list[ToolVerification]]:
        """固定环境变量或显式 context 对应的引擎和复核查询。"""
        if os.environ.get("DOCKER_HOST") and not (self.state.args.docker_context or os.environ.get("DOCKER_CONTEXT")):
            endpoint = os.environ["DOCKER_HOST"]
            base = [executable, "--host", endpoint]
            context = "default"
            verifications = []
        else:
            context = (
                self.state.args.docker_context
                or os.environ.get("DOCKER_CONTEXT")
                or query_text([executable, "context", "show"])
            )
            verification = [
                executable,
                "context",
                "inspect",
                context,
                "--format",
                "{{.Endpoints.docker.Host}}",
            ]
            endpoint = query_text(verification)
            if not endpoint:
                raise ValueError("Docker 上下文未返回引擎端点")
            verifications = [ToolVerification(verification, endpoint)]
            base = [executable, "--context", context]
        return base, context, endpoint, verifications

    def _add_docker_builder(
        self,
        base: list[str],
        context: str,
        endpoint: str,
        days: int,
        filters: list[str],
        verifications: list[ToolVerification],
    ) -> None:
        """仅为当前运行且 endpoint 一致的本地 builder 添加回收任务。"""
        builder = self.state.args.docker_builder or context
        inspect_command = [*base, "buildx", "inspect", builder]
        self.state.progress.visit(f"Buildx 构建器 {builder}")
        details = query_text(inspect_command)
        snapshot = BuilderSnapshot.parse(details)
        reason = ""
        if snapshot.driver not in {"docker", "docker-container"}:
            reason = "构建器未使用可验证的本地 Docker 驱动"
        elif any(node_endpoint not in {context, endpoint} for _, node_endpoint, _ in snapshot.nodes):
            reason = "构建器包含其他引擎端点"
        elif any(status != "running" for _, _, status in snapshot.nodes):
            reason = "构建器当前未运行"
        if reason:
            if self.state.args.docker_builder:
                raise ValueError(f"指定的构建器 {builder}：{reason}")
            self.state.add_note(Category.DOCKER, reason + "，跳过构建缓存")
            return
        builder_name = snapshot.name
        self.state.tasks.append(
            ToolTask(
                DockerTask.BUILD,
                Category.DOCKER,
                [
                    *base,
                    "buildx",
                    "prune",
                    "--builder",
                    builder_name,
                    "--force",
                    *filters,
                ],
                f"本地构建器 {builder_name} 超过 {days} 天未使用的构建缓存",
                "BuildKit 自行判断可回收项；容量未知；仅选择当前运行的本地构建器，保留其容器",
                verifications=[
                    *verifications,
                    ToolVerification(inspect_command, snapshot),
                ],
            )
        )

    def discover_prune_tasks(self) -> None:
        """查询原生工具当次清理范围，不加载或保存文件计划。"""
        for category, description, scan in (
            (Category.TOOLS, "查询工具缓存", self.scan_tools),
            (Category.SYSTEM_CACHE, "查询系统缓存", self.scan_system_cache),
            (Category.DOCKER, "查询 Docker 缓存", self.scan_docker),
        ):
            if category in self.state.args.categories:
                with self.state.progress.phase(description):
                    scan()

    def _scan_pnpm(self, executable: str) -> None:
        """固定 pnpm 存储路径；无法复核时撤销对应任务。"""
        task = self.add_cache_task(
            Tool.PNPM,
            [executable, "store", "path"],
            [executable, "store", "prune", "--store-dir"],
        )
        if task and task.cache:
            store = task.cache.parent if re.fullmatch(r"v\d+", task.cache.name) else task.cache
            task.command[-1] = str(store)
            task.verifications[0].command = [
                executable,
                "store",
                "path",
                "--store-dir",
                str(store),
            ]
            try:
                task.verifications[0].validate()
            except ValueError as exc:
                self.state.tasks.remove(task)
                raise ValueError("无法固定 pnpm 存储路径，已跳过") from exc

    def _scan_yarn(self, executable: str) -> None:
        """仅查询 Yarn Classic 的全局缓存，项目缓存由文件规则处理。"""
        if not query_text([executable, "--version"]).startswith("1."):
            self.state.add_note(Tool.YARN, "仅自动处理 Yarn Classic 全局缓存，项目缓存遵循 Git 规则")
            return
        self.add_cache_task(
            Tool.YARN,
            [executable, "--silent", "cache", "dir"],
            [executable, "cache", "clean", "--cache-folder"],
        )

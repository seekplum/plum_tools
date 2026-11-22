"""定义清理候选、工具任务和不可变状态快照。"""

from __future__ import annotations

import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .constants import CATEGORY_LABELS, DEPENDENCIES, DOCKER_TASK_LABELS, PROJECT_CATEGORIES, Category, SnapshotMode
from .filesystem import display, query_text


def plan_path(value: str) -> Path:
    """读取规范绝对路径，避免计划随当前目录变化或通过父目录越界。"""
    if (
        not isinstance(value, str)
        or "\0" in value
        or not Path(value).is_absolute()
        or ".." in Path(value).parts
        or str(Path(value)) != value
    ):
        raise ValueError("清理计划中的路径必须为规范绝对路径")
    return Path(value)


def plan_signature(value: list) -> tuple[int, ...]:
    """验证与文件状态指纹一致的五项整数快照。"""
    if not isinstance(value, list) or len(value) != 5 or any(not isinstance(part, int) for part in value):
        raise ValueError("清理计划中的文件状态指纹无效")
    return tuple(value)


@dataclass
class Candidate:  # pylint: disable=too-many-instance-attributes
    """记录文件候选及确认后需要复核的状态。"""

    path: Path
    root: Path
    category: Category
    reason: str
    rebuild: str
    repository: Path | None = None
    manifests: dict[Path, tuple[int, ...]] = field(default_factory=dict)
    size: int | None = 0
    digest: str = ""
    newest: float = 0
    files: int | None = 0
    identity: tuple[int, ...] = ()
    snapshot: SnapshotMode = SnapshotMode.TREE

    def plan_data(self) -> dict:
        """序列化候选路径和复核快照，供后续独立执行使用。"""
        return {
            "path": str(self.path),
            "root": str(self.root),
            "category": self.category,
            "reason": self.reason,
            "rebuild": self.rebuild,
            "repository": str(self.repository) if self.repository else None,
            "manifests": {str(path): value for path, value in self.manifests.items()},
            "size": self.size,
            "digest": self.digest,
            "files": self.files,
            "identity": self.identity,
            "snapshot": self.snapshot,
        }

    @classmethod
    def from_plan(cls, data: dict) -> Candidate:
        """解析候选快照，拒绝不完整、越界或无法复核的记录。"""
        item = cls(
            plan_path(data["path"]),
            plan_path(data["root"]),
            Category(data["category"]),
            data["reason"],
            data["rebuild"],
            plan_path(data["repository"]) if data["repository"] is not None else None,
            {plan_path(path): plan_signature(value) for path, value in data["manifests"].items()},
            size=data["size"],
            digest=data["digest"],
            files=data["files"],
            identity=plan_signature(data["identity"]),
            snapshot=SnapshotMode(data["snapshot"]),
        )
        if item.snapshot == SnapshotMode.DIRECTORY:
            valid_snapshot = (
                item.category == Category.DEPS
                and item.path.name in DEPENDENCIES
                and item.size is None
                and item.files is None
                and item.digest == ""
                and stat.S_ISDIR(item.identity[2])
            )
        else:
            valid_snapshot = (
                isinstance(item.size, int)
                and item.size >= 0
                and isinstance(item.files, int)
                and item.files >= 1
                and isinstance(item.digest, str)
                and re.fullmatch(r"[0-9a-f]{128}", item.digest) is not None
            )
        # pylint: disable=too-many-boolean-expressions
        if (
            item.root not in item.path.parents
            or item.root == Path("/")
            or (item.category not in PROJECT_CATEGORIES and item.root == Path.home().resolve())
            or (item.repository and item.repository not in item.path.parents)
            or item.category not in CATEGORY_LABELS
            or not all(isinstance(value, str) for value in (item.reason, item.rebuild))
            or not valid_snapshot
        ):
            raise ValueError("清理计划包含无效候选")
        return item


@dataclass(frozen=True)
class Note:
    """显式保存说明分组与路径，对外仍序列化为字符串。"""

    reason: str
    detail: str = ""
    path: Path | None = None

    def description(self) -> str:
        """返回路径及详情，供终端树形展示和文本序列化共用。"""
        if self.path is None:
            return self.detail
        return display(self.path) + (f": {self.detail}" if self.detail else "")

    def message(self) -> str:
        """以“原因: 详情”输出字符串，保留计划和 JSON 的说明格式。"""
        detail = self.description()
        return f"{self.reason}: {detail}" if detail else self.reason

    @classmethod
    def from_message(cls, message: str) -> Note:
        """读取计划的“原因: 详情”字符串，无分隔符时归入普通说明。"""
        reason, separator, detail = message.partition(": ")
        return cls(reason, detail) if separator else cls("说明", message)


@dataclass
class ExecutionSnapshot:
    """保留一次完整计量结果，供最终目录描述符复核使用。"""

    size: int
    digest: str
    records: dict[Path, tuple[int, ...]]


@dataclass
class CandidateResult:
    """隔离工作线程的计量结果与失败说明，由主线程统一接收。"""

    candidate: Candidate | None = None
    note: Note | None = None
    error: str = ""


@dataclass(frozen=True)
class BuilderSnapshot:
    """只保留 builder 名称、驱动及逐节点范围，忽略活动时间等易变字段。"""

    name: str
    driver: str
    nodes: tuple[tuple[str, str, str], ...]

    @classmethod
    def parse(cls, text: str) -> BuilderSnapshot:
        """读取 inspect 的节点区块，缺字段、重复字段或节点错误均拒绝。"""
        header: dict[str, str] = {}
        nodes: list[dict[str, str]] = []
        inside_nodes = False
        for line in text.splitlines():
            key, separator, value = line.strip().partition(":")
            if not separator:
                continue
            value = value.strip()
            if key == "Error":
                raise ValueError(f"Buildx builder 查询失败: {value or '未知错误'}")
            if key == "Nodes":
                if inside_nodes:
                    raise ValueError("Buildx inspect 包含重复的 Nodes 区块")
                inside_nodes = True
                continue
            target = _builder_field_target(key, header, nodes, inside_nodes)
            if target is None:
                continue
            if key in target or not value:
                raise ValueError(f"Buildx inspect 字段重复或为空: {key}")
            target[key] = value
        if set(header) != {"Name", "Driver"} or not nodes:
            raise ValueError("Buildx inspect 缺少 builder 名称、驱动或节点")
        if any(set(node) != {"Name", "Endpoint", "Status"} for node in nodes):
            raise ValueError("Buildx inspect 节点缺少 Name、Endpoint 或 Status")
        if len({node["Name"] for node in nodes}) != len(nodes):
            raise ValueError("Buildx inspect 包含重复的节点名称")
        return cls(
            header["Name"],
            header["Driver"],
            tuple(sorted((node["Name"], node["Endpoint"], node["Status"]) for node in nodes)),
        )


@dataclass
class ToolVerification:
    """保存一次只读查询的预期范围，builder 仅比较稳定字段。"""

    command: list[str]
    expected: str | BuilderSnapshot

    def validate(self) -> None:
        """重新查询相同对象，范围不符或查询异常时停止清理。"""
        result = query_text(self.command)
        current: str | BuilderSnapshot = result
        if isinstance(self.expected, BuilderSnapshot):
            current = BuilderSnapshot.parse(result)
        if current != self.expected:
            raise ValueError("工具范围或引擎身份已变化，请重新预览")


@dataclass
class ToolTask:  # pylint: disable=too-many-instance-attributes
    """记录原生工具命令、固定范围和只读预览。"""

    name: str
    category: Category
    command: list[str]
    scope: str
    preview: str
    cache: Path | None = None
    guard: tuple[int, int] | None = None
    verifications: list[ToolVerification] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """返回终端展示名称，保留工具产品名和原始任务标识。"""
        return DOCKER_TASK_LABELS.get(self.name, self.name)


def _builder_field_target(
    key: str, header: dict[str, str], nodes: list[dict[str, str]], inside_nodes: bool
) -> dict[str, str] | None:
    """选择有效字段所属的 builder 或节点区块，并拒绝无名称的节点。"""
    if not inside_nodes:
        return header if key in {"Name", "Driver"} else None
    if key == "Name":
        nodes.append({})
    if key not in {"Name", "Endpoint", "Status"}:
        return None
    if not nodes:
        raise ValueError("Buildx inspect 节点缺少 Name")
    return nodes[-1]


@dataclass(frozen=True)
class ProjectScope:
    """固定一次项目遍历的根目录、文件系统及缓存排除边界。"""

    root: Path
    device: int
    cache_roots: tuple[Path, ...]

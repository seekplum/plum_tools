"""定义报告使用的数据结构与枚举。"""

from dataclasses import dataclass, field

from plum_tools.utils.git_history import CommitRelationStatus
from plum_tools.utils.printer import display_path


@dataclass(frozen=True)
class RepositoryRelation:
    """保存当前目录相对目标目录的提交关系及无法判断的原因。"""

    path: str
    status: CommitRelationStatus
    local_only: int | None = None
    other_only: int | None = None
    reason: str = ""

    def label(self) -> str:
        """返回包含目标目录和提交数量的中文关系说明。"""
        target = repr(display_path(self.path))
        status = self.status
        if status == CommitRelationStatus.AHEAD:
            return f"{status.desc}目录 {target} {self.local_only} 个提交"
        if status == CommitRelationStatus.BEHIND:
            return f"{status.desc}目录 {target} {self.other_only} 个提交"
        if status == CommitRelationStatus.DIVERGED:
            return f"与目录 {target} {status.desc}，各自独有 {self.local_only} / {self.other_only} 个提交"
        reason = f"（{self.reason}）" if self.reason else ""
        return f"与目录 {target} {status.desc}{reason}"


@dataclass
class Repository:  # pylint: disable=too-many-instance-attributes
    """保存单个仓库目录的身份、远程及完整检查结果。"""

    path: str
    common_dir: str = ""
    remote_name: str = ""
    remote_url: str = ""
    branch: str = ""
    bare: bool = False
    worktree: bool = False
    issues: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    remotes: dict[str, list[str]] = field(default_factory=dict)
    statuses: list[str] = field(default_factory=list)
    changes: list[dict[str, str]] = field(default_factory=list)
    stashes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    commit_time: int | None = None
    commit: str = ""
    commit_relations: list[RepositoryRelation] = field(default_factory=list)
    submodule: bool = False

    @property
    def remote_urls(self) -> set[str]:
        """返回所有 remote 的规范化地址，包含首选远程地址并去重。"""
        return {url for urls in self.remotes.values() for url in urls} | (
            {self.remote_url} if self.remote_url else set()
        )


class GitScanError(RuntimeError):
    """表示 Git 命令失败或超时，避免单个仓库中断整次扫描。"""


@dataclass
class DirectoryScanError:
    """分别保存出错路径和原始原因，供目录扫描错误分组展示。"""

    path: str
    reason: str


@dataclass
class _ScanReport:
    """保存两种输出共用的已筛选仓库组、重复标记和全量统计。"""

    groups: dict[str, dict[str, list[Repository]]]
    duplicates: set[str]
    summary: dict[str, int]
    latest_paths: set[str] = field(default_factory=set)
    tied_latest_paths: set[str] = field(default_factory=set)

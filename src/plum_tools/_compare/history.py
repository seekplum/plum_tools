"""根据各输入的 HEAD 和可达提交，比较独立克隆的历史。"""

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from plum_tools._compare import remote
from plum_tools._compare.comparison import _remote_output, _split_remote
from plum_tools._compare.models import Comparison
from plum_tools._compare.remote import GitHead
from plum_tools.utils.git_history import CommitRelationStatus, compare_commits


@dataclass(frozen=True)
class CommitRelation:
    """用从 1 开始的输入编号描述两个 HEAD 的关系及各自独有的提交数。"""

    left: int
    right: int
    status: CommitRelationStatus
    left_only: int | None = None
    right_only: int | None = None

    def label(self) -> str:
        """返回包含输入编号和领先数量的终端说明。"""
        status = self.status
        if status == CommitRelationStatus.AHEAD:
            return f"[{self.left}] {status.desc} [{self.right}] {self.left_only} 个提交"
        if status == CommitRelationStatus.BEHIND:
            return f"[{self.right}] {CommitRelationStatus.AHEAD.desc} [{self.left}] {self.right_only} 个提交"
        return f"[{self.left}] 与 [{self.right}] {status.desc}"


@dataclass(frozen=True)
class GitComparison:
    """保存各输入的 HEAD 及仓库之间的逐对比较。"""

    heads: list[GitHead | None]
    relations: list[CommitRelation]


def _history(path: str, commit: str) -> set[str]:
    location = _split_remote(path)
    if location is None:
        data = remote.commit_history(Path(path).expanduser().absolute(), commit)
    else:
        try:
            data = _remote_output(*location, {"history": commit})
        except OSError:
            return set()
    return set(data.splitlines()) if data.strip() else set()


def _relation(first: tuple[int, str], second: tuple[int, str], histories: dict[str, set[str]]) -> CommitRelation:
    i, left = first
    j, right = second
    return CommitRelation(i, j, *compare_commits(left, right, histories.get(left, set()), histories.get(right, set())))


def compare_heads(paths: list[str], comparisons: list[Comparison]) -> GitComparison | None:
    """从根条目取得 HEAD 并比较可达历史，至少有两个仓库时返回报告。"""
    root = next((item for item in comparisons if item.path == Path(".")), None)
    if root is None:
        return None
    heads = [entry.git_head if entry else None for entry in root.entries]
    repos = [(i, head.commit) for i, head in enumerate(heads, 1) if head is not None]
    if len(repos) < 2:
        return None
    histories: dict[str, set[str]] = {}
    if len({commit for _, commit in repos if commit}) > 1:
        # 独立克隆可能各有未推送提交，比较各自可达集可避免依赖远程跟踪引用。
        for index, commit in repos:
            if commit and not histories.get(commit):
                histories[commit] = _history(paths[index - 1], commit)
    return GitComparison(heads, [_relation(left, right, histories) for left, right in combinations(repos, 2)])

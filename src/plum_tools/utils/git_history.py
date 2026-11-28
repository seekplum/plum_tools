"""根据固定 HEAD 的完整可达历史判定提交关系。"""

from plum_tools.utils.enums import DocStrEnum


class CommitRelationStatus(DocStrEnum):
    """统一维护提交关系的序列化值与中文描述。"""

    EQUAL = "equal", "提交相同"
    AHEAD = "ahead", "领先"
    BEHIND = "behind", "落后"
    DIVERGED = "diverged", "已分叉"
    UNRELATED = "unrelated", "无共同历史"
    UNKNOWN = "unknown", "关系未知"

    @property
    def style(self) -> str:
        """返回当前提交关系的终端颜色，供各命令统一展示。"""
        return {
            CommitRelationStatus.EQUAL: "green",
            CommitRelationStatus.AHEAD: "cyan",
            CommitRelationStatus.BEHIND: "yellow",
            CommitRelationStatus.DIVERGED: "bold red",
            CommitRelationStatus.UNRELATED: "magenta",
            CommitRelationStatus.UNKNOWN: "dim white",
        }[self]


def compare_commits(
    left: str, right: str, left_history: set[str], right_history: set[str]
) -> tuple[CommitRelationStatus, int | None, int | None]:
    """比较两个提交及其完整历史，返回关系和左右各自独有的提交数。"""
    if left and left == right:
        return CommitRelationStatus.EQUAL, 0, 0
    if not left or not right or not left_history or not right_history:
        return CommitRelationStatus.UNKNOWN, None, None
    left_only = len(left_history - right_history)
    right_only = len(right_history - left_history)
    if left in right_history:
        return CommitRelationStatus.BEHIND, left_only, right_only
    if right in left_history:
        return CommitRelationStatus.AHEAD, left_only, right_only
    status = CommitRelationStatus.DIVERGED if left_history & right_history else CommitRelationStatus.UNRELATED
    return status, left_only, right_only

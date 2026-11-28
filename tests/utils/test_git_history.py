"""验证完整提交历史的公共关系判定。"""

import pytest

from plum_tools.utils.git_history import CommitRelationStatus, compare_commits


@pytest.mark.parametrize(
    ("status", "value", "description"),
    [
        (CommitRelationStatus.EQUAL, "equal", "提交相同"),
        (CommitRelationStatus.AHEAD, "ahead", "领先"),
        (CommitRelationStatus.BEHIND, "behind", "落后"),
        (CommitRelationStatus.DIVERGED, "diverged", "已分叉"),
        (CommitRelationStatus.UNRELATED, "unrelated", "无共同历史"),
        (CommitRelationStatus.UNKNOWN, "unknown", "关系未知"),
    ],
)
def test_relation_status_value_and_description(status: CommitRelationStatus, value: str, description: str) -> None:
    assert status.value == value
    assert status.desc == description
    assert str(status) == value


@pytest.mark.parametrize(
    ("left", "right", "left_history", "right_history", "expected"),
    [
        ("a", "a", set(), set(), ("equal", 0, 0)),
        ("", "", set(), set(), ("unknown", None, None)),
        ("a", "b", {"a"}, set(), ("unknown", None, None)),
        ("", "b", set(), {"b"}, ("unknown", None, None)),
        ("a", "c", {"a"}, {"a", "b", "c"}, ("behind", 0, 2)),
        ("c", "a", {"a", "b", "c"}, {"a"}, ("ahead", 2, 0)),
        ("c", "d", {"a", "b", "c"}, {"a", "d"}, ("diverged", 2, 1)),
        ("a", "c", {"a"}, {"b", "c"}, ("unrelated", 1, 2)),
    ],
)
def test_compare_commits(
    left: str,
    right: str,
    left_history: set[str],
    right_history: set[str],
    expected: tuple[str, int | None, int | None],
) -> None:
    result = compare_commits(left, right, left_history, right_history)
    assert result == expected
    assert isinstance(result[0], CommitRelationStatus)

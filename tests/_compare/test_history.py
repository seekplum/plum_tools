"""验证公共关系判定接入后的比较报告与历史缓存。"""

from pathlib import Path
from unittest import mock

import pytest

from plum_tools._compare.history import CommitRelation, _history, compare_heads
from plum_tools._compare.models import Comparison
from plum_tools._compare.remote import Entry, EntryKind, GitHead
from plum_tools.utils.git_history import CommitRelationStatus


def _root(*commits: str | None) -> Comparison:
    return Comparison(
        Path("."),
        tuple(
            Entry(Path(f"/{i}"), EntryKind.DIRECTORY, git_head=GitHead("main", commit)) if commit is not None else None
            for i, commit in enumerate(commits)
        ),
        tuple(range(len(commits))),
        "一致",
    )


def test_equal_heads_skip_history() -> None:
    with mock.patch("plum_tools._compare.history._history") as history:
        report = compare_heads(["/a", "/b"], [_root("a", "a")])
    history.assert_not_called()
    assert report is not None
    assert report.relations == [CommitRelation(1, 2, CommitRelationStatus.EQUAL, 0, 0)]


def test_cache_retries_failed_copy_and_uses_input_numbers() -> None:
    paths = ["/a", "/b", "/plain", "/c", "/d"]
    with mock.patch("plum_tools._compare.history._history", side_effect=[set(), {"a"}, {"a", "b"}]) as history:
        report = compare_heads(paths, [_root("a", "a", None, "b", "b")])
    history.assert_has_calls([mock.call("/a", "a"), mock.call("/b", "a"), mock.call("/c", "b")])
    assert history.call_count == 3
    assert report is not None
    assert report.relations == [
        CommitRelation(1, 2, CommitRelationStatus.EQUAL, 0, 0),
        CommitRelation(1, 4, CommitRelationStatus.BEHIND, 0, 1),
        CommitRelation(1, 5, CommitRelationStatus.BEHIND, 0, 1),
        CommitRelation(2, 4, CommitRelationStatus.BEHIND, 0, 1),
        CommitRelation(2, 5, CommitRelationStatus.BEHIND, 0, 1),
        CommitRelation(4, 5, CommitRelationStatus.EQUAL, 0, 0),
    ]


@pytest.mark.parametrize("comparisons", [[], [_root("a", None)]])
def test_no_comparison_without_two_repositories(comparisons: list[Comparison]) -> None:
    with mock.patch("plum_tools._compare.history._history") as history:
        assert compare_heads(["/a", "/b"], comparisons) is None
    history.assert_not_called()


def test_empty_head_is_unknown() -> None:
    report = compare_heads(["/a", "/b"], [_root("", "a")])
    assert report is not None
    assert report.relations == [CommitRelation(1, 2, CommitRelationStatus.UNKNOWN)]


def test_remote_history_failure_is_unknown() -> None:
    with mock.patch("plum_tools._compare.history._remote_output", side_effect=OSError("无法连接")) as remote:
        assert _history("host:/repo", "a") == set()
    remote.assert_called_once_with("host", "/repo", {"history": "a"})


@pytest.mark.parametrize(
    ("status", "left", "right", "label"),
    [
        (CommitRelationStatus.EQUAL, 0, 0, "[1] 与 [3] 提交相同"),
        (CommitRelationStatus.AHEAD, 2, 0, "[1] 领先 [3] 2 个提交"),
        (CommitRelationStatus.BEHIND, 0, 3, "[3] 领先 [1] 3 个提交"),
        (CommitRelationStatus.DIVERGED, 2, 3, "[1] 与 [3] 已分叉"),
        (CommitRelationStatus.UNRELATED, 2, 3, "[1] 与 [3] 无共同历史"),
        (CommitRelationStatus.UNKNOWN, None, None, "[1] 与 [3] 关系未知"),
    ],
)
def test_relation_labels(status: CommitRelationStatus, left: int | None, right: int | None, label: str) -> None:
    assert CommitRelation(1, 3, status, left, right).label() == label

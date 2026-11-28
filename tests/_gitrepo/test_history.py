"""验证重复克隆的提交关系、时间标记、缓存及正常命令入口。"""

import json
import os
import shutil
import subprocess
from io import StringIO
from pathlib import Path
from threading import Lock
from unittest import mock

import pytest
from rich.console import Console

from plum_tools._gitrepo.grouping import _build_scan_report
from plum_tools._gitrepo.history import _read_head, _read_history, compare_duplicate_heads
from plum_tools._gitrepo.models import GitScanError, Repository, RepositoryRelation
from plum_tools._gitrepo.reporting import _print_scan_results, _scan_json_repositories
from plum_tools._gitrepo.repository import _git, _scan_repository
from plum_tools.cli.gitrepo import main
from plum_tools.cli.pcompare import main as compare_main
from plum_tools.utils.git_history import CommitRelationStatus


@pytest.fixture(autouse=True)  # noqa
def _isolate_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离提交 hook 的 Git 环境，保证临时仓库使用各自的索引和对象。"""
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)


def _local_git(path: Path, *args: str, data: str | None = None) -> str:
    executable = shutil.which("git")
    assert executable is not None
    # 可执行路径已解析，参数全部由本地测试夹具生成。
    return subprocess.run(  # nosec B603
        [executable, "-c", "core.hooksPath=/dev/null", *args],
        cwd=path,
        input=data,
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "测试",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "测试",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
        },
    ).stdout.strip()


@pytest.fixture
def clones(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    source = tmp_path / "source"
    source.mkdir()
    _local_git(source, "init", "-b", "main")
    tree = _local_git(source, "mktree", data="")
    commits: dict[str, str] = {}
    for name, parent in (("base", ""), ("left", "base"), ("left2", "left"), ("right", "base"), ("other", "")):
        commits[name] = _local_git(
            source, "commit-tree", tree, "-m", name, *(("-p", commits[parent]) if parent else ())
        )
        _local_git(source, "update-ref", f"refs/heads/{name}", commits[name])
    _local_git(source, "update-ref", "refs/heads/main", commits["base"])
    paths = [tmp_path / "first [red]", tmp_path / "second"]
    for path in paths:
        _local_git(tmp_path, "clone", "--no-hardlinks", str(source), str(path))
    return paths[0], paths[1], commits


@pytest.mark.parametrize(
    ("left", "right", "status", "counts"),
    [
        ("base", "base", "equal", (0, 0)),
        ("left2", "base", "ahead", (2, 0)),
        ("base", "left2", "behind", (0, 2)),
        ("left2", "right", "diverged", (2, 1)),
        ("base", "other", "unrelated", (1, 1)),
    ],
)
def test_cli_compares_real_clone_histories(
    clones: tuple[Path, Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    left: str,
    right: str,
    status: str,
    counts: tuple[int, int],
) -> None:
    first, second, commits = clones
    for path, name in ((first, left), (second, right)):
        _local_git(path, "update-ref", "refs/heads/main", commits[name])
    (first / "新文件").write_text("工作区有修改", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["gitrepo", "scan", "-p", str(first), str(second), "--json"])
    main()
    payload = json.loads(capsys.readouterr().out)
    rows = {row["path"]: row for row in payload["repositories"]}
    row = rows[str(first)]
    assert row["commit"] == commits[left]
    assert row["commit_relations"] == [
        {"path": str(second), "status": status, "local_only": counts[0], "other_only": counts[1], "reason": ""}
    ]
    reverse = {"ahead": "behind", "behind": "ahead"}.get(status, status)
    assert rows[str(second)]["commit_relations"][0] == {
        "path": str(first),
        "status": reverse,
        "local_only": counts[1],
        "other_only": counts[0],
        "reason": "",
    }
    assert "untracked" in row["statuses"]
    assert row["latest_commit_time"] is row["tied_latest_commit_time"] is True
    assert rows[str(second)]["latest_commit_time"] is rows[str(second)]["tied_latest_commit_time"] is True
    assert payload["summary"]["duplicate_group_count"] == 1
    monkeypatch.setattr("sys.argv", ["pcompare", str(first), str(second), "--json"])
    with pytest.raises(SystemExit) as exit_info:
        compare_main()
    compared = json.loads(capsys.readouterr().out)
    assert exit_info.value.code == 1
    assert compared["git"]["relations"] == [
        {"left": 1, "right": 2, "status": status, "left_only": counts[0], "right_only": counts[1]}
    ]


@pytest.mark.parametrize("kind", ["bare", "detached", "worktree"])
def test_head_for_bare_detached_and_worktree(clones: tuple[Path, Path, dict[str, str]], kind: str) -> None:
    first, second, commits = clones
    target = first.parent / kind
    if kind == "bare":
        _local_git(first.parent, "clone", "--bare", str(first), str(target))
        _local_git(target, "remote", "set-url", "origin", str(first.parent / "source"))
    elif kind == "worktree":
        _local_git(first, "worktree", "add", "--detach", str(target), commits["base"])
    else:
        target = first
        _local_git(first, "checkout", "--detach", commits["base"])
    repos = [_scan_repository(str(path), False, {}, Lock(), stash=False) for path in (target, second)]
    compare_duplicate_heads(repos)
    assert repos[0].commit == repos[1].commit == commits["base"]
    assert repos[0].commit_relations == [RepositoryRelation(str(second), CommitRelationStatus.EQUAL, 0, 0)]
    assert repos[0].bare is (kind == "bare")
    assert repos[0].worktree is (kind == "worktree")
    assert repos[0].commit_time == repos[1].commit_time


def test_shallow_history_is_unknown(clones: tuple[Path, Path, dict[str, str]]) -> None:
    first, second, commits = clones
    shallow = first.parent / "shallow"
    _local_git(first.parent, "clone", "--depth=1", (first.parent / "source").as_uri(), str(shallow))
    _local_git(second, "update-ref", "refs/heads/main", commits["left"])
    repos = [_scan_repository(str(path), False, {}, Lock(), stash=False) for path in (shallow, second)]
    compare_duplicate_heads(repos)
    relation = repos[0].commit_relations[0]
    assert relation.status == "unknown"
    assert relation.local_only is relation.other_only is None
    assert "浅克隆历史不完整" in relation.reason
    assert str(shallow) in relation.reason
    assert "关系未知" in relation.label()
    _local_git(second, "update-ref", "refs/heads/main", commits["base"])
    repos[1] = _scan_repository(str(second), False, {}, Lock(), stash=False)
    compare_duplicate_heads(repos)
    assert repos[0].commit_relations == [RepositoryRelation(str(second), CommitRelationStatus.EQUAL, 0, 0)]


def test_unborn_has_unknown_relation(clones: tuple[Path, Path, dict[str, str]]) -> None:
    first, _, _ = clones
    empty = first.parent / "empty"
    empty.mkdir()
    _local_git(empty, "init", "-b", "main")
    _local_git(empty, "remote", "add", "origin", str(first.parent / "source"))
    repos = [_scan_repository(str(path), False, {}, Lock(), stash=False) for path in (first, empty)]
    compare_duplicate_heads(repos)
    assert repos[1].commit == ""
    assert repos[0].commit_relations[0].status == "unknown"
    assert "尚无提交" in repos[0].commit_relations[0].reason
    assert "unborn" in repos[1].statuses


def _repo(path: str, commit: str) -> Repository:
    return Repository(path, common_dir=f"{path}/.git", remote_url="example.com/project", commit=commit)


def test_equal_heads_skip_history_and_keep_worktree_state() -> None:
    repos = [_repo("/a", "a" * 40), _repo("/b", "a" * 40)]
    repos[0].issues = ["未跟踪 1"]
    repos[0].statuses = ["untracked"]
    with mock.patch("plum_tools._gitrepo.history._git") as git:
        compare_duplicate_heads(repos)
    git.assert_not_called()
    assert repos[0].commit_relations == [RepositoryRelation("/b", CommitRelationStatus.EQUAL, 0, 0)]
    assert repos[0].issues == ["未跟踪 1"]
    assert repos[0].statuses == ["untracked"]


def test_only_duplicate_groups_read_history() -> None:
    repos = [_repo("/a", "a" * 40), _repo("/worktree", "b" * 40)]
    repos[1].common_dir = repos[0].common_dir
    repos.append(Repository("/local", common_dir="/local/.git"))
    with mock.patch("plum_tools._gitrepo.history._git") as git:
        compare_duplicate_heads(repos)
    git.assert_not_called()
    assert all(not repo.commit_relations for repo in repos)


def test_history_cache_retries_failed_copy_and_reuses_complete_copy() -> None:
    first, second = "a" * 40, "b" * 40
    repos = [_repo("/shallow", first), _repo("/full", first), _repo("/same", first), _repo("/new", second)]
    with mock.patch(
        "plum_tools._gitrepo.history._read_history",
        side_effect=[(set(), "浅克隆历史不完整"), ({first}, ""), ({first, second}, "")],
    ) as read:
        compare_duplicate_heads(repos)
    read.assert_has_calls([mock.call(repos[0]), mock.call(repos[1]), mock.call(repos[3])])
    assert read.call_count == 3
    assert [relation.status for relation in repos[0].commit_relations] == ["equal", "equal", "behind"]
    assert repos[0].commit_relations[-1].reason == ""
    assert {relation.path for relation in repos[3].commit_relations} == {"/shallow", "/full", "/same"}


@pytest.mark.parametrize("failure", ["shallow", "empty", "missing", "command"])
def test_read_history_preserves_unknown_reason(failure: str) -> None:
    repo = _repo("/a", "a" * 40)
    outputs = {"shallow": ["true"], "empty": ["false", ""], "missing": ["false", "b" * 40]}
    effect = GitScanError("读取失败") if failure == "command" else outputs[failure]
    with mock.patch("plum_tools._gitrepo.history._git", side_effect=effect) as git:
        history, reason = _read_history(repo)
    assert history == set()
    assert (
        reason
        == {
            "shallow": "浅克隆历史不完整",
            "empty": "提交历史不完整",
            "missing": "提交历史不完整",
            "command": "读取失败",
        }[failure]
    )
    calls = [mock.call("/a", "rev-parse", "--is-shallow-repository", local_history=True)]
    if failure in ("empty", "missing"):
        calls.append(mock.call("/a", "rev-list", repo.commit, "--", local_history=True))
    git.assert_has_calls(calls)
    assert git.call_count == len(calls)


@pytest.mark.parametrize("commit", ["", "-invalid", "a" * 39])
def test_read_head_rejects_unavailable_or_invalid_commit(commit: str) -> None:
    repo = _repo("/a", commit)
    with mock.patch("plum_tools._gitrepo.history._git", return_value="") as git:
        assert _read_head(repo) == ("无法读取 HEAD 提交" if not commit else "HEAD 提交 ID 无效")
    if commit:
        git.assert_not_called()
    else:
        git.assert_called_once_with(
            "/a", "rev-parse", "--verify", "--quiet", "HEAD^{commit}", allowed_codes=(0, 1), local_history=True
        )


def test_history_command_disables_network_and_replacements() -> None:
    with (
        mock.patch("plum_tools._gitrepo.repository.shutil.which", return_value="/usr/bin/git"),
        mock.patch(
            "plum_tools._gitrepo.repository.run_process", return_value=subprocess.CompletedProcess([], 0, "false")
        ) as run,
    ):
        assert _git("/repo", "rev-parse", "--is-shallow-repository", local_history=True) == "false"
    env = {
        **os.environ,
        "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_ALLOW_PROTOCOL": "",
        "GIT_NO_REPLACE_OBJECTS": "1",
    }
    run.assert_called_once_with(
        [
            "/usr/bin/git",
            "--no-optional-locks",
            "-c",
            "color.ui=false",
            "--no-replace-objects",
            "rev-parse",
            "--is-shallow-repository",
        ],
        cwd="/repo",
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("detail", [False, True])
def test_tied_timestamps_keep_distinct_heads_and_literal_paths(compact: bool, detail: bool) -> None:
    repos = [_repo("/a [red]", "a" * 40), _repo("/b", "b" * 40)]
    for repo in repos:
        repo.commit_time = 100
    with mock.patch(
        "plum_tools._gitrepo.history._read_history", side_effect=[({repos[0].commit}, ""), ({repos[1].commit}, "")]
    ):
        compare_duplicate_heads(repos)
    output = StringIO()
    _print_scan_results(
        Console(file=output, width=500), repos, [], "remote", ("all",), False, compact=compact, detail=detail
    )
    text = output.getvalue()
    assert text.count("提交时间并列最新") == 2
    assert "HEAD aaaaaaa" in text and "HEAD bbbbbbb" in text
    assert ("无共同历史" in text) is detail
    assert "/a [red]" in text
    assert "提交相同" not in text


@pytest.mark.parametrize("group_by", ["remote", "name"])
def test_filter_preserves_full_duplicate_context(group_by: str) -> None:
    repos = [_repo("/a", "a" * 40), _repo("/b", "b" * 40), _repo("/c", "b" * 40)]
    repos[0].statuses = ["untracked"]
    repos[0].issues = ["未跟踪 1"]
    repos[0].commit_time = 1
    repos[1].commit_time = repos[2].commit_time = 2
    with mock.patch(
        "plum_tools._gitrepo.history._read_history",
        side_effect=[({repos[0].commit}, ""), ({repos[0].commit, repos[1].commit}, "")],
    ) as history:
        compare_duplicate_heads(repos)
    history.assert_has_calls([mock.call(repos[0]), mock.call(repos[1])])
    assert history.call_count == 2
    report = _build_scan_report(repos, [], group_by, ("untracked",), None)
    rows = _scan_json_repositories(report)
    assert len(rows) == 1
    assert rows[0]["path"] == "/a"
    assert rows[0]["latest_commit_time"] is rows[0]["tied_latest_commit_time"] is False
    assert {relation["path"] for relation in rows[0]["commit_relations"]} == {"/b", "/c"}
    assert report.latest_paths == report.tied_latest_paths == {"/b", "/c"}
    assert report.summary["repository_count"] == 3
    assert report.summary["duplicate_group_count"] == 1


@pytest.mark.parametrize(
    ("timestamps", "latest", "tied"),
    [
        ((None, None), set(), set()),
        ((None, 100), {"/b"}, set()),
        ((100, 200), {"/b"}, set()),
        ((100, 100), {"/a", "/b"}, {"/a", "/b"}),
    ],
)
def test_latest_time_marks(timestamps: tuple[int | None, int | None], latest: set[str], tied: set[str]) -> None:
    repos = [_repo("/a", "a" * 40), _repo("/b", "b" * 40)]
    for repo, timestamp in zip(repos, timestamps, strict=True):
        repo.commit_time = timestamp
    report = _build_scan_report(repos, [], "remote", ("all",), None)
    assert report.latest_paths == latest
    assert report.tied_latest_paths == tied


def test_cancelling_history_uses_cli_cleanup(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repos = [_repo("/a", "a" * 40), _repo("/b", "b" * 40)]
    monkeypatch.setattr("sys.argv", ["gitrepo", "scan", "-p", "/projects", "--json"])
    with (
        mock.patch("plum_tools._gitrepo.scanner._collect_repositories", return_value=repos),
        mock.patch("plum_tools._gitrepo.history._read_history", side_effect=KeyboardInterrupt) as history,
        pytest.raises(SystemExit) as exit_info,
    ):
        main()
    history.assert_called_once_with(repos[0])
    assert exit_info.value.code == 130
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "已取消"


@pytest.mark.parametrize(
    ("status", "local", "other", "label"),
    [
        (CommitRelationStatus.EQUAL, 0, 0, "提交相同"),
        (CommitRelationStatus.AHEAD, 3, 0, "领先目录 '/target' 3 个提交"),
        (CommitRelationStatus.BEHIND, 0, 2, "落后目录 '/target' 2 个提交"),
        (CommitRelationStatus.DIVERGED, 2, 3, "已分叉，各自独有 2 / 3 个提交"),
        (CommitRelationStatus.UNRELATED, 1, 1, "无共同历史"),
        (CommitRelationStatus.UNKNOWN, None, None, "关系未知（读取失败）"),
    ],
)
def test_relation_labels(status: CommitRelationStatus, local: int | None, other: int | None, label: str) -> None:
    relation = RepositoryRelation(
        "/target", status, local, other, "读取失败" if status == CommitRelationStatus.UNKNOWN else ""
    )
    assert label in relation.label()

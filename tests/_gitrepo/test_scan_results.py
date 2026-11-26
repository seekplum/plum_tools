"""验证 scan_results 的相关行为。"""

import errno
import json
import subprocess
from io import StringIO
from pathlib import Path
from threading import Lock
from unittest import mock

import pytest
from rich.console import Console

from plum_tools._gitrepo.models import DirectoryScanError, GitScanError, Repository
from plum_tools._gitrepo.reporting import _print_scan_results
from plum_tools._gitrepo.repository import _git, _scan_repository
from plum_tools._gitrepo.scanner import iter_repositories, scan_projects


def test_discover_repository_paths() -> None:
    """迁移目录发现检查，统一识别普通仓库与链接工作树。"""
    directories = [(f"/tmp/{i}", [".git"] if i in (1, 2, 4) else [], [".git"] if i == 5 else []) for i in range(1, 6)]
    with mock.patch("plum_tools._gitrepo.scanner.os.walk", return_value=directories) as walk:
        assert list(iter_repositories(["/tmp"], [])) == ["/tmp/1", "/tmp/2", "/tmp/4", "/tmp/5"]
    walk.assert_called_once_with(Path("/tmp").resolve(), onerror=mock.ANY)


def test_scan_repository_with_changes_and_stash() -> None:
    """迁移修改与 stash 同时存在、仅 stash 及正常仓库的检查场景。"""
    for modified, stash in ((True, True), (False, True), (False, False)):
        repo = Repository("/tmp", common_dir="/tmp/.git")
        output = "# branch.head main\0" + ("? test1\0" if modified else "") + ("# stash 1\0" if stash else "")
        with (
            mock.patch("plum_tools._gitrepo.repository._identify_repository", return_value=repo),
            mock.patch(
                "plum_tools._gitrepo.repository._read_shared_refs",
                return_value=(
                    "main\0refs/remotes/origin/main\0origin/main\0\0origin",
                    ["stash@{0}: test2"] if stash else [],
                    [],
                ),
            ) as refs,
            mock.patch("plum_tools._gitrepo.repository._git", return_value=output),
        ):
            result = _scan_repository("/tmp", False, {}, Lock(), detail=True)
        assert bool(result.issues) is (modified or stash)
        assert result.changes == ([{"status": "??", "path": "test1"}] if modified else [])
        assert result.stashes == (["stash@{0}: test2"] if stash else [])
        refs.assert_called_once_with(repo, False, stash_details=True)


def test_scan_issues_details(capsys: pytest.CaptureFixture[str]) -> None:
    """迁移异常过滤与详情场景，重复克隆和 worktree 本身不算异常。"""
    repos = [
        Repository("/tmp/1", issues=["未跟踪 1"], changes=[{"status": "??", "path": "test1"}]),
        Repository("/tmp/2", issues=["未暂存 1"]),
        Repository("/tmp/4", issues=["已储藏 1"], stashes=["stash@{0}: test5"]),
        Repository("/tmp/5", common_dir="/one/.git", remote_url="github.com/team/repo"),
        Repository("/tmp/6", common_dir="/two/.git", remote_url="github.com/team/repo", worktree=True),
    ]
    with mock.patch("plum_tools._gitrepo.scanner._collect_repositories", return_value=repos) as collect:
        scan_projects(["/tmp"], statuses=("issues",), detail=True)
    assert collect.call_args.args[-1] is True
    output = capsys.readouterr().out
    for path in ("/tmp/1", "/tmp/2", "/tmp/4"):
        assert path in output
    for path in ("/tmp/5", "/tmp/6"):
        assert path not in output
    assert "test1" in output
    assert "test5" in output


def test_scan_issues_summary(capsys: pytest.CaptureFixture[str]) -> None:
    """迁移默认摘要展示，不收集额外 stash 详情。"""
    repos = [
        Repository("/tmp/1", issues=["未跟踪 1"], changes=[{"status": "??", "path": "test1"}]),
        Repository("/tmp/4", issues=["已储藏 1"], stashes=["stash@{0}: test5"]),
        Repository("/tmp/5"),
    ]
    with mock.patch("plum_tools._gitrepo.scanner._collect_repositories", return_value=repos) as collect:
        scan_projects(["/tmp"], statuses=("issues",))
    assert collect.call_args.args[-1] is False
    output = capsys.readouterr().out
    assert "/tmp/1" in output and "/tmp/4" in output
    assert "/tmp/5" not in output
    assert "test1" not in output and "test5" not in output


@pytest.mark.parametrize("modified", [False, True])
def test_scan_repository_ignores_stash_details(modified: bool) -> None:
    """迁移忽略 stash 场景，详情模式下也不查询 stash。"""
    repo = Repository("/tmp/project", common_dir="/tmp/project/.git")
    output = "# branch.head main\0" + ("? 工作区修改\0" if modified else "")
    with (
        mock.patch("plum_tools._gitrepo.repository._identify_repository", return_value=repo),
        mock.patch(
            "plum_tools._gitrepo.repository._read_shared_refs",
            return_value=("main\0refs/remotes/origin/main\0origin/main\0\0origin", [], []),
        ) as refs,
        mock.patch("plum_tools._gitrepo.repository._git", return_value=output) as git,
    ):
        result = _scan_repository(repo.path, False, {}, Lock(), stash=False, detail=True)
    assert bool(result.issues) is modified
    assert not result.stashes
    refs.assert_called_once_with(repo, False, stash_details=False)
    assert "--show-stash" not in git.call_args.args


@pytest.mark.parametrize("detail", [False, True])
@pytest.mark.parametrize("stash", [False, True])
def test_scan_json_includes_all_results_and_details(
    detail: bool, stash: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = ["/projects/failed", '/projects/修改[red]"目录', "/projects/clean"]
    changes = [{"status": ".M", "path": '未提交 "文件"\n第二行\\路径'}]
    results = [
        Repository(paths[0], errors=["超时"]),
        Repository(paths[1], issues=["未暂存 1"], changes=changes),
        Repository(paths[2]),
    ]
    with mock.patch("plum_tools._gitrepo.scanner._collect_repositories", return_value=results) as collect:
        scan_projects(["/projects"], stash=stash, exclude=(".venv",), detail=detail, json_output=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 2
    assert payload["command"] == "scan"
    assert payload["options"]["stash_checked"] is stash
    assert payload["summary"]["repository_count"] == 3
    assert payload["summary"]["issue_repository_count"] == 2
    assert payload["summary"]["failed_repository_count"] == 1
    rows = {row["path"]: row for row in payload["repositories"]}
    assert rows[paths[1]]["changes"] == changes
    assert rows[paths[0]]["errors"] == ["超时"]
    assert rows[paths[2]]["has_issues"] is False
    assert rows[paths[2]]["changes"] == rows[paths[2]]["stashes"] == []
    assert "修改" in captured.out
    assert captured.err == ""
    assert collect.call_args.args[:4] == (["/projects"], [], False, (".venv",))
    assert collect.call_args.args[-2:] == (stash, True)


@pytest.mark.parametrize("detail", [False, True])
def test_scan_rich_table_preserves_literal_paths_and_failure_details(detail: bool) -> None:
    result = [
        Repository("/projects/clean"),
        Repository("/projects/[red]修改", issues=["未跟踪 1"], changes=[{"status": "??", "path": "[bold]工作区修改"}]),
        Repository("/projects/failed", errors=["[red]超时"]),
    ]
    output = StringIO()
    _print_scan_results(
        Console(file=output, width=240),
        result,
        [DirectoryScanError("/protected", "Permission denied")],
        "remote",
        ("issues",),
        False,
        detail=detail,
    )
    rendered = output.getvalue()
    assert "│" in rendered
    assert "目录" in rendered and "状态" in rendered
    assert "/projects/clean" not in rendered
    assert "/projects/[red]修改" in rendered
    assert "检查失败：[red]超时" in rendered
    assert ("[bold]工作区修改" in rendered) is detail
    assert "异常仓库目录 2 个" in rendered
    assert "检查失败 1 个" in rendered
    assert "目录扫描错误" in rendered
    assert "Permission denied" in rendered


def test_scan_repository_keeps_command_errors() -> None:
    """迁移 Git 命令失败场景，错误不阻断扫描。"""
    repo = Repository("/repo", common_dir="/repo/.git")
    with (
        mock.patch("plum_tools._gitrepo.repository._identify_repository", return_value=repo),
        mock.patch("plum_tools._gitrepo.repository._read_shared_refs", return_value=(None, [], ["引用失败"])),
        mock.patch("plum_tools._gitrepo.repository._git", side_effect=GitScanError("git status 失败")),
    ):
        result = _scan_repository("/repo", False, {}, Lock(), detail=True)
    assert result.errors == ["引用失败", "git status 失败"]


def test_scan_command_catches_timeout() -> None:
    """迁移命令超时场景，统一转换为可展示的扫描错误。"""
    with (
        mock.patch("plum_tools._gitrepo.repository.shutil.which", return_value="/usr/bin/git"),
        mock.patch(
            "plum_tools._gitrepo.repository.run_process", side_effect=subprocess.TimeoutExpired("git status", 30)
        ),
        pytest.raises(GitScanError, match="超时"),
    ):
        _git("/repo", "status")


def test_scan_command_catches_oserror() -> None:
    """迁移系统错误场景，保留原始失败原因。"""
    with (
        mock.patch("plum_tools._gitrepo.repository.shutil.which", return_value="/usr/bin/git"),
        mock.patch("plum_tools._gitrepo.repository.run_process", side_effect=OSError(errno.ENOENT, "文件未找到")),
        pytest.raises(GitScanError, match="文件未找到"),
    ):
        _git("/repo", "status")


def test_scan_compact_details(capsys: pytest.CaptureFixture[str]) -> None:
    """迁移紧凑模式下的文件与 stash 详情展示。"""
    result = [
        Repository(
            "/repo",
            issues=["未跟踪 1"],
            changes=[{"status": "??", "path": "工作区有修改"}],
            stashes=["stash@{0}: 暂存"],
        )
    ]
    _print_scan_results(Console(), result, [], "remote", ("issues",), False, detail=True, compact=True)
    rendered = capsys.readouterr().out
    assert "/repo" in rendered
    assert "工作区有修改" in rendered
    assert "stash@{0}" in rendered


def test_scan_compact_details_escape_empty_lines() -> None:
    """迁移紧凑详情展示，文件名中的空行仍须保留可辨识形式。"""
    output = StringIO()
    result = [Repository("/repo", issues=["未跟踪 1"], changes=[{"status": "??", "path": "工作区修改\n\n未暂存变更"}])]
    _print_scan_results(
        Console(file=output, width=200), result, [], "remote", ("issues",), False, detail=True, compact=True
    )
    rendered = output.getvalue()
    assert "工作区修改" in rendered and "未暂存变更" in rendered
    assert r"\n\n" in rendered
    assert "\n\n\n" not in rendered

"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_gitrepo
#         Desc: 测试gitrepo模块
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 23:43
#=============================================================================
"""

import errno
import json
import os
import subprocess
import sys
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from threading import Lock
from unittest import mock

import pytest
from rich.console import Console

from plum_tools.git_scan import (
    DirectoryScanError,
    GitScanError,
    Repository,
    _git,
    _print_scan_results,
    _scan_repository,
    iter_repositories,
    scan_projects,
)
from plum_tools.gitrepo import main


def test_discover_repository_paths() -> None:
    """迁移目录发现检查，统一识别普通仓库与链接工作树。"""
    directories = [(f"/tmp/{i}", [".git"] if i in (1, 2, 4) else [], [".git"] if i == 5 else []) for i in range(1, 6)]
    with mock.patch("plum_tools.git_scan.os.walk", return_value=directories) as walk:
        assert list(iter_repositories(["/tmp"], [])) == ["/tmp/1", "/tmp/2", "/tmp/4", "/tmp/5"]
    walk.assert_called_once_with(Path("/tmp").resolve(), onerror=mock.ANY)


def test_scan_repository_with_changes_and_stash() -> None:
    """迁移修改与 stash 同时存在、仅 stash 及正常仓库的检查场景。"""
    for modified, stash in ((True, True), (False, True), (False, False)):
        repo = Repository("/tmp", common_dir="/tmp/.git")
        output = "# branch.head main\0" + ("? test1\0" if modified else "") + ("# stash 1\0" if stash else "")
        with (
            mock.patch("plum_tools.git_scan._identify_repository", return_value=repo),
            mock.patch(
                "plum_tools.git_scan._read_shared_refs",
                return_value=(
                    "main\0refs/remotes/origin/main\0origin/main\0\0origin",
                    ["stash@{0}: test2"] if stash else [],
                    [],
                ),
            ) as refs,
            mock.patch("plum_tools.git_scan._git", return_value=output),
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
        Repository("/tmp/4", issues=["stash 1"], stashes=["stash@{0}: test5"]),
        Repository("/tmp/5", common_dir="/one/.git", remote_url="github.com/team/repo"),
        Repository("/tmp/6", common_dir="/two/.git", remote_url="github.com/team/repo", worktree=True),
    ]
    with mock.patch("plum_tools.git_scan._collect_repositories", return_value=repos) as collect:
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
        Repository("/tmp/4", issues=["stash 1"], stashes=["stash@{0}: test5"]),
        Repository("/tmp/5"),
    ]
    with mock.patch("plum_tools.git_scan._collect_repositories", return_value=repos) as collect:
        scan_projects(["/tmp"], statuses=("issues",))
    assert collect.call_args.args[-1] is False
    output = capsys.readouterr().out
    assert "/tmp/1" in output and "/tmp/4" in output
    assert "/tmp/5" not in output
    assert "test1" not in output and "test5" not in output


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["-p", "/tmp/project"],
        ["-p", "/tmp/project", "check"],
        ["--json", "check"],
        ["--ignore-stash", "scan"],
        ["-d", "check"],
        ["check"],
        ["check", "--stash"],
        ["scan", "-s"],
        ["scan", "--stash"],
    ],
)
def test_main(options: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", *options]),
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "用法：" in captured.err
    assert captured.out == ""
    scan.assert_not_called()


@pytest.mark.parametrize("modified", [False, True])
def test_scan_repository_ignores_stash_details(modified: bool) -> None:
    """迁移忽略 stash 场景，详情模式下也不查询 stash。"""
    repo = Repository("/tmp/project", common_dir="/tmp/project/.git")
    output = "# branch.head main\0" + ("? 工作区修改\0" if modified else "")
    with (
        mock.patch("plum_tools.git_scan._identify_repository", return_value=repo),
        mock.patch(
            "plum_tools.git_scan._read_shared_refs",
            return_value=("main\0refs/remotes/origin/main\0origin/main\0\0origin", [], []),
        ) as refs,
        mock.patch("plum_tools.git_scan._git", return_value=output) as git,
    ):
        result = _scan_repository(repo.path, False, {}, Lock(), stash=False, detail=True)
    assert bool(result.issues) is modified
    assert not result.stashes
    refs.assert_called_once_with(repo, False, stash_details=False)
    assert "--show-stash" not in git.call_args.args


@pytest.mark.parametrize(
    ("options", "stash", "exclude"),
    [
        ([], True, ()),
        (["--ignore-stash"], False, ()),
        (["--exclude", ".venv"], True, (".venv",)),
        (["--ignore-stash", "--exclude", ".venv"], False, (".venv",)),
    ],
)
def test_main_scan_issues_stash_options(options: list[str], stash: bool, exclude: tuple[str, ...]) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", "scan", "--status", "issues", "-d", *options, "-p", "/tmp/project"]),
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
    ):
        main()
    scan.assert_called_once_with(
        ["/tmp/project"],
        "remote",
        ("issues",),
        False,
        exclude,
        stash=stash,
        host_filter=None,
        json_output=False,
        detail=True,
    )


@pytest.mark.parametrize("options", [["scan", "--status", "issues"], ["scan", "--host", "github.com"]])
def test_main_groups_directory_errors(options: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def walk_with_errors(path: Path, *, onerror: Callable[[OSError], None]) -> list:
        onerror(PermissionError(errno.EACCES, "Permission denied", str(path / "one")))
        onerror(PermissionError(errno.EACCES, "Permission denied", str(path / "two")))
        onerror(PermissionError(errno.EPERM, "Operation not permitted", str(path / "three")))
        return []

    with (
        mock.patch("sys.argv", ["gitrepo", *options, "-p", str(tmp_path)]),
        mock.patch("plum_tools.git_scan.os.walk", side_effect=walk_with_errors),
        mock.patch.dict(os.environ, {"COLUMNS": "240"}),
    ):
        main()
    rendered = capsys.readouterr().out
    assert rendered.count("目录扫描错误") == 1
    assert rendered.count("Permission denied") == 1
    assert rendered.count("Operation not permitted") == 1
    assert "2 种原因 · 3 个目录" in rendered
    for name in ("one", "two", "three"):
        assert str(tmp_path / name) in rendered
    assert "扫描错误 3 个" in rendered


@pytest.mark.parametrize("options", [["scan", "--status", "issues"], ["scan"]])
def test_main_hides_directory_error_table_without_errors(
    options: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", *options, "-p", str(tmp_path)]),
        mock.patch("plum_tools.git_scan.os.walk", return_value=[]),
    ):
        main()
    rendered = capsys.readouterr().out
    assert "目录扫描错误" not in rendered
    assert "扫描错误 0 个" in rendered


@pytest.mark.parametrize("options", [[], ["--ignore-stash"], ["--ignore-stash", "--group-by", "name"]])
def test_main_scan_stash_options(options: list[str]) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", "scan", "-p", "/tmp/project", *options]),
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
    ):
        main()
    scan.assert_called_once_with(
        ["/tmp/project"],
        "name" if "name" in options else "remote",
        ("all",),
        False,
        (),
        stash="--ignore-stash" not in options,
        host_filter=None,
        json_output=False,
        detail=False,
    )


@pytest.mark.parametrize(
    ("option", "pattern"),
    [("--host", "*.xxx.net|github.com"), ("--host-regex", r".*\.xxx\.net|github\.com")],
)
def test_main_scan_host_options(option: str, pattern: str) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", "scan", "--ignore-stash", option, pattern, "-p", "/tmp/project"]),
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
    ):
        main()
    assert scan.call_count == 1
    assert scan.call_args.args == (["/tmp/project"], "remote", ("all",), False, ())
    assert scan.call_args.kwargs["stash"] is False
    assert scan.call_args.kwargs["json_output"] is False
    pattern_filter = scan.call_args.kwargs["host_filter"]
    assert pattern_filter.fullmatch("git.xxx.net")
    assert pattern_filter.fullmatch("github.com")
    assert pattern_filter.fullmatch("github.com.invalid") is None


@pytest.mark.parametrize("options", [["--host-regex", "["], ["--host", "*", "--host-regex", ".*"]])
def test_main_rejects_invalid_host_options(options: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", "scan", *options]),
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 2
    assert "--host-regex" in capsys.readouterr().err
    scan.assert_not_called()


@pytest.mark.parametrize(
    ("options", "command", "stash"),
    [
        (["scan", "--json", "--status", "issues"], "scan", True),
        (["scan", "--json", "-d"], "scan", True),
        (["scan", "--json", "--ignore-stash", "--status", "issues"], "scan", False),
        (["scan", "--json"], "scan", True),
        (["scan", "--json", "--ignore-stash"], "scan", False),
    ],
)
def test_main_json_empty_results_and_progress_stream(
    options: list[str], command: str, stash: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", *options, "-p", str(tmp_path)]),
        mock.patch("plum_tools.git_scan.os.walk", return_value=[]) as walk,
        mock.patch.object(sys.stderr, "isatty", return_value=True),
        mock.patch.dict(os.environ, {"TERM": "xterm", "COLUMNS": "160"}),
    ):
        main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 2
    assert payload["command"] == command
    assert payload["options"]["stash_checked"] is stash
    assert payload["repositories"] == []
    assert payload["directory_errors"] == []
    assert all(value == 0 for value in payload["summary"].values())
    assert "\x1b" not in captured.out
    assert "发现目录" in captured.err
    assert "检查仓库" in captured.err
    walk.assert_called_once_with(tmp_path.resolve(), onerror=mock.ANY)


@pytest.mark.parametrize("options", [["scan", "--status", "issues"], ["scan"]])
def test_main_json_directory_errors(options: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    denied = str(tmp_path / '配置[red]"目录\n')

    def walk_with_errors(path: Path, *, onerror: Callable[[OSError], None]) -> list:
        assert path == tmp_path.resolve()
        onerror(PermissionError(errno.EACCES, "Permission denied", denied))
        return []

    with (
        mock.patch("sys.argv", ["gitrepo", *options, "--json", "-p", str(tmp_path)]),
        mock.patch("plum_tools.git_scan.os.walk", side_effect=walk_with_errors) as walk,
    ):
        main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["repositories"] == []
    assert payload["directory_errors"] == [{"path": denied, "reason": "Permission denied"}]
    assert payload["summary"]["directory_error_count"] == 1
    assert captured.err == ""
    walk.assert_called_once_with(tmp_path.resolve(), onerror=mock.ANY)


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
    with mock.patch("plum_tools.git_scan._collect_repositories", return_value=results) as collect:
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
        mock.patch("plum_tools.git_scan._identify_repository", return_value=repo),
        mock.patch("plum_tools.git_scan._read_shared_refs", return_value=(None, [], ["引用失败"])),
        mock.patch("plum_tools.git_scan._git", side_effect=GitScanError("git status 失败")),
    ):
        result = _scan_repository("/repo", False, {}, Lock(), detail=True)
    assert result.errors == ["引用失败", "git status 失败"]


def test_scan_command_catches_timeout() -> None:
    """迁移命令超时场景，统一转换为可展示的扫描错误。"""
    with (
        mock.patch("plum_tools.git_scan.shutil.which", return_value="/usr/bin/git"),
        mock.patch("plum_tools.git_scan.run_process", side_effect=subprocess.TimeoutExpired("git status", 30)),
        pytest.raises(GitScanError, match="超时"),
    ):
        _git("/repo", "status")


def test_scan_command_catches_oserror() -> None:
    """迁移系统错误场景，保留原始失败原因。"""
    with (
        mock.patch("plum_tools.git_scan.shutil.which", return_value="/usr/bin/git"),
        mock.patch("plum_tools.git_scan.run_process", side_effect=OSError(errno.ENOENT, "文件未找到")),
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

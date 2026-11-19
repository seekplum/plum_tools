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
import sys
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from rich.console import Console

from plum_tools.git_scan import DirectoryScanError
from plum_tools.gitrepo import _print_check_results, check_project, check_projects, find_git_project_for_python, main
from tests.common import MockPool


# @mock.patch("builtins.os")
@mock.patch(
    "plum_tools.gitrepo.check_is_git_repository",
    side_effect=[True, True, False, True, True],
)
def test_find_git_project_for_python(mock_check: mock.MagicMock) -> None:
    mock_os_result: list[tuple[str, list[str], list[str]]] = [(f"/tmp/{i + 1}", [], []) for i in range(5)]

    with mock.patch("plum_tools.git_scan.os.walk") as mock_walk:
        mock_walk.return_value = mock_os_result
        result = list(find_git_project_for_python("/tmp"))
        assert result == ["/tmp/1", "/tmp/2", "/tmp/4", "/tmp/5"]
    mock_walk.assert_called_once_with(Path("/tmp").resolve(), onerror=mock.ANY)
    mock_check.assert_has_calls(
        [
            mock.call("/tmp/1"),
            mock.call("/tmp/2"),
            mock.call("/tmp/3"),
            mock.call("/tmp/4"),
            mock.call("/tmp/5"),
        ]
    )


def test_check_project_with_modify() -> None:
    with (
        mock.patch("plum_tools.gitrepo.check_repository_modify_status", return_value=(True, "test1")) as mock_modify,
        mock.patch("plum_tools.gitrepo.check_repository_stash", return_value=(True, "test2")) as mock_stash,
    ):
        result = check_project("/tmp")
        assert result == {
            "path": "/tmp",
            "status": True,
            "output": "test1\ntest2",
        }
        mock_modify.assert_called_once_with("/tmp")
        mock_stash.assert_called_once_with("/tmp")
    with (
        mock.patch(
            "plum_tools.gitrepo.check_repository_modify_status",
            return_value=(False, "test1"),
        ) as mock_modify,
        mock.patch("plum_tools.gitrepo.check_repository_stash", return_value=(True, "test2")) as mock_stash,
    ):
        result = check_project("/tmp")
        assert result == {
            "path": "/tmp",
            "status": True,
            "output": "test2",
        }
        mock_modify.assert_called_once_with("/tmp")
        mock_stash.assert_called_once_with("/tmp")
    with (
        mock.patch(
            "plum_tools.gitrepo.check_repository_modify_status",
            return_value=(False, "test1"),
        ) as mock_modify,
        mock.patch("plum_tools.gitrepo.check_repository_stash", return_value=(False, "test2")) as mock_stash,
    ):
        result = check_project("/tmp")
        assert result == {
            "path": "/tmp",
            "status": False,
        }
        mock_modify.assert_called_once_with("/tmp")
        mock_stash.assert_called_once_with("/tmp")


@mock.patch(
    "plum_tools.gitrepo.check_is_git_repository",
    side_effect=[True, True, False, True, True],
)
def test_check_projects(mock_check: mock.MagicMock, capsys: pytest.CaptureFixture) -> None:
    mock_os_result: list[tuple[str, list[str], list[str]]] = [(f"/tmp/{i + 1}", [], []) for i in range(5)]

    with (
        mock.patch("plum_tools.gitrepo.Pool", return_value=MockPool()) as mock_pool,
        mock.patch("plum_tools.git_scan.os.walk") as mock_walk,
        mock.patch(
            "plum_tools.gitrepo.check_repository_modify_status",
            side_effect=[
                (True, "test1"),
                (True, "test2"),
                (False, "test3"),
                (False, "test4"),
            ],
        ) as mock_modify,
        mock.patch(
            "plum_tools.gitrepo.check_repository_stash",
            side_effect=[(False, ""), (False, ""), (True, "test5"), (False, "test6")],
        ) as mock_stash,
    ):
        mock_walk.return_value = mock_os_result
        check_projects(["/tmp"], True)
    mock_pool.assert_called_once_with(processes=min(4, os.cpu_count() or 2))
    mock_walk.assert_called_once_with(Path("/tmp").resolve(), onerror=mock.ANY)
    mock_check.assert_has_calls(
        [
            mock.call("/tmp/1"),
            mock.call("/tmp/2"),
            mock.call("/tmp/3"),
            mock.call("/tmp/4"),
            mock.call("/tmp/5"),
        ]
    )
    mock_modify.assert_has_calls(
        [
            mock.call("/tmp/1"),
            mock.call("/tmp/2"),
            mock.call("/tmp/4"),
            mock.call("/tmp/5"),
        ]
    )
    mock_stash.assert_has_calls([mock.call(f"/tmp/{index}") for index in (1, 2, 4, 5)], any_order=True)
    assert mock_stash.call_count == 4

    captured = capsys.readouterr()
    assert "/tmp/1" in captured.out
    assert "/tmp/2" in captured.out
    assert "/tmp/3" not in captured.out
    assert "/tmp/4" in captured.out
    assert "/tmp/5" not in captured.out
    assert "test5" in captured.out


@mock.patch(
    "plum_tools.gitrepo.check_is_git_repository",
    side_effect=[True, True, False, True, True],
)
def test_check_projects_with_not_detail(mock_check: mock.MagicMock, capsys: pytest.CaptureFixture) -> None:
    mock_os_result: list[tuple[str, list[str], list[str]]] = [(f"/tmp/{i + 1}", [], []) for i in range(5)]

    with (
        mock.patch("plum_tools.gitrepo.Pool", return_value=MockPool()) as mock_pool,
        mock.patch("plum_tools.git_scan.os.walk") as mock_walk,
        mock.patch(
            "plum_tools.gitrepo.check_repository_modify_status",
            side_effect=[
                (True, "test1"),
                (True, "test2"),
                (False, "test3"),
                (False, "test4"),
            ],
        ) as mock_modify,
        mock.patch(
            "plum_tools.gitrepo.check_repository_stash",
            side_effect=[(False, ""), (False, ""), (True, "test5"), (False, "test6")],
        ) as mock_stash,
    ):
        mock_walk.return_value = mock_os_result
        check_projects(["/tmp"], False)
    mock_pool.assert_called_once_with(processes=min(4, os.cpu_count() or 2))
    mock_walk.assert_called_once_with(Path("/tmp").resolve(), onerror=mock.ANY)
    mock_check.assert_has_calls(
        [
            mock.call("/tmp/1"),
            mock.call("/tmp/2"),
            mock.call("/tmp/3"),
            mock.call("/tmp/4"),
            mock.call("/tmp/5"),
        ]
    )
    mock_modify.assert_has_calls(
        [
            mock.call("/tmp/1"),
            mock.call("/tmp/2"),
            mock.call("/tmp/4"),
            mock.call("/tmp/5"),
        ]
    )
    mock_stash.assert_has_calls([mock.call(f"/tmp/{index}") for index in (1, 2, 4, 5)], any_order=True)
    assert mock_stash.call_count == 4

    captured = capsys.readouterr()
    assert "/tmp/1" in captured.out
    assert "/tmp/2" in captured.out
    assert "/tmp/3" not in captured.out
    assert "/tmp/4" in captured.out
    assert "/tmp/5" not in captured.out
    assert "test5" not in captured.out


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["-p", "/tmp/project"],
        ["-p", "/tmp/project", "check"],
        ["--json", "check"],
        ["--ignore-stash", "scan"],
        ["-d", "check"],
        ["check", "-s"],
        ["check", "--stash"],
        ["scan", "-s"],
        ["scan", "--stash"],
    ],
)
def test_main(options: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", *options]),
        mock.patch("plum_tools.gitrepo.check_projects") as check,
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "用法：" in captured.err
    assert captured.out == ""
    check.assert_not_called()
    scan.assert_not_called()


@pytest.mark.parametrize("modified", [False, True])
def test_check_project_ignores_stash(modified: bool) -> None:
    with (
        mock.patch(
            "plum_tools.gitrepo.check_repository_modify_status", return_value=(modified, "工作区修改")
        ) as modify,
        mock.patch("plum_tools.gitrepo.check_repository_stash") as stash,
    ):
        result = check_project("/tmp/project", stash=False)
    assert result == (
        {"path": "/tmp/project", "status": True, "output": "工作区修改"}
        if modified
        else {"path": "/tmp/project", "status": False}
    )
    modify.assert_called_once_with("/tmp/project")
    stash.assert_not_called()


@pytest.mark.parametrize(
    ("options", "stash", "exclude"),
    [
        ([], True, ()),
        (["--ignore-stash"], False, ()),
        (["--exclude", ".venv"], True, (".venv",)),
        (["--ignore-stash", "--exclude", ".venv"], False, (".venv",)),
    ],
)
def test_main_check_stash_options(options: list[str], stash: bool, exclude: tuple[str, ...]) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", "check", *options, "-p", "/tmp/project"]),
        mock.patch("plum_tools.gitrepo.check_projects") as check,
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
    ):
        main()
    check.assert_called_once_with(["/tmp/project"], False, stash, exclude, json_output=False)
    scan.assert_not_called()


@pytest.mark.parametrize("options", [["check"], ["scan", "--host", "github.com"]])
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
    if "scan" in options:
        assert "扫描错误 3 个" in rendered


@pytest.mark.parametrize("options", [["check"], ["scan"]])
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
    if "scan" in options:
        assert "扫描错误 0 个" in rendered
    else:
        assert rendered == ""


@pytest.mark.parametrize("options", [[], ["--ignore-stash"], ["--ignore-stash", "--group-by", "name"]])
def test_main_scan_stash_options(options: list[str]) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", "scan", "-p", "/tmp/project", *options]),
        mock.patch("plum_tools.gitrepo.check_projects") as check,
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
    ):
        main()
    scan.assert_called_once_with(
        ["/tmp/project"],
        "name" if "name" in options else "remote",
        False,
        False,
        (),
        stash="--ignore-stash" not in options,
        host_filter=None,
        json_output=False,
    )
    check.assert_not_called()


@pytest.mark.parametrize(
    ("option", "pattern"),
    [("--host", "*.meideng.net|github.com"), ("--host-regex", r".*\.meideng\.net|github\.com")],
)
def test_main_scan_host_options(option: str, pattern: str) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", "scan", "--ignore-stash", option, pattern, "-p", "/tmp/project"]),
        mock.patch("plum_tools.gitrepo.scan_projects") as scan,
    ):
        main()
    assert scan.call_count == 1
    assert scan.call_args.args == (["/tmp/project"], "remote", False, False, ())
    assert scan.call_args.kwargs["stash"] is False
    assert scan.call_args.kwargs["json_output"] is False
    pattern_filter = scan.call_args.kwargs["host_filter"]
    assert pattern_filter.fullmatch("git.meideng.net")
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
        (["check", "--json"], "check", True),
        (["check", "--json", "-d"], "check", True),
        (["check", "--json", "--ignore-stash"], "check", False),
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
    assert payload["schema_version"] == 1
    assert payload["command"] == command
    assert payload["options"]["stash_checked"] is stash
    assert payload["repositories"] == []
    assert payload["directory_errors"] == []
    assert all(value == 0 for value in payload["summary"].values())
    assert "\x1b" not in captured.out
    assert "发现目录" in captured.err
    assert "检查仓库" in captured.err
    walk.assert_called_once_with(tmp_path.resolve(), onerror=mock.ANY)


@pytest.mark.parametrize("command", ["check", "scan"])
def test_main_json_directory_errors(command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    denied = str(tmp_path / '配置[red]"目录\n')

    def walk_with_errors(path: Path, *, onerror: Callable[[OSError], None]) -> list:
        assert path == tmp_path.resolve()
        onerror(PermissionError(errno.EACCES, "Permission denied", denied))
        return []

    with (
        mock.patch("sys.argv", ["gitrepo", command, "--json", "-p", str(tmp_path)]),
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
def test_check_json_includes_all_results(detail: bool, stash: bool, capsys: pytest.CaptureFixture[str]) -> None:
    paths = ["/projects/failed", '/projects/修改[red]"目录', "/projects/clean"]
    output = '未提交 "文件"\n第二行\\路径'
    results = [
        {"path": paths[0], "status": True, "error": True, "output": "检查失败：超时"},
        {"path": paths[1], "status": True, "output": output},
        {"path": paths[2], "status": False},
    ]
    with (
        mock.patch("plum_tools.gitrepo.walk_directories", return_value=[(path, [], []) for path in paths]) as walk,
        mock.patch("plum_tools.gitrepo.check_is_git_repository", return_value=True) as identify,
        mock.patch("plum_tools.gitrepo.Pool", return_value=MockPool()) as pool,
        mock.patch("plum_tools.gitrepo.check_project", side_effect=results) as check,
    ):
        check_projects(["/projects"], detail, stash, (".venv",), json_output=True)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {
        "schema_version": 1,
        "command": "check",
        "options": {"stash_checked": stash},
        "summary": {
            "repository_count": 3,
            "shown_repository_count": 3,
            "issue_repository_count": 2,
            "failed_repository_count": 1,
            "directory_error_count": 0,
        },
        "repositories": [
            {"path": paths[2], "has_issues": False, "failed": False, "output": ""},
            {"path": paths[0], "has_issues": True, "failed": True, "output": "检查失败：超时"},
            {"path": paths[1], "has_issues": True, "failed": False, "output": output},
        ],
        "directory_errors": [],
    }
    assert "修改" in captured.out
    assert captured.err == ""
    walk.assert_called_once_with(["/projects"], [], (".venv",))
    assert identify.call_args_list == [mock.call(path) for path in paths]
    pool.assert_called_once_with(processes=min(3, os.cpu_count() or 2))
    assert check.call_args_list == [mock.call(path, stash=stash) for path in paths]


@pytest.mark.parametrize("detail", [False, True])
def test_check_rich_table_preserves_literal_paths_and_failure_details(detail: bool) -> None:
    result = [
        {"path": "/projects/clean", "status": False},
        {"path": "/projects/[red]修改", "status": True, "output": "[bold]工作区修改"},
        {"path": "/projects/failed", "status": True, "error": True, "output": "检查失败：[red]超时"},
    ]
    output = StringIO()
    _print_check_results(
        Console(file=output, width=200), result, [DirectoryScanError("/protected", "Permission denied")], detail
    )
    rendered = output.getvalue()
    assert "仓库检查结果" in rendered
    assert "│" in rendered
    assert "目录" in rendered
    assert "状态" in rendered
    assert "详细信息" in rendered
    assert "/projects/clean" not in rendered
    assert "/projects/[red]修改" in rendered
    assert "检查失败：[red]超时" in rendered
    assert ("[bold]工作区修改" in rendered) is detail
    assert "检查 3 个仓库 · 异常 2 个 · 检查失败 1 个" in rendered
    assert "目录扫描错误" in rendered
    assert "Permission denied" in rendered

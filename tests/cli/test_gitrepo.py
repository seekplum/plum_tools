"""验证 gitrepo 的相关行为。"""

import errno
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import pytest

from plum_tools.cli.gitrepo import main


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
        mock.patch("plum_tools.cli.gitrepo.scan_projects") as scan,
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "用法：" in captured.err
    assert captured.out == ""
    scan.assert_not_called()


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
        mock.patch("plum_tools.cli.gitrepo.scan_projects") as scan,
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
        mock.patch("plum_tools._gitrepo.scanner.os.walk", side_effect=walk_with_errors),
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
        mock.patch("plum_tools._gitrepo.scanner.os.walk", return_value=[]),
    ):
        main()
    rendered = capsys.readouterr().out
    assert "目录扫描错误" not in rendered
    assert "扫描错误 0 个" in rendered


@pytest.mark.parametrize("options", [[], ["--ignore-stash"], ["--ignore-stash", "--group-by", "name"]])
def test_main_scan_stash_options(options: list[str]) -> None:
    with (
        mock.patch("sys.argv", ["gitrepo", "scan", "-p", "/tmp/project", *options]),
        mock.patch("plum_tools.cli.gitrepo.scan_projects") as scan,
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
        mock.patch("plum_tools.cli.gitrepo.scan_projects") as scan,
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
        mock.patch("plum_tools.cli.gitrepo.scan_projects") as scan,
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
        mock.patch("plum_tools._gitrepo.scanner.os.walk", return_value=[]) as walk,
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
        mock.patch("plum_tools._gitrepo.scanner.os.walk", side_effect=walk_with_errors) as walk,
    ):
        main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["repositories"] == []
    assert payload["directory_errors"] == [{"path": denied, "reason": "Permission denied"}]
    assert payload["summary"]["directory_error_count"] == 1
    assert captured.err == ""
    walk.assert_called_once_with(tmp_path.resolve(), onerror=mock.ANY)

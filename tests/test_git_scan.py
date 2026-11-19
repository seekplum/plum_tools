"""验证主机展示过滤及普通、裸仓库的 stash 忽略行为。"""

import errno
import json
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from rich.console import Console

from plum_tools.git_scan import (
    DirectoryScanError,
    Repository,
    _compile_host_glob,
    _compile_host_regex,
    _print_scan_results,
    print_directory_errors,
    scan_projects,
    walk_directories,
)


@pytest.mark.parametrize("group_by", ["remote", "name"])
@pytest.mark.parametrize("regex", [False, True])
@pytest.mark.parametrize("duplicates_only", [False, True])
def test_host_filter_preserves_grouping_and_totals(group_by: str, regex: bool, duplicates_only: bool) -> None:
    repos = [
        Repository("/one/project", common_dir="/one/.git", remote_url="github.com/team/project"),
        Repository("/two/project", common_dir="/two/.git", remote_url="github.com/team/project"),
        Repository("/three/project", common_dir="/three/.git", remote_url="git.meideng.net:2222/team/project"),
        Repository("/four/hidden", common_dir="/four/.git", remote_url="gitlab.com/team/hidden"),
        Repository("/five/local", common_dir="/five/.git", remote_url="/local/project.git"),
        Repository("/six/unknown", common_dir="/six/.git"),
    ]
    host_filter = (
        _compile_host_regex(r".*\.meideng\.net|github\.com")
        if regex
        else _compile_host_glob("*.meideng.net|github.com")
    )
    output = StringIO()
    _print_scan_results(Console(file=output, width=200), repos, [], group_by, duplicates_only, False, host_filter)
    rendered = output.getvalue()
    assert "github.com" in rendered
    assert "/one/project" in rendered
    assert "/two/project" in rendered
    assert "重复克隆" in rendered
    assert ("git.meideng.net" in rendered) is (not duplicates_only)
    assert "gitlab.com" not in rendered
    assert "/local/project.git" not in rendered
    assert "无远程 / 无法识别" not in rendered
    assert "扫描 6 个目录，6 个独立仓库" in rendered
    assert f"展示 {1 if duplicates_only else 2}/5 个仓库组" in rendered


@pytest.mark.parametrize("pattern", ["*", "unmatched.example"])
def test_host_glob_excludes_non_hosts(pattern: str) -> None:
    repos = [
        Repository("/one/project", remote_url="github.com/team/project"),
        Repository("/two/local", remote_url="file://server/project.git"),
        Repository("/three/unknown"),
    ]
    output = StringIO()
    _print_scan_results(Console(file=output, width=200), repos, [], "remote", False, False, _compile_host_glob(pattern))
    rendered = output.getvalue()
    assert "本地路径" not in rendered
    assert "无远程 / 无法识别" not in rendered
    assert ("github.com" in rendered) is (pattern == "*")
    assert f"展示 {1 if pattern == '*' else 0}/3 个仓库组" in rendered


@pytest.mark.parametrize(
    ("pattern", "matching", "excluded"),
    [
        ("*.meideng.net|github.com", "git.meideng.net", "github.com.invalid"),
        ("GITHUB.COM", "github.com", "mygithub.com"),
        ("git?.meideng.net", "git1.meideng.net", "git12.meideng.net"),
        ("git[12].meideng.net", "git2.meideng.net", "git3.meideng.net"),
    ],
)
def test_host_glob_matching(pattern: str, matching: str, excluded: str) -> None:
    host_filter = _compile_host_glob(pattern)
    assert host_filter.fullmatch(matching)
    assert host_filter.fullmatch(excluded) is None


def test_host_regex_uses_full_matching() -> None:
    output = StringIO()
    repos = [Repository("/one/project", remote_url="github.com/team/project")]
    _print_scan_results(Console(file=output), repos, [], "remote", False, False, _compile_host_regex("github"))
    assert "展示 0/1 个仓库组" in output.getvalue()
    assert _compile_host_regex(r"GITHUB\.COM").fullmatch("github.com")


@pytest.mark.parametrize("stash", [False, True])
@pytest.mark.parametrize("bare", [False, True])
@pytest.mark.parametrize("stash_count", [0, 2])
@pytest.mark.parametrize("json_output", [False, True])
def test_scan_stash_queries_and_status(
    stash: bool, bare: bool, stash_count: int, json_output: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = Repository("/project", common_dir="/project/.git", remote_url="github.com/team/project", bare=bare)
    status = "# branch.head main\0# branch.oid abcdef123\0"
    if stash_count:
        status += f"# stash {stash_count}\0"
    if not bare:
        status += "? changed.txt\0"
    branch_refs = "main\0refs/remotes/origin/main\0origin/main\0\0origin\n"
    responses = ["main\n"] if bare else [status]
    expected_calls = [mock.call("/project", "symbolic-ref", "--quiet", "--short", "HEAD", allowed_codes=(0, 1))]
    if bare and stash:
        responses.append("abcdef123\n" if stash_count else "")
        expected_calls.append(
            mock.call("/project", "rev-parse", "--verify", "--quiet", "refs/stash", allowed_codes=(0, 1))
        )
        if stash_count:
            responses.append("stash@{0}\nstash@{1}\n")
            expected_calls.append(mock.call("/project", "reflog", "show", "--format=%gd", "refs/stash"))
    if not bare:
        expected_calls = [
            mock.call(
                "/project",
                "status",
                "--porcelain=v2",
                "--branch",
                *(("--show-stash",) if stash else ()),
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
            )
        ]
    with (
        mock.patch("plum_tools.git_scan.iter_repositories", return_value=iter(["/project"])) as discover,
        mock.patch("plum_tools.git_scan._identify_repository", return_value=repo) as identify,
        mock.patch("plum_tools.git_scan._read_shared_refs", return_value=(branch_refs, [])) as refs,
        mock.patch("plum_tools.git_scan._git", side_effect=responses) as git,
    ):
        scan_projects(["/projects"], stash=stash, json_output=json_output)
    assert discover.call_count == 1
    assert discover.call_args.args[:3] == (["/projects"], [], ())
    identify.assert_called_once_with("/project")
    refs.assert_called_once_with(repo, False)
    git.assert_has_calls(expected_calls)
    assert git.call_count == len(expected_calls)
    assert repo.branch == "main"
    assert not repo.errors
    has_stash = bool(stash_count and stash)
    assert ("stash 2" in repo.issues) is has_stash
    assert ("未跟踪 1" in repo.issues) is (not bare)
    output = capsys.readouterr().out
    assert ("stash 2" in output) is has_stash
    if json_output:
        payload = json.loads(output)
        assert payload["options"]["stash_checked"] is stash
        assert payload["summary"]["issue_repository_count"] == int(not bare or has_stash)
        assert payload["repositories"][0]["issues"] == repo.issues
        assert payload["repositories"][0]["kind"] == ("bare" if bare else "normal")
    else:
        assert f"异常仓库目录{int(not bare or has_stash)}个" in "".join(output.split())


@pytest.mark.parametrize("group_by", ["remote", "name"])
@pytest.mark.parametrize("regex", [False, True])
@pytest.mark.parametrize("duplicates_only", [False, True])
def test_scan_json_filtering_preserves_all_scan_totals(
    group_by: str, regex: bool, duplicates_only: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    repos = [
        Repository(
            "/one/project",
            common_dir="/one/.git",
            remote_name="upstream",
            remote_url="github.com/team/project",
            branch="main",
            issues=["stash 2"],
        ),
        Repository("/two/project", common_dir="/two/.git", remote_url="github.com/team/project"),
        Repository(
            "/three/project",
            common_dir="/three/.git",
            remote_url="github.com/other/project",
            bare=True,
            errors=['fetch 失败："断开"\n请重试'],
        ),
        Repository(
            "/worktrees/project", common_dir="/three/.git", remote_url="github.com/other/project", worktree=True
        ),
        Repository("/four/hidden", common_dir="/four/.git", remote_url="gitlab.com/team/hidden"),
        Repository("/five/local", common_dir="/five/.git", remote_url="/local/project.git"),
        Repository("/six/unknown", common_dir="/six/.git"),
    ]
    error = DirectoryScanError('/protected/配置"目录\n', "Permission denied")

    def collect(
        paths: list[str],
        errors: list[DirectoryScanError],
        fetch: bool,
        exclude: tuple[str, ...],
        progress: object,
        stash: bool,
    ) -> list[Repository]:
        assert paths == ["/projects"]
        assert fetch is True
        assert exclude == (".venv",)
        assert progress is not None
        assert stash is False
        errors.append(error)
        return repos

    host_filter = _compile_host_regex(r"github\.com") if regex else _compile_host_glob("github.com")
    with mock.patch("plum_tools.git_scan._collect_repositories", side_effect=collect) as collector:
        scan_projects(
            ["/projects"],
            group_by,
            duplicates_only,
            True,
            (".venv",),
            stash=False,
            host_filter=host_filter,
            json_output=True,
        )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "scan"
    assert payload["options"] == {
        "group_by": group_by,
        "duplicates_only": duplicates_only,
        "fetch": True,
        "stash_checked": False,
    }
    only_remote_duplicates = duplicates_only and group_by == "remote"
    assert payload["summary"] == {
        "repository_count": 7,
        "shown_repository_count": 2 if only_remote_duplicates else 4,
        "independent_repository_count": 6,
        "group_count": 5 if group_by == "remote" else 4,
        "shown_group_count": 2 if group_by == "remote" and not duplicates_only else 1,
        "duplicate_remote_count": 1,
        "issue_repository_count": 2,
        "failed_repository_count": 1,
        "directory_error_count": 1,
    }
    rows = {item["path"]: item for item in payload["repositories"]}
    assert set(rows) == (
        {"/one/project", "/two/project"}
        if only_remote_duplicates
        else {
            "/one/project",
            "/two/project",
            "/three/project",
            "/worktrees/project",
        }
    )
    assert rows["/one/project"] == {
        "path": "/one/project",
        "common_dir": "/one/.git",
        "remote_name": "upstream",
        "remote_url": "github.com/team/project",
        "branch": "main",
        "bare": False,
        "worktree": False,
        "issues": ["stash 2"],
        "errors": [],
        "host": "github.com",
        "group_key": "project" if group_by == "name" else "github.com/team/project",
        "kind": "normal",
        "duplicate_clone": True,
        "has_issues": True,
        "failed": False,
    }
    assert rows["/two/project"]["has_issues"] is False
    if not only_remote_duplicates:
        assert rows["/three/project"]["errors"] == ['fetch 失败："断开"\n请重试']
        assert rows["/three/project"]["failed"] is True
        assert rows["/three/project"]["has_issues"] is True
        assert rows["/three/project"]["kind"] == "bare"
        assert rows["/three/project"]["duplicate_clone"] is False
        assert rows["/worktrees/project"]["kind"] == "worktree"
        assert rows["/worktrees/project"]["duplicate_clone"] is False
    assert payload["directory_errors"] == [{"path": error.path, "reason": error.reason}]
    assert captured.err == ""
    assert collector.call_count == 1


@pytest.mark.parametrize("group_by", ["remote", "name"])
def test_scan_json_no_matching_hosts(group_by: str, capsys: pytest.CaptureFixture[str]) -> None:
    repos = [Repository("/one/project", common_dir="/one/.git", remote_url="github.com/team/project")]
    with mock.patch("plum_tools.git_scan._collect_repositories", return_value=repos) as collect:
        scan_projects(["/projects"], group_by, host_filter=_compile_host_glob("unmatched.example"), json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["repositories"] == []
    assert payload["summary"]["repository_count"] == 1
    assert payload["summary"]["group_count"] == 1
    assert payload["summary"]["shown_repository_count"] == 0
    assert payload["summary"]["shown_group_count"] == 0
    assert collect.call_count == 1


def test_walk_directories_collects_paths_and_reasons(tmp_path: Path) -> None:
    denied = str(tmp_path / "config：[red]store")
    protected = str(tmp_path / "Photos Library.photoslibrary")
    errors: list[DirectoryScanError] = []

    def walk_with_errors(path: Path, *, onerror: Callable[[OSError], None]) -> list:
        onerror(PermissionError(errno.EACCES, "Permission denied", denied))
        onerror(PermissionError(errno.EPERM, "Operation not permitted", protected))
        return [(str(path), [], [])]

    with mock.patch("plum_tools.git_scan.os.walk", side_effect=walk_with_errors) as walk:
        directories = list(walk_directories([str(tmp_path)], errors))
    assert directories == [(str(tmp_path.resolve()), [], [])]
    assert errors == [
        DirectoryScanError(denied, "Permission denied"),
        DirectoryScanError(protected, "Operation not permitted"),
    ]
    assert walk.call_count == 1
    assert walk.call_args.args == (tmp_path.resolve(),)
    assert callable(walk.call_args.kwargs["onerror"])


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PermissionError(errno.EACCES, "Permission denied", "/projects/one"), "Permission denied"),
        (RuntimeError("路径解析失败"), "路径解析失败"),
    ],
)
def test_walk_directories_collects_resolution_errors(error: OSError | RuntimeError, reason: str) -> None:
    errors: list[DirectoryScanError] = []
    with (
        mock.patch("plum_tools.git_scan.Path.resolve", side_effect=error),
        mock.patch("plum_tools.git_scan.os.walk") as walk,
    ):
        assert list(walk_directories(["/projects/one"], errors)) == []
    assert errors == [DirectoryScanError("/projects/one", reason)]
    walk.assert_not_called()


@pytest.mark.parametrize("exists", [False, True])
def test_walk_directories_collects_invalid_roots(tmp_path: Path, exists: bool) -> None:
    path = tmp_path / "invalid"
    if exists:
        path.write_text("普通文件", encoding="utf-8")
    errors: list[DirectoryScanError] = []
    with mock.patch("plum_tools.git_scan.os.walk") as walk:
        assert list(walk_directories([str(path)], errors)) == []
    assert errors == [DirectoryScanError(str(path.resolve()), "扫描路径不是目录")]
    walk.assert_not_called()


def test_directory_error_table_merges_reasons_and_separates_groups() -> None:
    errors = [
        DirectoryScanError("/projects/z", "Permission denied"),
        DirectoryScanError("/Pictures/Photos Library.photoslibrary", "Operation not permitted"),
        DirectoryScanError("/projects/a：[red]", "Permission denied"),
    ]
    output = StringIO()
    console = Console(file=output, width=200)
    with mock.patch.object(console, "print", wraps=console.print) as printer:
        print_directory_errors(console, errors)
    assert printer.call_count == 1
    table = printer.call_args.args[0]
    assert [row.end_section for row in table.rows] == [True, False, True]
    rendered = output.getvalue()
    rows = [[cell.strip() for cell in line.split("│")[1:-1]] for line in rendered.splitlines() if line.startswith("│")]
    assert rows == [
        ["Operation not permitted", "/Pictures/Photos Library.photoslibrary"],
        ["Permission denied", "/projects/a：[red]"],
        ["", "/projects/z"],
    ]
    assert "目录扫描错误" in rendered
    assert "2 种原因 · 3 个目录" in rendered


def test_directory_error_table_wraps_long_paths() -> None:
    path = "/projects/" + "目录名/" * 30 + "[red]repo"
    output = StringIO()
    print_directory_errors(Console(file=output, width=70), [DirectoryScanError(path, "Permission denied")])
    parts = [line.split("│")[2].strip() for line in output.getvalue().splitlines() if line.startswith("│")]
    assert len(parts) > 1
    assert "".join(parts) == path


def test_directory_error_table_is_hidden_without_errors() -> None:
    output = StringIO()
    print_directory_errors(Console(file=output), [])
    assert output.getvalue() == ""

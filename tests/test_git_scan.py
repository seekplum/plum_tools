"""验证主机展示过滤及普通、裸仓库的 stash 忽略行为。"""

import errno
import json
import subprocess
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import Any, Generator
from unittest import mock

import pytest
from rich.console import Console

from plum_tools.git_scan import (
    DirectoryScanError,
    GitScanError,
    Repository,
    _collect_repositories,
    _compile_host_glob,
    _compile_host_regex,
    _git,
    _group_label,
    _identify_repository,
    _print_scan_results,
    _read_bare_status,
    _read_branches,
    _read_shared_refs,
    _read_worktree,
    _remote_host,
    _repository_cells,
    _scan_json_repositories,
    _scan_repository,
    iter_repositories,
    normalize_remote_url,
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
        Repository("/three/project", common_dir="/three/.git", remote_url="git.xxx.net:2222/team/project"),
        Repository("/four/hidden", common_dir="/four/.git", remote_url="gitlab.com/team/hidden"),
        Repository("/five/local", common_dir="/five/.git", remote_url="/local/project.git"),
        Repository("/six/unknown", common_dir="/six/.git"),
    ]
    host_filter = (
        _compile_host_regex(r".*\.xxx\.net|github\.com") if regex else _compile_host_glob("*.xxx.net|github.com")
    )
    output = StringIO()
    _print_scan_results(Console(file=output, width=200), repos, [], group_by, duplicates_only, False, host_filter)
    rendered = output.getvalue()
    assert "github.com" in rendered
    assert "/one/project" in rendered
    assert "/two/project" in rendered
    assert "重复克隆" in rendered
    assert ("git.xxx.net" in rendered) is (not duplicates_only)
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
        ("*.xxx.net|github.com", "git.xxx.net", "github.com.invalid"),
        ("GITHUB.COM", "github.com", "mygithub.com"),
        ("git?.xxx.net", "git1.xxx.net", "git12.xxx.net"),
        ("git[12].xxx.net", "git2.xxx.net", "git3.xxx.net"),
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


def test_git_raises_when_executable_missing() -> None:
    with mock.patch("plum_tools.git_scan.shutil.which", return_value=None):
        with pytest.raises(GitScanError, match="未找到 git 可执行文件"):
            _git("/path", "status")


def test_git_raises_on_timeout() -> None:
    with mock.patch("plum_tools.git_scan.shutil.which", return_value="/usr/bin/git"):
        with mock.patch(
            "plum_tools.git_scan.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
        ):
            with pytest.raises(GitScanError, match="超时"):
                _git("/path", "status")


def test_git_raises_on_oserror() -> None:
    with mock.patch("plum_tools.git_scan.shutil.which", return_value="/usr/bin/git"):
        with mock.patch(
            "plum_tools.git_scan.subprocess.run",
            side_effect=OSError(errno.ENOENT, "not found"),
        ):
            with pytest.raises(GitScanError, match="无法执行 git"):
                _git("/path", "status")


def test_git_raises_on_nonzero_exit() -> None:
    result = mock.Mock(return_code=128, stdout="")
    with mock.patch("plum_tools.git_scan.shutil.which", return_value="/usr/bin/git"):
        with mock.patch("plum_tools.git_scan.subprocess.run", return_value=result):
            with pytest.raises(GitScanError, match="git status 失败"):
                _git("/path", "status")


def test_git_accepts_allowed_codes() -> None:
    result = mock.Mock(returncode=1, stdout="")
    with mock.patch("plum_tools.git_scan.shutil.which", return_value="/usr/bin/git"):
        with mock.patch("plum_tools.git_scan.subprocess.run", return_value=result):
            assert _git("/path", "symbolic-ref", "--quiet", "--short", "HEAD", allowed_codes=(0, 1)) == ""


def test_git_returns_stdout() -> None:
    result = mock.Mock(returncode=0, stdout="main\n")
    with mock.patch("plum_tools.git_scan.shutil.which", return_value="/usr/bin/git"):
        with mock.patch("plum_tools.git_scan.subprocess.run", return_value=result):
            assert _git("/path", "symbolic-ref", "--short", "HEAD") == "main\n"


@pytest.mark.parametrize(
    ("url", "repo_path", "expected"),
    [
        ("https://github.com/team/project.git", "/repo", "github.com/team/project"),
        ("https://github.com/team/project", "/repo", "github.com/team/project"),
        ("http://example.com:8080/team/project.git", "/repo", "example.com:8080/team/project"),
        ("ssh://git@github.com/team/project.git", "/repo", "github.com/team/project"),
        ("git@github.com:team/project.git", "/repo", "github.com/team/project"),
        ("file:///local/project.git", "/repo", str(Path("/local/project.git").resolve())),
        ("file://server/project.git", "/repo", "file://server/project.git"),
        ("../project.git", "/home/user/work", str(Path("/home/user/project.git").resolve())),
        ("/abs/project.git", "/repo", str(Path("/abs/project.git").resolve())),
    ],
)
def test_normalize_remote_url(url: str, repo_path: str, expected: str) -> None:
    assert normalize_remote_url(url, repo_path) == expected


def test_normalize_remote_url_rejects_missing_host() -> None:
    with pytest.raises(ValueError, match="远程 URL 缺少主机名"):
        normalize_remote_url(":///path", "/repo")


def test_normalize_remote_url_preserves_local_git_suffix() -> None:
    result = normalize_remote_url("/local/project.git", "/repo")
    assert result.endswith(".git")


def test_identify_repository_collects_errors() -> None:
    # fmt: off
    with (
        mock.patch("plum_tools.git_scan._git", side_effect=GitScanError("git rev-parse 失败")) as git_call,
    ):
        # fmt: on
        repo = _identify_repository("/bad/repo")
    assert repo.errors == ["git rev-parse 失败"]
    assert not repo.issues
    git_call.assert_called_once()


def test_identify_repository_handles_value_error() -> None:
    # fmt: off
    with (
        mock.patch("plum_tools.git_scan._git", side_effect=ValueError("bad path")) as git_call,
    ):
        # fmt: on
        repo = _identify_repository("/bad/repo")
    assert repo.errors == ["无法解析仓库路径或远程地址"]
    git_call.assert_called_once()


def test_identify_repository_sets_bare_and_worktree_flags() -> None:
    responses = [
        "true\n/repo/.git\n/repo/.git\n",
        "origin\n",
        "git@github.com:team/project.git\n",
    ]
    with mock.patch("plum_tools.git_scan._git", side_effect=responses):
        repo = _identify_repository("/repo")
    assert repo.bare is True
    assert repo.worktree is False
    assert repo.common_dir == str(Path("/repo/.git").resolve())
    assert repo.remote_url == "github.com/team/project"


def test_identify_repository_marks_worktree() -> None:
    responses = [
        "false\n/repo/.git\n/repo/.git/worktrees/wt\n",
        "origin\n",
        "git@github.com:team/project.git\n",
    ]
    with mock.patch("plum_tools.git_scan._git", side_effect=responses):
        repo = _identify_repository("/repo")
    assert repo.worktree is True


def test_identify_repository_appends_no_remote_issue() -> None:
    responses = ["false\n/repo/.git\n/repo/.git\n", ""]
    with mock.patch("plum_tools.git_scan._git", side_effect=responses):
        repo = _identify_repository("/repo")
    assert "无远程" in repo.issues


def test_identify_repository_raises_on_empty_remote_url() -> None:
    responses = ["false\n/repo/.git\n/repo/.git\n", "origin\n", ""]
    with mock.patch("plum_tools.git_scan._git", side_effect=responses):
        repo = _identify_repository("/repo")
    assert any("未配置地址" in error for error in repo.errors)


def test_read_worktree_parses_status_entries() -> None:
    repo = Repository("/repo")
    output = (
        "# branch.oid abcdef123\0"
        "# branch.head main\0"
        "1 M. file1\0"
        "1 M. file2\0"
        "1 .M file3\0"
        "1 .M file4\0"
        "? untracked.txt\0"
        "u conflict.txt\0"
    )
    with mock.patch("plum_tools.git_scan._git", return_value=output):
        _read_worktree(repo, stash=False)
    assert repo.branch == "main"
    assert "暂存 2" in repo.issues
    assert "未暂存 2" in repo.issues
    assert "未跟踪 1" in repo.issues
    assert "冲突 1" in repo.issues


def test_read_worktree_skips_rename_original_path() -> None:
    repo = Repository("/repo")
    output = "# branch.head main\02.R old.txt\0new.txt\0"
    with mock.patch("plum_tools.git_scan._git", return_value=output):
        _read_worktree(repo, stash=False)
    assert not any("old.txt" in issue for issue in repo.issues)
    assert not any("new.txt" in issue for issue in repo.issues)


def test_read_worktree_skips_stash_when_disabled() -> None:
    repo = Repository("/repo")
    output = "# branch.head main\0# stash 2\0"
    with mock.patch("plum_tools.git_scan._git", return_value=output):
        _read_worktree(repo, stash=False)
    assert not any("stash" in issue for issue in repo.issues)


def test_read_worktree_detects_detached_head() -> None:
    repo = Repository("/repo")
    output = "# branch.oid abcdef123\0# branch.head (detached)\0"
    with mock.patch("plum_tools.git_scan._git", return_value=output):
        _read_worktree(repo, stash=False)
    assert repo.branch == "HEAD@abcdef1"
    assert "游离 HEAD" in repo.issues


def test_read_worktree_parses_stash_issue() -> None:
    repo = Repository("/repo")
    output = "# branch.head main\0# stash 3\0"
    with mock.patch("plum_tools.git_scan._git", return_value=output):
        _read_worktree(repo, stash=True)
    assert "stash 3" in repo.issues


def test_read_worktree_propagates_git_error() -> None:
    repo = Repository("/repo")
    with mock.patch("plum_tools.git_scan._git", side_effect=GitScanError("git status 失败")):
        with pytest.raises(GitScanError, match="git status 失败"):
            _read_worktree(repo, stash=False)


def test_read_branches_detects_issues() -> None:
    repo = Repository("/repo", branch="main")
    output = (
        "main\0refs/remotes/origin/main\0origin/main\0ahead 2\0origin\n"
        "feature\0\0\0\0\n"
        "bugfix\0refs/remotes/origin/bugfix\0origin/bugfix\0gone\0origin\n"
        "local\0refs/heads/other\0other\0\0.\n"
    )
    _read_branches(repo, output)
    issues = repo.issues
    assert "main → origin/main：领先 2" in issues
    assert "feature：无 upstream" in issues
    assert "bugfix：upstream 已失效（origin/bugfix）" in issues
    assert "local：跟踪本地分支（other）" in issues


def test_read_branches_appends_no_commit_issue() -> None:
    repo = Repository("/repo")
    _read_branches(repo, "")
    assert "尚无提交" in repo.issues


def test_read_branches_skips_no_commit_for_detached() -> None:
    repo = Repository("/repo", branch="HEAD@abc")
    _read_branches(repo, "")
    assert "尚无提交" not in repo.issues


def test_read_bare_status_detects_detached_head() -> None:
    repo = Repository("/repo", bare=True)
    with mock.patch("plum_tools.git_scan._git", side_effect=["", "abcdef123\n"]):
        _read_bare_status(repo, stash=False)
    assert repo.branch == "HEAD@abcdef123"
    assert "游离 HEAD" in repo.issues


def test_read_bare_status_parses_branch() -> None:
    repo = Repository("/repo", bare=True)
    with mock.patch("plum_tools.git_scan._git", side_effect=["main\n"]):
        _read_bare_status(repo, stash=False)
    assert repo.branch == "main"


def test_read_bare_status_detects_stash() -> None:
    repo = Repository("/repo", bare=True)
    with mock.patch("plum_tools.git_scan._git", side_effect=["main\n", "refs/stash\n", "stash@{0}\nstash@{1}\n"]):
        _read_bare_status(repo, stash=True)
    assert "stash 2" in repo.issues


def test_read_shared_refs_skips_fetch_when_disabled() -> None:
    repo = Repository("/repo")
    with mock.patch("plum_tools.git_scan._git", return_value="") as git_call:
        refs, errors = _read_shared_refs(repo, fetch=False)
    assert refs == ""
    assert errors == []
    assert git_call.call_count == 1


def test_read_shared_refs_appends_fetch_error() -> None:
    repo = Repository("/repo")
    with mock.patch(
        "plum_tools.git_scan._git",
        side_effect=[GitScanError("fetch 失败"), ""],
    ):
        refs, errors = _read_shared_refs(repo, fetch=True)
    assert refs == ""
    assert len(errors) == 1
    assert "远程更新失败" in errors[0]


def test_read_shared_refs_appends_for_each_ref_error() -> None:
    repo = Repository("/repo")
    with mock.patch("plum_tools.git_scan._git", side_effect=GitScanError("for-each-ref 失败")):
        refs, errors = _read_shared_refs(repo, fetch=False)
    assert refs is None
    assert errors == ["for-each-ref 失败"]


def test_scan_repository_reuses_shared_future() -> None:
    shared: dict = {}
    lock = mock.MagicMock()
    with (
        mock.patch(
            "plum_tools.git_scan._identify_repository", return_value=Repository("/repo", common_dir="/repo/.git")
        ),
        mock.patch("plum_tools.git_scan._read_shared_refs", return_value=("", [])) as refs,
        mock.patch("plum_tools.git_scan._read_worktree"),
    ):
        repo1 = _scan_repository("/repo", fetch=False, shared=shared, lock=lock)
        repo2 = _scan_repository("/repo", fetch=False, shared=shared, lock=lock)
    assert refs.call_count == 1
    assert repo1.errors == repo2.errors == []


def test_scan_repository_returns_repo_without_common_dir() -> None:
    shared: dict = {}
    lock = mock.MagicMock()
    with mock.patch("plum_tools.git_scan._identify_repository", return_value=Repository("/repo")):
        repo = _scan_repository("/repo", fetch=False, shared=shared, lock=lock)
    assert repo.common_dir == ""
    assert not repo.errors


def test_scan_repository_appends_read_errors() -> None:
    shared: dict = {}
    lock = mock.MagicMock()
    with (
        mock.patch(
            "plum_tools.git_scan._identify_repository", return_value=Repository("/repo", common_dir="/repo/.git")
        ),
        mock.patch("plum_tools.git_scan._read_shared_refs", return_value=(None, ["ref error"])),
        mock.patch("plum_tools.git_scan._read_worktree", side_effect=GitScanError("status 失败")),
    ):
        repo = _scan_repository("/repo", fetch=False, shared=shared, lock=lock)
    assert repo.errors == ["ref error", "status 失败"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("", "无远程 / 无法识别"),
        ("/local/path", "本地路径"),
        ("file:///local", "本地路径"),
        ("github.com/team/project", "github.com"),
        ("git@github.com:team/project", "github.com"),
    ],
)
def test_remote_host(url: str, expected: str) -> None:
    assert _remote_host(url) == expected


def test_group_label_adds_duplicate_note() -> None:
    repos = [Repository("/repo", remote_url="github.com/team/project")]
    label = _group_label("github.com/team/project", repos, "remote", {"github.com/team/project"})
    assert "重复克隆" in label.plain


def test_group_label_adds_same_name_note() -> None:
    repos = [
        Repository("/one/project", remote_url="github.com/a/project"),
        Repository("/two/project", remote_url="gitlab.com/b/project"),
    ]
    label = _group_label("project", repos, "name", set())
    assert "同名仓库（远程不同）" in label.plain


def test_group_label_strips_host_prefix_for_remote_grouping() -> None:
    repos = [Repository("/repo", remote_url="github.com/team/project")]
    label = _group_label("github.com/team/project", repos, "remote", set())
    assert label.plain == "team/project"


def test_repository_cells_shows_bare_and_worktree_kinds() -> None:
    repo = Repository("/repo", bare=True)
    path_text, branch_text, remote_text, status_text = _repository_cells(repo, "remote")  # noqa
    assert "（裸仓库）" in path_text.plain

    repo2 = Repository("/repo2", worktree=True)
    path_text, *_ = _repository_cells(repo2, "remote")
    assert "（worktree）" in path_text.plain


def test_repository_cells_shows_clean_status() -> None:
    repo = Repository("/repo", bare=False)
    _, _, _, status_text = _repository_cells(repo, "remote")
    assert "工作区干净" in status_text.plain


def test_repository_cells_shows_bare_clean_status() -> None:
    repo = Repository("/repo", bare=True)
    _, _, _, status_text = _repository_cells(repo, "remote")
    assert "与跟踪引用一致" in status_text.plain


def test_repository_cells_shows_errors() -> None:
    repo = Repository("/repo", errors=["git status 失败"])
    _, _, _, status_text = _repository_cells(repo, "remote")
    assert "检查失败" in status_text.plain


def test_repository_cells_shows_remote_url_for_name_grouping() -> None:
    repo = Repository("/repo", remote_name="origin", remote_url="github.com/team/project")
    _, _, remote_text, _ = _repository_cells(repo, "name")
    assert "github.com/team/project" in remote_text.plain


def test_collect_repositories_processes_all_paths(tmp_path: Path) -> None:
    repos = [Repository("/one/repo", common_dir="/one/.git"), Repository("/two/repo", common_dir="/two/.git")]
    with (
        mock.patch("plum_tools.git_scan.iter_repositories", return_value=iter(["/one/repo", "/two/repo"])),
        mock.patch("plum_tools.git_scan._identify_repository", side_effect=repos),
        mock.patch("plum_tools.git_scan._read_shared_refs", return_value=("", [])),
        mock.patch("plum_tools.git_scan._read_worktree"),
    ):
        result = _collect_repositories(["/projects"], [], fetch=False)
    assert result == sorted(repos, key=lambda repo: repo.path)


def test_collect_repositories_with_progress(tmp_path: Path) -> None:
    repo = Repository("/one/repo", common_dir="/one/.git")
    progress = mock.MagicMock()

    def fake_iter(
        paths: list[str],
        errors: list[DirectoryScanError],
        exclude: tuple[str, ...],
        progress: Any = None,
    ) -> Generator[str]:
        if progress is not None:
            progress.discovered(True)
        yield "/one/repo"

    with (
        mock.patch("plum_tools.git_scan.iter_repositories", side_effect=fake_iter),
        mock.patch("plum_tools.git_scan._identify_repository", return_value=repo),
        mock.patch("plum_tools.git_scan._read_shared_refs", return_value=("", [])),
        mock.patch("plum_tools.git_scan._read_worktree"),
    ):
        result = _collect_repositories(["/projects"], [], fetch=False, progress=progress)
    assert result == [repo]
    progress.discovered.assert_called_once_with(True)
    progress.checked.assert_called_once_with(False)
    progress.finish_discovery.assert_called_once()


def test_scan_json_repositories_produces_enriched_rows() -> None:
    from plum_tools.git_scan import _ScanReport

    repos = [
        Repository(
            "/one/repo", common_dir="/one/.git", remote_url="github.com/team/project", bare=True, issues=["stash 1"]
        ),
        Repository("/two/repo", common_dir="/two/.git", remote_url="gitlab.com/team/repo", errors=["failed"]),
    ]
    grouped = {
        "github.com": {"team/project": [repos[0]]},
        "gitlab.com": {"team/repo": [repos[1]]},
    }
    report = _ScanReport(grouped, {"github.com/team/project"}, {})
    rows = _scan_json_repositories(report)

    assert len(rows) == 2
    assert rows[0]["kind"] == "bare"
    assert rows[0]["duplicate_clone"] is True
    assert rows[0]["has_issues"] is True
    assert rows[0]["failed"] is False
    assert rows[1]["kind"] == "normal"
    assert rows[1]["failed"] is True
    assert rows[1]["host"] == "gitlab.com"


def test_git_raises_timeout_error(tmp_path: Path) -> None:
    """验证 _git 在超时时抛出 GitScanError。"""
    with (
        mock.patch("shutil.which", return_value="/usr/bin/git"),
        mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)),
    ):
        with pytest.raises(GitScanError, match="超时"):
            _git(str(tmp_path), "status")


def test_git_raises_when_executable_not_found(tmp_path: Path) -> None:
    """验证 _git 在未找到 git 可执行文件时抛出 GitScanError。"""
    with mock.patch("shutil.which", return_value=None):
        with pytest.raises(GitScanError, match="未找到 git"):
            _git(str(tmp_path), "status")


def test_git_raises_on_non_zero_exit(tmp_path: Path) -> None:
    """验证 _git 在非零退出码时抛出 GitScanError。"""
    mock_result = mock.MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    with (
        mock.patch("shutil.which", return_value="/usr/bin/git"),
        mock.patch("subprocess.run", return_value=mock_result),
    ):
        with pytest.raises(GitScanError, match="失败"):
            _git(str(tmp_path), "status")


def test_walk_directories_deduplicates_roots(tmp_path: Path) -> None:
    """验证 walk_directories 对已访问的根目录去重。"""
    # 创建嵌套目录结构，其中一个目录通过多次路径引用
    (tmp_path / "sub1").mkdir()
    (tmp_path / "sub1" / "sub2").mkdir()

    results = list(walk_directories([str(tmp_path), str(tmp_path / "sub1")], []))
    roots = [root for root, _, _ in results]

    # sub1 只应出现一次
    assert roots.count(str(tmp_path / "sub1")) == 1
    assert str(tmp_path) in roots


def test_iter_repositories_detects_bare_repo(tmp_path: Path) -> None:
    """验证 iter_repositories 识别裸仓库（无 .git 但有 HEAD/config/objects）。"""
    bare_repo = tmp_path / "bare.git"
    bare_repo.mkdir()
    (bare_repo / "HEAD").write_text("ref: refs/heads/main\n")
    (bare_repo / "config").write_text("[core]\n\tbare = true\n")
    (bare_repo / "objects").mkdir()

    repos = list(iter_repositories([str(tmp_path)], []))

    assert str(bare_repo) in repos


def test_iter_repositories_updates_progress(tmp_path: Path) -> None:
    """验证 iter_repositories 通过 progress 更新发现数量。"""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    progress = mock.MagicMock()
    repos = list(iter_repositories([str(tmp_path)], [], progress=progress))

    assert str(repo_dir) in repos
    # walk_directories 会遍历多个目录，discovered 会被多次调用
    assert progress.discovered.call_count >= 1
    assert mock.call(True) in progress.discovered.call_args_list


def test_normalize_remote_url_handles_ipv6() -> None:
    """验证 normalize_remote_url 正确处理 IPv6 地址。"""
    url = "http://[2001:db8::1]:8080/team/project.git"
    normalized = normalize_remote_url(url, "/repo")

    assert normalized == "[2001:db8::1]:8080/team/project"


def test_read_worktree_skips_rename_source(tmp_path: Path) -> None:
    """验证 _read_worktree 跳过重命名源路径。"""
    repo = Repository(str(tmp_path))
    # -z 模式下重命名记录：状态码 2 + 新路径 + 旧路径，另加一个修改记录
    output = "2  new_name\0old_name\01  modified\0"

    with mock.patch("plum_tools.git_scan._git", return_value=output):
        _read_worktree(repo)

    # 应识别修改状态，跳过旧路径（不作为单独状态记录）
    assert any("暂存" in issue for issue in repo.issues)
    assert "old_name" not in " ".join(repo.issues)


def test_read_shared_refs_propagates_exception(tmp_path: Path) -> None:
    """验证共享 future 异常能被正确传递。"""
    from threading import Lock

    repo = Repository(str(tmp_path), common_dir="/shared/.git")
    shared: dict = {}
    lock = Lock()

    with mock.patch("plum_tools.git_scan._identify_repository", return_value=repo):
        with mock.patch("plum_tools.git_scan._read_shared_refs", side_effect=GitScanError("fetch 失败")):
            with pytest.raises(GitScanError, match="fetch 失败"):
                _scan_repository(str(tmp_path), True, shared, lock)

    # 异常应设置到 future 中
    assert shared["/shared/.git"].exception() is not None


def test_remote_host_handles_invalid_url() -> None:
    """验证 _remote_host 在 URL 解析失败时回退到简单分割。"""
    # 构造一个可能引发 ValueError 的 URL
    result = _remote_host("http://[invalid::ipv6::address/path")

    # 应回退到简单分割，返回 scheme 部分
    assert result == "http"


def test_repository_cells_compact_mode_for_bare() -> None:
    """验证 _repository_cells 紧凑模式下裸仓库状态文案。"""
    repo = Repository("/repo", bare=True)
    _, _, _, status_text = _repository_cells(repo, "remote", compact=True)

    assert "跟踪一致" in status_text.plain
    assert "工作区干净" not in status_text.plain


def test_repository_cells_compact_mode_for_clean_repo() -> None:
    """验证 _repository_cells 紧凑模式下干净仓库状态文案。"""
    repo = Repository("/repo")
    _, _, _, status_text = _repository_cells(repo, "remote", compact=True)

    assert "干净 / 跟踪一致" in status_text.plain


def test_print_directory_errors_compact_mode() -> None:
    """验证 print_directory_errors 紧凑模式下使用紧凑表格。"""
    from plum_tools.git_scan import DirectoryScanError, print_directory_errors

    errors = [
        DirectoryScanError("/bad1", "权限不足"),
        DirectoryScanError("/bad2", "不存在"),
    ]
    output = StringIO()
    console = Console(file=output, width=200)

    print_directory_errors(console, errors, compact=True)

    rendered = output.getvalue()
    assert "目录扫描错误" in rendered
    assert "/bad1" in rendered
    assert "权限不足" in rendered


def test_repository_cells_with_multiple_errors() -> None:
    """验证 _repository_cells 在多个错误时正确换行。"""
    repo = Repository("/repo", errors=["错误1", "错误2"])
    _, _, _, status_text = _repository_cells(repo, "remote")

    # 应包含两个错误信息，且有换行分隔
    assert "检查失败：错误1" in status_text.plain
    assert "检查失败：错误2" in status_text.plain
    assert "\n" in status_text.plain


def test_print_host_table_compact_mode() -> None:
    """验证 _print_host_table 紧凑模式下使用紧凑表格。"""
    from plum_tools.git_scan import _print_host_table

    repos = [Repository("/repo", common_dir="/repo/.git", remote_url="github.com/team/project")]
    groups = {"team/project": repos}
    output = StringIO()
    console = Console(file=output, width=200)

    _print_host_table(console, "github.com", groups, "remote", set(), compact=True)

    rendered = output.getvalue()
    assert "github.com" in rendered
    assert "/repo" in rendered


def test_collect_repositories_handles_keyboard_interrupt() -> None:
    """验证 _collect_repositories 在键盘中断时取消所有任务。"""
    from concurrent.futures import Future

    mock_future = mock.MagicMock(spec=Future)
    # 让 done() 返回 False，确保 future 保留在 pending 集合中
    mock_future.done.return_value = False

    # 让 iter_repositories 在遍历时抛出 KeyboardInterrupt
    def mock_iter(*args: Any, **kwargs: Any) -> Generator[str, None, None]:
        yield "/repo1"
        raise KeyboardInterrupt

    with (
        mock.patch("plum_tools.git_scan.iter_repositories", side_effect=mock_iter),
        mock.patch("plum_tools.git_scan.ThreadPoolExecutor") as mock_executor,
        mock.patch("plum_tools.git_scan.cancel_current") as mock_cancel,
    ):
        mock_pool = mock.MagicMock()
        mock_pool.submit.return_value = mock_future
        mock_executor.return_value.__enter__.return_value = mock_pool

        with pytest.raises(KeyboardInterrupt):
            _collect_repositories(["/projects"], [], fetch=False)

        # 应调用 cancel_current 和 future.cancel
        mock_cancel.assert_called_once()
        assert mock_future.cancel.called

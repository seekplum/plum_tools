"""验证各列表命令的排序参数、数值口径与输出一致性。"""

import json
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from rich.console import Console

from plum_tools._agent_usage import cli as usage_cli
from plum_tools._agent_usage.models import Client, Kind, record
from plum_tools._agent_usage.reporting import print_mcp_tools, sort_usage_rows
from plum_tools._gitrepo.models import GitScanError, Repository
from plum_tools._gitrepo.repository import _read_bare_status, _read_branches, _read_worktree
from plum_tools._gitrepo.sorting import sorted_repository_groups
from plum_tools.cli import gitrepo, pcompare, pfind_imports, pforkcheck, pping
from plum_tools.utils.sorting import SortField


@pytest.mark.parametrize("format_args", [[], ["--compact"], ["--json"]])
@pytest.mark.parametrize("group_by", ["name", "remote"])
def test_gitrepo_sort_preserves_groups_and_numeric_priority(
    format_args: list[str], group_by: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """两种分组的摘要、紧凑和 JSON 输出都遵循组首项与组内排序。"""
    repos = [
        Repository("/a/SORT_ALPHA", remote_url="github.com/team/shared", counts={"stash": 2, "untracked": 1}),
        Repository("/b/SORT_BETA", remote_url="github.com/team/other", counts={"stash": 12, "untracked": 0}),
        Repository("/c/SORT_GAMMA", remote_url="github.com/team/shared", counts={"stash": 2, "untracked": 9}),
        Repository("/d/SORT_UNKNOWN", remote_url="github.com/team/unknown", errors=["无法读取"]),
    ]
    monkeypatch.setattr(
        "sys.argv",
        [
            "gitrepo",
            "scan",
            "-p",
            "/unused",
            "--group-by",
            group_by,
            "--sort",
            "stash,untracked,path:asc",
            *format_args,
        ],
    )
    with mock.patch("plum_tools._gitrepo.scanner._collect_repositories", return_value=repos) as collect:
        gitrepo.main()
    assert collect.call_count == 1
    assert collect.call_args.args[-1] is ("--json" in format_args)
    output = capsys.readouterr().out
    expected = [repos[1].path, repos[2].path, repos[0].path, repos[3].path]
    if "--json" in format_args:
        payload = json.loads(output)
        assert [row["path"] for row in payload["repositories"]] == expected
        assert payload["repositories"][0]["counts"]["stash"] == 12
        assert payload["summary"]["repository_count"] == 4
    else:
        assert [output.index(path) for path in expected] == sorted(output.index(path) for path in expected)


def test_gitrepo_captures_counts_without_details() -> None:
    """排序不要求开启详情，领先和落后按各本地分支合计。"""
    repo = Repository("/repo")
    output = "# branch.head main\0# stash 12\0? a\0? b\x001 M. N... 100644 100644 100644 a b x\0"
    with mock.patch("plum_tools._gitrepo.repository._git", return_value=output):
        _read_worktree(repo, detail=False)
    _read_branches(
        repo,
        "main\0refs/remotes/origin/main\0origin/main\0ahead 10, behind 2\0origin\0\n"
        "dev\0refs/remotes/origin/dev\0origin/dev\0ahead 3\0origin\0\n",
    )
    assert repo.counts == {
        "stash": 12,
        "untracked": 2,
        "staged": 1,
        "unstaged": 0,
        "conflict": 0,
        "ahead": 13,
        "behind": 2,
    }
    assert repo.changes == repo.stashes == []


@pytest.mark.parametrize("bare", [False, True])
def test_gitrepo_ignored_stash_remains_unknown(bare: bool) -> None:
    """未检查 stash 时不伪装成零，其他已读取指标仍可排序。"""
    repo = Repository("/repo")
    with mock.patch("plum_tools._gitrepo.repository._git", return_value="main" if bare else "# branch.head main\0"):
        if bare:
            _read_bare_status(repo, stash=False)
        else:
            _read_worktree(repo, stash=False)
    assert "stash" not in repo.counts
    assert repo.counts["untracked"] == 0


@pytest.mark.parametrize(
    "field",
    ["path", "name", "branch", "remote", "stash", "untracked", "staged", "unstaged", "conflict", "ahead", "behind"],
)
@pytest.mark.parametrize("descending", [False, True])
def test_gitrepo_sort_fields_use_strings_or_actual_counts(field: str, descending: bool) -> None:
    """每个公开字段均使用对应值，数值排序区分 2 和 10。"""
    low = Repository("/a/alpha", branch="branch-a", remote_url="a.example/team/repo")
    high = Repository("/z/zulu", branch="branch-z", remote_url="z.example/team/repo")
    for repo, count in ((low, 2), (high, 10)):
        repo.counts.update(
            dict.fromkeys(("stash", "untracked", "staged", "unstaged", "conflict", "ahead", "behind"), count)
        )
    ordered = sorted_repository_groups({"group": [low, high]}, [SortField(field, descending)])
    assert ordered["group"] == ([high, low] if descending else [low, high])


def test_failed_bare_stash_query_does_not_report_zero() -> None:
    """Git 查询失败保留未知计数，避免在排序中被当作无 stash。"""
    repo = Repository("/repo")
    with mock.patch("plum_tools._gitrepo.repository._git", side_effect=["main", "refs/stash", GitScanError("不可读")]):
        with pytest.raises(GitScanError):
            _read_bare_status(repo)
    assert "stash" not in repo.counts


@pytest.mark.parametrize("format_args", [[], ["--format", "json"]])
def test_usage_cli_sorts_count_then_time(
    format_args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """次数默认降序、时间显式升序，终端与 JSON 展示一致。"""
    records: dict = {}
    for name, calls, when in (
        ("SORT_ALPHA", 2, "2026-01-01T00:00:00Z"),
        ("SORT_BETA", 12, "2026-02-01T00:00:00Z"),
        ("SORT_GAMMA", 12, "2026-01-01T00:00:00Z"),
    ):
        row = record(records, Kind.SKILL, name)
        row.update(calls=calls, last_used=when)
    report = {
        "items": list(records.values()),
        "clients": [Client.CLAUDE],
        "coverage": {},
        "limitations": [],
        "missing_sources": [],
    }
    monkeypatch.setattr("sys.argv", ["agent_usage_report", "--sort", "count,time:asc", *format_args])
    with mock.patch("plum_tools._agent_usage.cli.collect", return_value=report):
        assert usage_cli.main() == 0
    output = capsys.readouterr().out
    expected = ["SORT_GAMMA", "SORT_BETA", "SORT_ALPHA"]
    if format_args:
        assert [row["name"] for row in json.loads(output)["items"]] == expected
    else:
        assert [output.index(name) for name in expected] == sorted(output.index(name) for name in expected)


def test_usage_sort_uses_kind_specific_counts_and_timezone_aware_evidence() -> None:
    """规则用读取数、命令用展开数，最近时间按实际时刻而非时区字符串比较。"""
    records: dict = {}
    skill = record(records, Kind.SKILL, "skill")
    skill.update(calls=2, last_attributed="2026-01-01T01:00:00Z")
    rule = record(records, Kind.RULE, "rule")
    rule.update(reads=10, last_read="2026-01-01T08:30:00+08:00")
    command = record(records, Kind.COMMAND, "command")
    command.update(expansions=3, last_expanded="2026-01-01T00:00:00Z")
    record(records, Kind.MCP, "unknown")
    rows = list(records.values())
    assert [row["name"] for row in sort_usage_rows(rows, [SortField("count")])] == [
        "rule",
        "command",
        "skill",
        "unknown",
    ]
    assert [row["name"] for row in sort_usage_rows(rows, [SortField("time")])] == [
        "skill",
        "rule",
        "command",
        "unknown",
    ]


@pytest.mark.parametrize(
    "field,descending,expected",
    [
        ("count", False, ["TOOL_LOW", "TOOL_HIGH", "TOOL_NEW"]),
        ("time", True, ["TOOL_NEW", "TOOL_HIGH", "TOOL_LOW"]),
    ],
)
def test_mcp_tool_details_sort_by_tool_count_or_service_time(field: str, descending: bool, expected: list[str]) -> None:
    """工具明细按各工具次数排序，时间仅使用所属服务可观察到的时间。"""
    records: dict = {}
    old = record(records, Kind.MCP, "old")
    old.update(last_used="2026-01-01T00:00:00Z", tool_calls={"TOOL_LOW": 2, "TOOL_HIGH": 10})
    new = record(records, Kind.MCP, "new")
    new.update(last_used="2026-02-01T00:00:00Z", tool_calls={"TOOL_NEW": 20})
    output = StringIO()
    print_mcp_tools(Console(file=output, width=160), list(records.values()), [SortField(field, descending)])
    rendered = output.getvalue()
    assert [rendered.index(name) for name in expected] == sorted(rendered.index(name) for name in expected)


@pytest.mark.parametrize("format_args", [[], ["--compact"], ["--json"]])
def test_import_sort_uses_mapped_package_name(
    tmp_path: Path, format_args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """映射后的包名可用于多字段排序，三个输出模式均生效。"""
    (tmp_path / "imports.py").write_text("import requests\nimport yaml\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["pfind_imports", "-p", str(tmp_path), "-e", "yaml=aaa", "--sort", "package_name:asc,name", *format_args],
    )
    pfind_imports.main()
    output = capsys.readouterr().out
    if "--json" in format_args:
        assert [row["name"] for row in json.loads(output)["modules"]] == ["yaml", "requests"]
    else:
        assert output.index("yaml") < output.index("requests")


@pytest.mark.parametrize("format_args", [[], ["--compact"], ["--json"]])
def test_compare_sorts_by_maximum_size_across_inputs(
    tmp_path: Path, format_args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """大小比较所有输入，排序不影响差异退出码和统计。"""
    roots = [tmp_path / "left", tmp_path / "right"]
    for root in roots:
        root.mkdir()
    (roots[0] / "SORT_ALPHA").write_bytes(b"a" * 20)
    (roots[1] / "SORT_ALPHA").write_bytes(b"b")
    (roots[0] / "SORT_BETA").write_bytes(b"a" * 2)
    (roots[1] / "SORT_BETA").write_bytes(b"b" * 10)
    monkeypatch.setattr("sys.argv", ["pcompare", *map(str, roots), "--sort", "size,name:asc", *format_args])
    with pytest.raises(SystemExit) as error:
        pcompare.main()
    assert error.value.code == 1
    output = capsys.readouterr().out
    if "--json" in format_args:
        payload = json.loads(output)
        names = [row["path"] for row in payload["entries"] if row["path"] != "."]
        assert names == ["SORT_ALPHA", "SORT_BETA"]
        assert payload["summary"]["different_count"] == 3
    else:
        assert output.index("SORT_ALPHA") < output.index("SORT_BETA")


@pytest.mark.parametrize("format_args", [[], ["--compact"], ["--json"]])
def test_forkcheck_sorts_by_hits_then_source_index(
    tmp_path: Path, format_args: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """排序保留来源编号以及未筛选的汇总计数。"""
    (tmp_path / "SORT_BETA").mkdir()
    monkeypatch.setattr(
        "sys.argv",
        [
            "pforkcheck",
            "--pair",
            "alice/SORT_ALPHA",
            "up/SORT_ALPHA",
            "--pair",
            "alice/SORT_BETA",
            "up/SORT_BETA",
            "--target",
            str(tmp_path),
            "--sort",
            "hits,index:asc",
            *format_args,
        ],
    )
    pforkcheck.main()
    output = capsys.readouterr().out
    if "--json" in format_args:
        payload = json.loads(output)
        assert [row["index"] for row in payload["pairs"]] == [2, 1]
    else:
        assert output.index("SORT_BETA") < output.index("SORT_ALPHA")


@pytest.mark.parametrize("format_args", [[], ["--compact"], ["--json"]])
@pytest.mark.parametrize("sort,expected", [("ip", ["1.1.1.10", "1.1.1.2"]), ("ip:asc", ["1.1.1.2", "1.1.1.10"])])
def test_pping_sorts_numeric_addresses(
    format_args: list[str],
    sort: str,
    expected: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """IP 按地址数值排序，不受探测完成顺序影响。"""
    monkeypatch.setattr("sys.argv", ["pping", "-p", "1.1.1", "--sort", sort, *format_args])
    with mock.patch("plum_tools.cli.pping.Pool") as pool:
        pool.return_value.__enter__.return_value.imap_unordered.return_value = iter(["1.1.1.2", None, "1.1.1.10"])
        pping.main()
    output = capsys.readouterr().out
    if "--json" in format_args:
        assert json.loads(output)["reachable"] == expected
    else:
        assert output.splitlines() == expected


@pytest.mark.parametrize(
    "command,args,entry,boundary",
    [
        ("gitrepo", ["scan"], gitrepo.main, "plum_tools.cli.gitrepo.scan_projects"),
        ("agent_usage_report", [], usage_cli.main, "plum_tools._agent_usage.cli.collect"),
        ("pfind_imports", [], pfind_imports.main, "plum_tools.cli.pfind_imports.find_imports"),
        ("pcompare", ["a", "b"], pcompare.main, "plum_tools.cli.pcompare.compare_paths"),
        (
            "pforkcheck",
            ["--pair", "a/b", "c/d", "--target", "."],
            pforkcheck.main,
            "plum_tools.cli.pforkcheck._resolve_targets",
        ),
        ("pping", [], pping.main, "plum_tools.cli.pping.run"),
    ],
)
def test_invalid_sort_rejected_before_work(
    command: str,
    args: list[str],
    entry: Callable,
    boundary: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """未知排序字段不会启动扫描、网络探测或日志读取。"""
    monkeypatch.setattr("sys.argv", [command, *args, "--sort", "not_a_field"])
    with mock.patch(boundary) as work, pytest.raises(SystemExit) as error:
        entry()
    assert error.value.code == 2
    work.assert_not_called()
    assert "可用字段" in capsys.readouterr().err

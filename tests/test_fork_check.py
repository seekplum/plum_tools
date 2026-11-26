"""覆盖仓库对 CLI 的输入契约、目录匹配、筛选统计和读取错误。"""

import argparse
import json
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
from rich.console import Console

from plum_tools.fork_check import (
    RepoRow,
    RepoStatus,
    _find_repo,
    _is_directory,
    _load_pairs,
    _print_results,
    _repo_reference,
    _resolve_targets,
    build_parser,
    main,
)

# 使用不同仓库名，避免平铺目录匹配使 fork 和父仓库同时命中。
_PAIRS = (
    ("alice/both", "upstream/base-both"),
    ("alice/fork", "upstream/base-fork"),
    ("alice/parent", "upstream/base-parent"),
    ("alice/none", "upstream/base-none"),
)


@pytest.fixture
def repository_roots(tmp_path: Path) -> tuple[Path, Path]:
    """在临时路径创建覆盖四种状态和两种目录结构的目标，返回两个根目录。"""
    first = tmp_path / "python projects"
    second = tmp_path / "web"
    for directory in (first / "alice/both", second / "upstream/base-both", first / "fork", second / "base-parent"):
        directory.mkdir(parents=True)
    return first, second


def test_parser_accepts_repeated_pairs_targets_and_case_insensitive_statuses() -> None:
    args = build_parser().parse_args(
        [
            "--pair",
            "alice/repo",
            "upstream/repo",
            "--pair",
            "bob/tool",
            "team/tool",
            "--target",
            "./python",
            "--target",
            "./web",
            "--status",
            "fork_only",
            "--status",
            "Parent_Only",
            "--json",
            "--compact",
        ]
    )

    assert args.pair == [["alice/repo", "upstream/repo"], ["bob/tool", "team/tool"]]
    assert args.target == ["./python", "./web"]
    assert args.status == ["FORK_ONLY", "PARENT_ONLY"]
    assert args.data is None
    assert args.json_output is True
    assert args.compact is True


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--target", "."], "必须提供以下参数之一"),
        (["--data", "repos.txt"], "缺少必填参数：--target"),
        (["--pair", "alice/repo", "upstream/repo"], "缺少必填参数：--target"),
        (["--data", "repos.txt", "--pair", "alice/repo", "upstream/repo", "--target", "."], "不能与参数"),
        (["--pair", "alice/repo"], "--pair"),
        (["--pair", "alice/repo", "upstream/repo", "extra", "--target", "."], "无法识别的参数"),
        (["--data", "repos.txt", "--target", ".", "--status", "unknown"], "无效的选项值"),
    ],
)
def test_parser_rejects_invalid_inputs(options: list[str], message: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(options)

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


@pytest.mark.parametrize(
    "value",
    [
        "repo",
        "",
        "/repo",
        "owner/",
        "owner/repo/extra",
        "../repo",
        "owner/..",
        "./repo",
        "owner/.",
        "owner/re po",
        "ow\nner/repo",
        "owner/repo\\child",
        "owner/repo\x00",
    ],
)
def test_repo_reference_rejects_malformed_or_escaping_paths(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="应为 owner/repo"):
        _repo_reference(value)


def test_resolve_targets_keeps_order_and_resolves_relative_paths_with_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repository_roots: tuple[Path, Path]
) -> None:
    first, second = repository_roots
    monkeypatch.chdir(tmp_path)

    assert _resolve_targets(["python projects", "web"]) == {"T1": first.resolve(), "T2": second.resolve()}


@pytest.mark.parametrize("value", ["", "missing", "regular-file"])
def test_resolve_targets_rejects_empty_missing_and_file_paths(
    value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "regular-file").write_text("data", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="目标路径"):
        _resolve_targets([value])


def test_find_repo_matches_both_layouts_once_per_target(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for path in (first / "owner/project", first / "project", second / "project"):
        path.mkdir(parents=True)

    assert _find_repo("owner/project", {"T1": first, "T2": second}) == ("T1", "T2")


def test_find_repo_does_not_recurse_match_other_owners_or_accept_files(tmp_path: Path) -> None:
    (tmp_path / "nested/owner/project").mkdir(parents=True)
    (tmp_path / "other/project").mkdir(parents=True)
    (tmp_path / "owner").mkdir()
    (tmp_path / "owner/project").write_text("data", encoding="utf-8")
    (tmp_path / "project").write_text("data", encoding="utf-8")

    assert _find_repo("owner/project", {"T1": tmp_path}) == ()


def test_find_repo_flat_layout_matches_different_owners(tmp_path: Path) -> None:
    (tmp_path / "project").mkdir()

    assert _find_repo("alice/project", {"T1": tmp_path}) == ("T1",)
    assert _find_repo("upstream/project", {"T1": tmp_path}) == ("T1",)


def test_is_directory_handles_missing_children_under_files(tmp_path: Path) -> None:
    path = tmp_path / "file"
    path.write_text("data", encoding="utf-8")

    assert _is_directory(tmp_path / "missing") is False
    assert _is_directory(path) is False
    assert _is_directory(path / "child") is False


def test_is_directory_propagates_permission_errors(tmp_path: Path) -> None:
    with mock.patch.object(Path, "stat", side_effect=PermissionError("无法读取目录")) as path_stat:
        with pytest.raises(PermissionError, match="无法读取目录"):
            _is_directory(tmp_path)

    path_stat.assert_called_once_with()


def test_load_pairs_preserves_line_numbers_skips_invalid_rows_and_accepts_bom(tmp_path: Path) -> None:
    path = tmp_path / "repos.txt"
    path.write_text(
        "\ufeff\n"
        "alice/project upstream/project\n"
        "invalid\n"
        "../outside upstream/project\n"
        "alice/project invalid\n"
        "\t\n"
        "bob/tool\tteam/tool extra\n",
        encoding="utf-8",
    )

    assert _load_pairs(path) == ([(2, "alice/project", "upstream/project"), (7, "bob/tool", "team/tool")], 3)


@pytest.mark.parametrize("content", ["", "\n \t\n", "invalid\n"])
def test_load_pairs_with_no_valid_rows(content: str, tmp_path: Path) -> None:
    path = tmp_path / "repos.txt"
    path.write_text(content, encoding="utf-8")

    assert _load_pairs(path) == ([], int(content == "invalid\n"))


@pytest.mark.parametrize("from_file", [False, True])
def test_main_checks_all_statuses_with_both_input_sources(
    from_file: bool,
    repository_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first, second = repository_roots
    if from_file:
        path = tmp_path / "repos.txt"
        path.write_text(
            "\n" + "\n".join(f"{fork} {parent}" for fork, parent in _PAIRS) + "\ninvalid\n", encoding="utf-8"
        )
        source = ["--data", str(path)]
    else:
        source = [value for fork, parent in _PAIRS for value in ("--pair", fork, parent)]
    monkeypatch.setattr("sys.argv", ["pforkcheck", *source, "--target", str(first), "--target", str(second)])
    monkeypatch.setenv("COLUMNS", "240")

    main()

    captured = capsys.readouterr()
    assert captured.err == ""
    output = captured.out
    assert ("行号" if from_file else "序号") in output
    data_rows = [line.split("│")[1:-1] for line in output.splitlines() if line.startswith("│")]
    repository_rows = [cells for cells in data_rows if cells[0].strip()]
    hit_rows = [cells for cells in data_rows if not cells[0].strip()]
    assert len(repository_rows) == len(hit_rows) == 4
    expected_statuses = (RepoStatus.BOTH, RepoStatus.FORK_ONLY, RepoStatus.PARENT_ONLY, RepoStatus.NONE)
    expected_hits = (("存在：T1", "存在：T2"), ("存在：T1", "未找到"), ("未找到", "存在：T2"), ("未找到", "未找到"))
    for index, (cells, pair, status, hit_cells, hits) in enumerate(
        zip(repository_rows, _PAIRS, expected_statuses, hit_rows, expected_hits, strict=True), 1
    ):
        assert cells[0].strip() == str(index + int(from_file))
        assert cells[1].strip() == status.value
        assert cells[2].strip() == pair[0]
        assert cells[3].strip() == pair[1]
        assert tuple(cell.strip() for cell in hit_cells[2:]) == hits
        assert f"{status.value} 1" in output
    assert ("跳过 1" in output) is from_file
    assert "检查 4 对 · 展示 4 对" in output
    assert f"T1  {first.resolve()}" in output
    assert f"T2  {second.resolve()}" in output


def test_main_filters_multiple_statuses_but_keeps_full_summary(
    repository_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = repository_roots
    pairs = [value for fork, parent in _PAIRS for value in ("--pair", fork, parent)]
    monkeypatch.setattr(
        "sys.argv",
        ["pforkcheck", *pairs, "--target", str(first), "--target", str(second), "--status", "both", "--status", "none"],
    )
    monkeypatch.setenv("COLUMNS", "240")

    main()

    output = capsys.readouterr().out
    assert "alice/both" in output and "alice/none" in output
    assert "alice/fork" not in output and "alice/parent" not in output
    for status in RepoStatus:
        assert f"{status.value} 1" in output
    assert "全量统计，表格按筛选显示" in output


@pytest.mark.parametrize("compact", [False, True])
def test_main_empty_filter_result_keeps_unfiltered_counts(
    compact: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["pforkcheck", "--pair", "alice/missing", "upstream/missing", "--target", str(tmp_path), "--status", "BOTH"]
        + (["--compact"] if compact else []),
    )
    monkeypatch.setenv("COLUMNS", "240")

    main()

    output = capsys.readouterr().out
    assert "alice/missing" not in output
    assert "均不存在 1" in output
    assert "fork 与父仓库均存在 0" in output
    assert "没有符合筛选条件的仓库对" in output
    assert "检查 1 对 · 展示 0 对" in output
    assert "┏" not in output and "│" not in output


@pytest.mark.parametrize("source_kind", ["missing", "directory", "invalid-encoding"])
@pytest.mark.parametrize("json_output", [False, True])
def test_main_reports_data_read_errors_without_results(
    source_kind: str,
    json_output: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "repos.txt"
    if source_kind == "directory":
        source.mkdir()
    elif source_kind == "invalid-encoding":
        source.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(
        "sys.argv",
        ["pforkcheck", "--data", str(source), "--target", str(tmp_path)] + (["--json"] if json_output else []),
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "无法检查仓库" in captured.err


@pytest.mark.parametrize("json_output", [False, True])
def test_main_reports_repository_permission_errors_instead_of_missing(
    json_output: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["pforkcheck", "--pair", "alice/repo", "upstream/repo", "--target", str(tmp_path)]
        + (["--json"] if json_output else []),
    )
    with mock.patch("plum_tools.fork_check._find_repo", side_effect=PermissionError("没有读取权限")) as find_repo:
        with pytest.raises(SystemExit) as error:
            main()

    find_repo.assert_called_once_with("alice/repo", {"T1": tmp_path.resolve()})
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "没有读取权限" in captured.err


def test_print_results_preserves_literal_markup_and_long_repository_names() -> None:
    output = StringIO()
    console = Console(file=output, width=65)
    fork = "[bold]/" + "long-fork-name" * 3
    parent = "[red]/" + "long-parent-name" * 3
    row = RepoRow(1, fork, parent, ("T1",), ())
    with mock.patch("plum_tools.fork_check.Console", return_value=console) as console_factory:
        _print_results([row], {"T1": Path("/projects")}, set(), 0, from_file=False)

    console_factory.assert_called_once_with()
    table_rows = [line.split("│") for line in output.getvalue().splitlines() if line.startswith("│")]
    assert "".join(cells[3].strip() for cells in table_rows).split("存在：", 1)[0] == fork
    assert "".join(cells[4].strip() for cells in table_rows).split("未找到", 1)[0] == parent


def test_main_compact_preserves_names_and_target_labels_without_borders(
    repository_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = repository_roots
    (second / "both").mkdir()
    monkeypatch.setattr(
        "sys.argv",
        [
            "pforkcheck",
            "--pair",
            "alice/both",
            "upstream/base-both",
            "--pair",
            "alice/none",
            "upstream/base-none",
            "--target",
            str(first),
            "--target",
            str(second),
            "--compact",
        ],
    )
    monkeypatch.setenv("COLUMNS", "160")

    main()

    captured = capsys.readouterr()
    assert captured.err == ""
    rendered = captured.out
    for text in ("alice/both", "upstream/base-both", "alice/none", "存在：T1, T2", "未找到", "检查 2 对 · 展示 2 对"):
        assert text in rendered
    assert "│" not in rendered and "┏" not in rendered


@pytest.mark.parametrize(("content", "skipped"), [("", 0), ("invalid\n", 1)])
def test_main_empty_input_shows_message_without_table(
    content: str,
    skipped: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "repos.txt"
    source.write_text(content, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["pforkcheck", "--data", str(source), "--target", str(tmp_path)])

    main()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "没有有效的仓库对" in captured.out
    assert f"检查 0 对 · 展示 0 对 · 跳过 {skipped} 行" in captured.out
    assert "│" not in captured.out and "┏" not in captured.out


@pytest.mark.parametrize("from_file", [False, True])
@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("filtered", [False, True])
def test_main_json_contract_for_both_sources_filtering_and_compact(
    from_file: bool,
    compact: bool,
    filtered: bool,
    repository_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first, second = repository_roots
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repos.txt"
    if from_file:
        source.write_text(
            "\n" + "\n".join(f"{fork} {parent}" for fork, parent in _PAIRS) + "\ninvalid\n", encoding="utf-8"
        )
        arguments = ["--data", "repos.txt"]
    else:
        arguments = [value for fork, parent in _PAIRS for value in ("--pair", fork, parent)]
    arguments += ["--target", "python projects", "--target", "web", "--json"]
    if compact:
        arguments.append("--compact")
    if filtered:
        arguments += ["--status", "fork_only", "--status", "none", "--status", "fork_only"]
    monkeypatch.setattr("sys.argv", ["pforkcheck", *arguments])

    main()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert "\x1b" not in captured.out and "\\u" not in captured.out
    expected_pairs = [
        {
            "index": 1 + int(from_file),
            "status": "BOTH",
            "status_label": "fork 与父仓库均存在",
            "fork": "alice/both",
            "parent": "upstream/base-both",
            "fork_hits": ["T1"],
            "parent_hits": ["T2"],
        },
        {
            "index": 2 + int(from_file),
            "status": "FORK_ONLY",
            "status_label": "仅 fork 存在",
            "fork": "alice/fork",
            "parent": "upstream/base-fork",
            "fork_hits": ["T1"],
            "parent_hits": [],
        },
        {
            "index": 3 + int(from_file),
            "status": "PARENT_ONLY",
            "status_label": "仅父仓库存在",
            "fork": "alice/parent",
            "parent": "upstream/base-parent",
            "fork_hits": [],
            "parent_hits": ["T2"],
        },
        {
            "index": 4 + int(from_file),
            "status": "NONE",
            "status_label": "均不存在",
            "fork": "alice/none",
            "parent": "upstream/base-none",
            "fork_hits": [],
            "parent_hits": [],
        },
    ]
    assert json.loads(captured.out) == {
        "schema_version": 1,
        "command": "pforkcheck",
        "options": {
            "source": "file" if from_file else "pairs",
            "data_path": str(source.resolve()) if from_file else None,
            "statuses": ["FORK_ONLY", "NONE"] if filtered else [],
        },
        "targets": {"T1": str(first.resolve()), "T2": str(second.resolve())},
        "summary": {
            "pair_count": 4,
            "shown_pair_count": 2 if filtered else 4,
            "skipped_count": int(from_file),
            "status_counts": {"BOTH": 1, "FORK_ONLY": 1, "PARENT_ONLY": 1, "NONE": 1},
        },
        "pairs": [expected_pairs[1], expected_pairs[3]] if filtered else expected_pairs,
    }


@pytest.mark.parametrize(
    ("content", "skipped", "pair_count"), [("", 0, 0), ("invalid\n", 1, 0), ("alice/repo upstream/repo\n", 0, 1)]
)
def test_main_json_empty_result_remains_parseable_with_full_summary(
    content: str,
    skipped: int,
    pair_count: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "repos.txt"
    source.write_text(content, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["pforkcheck", "--data", str(source), "--target", str(tmp_path), "--status", "BOTH", "--json"]
    )

    main()

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["pairs"] == []
    assert payload["summary"] == {
        "pair_count": pair_count,
        "shown_pair_count": 0,
        "skipped_count": skipped,
        "status_counts": {"BOTH": 0, "FORK_ONLY": 0, "PARENT_ONLY": 0, "NONE": pair_count},
    }


def test_main_json_rejects_invalid_target_without_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["pforkcheck", "--pair", "alice/repo", "upstream/repo", "--target", str(tmp_path / "missing"), "--json"],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "目标路径不是已存在的目录" in captured.err

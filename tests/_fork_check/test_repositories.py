"""验证 repositories 的相关行为。"""

import argparse
from pathlib import Path
from unittest import mock

import pytest

from plum_tools._fork_check.repositories import (
    _find_repo,
    _is_directory,
    _load_pairs,
    _repo_reference,
    _resolve_targets,
)


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

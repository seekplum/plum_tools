"""覆盖多路径比较、Rich 报告及命令行退出行为。"""

import json
import os
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from rich.console import Console

from plum_tools.compare import (
    Entry,
    _decode_remote_tree,
    _file_md5,
    _load_trees,
    _scan_remote,
    _split_remote,
    compare_paths,
    main,
    print_report,
)


@pytest.mark.parametrize(
    ("contents", "result", "same_pairs"),
    [
        ((b"", b"", b""), "一致", (True, True, True)),
        ((b"\x00\xffdata",) * 3, "一致", (True, True, True)),
        ((b"abc", b"xyz", b"abc"), "内容不同", (False, True, False)),
        ((b"short", b"longer", b"short"), "大小不同", (False, True, False)),
        ((b"a", b"bb", b"ccc"), "大小不同", (False, False, False)),
    ],
)
def test_compare_files_groups_matching_contents(
    tmp_path: Path, contents: tuple[bytes, ...], result: str, same_pairs: tuple[bool, ...]
) -> None:
    paths = [tmp_path / f"file_{index}" for index in range(len(contents))]
    for path, content in zip(paths, contents, strict=True):
        path.write_bytes(content)

    comparisons = compare_paths(paths)

    assert len(comparisons) == 1
    item = comparisons[0]
    assert item.path == Path(".")
    assert item.result == result
    assert tuple(item.groups[left] == item.groups[right] for left, right in ((0, 1), (0, 2), (1, 2))) == same_pairs


def test_compare_different_sizes_skips_md5(tmp_path: Path) -> None:
    paths = [tmp_path / "small", tmp_path / "large"]
    paths[0].write_bytes(b"a")
    paths[1].write_bytes(b"longer")

    with mock.patch("plum_tools.compare._file_md5") as digest:
        comparisons = compare_paths(paths)

    assert comparisons[0].result == "大小不同"
    digest.assert_not_called()


def test_compare_reads_all_chunks_and_ignores_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = [tmp_path / "first", tmp_path / "second", tmp_path / "third"]
    for index, path in enumerate(paths):
        path.write_bytes(b"\x00\xffabcdef" + (b"x" if index == 2 else b"y"))
    paths[0].chmod(0o600)
    paths[1].chmod(0o644)
    os.utime(paths[0], (1_000_000, 1_000_000))
    os.utime(paths[1], (2_000_000, 2_000_000))
    monkeypatch.setattr("plum_tools.compare._CHUNK_SIZE", 3)

    item = compare_paths(paths)[0]

    assert item.result == "内容不同"
    assert item.groups[0] == item.groups[1]
    assert item.groups[0] != item.groups[2]


def test_compare_nested_directories_propagates_differences(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("first", "second", "third")]
    for index, root in enumerate(roots):
        (root / "shared" / "empty").mkdir(parents=True)
        (root / "shared" / ".hidden").write_bytes(b"same")
        (root / "changed" / "nested").mkdir(parents=True)
        (root / "changed" / "nested" / "data").write_bytes(b"left" if index != 1 else b"next")

    comparisons = compare_paths(roots)
    rows = {str(item.path): item for item in comparisons}

    assert [item.path for item in comparisons] == sorted(item.path for item in comparisons)
    assert {path: item.result for path, item in rows.items()} == {
        ".": "子项不同",
        "changed": "子项不同",
        "changed/nested": "子项不同",
        "changed/nested/data": "内容不同",
        "shared": "一致",
        "shared/.hidden": "一致",
        "shared/empty": "一致",
    }
    for path in (".", "changed", "changed/nested", "changed/nested/data"):
        assert rows[path].groups[0] == rows[path].groups[2]
        assert rows[path].groups[0] != rows[path].groups[1]


def test_compare_missing_entries_and_type_conflicts(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    (second / "conflict").mkdir(parents=True)
    (first / "conflict").write_bytes(b"file")
    (second / "conflict" / "child").write_bytes(b"child")
    (first / "empty").mkdir()

    rows = {str(item.path): item for item in compare_paths([first, second])}

    assert {path: item.result for path, item in rows.items()} == {
        ".": "子项不同",
        "conflict": "类型不同",
        "conflict/child": "缺失",
        "empty": "缺失",
    }
    assert rows["empty"].entries[1] is None
    assert rows["conflict/child"].entries[0] is None


def test_compare_links_does_not_follow_broken_or_recursive_targets(tmp_path: Path) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    for index, root in enumerate(roots):
        (root / "directory").mkdir(parents=True)
        (root / "directory" / "data").write_bytes(b"same")
        (root / "directory_link").symlink_to("directory", target_is_directory=True)
        (root / "loop").symlink_to(".", target_is_directory=True)
        (root / "broken").symlink_to("absent")
        (root / "changed_link").symlink_to(f"absent_{index}")

    rows = {str(item.path): item.result for item in compare_paths(roots)}

    assert rows == {
        ".": "子项不同",
        "broken": "一致",
        "changed_link": "链接目标不同",
        "directory": "一致",
        "directory/data": "一致",
        "directory_link": "一致",
        "loop": "一致",
    }


def test_compare_top_level_links_uses_the_target_text(tmp_path: Path) -> None:
    paths = [tmp_path / "first", tmp_path / "second"]
    for path in paths:
        path.symlink_to("absent")

    item = compare_paths(paths)[0]

    assert item.result == "一致"
    assert all(entry is not None and entry.kind == "链接" for entry in item.entries)


def test_compare_empty_directories_are_identical(tmp_path: Path) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()

    comparisons = compare_paths(roots)

    assert len(comparisons) == 1
    assert comparisons[0].path == Path(".")
    assert comparisons[0].result == "一致"


def test_compare_expands_home_and_relative_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "first").write_bytes(b"same")
    (tmp_path / "second").write_bytes(b"same")

    item = compare_paths([Path("~/first"), Path("second")])[0]

    assert item.result == "一致"
    assert tuple(entry.path for entry in item.entries if entry is not None) == (
        tmp_path / "first",
        tmp_path / "second",
    )


@pytest.mark.parametrize("count", [0, 1])
def test_compare_requires_multiple_paths(tmp_path: Path, count: int) -> None:
    with pytest.raises(ValueError, match="至少需要两个路径"):
        compare_paths([tmp_path] * count)


def test_compare_rejects_mixed_files_and_directories(tmp_path: Path) -> None:
    file_path = tmp_path / "file"
    file_path.write_bytes(b"data")

    with pytest.raises(ValueError, match="不能混合比较目录和文件"):
        compare_paths([tmp_path, file_path])


def test_compare_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compare_paths([tmp_path, tmp_path / "absent"])


def test_compare_rejects_special_files_without_opening_them(tmp_path: Path) -> None:
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)

    with pytest.raises(ValueError, match="不支持的文件类型"):
        compare_paths([fifo, fifo])


@pytest.mark.parametrize("operation", ["iterdir", "open"])
def test_compare_propagates_read_failures(tmp_path: Path, operation: str) -> None:
    paths = [tmp_path / "first", tmp_path / "second"]
    for path in paths:
        if operation == "iterdir":
            path.mkdir()
        else:
            path.write_bytes(b"data")

    with mock.patch.object(Path, operation, side_effect=PermissionError("无法读取")):
        with pytest.raises(PermissionError, match="无法读取"):
            compare_paths(paths)


@pytest.mark.parametrize(
    ("before_size", "after_size", "after_mtime", "after_ctime"),
    [(5, 5, 1, 1), (4, 5, 1, 1), (4, 4, 2, 1), (4, 4, 1, 2)],
)
def test_file_md5_rejects_changes_during_comparison(
    tmp_path: Path, before_size: int, after_size: int, after_mtime: int, after_ctime: int
) -> None:
    path = tmp_path / "file"
    path.write_bytes(b"data")
    states = [
        SimpleNamespace(st_size=before_size, st_mtime_ns=1, st_ctime_ns=1),
        SimpleNamespace(st_size=after_size, st_mtime_ns=after_mtime, st_ctime_ns=after_ctime),
    ]

    with mock.patch("plum_tools.compare.os.fstat", side_effect=states):
        with pytest.raises(OSError, match="比较期间文件发生变化"):
            _file_md5(Entry(path, "文件", size=4))


def test_report_separates_identical_and_different_entries(tmp_path: Path) -> None:
    roots = [tmp_path / "first[red]", tmp_path / "second"]
    for index, root in enumerate(roots):
        root.mkdir()
        (root / "same[bold].txt").write_bytes(b"same")
        (root / "different.txt").write_bytes(b"left" if index == 0 else b"next")
        (root / "link").symlink_to("absent[red]")
    (roots[0] / "missing").mkdir()
    output = StringIO()

    print_report(roots, compare_paths(roots), Console(file=output, width=180, color_system=None))

    rendered = output.getvalue()
    same, different = rendered.split("不一致的目录 / 文件", maxsplit=1)
    assert "一致的目录 / 文件（2）" in same
    assert "same[bold].txt" in same
    assert "same[bold].txt" not in different
    assert "different.txt" in different
    assert "different.txt" not in same
    assert "（3）" in different
    assert "缺失" in different
    assert "链接 · 组1 → absent[red]" in same
    assert f"[1] {roots[0]}" in rendered
    assert "整体不一致：一致 2 项，不一致 3 项。" in rendered


@pytest.mark.parametrize(("second_content", "exit_code"), [(b"same", 0), (b"diff", 1)])
def test_main_returns_comparison_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    second_content: bytes,
    exit_code: int,
) -> None:
    paths = [tmp_path / "first", tmp_path / "second"]
    paths[0].write_bytes(b"same")
    paths[1].write_bytes(second_content)
    monkeypatch.setattr("sys.argv", ["pcompare", *(str(path) for path in paths)])

    with pytest.raises(SystemExit) as error:
        main()

    captured = capsys.readouterr()
    assert error.value.code == exit_code
    assert ("整体一致" if exit_code == 0 else "整体不一致") in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("invalid_input", ["missing", "mixed", "single", "none"])
def test_main_reports_invalid_input_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], invalid_input: str
) -> None:
    file_path = tmp_path / "file"
    file_path.write_bytes(b"data")
    paths = {
        "missing": [tmp_path / "absent", tmp_path],
        "mixed": [file_path, tmp_path],
        "single": [tmp_path],
        "none": [],
    }[invalid_input]
    monkeypatch.setattr("sys.argv", ["pcompare", *(str(path) for path in paths)])

    with pytest.raises(SystemExit) as error:
        main()

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert captured.out == ""
    assert ("比较失败" if invalid_input != "none" else "用法：") in captured.err


def test_main_version_includes_release_date(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["pcompare", "--version"])
    monkeypatch.setattr("plum_tools.utils.parser.VERSION", "1.2.3")
    monkeypatch.setattr("plum_tools.utils.parser.RELEASE_DATE", "2030-01-02")

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 0
    assert "pcompare 版本: 1.2.3（2030-01-02）" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("path", "error"),
    [
        ("-bad:/path", "无效的远端路径"),
        ("host:", "无效的远端路径"),
        ("host:/a\x00b", "无效的远端路径"),
    ],
)
def test_split_remote_rejects_invalid_inputs(path: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        _split_remote(path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("host:/path", ("host", "/path")),
        ("user@host:/path", ("user@host", "/path")),
        ("[::1]:/path", ("::1", "/path")),
    ],
)
def test_split_remote_parses_valid_inputs(path: str, expected: tuple[str, str]) -> None:
    assert _split_remote(path) == expected


def test_split_remote_returns_none_for_local_path() -> None:
    assert _split_remote("/local/path") is None
    assert _split_remote("/local/path/with:colon") is None


def test_decode_remote_tree_rejects_non_dict() -> None:
    with pytest.raises(ValueError, match="缺少根条目"):
        _decode_remote_tree("[]")


def test_decode_remote_tree_rejects_missing_root() -> None:
    with pytest.raises(ValueError, match="缺少根条目"):
        _decode_remote_tree('{"sub": {}}')


def test_decode_remote_tree_rejects_absolute_path() -> None:
    payload = {".": _entry_dict(Path("."), "目录"), "/abs": _entry_dict(Path("."), "目录")}
    with pytest.raises(ValueError, match="无效的相对路径"):
        _decode_remote_tree(json.dumps(payload))


def test_decode_remote_tree_rejects_parent_traversal() -> None:
    payload = {".": _entry_dict(Path("."), "目录"), "../escape": _entry_dict(Path("."), "目录")}
    with pytest.raises(ValueError, match="无效的相对路径"):
        _decode_remote_tree(json.dumps(payload))


def test_decode_remote_tree_rejects_invalid_kind() -> None:
    payload = {".": _entry_dict(Path("."), "未知类型")}
    with pytest.raises(ValueError, match="无效的条目类型"):
        _decode_remote_tree(json.dumps(payload))


def test_decode_remote_tree_rejects_invalid_size() -> None:
    payload = {".": {"path": str(Path(".")), "kind": "文件", "size": -1, "target": "", "digest": None}}
    with pytest.raises(ValueError, match="无效的文件大小"):
        _decode_remote_tree(json.dumps(payload))


def test_decode_remote_tree_rejects_missing_digest_for_file() -> None:
    payload = {".": {"path": str(Path(".")), "kind": "文件", "size": 4, "target": "", "digest": None}}
    with pytest.raises(ValueError, match="缺少有效的 MD5 摘要"):
        _decode_remote_tree(json.dumps(payload))


def test_decode_remote_tree_rejects_invalid_digest() -> None:
    payload = {".": {"path": str(Path(".")), "kind": "文件", "size": 4, "target": "", "digest": "not-hex"}}
    with pytest.raises(ValueError, match="缺少有效的 MD5 摘要"):
        _decode_remote_tree(json.dumps(payload))


def test_decode_remote_tree_rejects_missing_parent() -> None:
    payload = {
        ".": _entry_dict(Path("."), "目录"),
        "child/grandchild": _entry_dict(Path("."), "目录"),
    }
    with pytest.raises(ValueError, match="缺少父目录条目"):
        _decode_remote_tree(json.dumps(payload))


def test_decode_remote_tree_parses_valid_payload() -> None:
    payload = {
        ".": _entry_dict(Path("."), "目录"),
        "file.txt": {
            "path": str(Path("/root") / "file.txt"),
            "kind": "文件",
            "size": 3,
            "target": "",
            "digest": "900150983cd24fb0d6963f7d28e17f72",
        },
        "link": {"path": str(Path("/root") / "link"), "kind": "链接", "size": 0, "target": "absent", "digest": None},
    }
    entries = _decode_remote_tree(json.dumps(payload))

    assert set(entries) == {Path("."), Path("file.txt"), Path("link")}
    assert entries[Path("file.txt")].digest == "900150983cd24fb0d6963f7d28e17f72"
    assert entries[Path("link")].target == "absent"


def test_scan_remote_raises_when_ssh_not_found(tmp_path: Path) -> None:
    with mock.patch("plum_tools.compare.shutil.which", return_value=None):
        with pytest.raises(OSError, match="找不到 ssh 命令"):
            _scan_remote("host", "/path")


def test_scan_remote_raises_on_ssh_failure(tmp_path: Path) -> None:
    complete = mock.Mock(return_code=1, stdout="", stderr="connection refused")
    with (
        mock.patch("plum_tools.compare.shutil.which", return_value="/usr/bin/ssh"),
        mock.patch("plum_tools.compare.subprocess.run", return_value=complete),
    ):
        with pytest.raises(OSError, match="远端读取失败"):
            _scan_remote("host", "/path")


def test_scan_remote_raises_on_invalid_output(tmp_path: Path) -> None:
    complete = mock.Mock(returncode=0, stdout="not-json", stderr="")
    with (
        mock.patch("plum_tools.compare.shutil.which", return_value="/usr/bin/ssh"),
        mock.patch("plum_tools.compare.subprocess.run", return_value=complete),
    ):
        with pytest.raises(ValueError, match="远端返回的文件清单无效"):
            _scan_remote("host", "/path")


def test_scan_remote_parses_valid_output(tmp_path: Path) -> None:
    payload = {
        ".": {"path": str(tmp_path), "kind": "目录", "size": 0, "target": "", "digest": None},
    }
    complete = mock.Mock(returncode=0, stdout=json.dumps(payload), stderr="")
    with (
        mock.patch("plum_tools.compare.shutil.which", return_value="/usr/bin/ssh"),
        mock.patch("plum_tools.compare.subprocess.run", return_value=complete) as run,
    ):
        entries = _scan_remote("host", "/path")
    assert Path(".") in entries
    assert run.call_count == 1


def test_load_trees_supports_remote_paths(tmp_path: Path) -> None:
    remote_payload = {
        ".": {"path": str(tmp_path), "kind": "目录", "size": 0, "target": "", "digest": None},
    }
    complete = mock.Mock(returncode=0, stdout=json.dumps(remote_payload), stderr="")
    with (
        mock.patch("plum_tools.compare.shutil.which", return_value="/usr/bin/ssh"),
        mock.patch("plum_tools.compare.subprocess.run", return_value=complete),
    ):
        trees = _load_trees(["host:/path", str(tmp_path)])
    assert len(trees) == 2
    assert Path(".") in trees[0]
    assert Path(".") in trees[1]


def _entry_dict(path: Path, kind: str) -> dict:
    digest = None
    size = 0
    if kind == "文件":
        size = 4
        digest = "900150983cd24fb0d6963f7d28e17f72"
    return {"path": str(path), "kind": kind, "size": size, "target": "", "digest": digest}

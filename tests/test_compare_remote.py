"""覆盖远端扫描共用逻辑：条目读取、MD5、排除规则、扫描及命令行入口。"""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import pytest

from plum_tools._compare_remote import Entry, exclusion_rules, file_md5, main, read_entry, scan


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a\x00b"])
def test_exclusion_rules_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError, match="排除名称必须是单个目录名或文件名"):
        exclusion_rules([name], [])


@pytest.mark.parametrize("path", ["", "/abs/path", "../escape", ".", "a\x00b"])
def test_exclusion_rules_rejects_invalid_paths(path: str) -> None:
    with pytest.raises(ValueError, match="排除路径必须是输入根目录内的相对路径"):
        exclusion_rules([], [path])


def test_exclusion_rules_returns_normalized_sets() -> None:
    names, paths = exclusion_rules(["node_modules", ".venv"], ["a/b", "c"])

    assert names == {"node_modules", ".venv"}
    assert paths == {Path("a/b"), Path("c")}


def test_read_entry_returns_directory_entry(tmp_path: Path) -> None:
    directory = tmp_path / "dir"
    directory.mkdir()

    entry = read_entry(directory)

    assert entry.path == directory
    assert entry.kind == "目录"
    assert entry.size == 0


def test_read_entry_returns_file_entry_with_size(tmp_path: Path) -> None:
    file_path = tmp_path / "file"
    file_path.write_bytes(b"data")

    entry = read_entry(file_path)

    assert entry.path == file_path
    assert entry.kind == "文件"
    assert entry.size == 4


def test_read_entry_returns_link_entry_with_target(tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to("absent")

    entry = read_entry(link)

    assert entry.kind == "链接"
    assert entry.target == "absent"


def test_read_entry_rejects_special_files(tmp_path: Path) -> None:
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)

    with pytest.raises(ValueError, match="不支持的文件类型"):
        read_entry(fifo)


def test_file_md5_returns_hex_digest(tmp_path: Path) -> None:
    file_path = tmp_path / "file"
    file_path.write_bytes(b"abc")

    entry = Entry(file_path, "文件", size=3)
    digest = file_md5(entry)

    assert len(digest) == 32
    assert digest == "900150983cd24fb0d6963f7d28e17f72"


def test_file_md5_reads_in_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "file"
    file_path.write_bytes(b"abcdefghij")

    monkeypatch.setattr("plum_tools._compare_remote.CHUNK_SIZE", 3)
    entry = Entry(file_path, "文件", size=10)

    assert file_md5(entry) == "a925576942e94b2ef57a066101b48876"


def test_file_md5_rejects_size_change_during_read(tmp_path: Path) -> None:
    file_path = tmp_path / "file"
    file_path.write_bytes(b"data")
    entry = Entry(file_path, "文件", size=4)
    before = SimpleNamespace(st_size=4, st_mtime_ns=1, st_ctime_ns=1)
    after = SimpleNamespace(st_size=5, st_mtime_ns=1, st_ctime_ns=1)

    with mock.patch("plum_tools._compare_remote.os.fstat", side_effect=[before, after]):
        with pytest.raises(OSError, match="比较期间文件发生变化"):
            file_md5(entry)


def test_scan_collects_nested_entries(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "sub" / "file.txt").write_bytes(b"data")
    (root / "sub" / "deep" / "inner.txt").write_bytes(b"inner")

    entries = scan(read_entry(root))

    assert set(entries) == {
        Path("."),
        Path("sub"),
        Path("sub/file.txt"),
        Path("sub/deep"),
        Path("sub/deep/inner.txt"),
    }
    assert entries[Path("sub/file.txt")].size == 4


def test_scan_excludes_by_name(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "node_modules" / "lib").mkdir(parents=True)
    (root / "node_modules" / "lib" / "file.txt").write_bytes(b"data")
    (root / "app.py").write_text("x", encoding="utf-8")

    entries = scan(read_entry(root), exclude_names=["node_modules"])

    assert Path("node_modules") not in entries
    assert Path("node_modules/lib") not in entries
    assert Path("app.py") in entries


def test_scan_excludes_by_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "file.txt").write_bytes(b"data")
    (root / "a" / "keep.py").write_text("x", encoding="utf-8")

    entries = scan(read_entry(root), exclude_paths=["a/b"])

    assert Path("a/b") not in entries
    assert Path("a/b/file.txt") not in entries
    assert Path("a/keep.py") in entries


def test_scan_computes_file_digests(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "file.txt").write_bytes(b"abc")

    entries = scan(read_entry(root), hash_files=True)

    assert entries[Path("file.txt")].digest == "900150983cd24fb0d6963f7d28e17f72"
    assert entries[Path(".")].digest is None


def test_scan_skips_hashing_for_directories_and_links(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "dir").mkdir()
    (root / "dir" / "file.txt").write_bytes(b"abc")
    link = root / "link"
    link.symlink_to("absent")

    entries = scan(read_entry(root), hash_files=True)

    assert entries[Path("dir")].digest is None
    assert entries[Path("link")].digest is None
    assert entries[Path("dir/file.txt")].digest == "900150983cd24fb0d6963f7d28e17f72"


def test_scan_does_not_follow_symlinked_directories(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "real").mkdir()
    (root / "real" / "file.txt").write_bytes(b"data")
    link = root / "link"
    link.symlink_to("real", target_is_directory=True)

    entries = scan(read_entry(root))

    assert entries[Path("link")].kind == "链接"
    assert entries[Path("link")].target == "real"
    assert Path("link/file.txt") not in entries


def test_main_prints_json_scan_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "file.txt").write_bytes(b"abc")
    monkeypatch.setattr("sys.argv", ["_compare_remote", str(root)])

    main()

    payload = json.loads(capsys.readouterr().out)
    assert Path(".") in [Path(key) for key in payload]
    assert payload[str(Path("."))]["kind"] == "目录"
    assert payload[str(Path("file.txt"))]["digest"] == "900150983cd24fb0d6963f7d28e17f72"


def test_main_accepts_exclusion_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    root = tmp_path / "root"
    (root / "skip").mkdir(parents=True)
    (root / "skip" / "file.txt").write_bytes(b"data")
    (root / "keep.txt").write_bytes(b"keep")
    monkeypatch.setattr(
        "sys.argv",
        ["_compare_remote", str(root), json.dumps({"exclude_names": ["skip"]})],
    )

    main()

    payload = json.loads(capsys.readouterr().out)
    assert "skip" not in payload
    assert "keep.txt" in payload


def test_main_exits_on_missing_path(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr("sys.argv", ["_compare_remote", "/nonexistent/path"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "远端扫描失败" in capsys.readouterr().err


def test_exclusion_regex_rejects_empty_pattern() -> None:
    """验证 _exclusion_regex 拒绝空的正则模式。"""
    from plum_tools._compare_remote import _exclusion_regex

    with pytest.raises(ValueError, match="无效的排除正则"):
        _exclusion_regex("re:")


def test_exclusion_regex_rejects_invalid_regex() -> None:
    """验证 _exclusion_regex 拒绝无效的正则表达式。"""
    from plum_tools._compare_remote import _exclusion_regex

    with pytest.raises(ValueError, match="无效的排除正则"):
        _exclusion_regex("re:[")


def test_path_glob_matches_single_star() -> None:
    """验证 _path_glob_matches 中 * 不跨目录匹配。"""
    from pathlib import Path

    from plum_tools._compare_remote import _path_glob_matches

    pattern = Path("src/*.py")
    # 应匹配
    assert _path_glob_matches(Path("src/main.py"), pattern) is True
    assert _path_glob_matches(Path("src/utils.py"), pattern) is True
    # 不应跨目录匹配
    assert _path_glob_matches(Path("src/lib/main.py"), pattern) is False


def test_path_glob_matches_double_star() -> None:
    """验证 _path_glob_matches 中 ** 可跨多层目录匹配。"""
    from pathlib import Path

    from plum_tools._compare_remote import _path_glob_matches

    pattern = Path("src/**/*.py")
    # 应匹配多层目录
    assert _path_glob_matches(Path("src/main.py"), pattern) is True
    assert _path_glob_matches(Path("src/lib/main.py"), pattern) is True
    assert _path_glob_matches(Path("src/lib/sub/main.py"), pattern) is True
    # 不应匹配其他顶层目录
    assert _path_glob_matches(Path("test/main.py"), pattern) is False


def test_path_glob_matches_complex_pattern() -> None:
    """验证 _path_glob_matches 处理复杂模式。"""
    from pathlib import Path

    from plum_tools._compare_remote import _path_glob_matches

    pattern = Path("**/test*/**")
    # 应匹配
    assert _path_glob_matches(Path("test/unit"), pattern) is True
    assert _path_glob_matches(Path("src/test/unit"), pattern) is True
    # 不应匹配
    assert _path_glob_matches(Path("src/unit"), pattern) is False


def test_scan_rejects_invalid_max_depth() -> None:
    """验证 scan 拒绝无效的 max_depth 参数。"""
    from plum_tools._compare_remote import read_entry

    root = Path("/tmp")
    # 布尔值不应被接受
    with pytest.raises(ValueError, match="比较深度必须是大于等于 1 的整数"):
        scan(read_entry(root), max_depth=True)
    # 非整数不应被接受
    with pytest.raises(ValueError, match="比较深度必须是大于等于 1 的整数"):
        scan(read_entry(root), max_depth=cast(Any, "2"))
    # 小于 1 不应被接受
    with pytest.raises(ValueError, match="比较深度必须是大于等于 1 的整数"):
        scan(read_entry(root), max_depth=0)


def test_main_raises_on_low_python_version(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """验证 main 在 Python 版本过低时抛出异常。"""
    monkeypatch.setattr("sys.argv", ["_compare_remote", "/tmp"])
    # 模拟 Python 3.8
    monkeypatch.setattr("sys.version_info", (3, 8, 0))

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "Python 3.9" in capsys.readouterr().err

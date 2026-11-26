"""覆盖 Python import 扫描的解析、过滤、进度、错误收集及命令行输出。"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest import mock

import pytest
from rich.console import Console
from rich.progress import Progress

from plum_tools.find_imports import (
    FindMode,
    ImportScanReport,
    ModuleDict,
    _collect_python_files,
    _map_modules,
    _print_results,
    calc_mode,
    find_imports,
    find_imports_by_file,
    main,
    parse_imports,
)


def test_calc_mode_returns_std_for_stdlib_module() -> None:
    assert calc_mode("sys") == FindMode.STD
    assert calc_mode("custom_module") == FindMode.THIRD_PARTY


def test_parse_imports_handles_import_and_from_statements() -> None:
    source = """
import os
import requests.sessions
from collections import deque
from urllib.parse import urlparse
from .local import helper
from ..parent import helper
from ...root import helper
"""

    modules = list(parse_imports(source))

    assert modules == [
        {"type": "import", "origin_name": "os", "name": "os", "mode": FindMode.STD},
        {
            "type": "import",
            "origin_name": "requests.sessions",
            "name": "requests",
            "mode": FindMode.THIRD_PARTY,
        },
        {
            "type": "from",
            "origin_name": "collections",
            "name": "collections",
            "mode": FindMode.STD,
        },
        {
            "type": "from",
            "origin_name": "urllib.parse",
            "name": "urllib",
            "mode": FindMode.STD,
        },
    ]


def test_find_imports_by_file_reads_python_source(tmp_path: Path) -> None:
    file_path = tmp_path / "demo.py"
    file_path.write_text("import rich\n", encoding="utf-8")

    modules = list(find_imports_by_file(str(file_path)))

    assert modules == [{"type": "import", "origin_name": "rich", "name": "rich", "mode": FindMode.THIRD_PARTY}]


def test_find_imports_filters_duplicates_ignored_paths_and_local_modules(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "plum_tools").mkdir()
    (project_dir / "a.py").write_text("import requests\nimport requests.adapters\n", encoding="utf-8")
    (project_dir / "ignored.py").write_text("import click\n", encoding="utf-8")
    (project_dir / "local.py").write_text("import plum_tools.helper\n", encoding="utf-8")
    (project_dir / "std.py").write_text("import os\n", encoding="utf-8")

    modules = list(find_imports(str(project_dir), ignore_paths=[str(project_dir / "ignored.py")]))

    assert sorted(modules, key=lambda item: item["name"]) == [
        {"type": "import", "origin_name": "os", "name": "os", "mode": FindMode.STD},
        {"type": "import", "origin_name": "requests", "name": "requests", "mode": FindMode.THIRD_PARTY},
    ]


def test_find_imports_exact_file_ignore_does_not_skip_same_named_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    left_dir = project_dir / "left"
    right_dir = project_dir / "right"
    left_dir.mkdir(parents=True)
    right_dir.mkdir()
    (left_dir / "ignored.py").write_text("import left_only\n", encoding="utf-8")
    (right_dir / "ignored.py").write_text("import right_only\n", encoding="utf-8")

    modules = list(find_imports(str(project_dir), ignore_paths=[str(left_dir / "ignored.py")]))

    assert modules == [
        {"type": "import", "origin_name": "right_only", "name": "right_only", "mode": FindMode.THIRD_PARTY}
    ]


def test_find_imports_ignores_default_virtualenv_directory(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    venv_dir = project_dir / ".venv" / "lib"
    venv_dir.mkdir(parents=True)
    (project_dir / "app.py").write_text("import requests\n", encoding="utf-8")
    (venv_dir / "demo.py").write_text("import venv_only_package\n", encoding="utf-8")

    modules = list(find_imports(str(project_dir)))

    assert modules == [{"type": "import", "origin_name": "requests", "name": "requests", "mode": FindMode.THIRD_PARTY}]


def test_find_imports_detects_local_modules_from_project_dir_when_cwd_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    project_dir = tmp_path / "project"
    package_dir = project_dir / "src" / "demo_pkg"
    cwd.mkdir()
    package_dir.mkdir(parents=True)
    (project_dir / "app.py").write_text("import demo_pkg.helper\nimport requests\n", encoding="utf-8")

    monkeypatch.chdir(cwd)

    modules = list(find_imports(str(project_dir)))

    assert modules == [{"type": "import", "origin_name": "requests", "name": "requests", "mode": FindMode.THIRD_PARTY}]


def test_find_imports_respects_mode_and_collects_parse_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    target_file = project_dir / "demo.py"
    target_file.write_text("import placeholder\n", encoding="utf-8")
    (project_dir / "valid.py").write_text("import sys\nimport requests\n", encoding="utf-8")
    report = ImportScanReport()

    def fake_find_imports_by_file(file_path: str) -> Iterator[ModuleDict]:
        if file_path.endswith("demo.py"):
            raise ValueError("boom")
        return parse_imports("import sys\nimport requests\n")

    with mock.patch("plum_tools.find_imports.find_imports_by_file", side_effect=fake_find_imports_by_file):
        modules = list(find_imports(str(project_dir), mode=FindMode.STD, report=report))

    captured = capsys.readouterr()
    assert modules == [{"type": "import", "origin_name": "sys", "name": "sys", "mode": FindMode.STD}]
    assert report.errors == [{"path": str(target_file), "reason": "boom"}]
    assert report.file_count == report.scanned_file_count == 2
    assert captured.out == captured.err == ""


def test_main_prints_extra_and_builtin_name_mapping(capsys: pytest.CaptureFixture[str]) -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock(
        project_dir=".",
        mode=FindMode.ALL,
        ignore_paths=["tests"],
        extra={"custom": "renamed"},
        json_output=False,
        sort=None,
    )
    mock_parser.parse_args.return_value = mock_args
    modules = [
        {"name": "custom", "origin_name": "custom", "type": "import", "mode": FindMode.THIRD_PARTY},
        {"name": "PIL", "origin_name": "PIL.Image", "type": "from", "mode": FindMode.THIRD_PARTY},
        {"name": "os", "origin_name": "os", "type": "import", "mode": FindMode.STD},
    ]

    with (
        mock.patch("plum_tools.find_imports.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.find_imports.add_extra_argument") as mock_add_extra_argument,
        mock.patch("plum_tools.find_imports.find_imports", return_value=modules) as mock_find_imports,
    ):
        main()

    mock_add_extra_argument.assert_called_once_with(mock_parser)
    progress = mock_find_imports.call_args.kwargs["progress"]
    assert isinstance(progress, Progress)
    mock_find_imports.assert_called_once_with(
        ".", mode=FindMode.ALL, ignore_paths=["tests"], report=ImportScanReport(), progress=progress
    )
    captured = capsys.readouterr()
    rows = [
        [cell.strip() for cell in line.split("│")[1:-1]] for line in captured.out.splitlines() if line.startswith("│")
    ]
    assert rows == [["PIL", "pillow", "第三方库"], ["custom", "renamed", "第三方库"], ["os", "os", "标准库"]]
    assert "导入模块" in captured.out
    assert "展示 3 个模块，错误 0 个" in captured.out
    assert captured.err == ""


def test_collect_python_files_skips_non_py_files(tmp_path: Path) -> None:
    report = ImportScanReport()
    (tmp_path / "demo.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

    files = _collect_python_files(tmp_path, [], report, None)

    assert [str(file) for file in files] == [str(tmp_path / "demo.py")]


def test_collect_python_files_records_walk_errors(tmp_path: Path) -> None:
    report = ImportScanReport()
    error = OSError(13, "Permission denied", str(tmp_path / "locked"))

    def walk_with_onerror(
        path: Path, onerror: Callable[[OSError], None] | None = None
    ) -> Iterator[tuple[str, list[str], list[str]]]:
        if onerror is not None:
            onerror(error)
        return iter([])

    with mock.patch("plum_tools.find_imports.os.walk", side_effect=walk_with_onerror):
        files = _collect_python_files(tmp_path, [], report, None)

    assert files == []
    assert report.errors == [{"path": str(tmp_path / "locked"), "reason": str(error)}]


def test_collect_python_files_updates_progress(tmp_path: Path) -> None:
    report = ImportScanReport()
    progress = mock.MagicMock()
    task = mock.MagicMock()
    progress.add_task.return_value = task
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import sys\n", encoding="utf-8")

    files = _collect_python_files(tmp_path, [], report, progress)

    progress.add_task.assert_called_once()
    progress.update.assert_called_with(task, total=2, completed=2, summary="文件 2 · 错误 0")
    progress.stop_task.assert_called_once_with(task)
    assert len(files) == 2


def test_collect_python_files_skips_ignore_paths(tmp_path: Path) -> None:
    report = ImportScanReport()
    target = tmp_path / "ignored.py"
    target.write_text("import os\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("import sys\n", encoding="utf-8")

    files = _collect_python_files(tmp_path, [str(target)], report, None)

    assert [str(file) for file in files] == [str(tmp_path / "kept.py")]


def test_collect_python_files_skips_scan_module_itself(tmp_path: Path) -> None:
    report = ImportScanReport()
    scan_file = Path(__file__).parent.parent / "src" / "plum_tools" / "find_imports.py"
    (tmp_path / "demo.py").write_text("import os\n", encoding="utf-8")

    files = _collect_python_files(tmp_path, [str(scan_file)], report, None)

    assert all(file.absolute() != scan_file for file in files)


def test_find_imports_appends_iterdir_error(tmp_path: Path) -> None:
    report = ImportScanReport()
    with mock.patch("plum_tools.find_imports.Path.iterdir", side_effect=OSError("denied")):
        modules = list(find_imports(str(tmp_path), report=report))
    assert modules == []
    assert report.errors == [{"path": str(tmp_path), "reason": "denied"}]


def test_find_imports_appends_src_iterdir_error(tmp_path: Path) -> None:
    report = ImportScanReport()
    (tmp_path / "src").mkdir()
    with mock.patch("plum_tools.find_imports.Path.iterdir", side_effect=[iter([]), OSError("denied")]):
        modules = list(find_imports(str(tmp_path), report=report))
    assert modules == []
    assert report.errors == [{"path": str(tmp_path / "src"), "reason": "denied"}]


def test_find_imports_updates_progress(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "a.py").write_text("import os\n", encoding="utf-8")
    report = ImportScanReport()
    progress = mock.MagicMock()
    discover_task = mock.MagicMock()
    parse_task = mock.MagicMock()
    progress.add_task.side_effect = [discover_task, parse_task]

    with mock.patch("plum_tools.find_imports.Progress") as progress_cls:
        progress_cls.return_value.__enter__.return_value = progress
        list(find_imports(str(project_dir), report=report, progress=progress))

    progress.add_task.assert_called_with("解析文件", total=1, summary="完成 0/1 · 错误 0")
    progress.update.assert_any_call(parse_task, advance=1, summary="完成 1/1 · 错误 0")


def test_map_modules_uses_builtin_pairs_and_extra() -> None:
    modules: list[ModuleDict] = [
        {"name": "PIL", "origin_name": "PIL", "type": "import", "mode": FindMode.THIRD_PARTY},
        {"name": "custom", "origin_name": "custom", "type": "import", "mode": FindMode.THIRD_PARTY},
        {"name": "os", "origin_name": "os", "type": "import", "mode": FindMode.STD},
    ]
    result = _map_modules(modules, {"custom": "renamed"})
    assert result == [
        {"name": "PIL", "origin_name": "PIL", "type": "import", "mode": FindMode.THIRD_PARTY, "package_name": "pillow"},
        {
            "name": "custom",
            "origin_name": "custom",
            "type": "import",
            "mode": FindMode.THIRD_PARTY,
            "package_name": "renamed",
        },
        {"name": "os", "origin_name": "os", "type": "import", "mode": FindMode.STD, "package_name": "os"},
    ]


def test_print_results_shows_error_table(capsys: pytest.CaptureFixture[str]) -> None:
    modules: list[dict[str, str]] = []
    report = ImportScanReport(scanned_file_count=2, file_count=3)
    report.errors = [{"path": "/bad.py", "reason": "boom"}]

    _print_results(Console(), modules, report)

    rendered = capsys.readouterr().out
    assert "扫描错误" in rendered
    assert "/bad.py" in rendered
    assert "boom" in rendered
    assert "扫描 2/3 个文件，展示 0 个模块，错误 1 个" in rendered


def test_print_results_omits_error_table_when_clean(capsys: pytest.CaptureFixture[str]) -> None:
    modules: list[dict[str, str]] = []
    report = ImportScanReport(scanned_file_count=1, file_count=1)

    _print_results(Console(), modules, report)

    rendered = capsys.readouterr().out
    assert "扫描错误" not in rendered
    assert "扫描 1/1 个文件，展示 0 个模块，错误 0 个" in rendered


def test_main_outputs_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock(
        project_dir=str(tmp_path),
        mode=FindMode.THIRD_PARTY,
        ignore_paths=None,
        extra={},
        json_output=True,
        sort=None,
    )
    mock_parser.parse_args.return_value = mock_args
    modules = [{"name": "requests", "origin_name": "requests", "type": "import", "mode": FindMode.THIRD_PARTY}]

    with (
        mock.patch("plum_tools.find_imports.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.find_imports.add_extra_argument"),
        mock.patch("plum_tools.find_imports.find_imports", return_value=modules),
    ):
        main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["project_dir"] == str(tmp_path.absolute())
    assert payload["mode"] == FindMode.THIRD_PARTY
    assert payload["summary"]["module_count"] == 1
    assert payload["modules"] == [
        {
            "name": "requests",
            "origin_name": "requests",
            "type": "import",
            "mode": FindMode.THIRD_PARTY,
            "package_name": "requests",
        }
    ]
    assert payload["errors"] == []


def test_print_results_compact_mode_with_modules(capsys: pytest.CaptureFixture[str]) -> None:
    """验证紧凑模式下按标准库/第三方库分组展示模块。"""
    from plum_tools.find_imports import _print_results

    modules = [
        {"name": "sys", "package_name": "sys", "mode": FindMode.STD},
        {"name": "os", "package_name": "os", "mode": FindMode.STD},
        {"name": "requests", "package_name": "requests", "mode": FindMode.THIRD_PARTY},
    ]
    report = ImportScanReport(scanned_file_count=3, file_count=3)

    _print_results(Console(), modules, report, compact=True)

    rendered = capsys.readouterr().out
    assert "导入模块" in rendered
    assert "标准库（2）" in rendered
    assert "第三方库（1）" in rendered
    assert "sys" in rendered
    assert "requests" in rendered


def test_print_results_compact_mode_shows_package_mapping(capsys: pytest.CaptureFixture[str]) -> None:
    """验证紧凑模式下显示导入名到包名的映射。"""
    from plum_tools.find_imports import _print_results

    modules = [{"name": "bs4", "package_name": "beautifulsoup4", "mode": FindMode.THIRD_PARTY}]
    report = ImportScanReport(scanned_file_count=1, file_count=1)

    _print_results(Console(), modules, report, compact=True)

    rendered = capsys.readouterr().out
    assert "bs4→beautifulsoup4" in rendered


def test_print_results_compact_mode_with_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """验证紧凑模式下错误表格使用紧凑样式。"""
    from plum_tools.find_imports import _print_results

    modules: list[dict[str, str]] = []
    report = ImportScanReport(
        scanned_file_count=1,
        file_count=2,
        errors=[{"path": "/bad.py", "reason": "语法错误"}],
    )

    _print_results(Console(), modules, report, compact=True)

    rendered = capsys.readouterr().out
    assert "扫描错误" in rendered
    assert "/bad.py" in rendered
    assert "语法错误" in rendered
    assert "扫描 1/2 个文件，展示 0 个模块，错误 1 个" in rendered

from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from plum_tools.find_imports import FindMode, calc_mode, find_imports, find_imports_by_file, main, parse_imports


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


def test_find_imports_respects_mode_and_prints_parse_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    target_file = project_dir / "demo.py"
    target_file.write_text("import placeholder\n", encoding="utf-8")

    def fake_find_imports_by_file(file_path: str) -> Iterator[dict[str, object]]:
        if file_path.endswith("demo.py"):
            raise ValueError("boom")
        return iter(())

    with mock.patch("plum_tools.find_imports.find_imports_by_file", side_effect=fake_find_imports_by_file):
        modules = list(find_imports(str(project_dir), mode=FindMode.STD))

    captured = capsys.readouterr()
    assert modules == []
    assert f"Error parsing {target_file}: boom" in captured.out


def test_main_prints_extra_and_builtin_name_mapping() -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock(project_dir=".", mode=FindMode.ALL, ignore_paths=["tests"], extra={"custom": "renamed"})
    mock_parser.parse_args.return_value = mock_args
    modules = [
        {"name": "custom", "mode": FindMode.THIRD_PARTY},
        {"name": "PIL", "mode": FindMode.THIRD_PARTY},
        {"name": "os", "mode": FindMode.STD},
    ]

    with (
        mock.patch("plum_tools.find_imports.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.find_imports.add_extra_argument") as mock_add_extra_argument,
        mock.patch("plum_tools.find_imports.find_imports", return_value=modules) as mock_find_imports,
        mock.patch("builtins.print") as mock_print,
    ):
        main()

    mock_add_extra_argument.assert_called_once_with(mock_parser)
    mock_find_imports.assert_called_once_with(".", mode=FindMode.ALL, ignore_paths=["tests"])
    mock_print.assert_has_calls([mock.call("pillow"), mock.call("renamed"), mock.call("os")])

"""验证 pfind_imports 的相关行为。"""

import json
from pathlib import Path
from unittest import mock

import pytest
from rich.progress import Progress

from plum_tools._find_imports.scanner import (
    FindMode,
    ImportScanReport,
)
from plum_tools.cli.pfind_imports import main


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
        mock.patch("plum_tools.cli.pfind_imports.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.cli.pfind_imports.add_extra_argument") as mock_add_extra_argument,
        mock.patch("plum_tools.cli.pfind_imports.find_imports", return_value=modules) as mock_find_imports,
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
        mock.patch("plum_tools.cli.pfind_imports.get_base_parser", return_value=mock_parser),
        mock.patch("plum_tools.cli.pfind_imports.add_extra_argument"),
        mock.patch("plum_tools.cli.pfind_imports.find_imports", return_value=modules),
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

"""验证 reporting 的相关行为。"""

import pytest
from rich.console import Console

from plum_tools._find_imports.reporting import _map_modules, _print_results
from plum_tools._find_imports.scanner import (
    FindMode,
    ImportScanReport,
    ModuleDict,
)


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


def test_print_results_compact_mode_with_modules(capsys: pytest.CaptureFixture[str]) -> None:
    """验证紧凑模式下按标准库/第三方库分组展示模块。"""
    from plum_tools._find_imports.reporting import _print_results

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
    from plum_tools._find_imports.reporting import _print_results

    modules = [{"name": "bs4", "package_name": "beautifulsoup4", "mode": FindMode.THIRD_PARTY}]
    report = ImportScanReport(scanned_file_count=1, file_count=1)

    _print_results(Console(), modules, report, compact=True)

    rendered = capsys.readouterr().out
    assert "bs4→beautifulsoup4" in rendered


def test_print_results_compact_mode_with_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """验证紧凑模式下错误表格使用紧凑样式。"""
    from plum_tools._find_imports.reporting import _print_results

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

"""pytest 共享夹具，保证依赖终端宽度的展示测试输出稳定。"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)  # noqa
def _stable_terminal_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定终端宽度，避免环境 COLUMNS 落在 rich 折叠区间导致渲染输出不稳定。"""
    monkeypatch.setenv("COLUMNS", "200")


@pytest.fixture
def repository_roots(tmp_path: Path) -> tuple[Path, Path]:
    """在临时路径创建覆盖四种状态和两种目录结构的目标，返回两个根目录。"""
    first = tmp_path / "python projects"
    second = tmp_path / "web"
    for directory in (first / "alice/both", second / "upstream/base-both", first / "fork", second / "base-parent"):
        directory.mkdir(parents=True)
    return first, second

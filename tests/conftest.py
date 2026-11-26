"""pytest 共享夹具，保证依赖终端宽度的展示测试输出稳定。"""

import pytest


@pytest.fixture(autouse=True)  # noqa
def _stable_terminal_width(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定终端宽度，避免环境 COLUMNS 落在 rich 折叠区间导致渲染输出不稳定。"""
    monkeypatch.setenv("COLUMNS", "200")

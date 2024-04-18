# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_printer
#         Desc: 测试颜色打印
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 20:03
#=============================================================================
"""

from typing import Any

import pytest
from plum_tools.utils.printer import (
    get_color,
    get_green,
    get_red,
    get_yellow,
    print_error,
    print_ok,
    print_text,
    print_warn,
)


@pytest.mark.parametrize(
    "c, s",
    [
        (1, 1),
        (2, 2.02),
        (3, None),
        (4, ""),
        (5, "1"),
        (6, "测试"),
    ],
)
def test_color(c: int, s: Any) -> None:
    assert get_color(c, s) == f"\033[3{c}m{s}\033[0m"


@pytest.mark.parametrize(
    "s",
    [
        1,
        2.02,
        None,
        "",
        "1",
        "测试",
    ],
)
def test_get_red(s: Any) -> None:
    assert get_red(s) == f"\033[3{1}m{s}\033[0m"


@pytest.mark.parametrize(
    "s",
    [
        1,
        2.02,
        None,
        "",
        "1",
        "测试",
    ],
)
def test_get_green(s: Any) -> None:
    assert get_green(s) == f"\033[3{2}m{s}\033[0m"


@pytest.mark.parametrize(
    "s",
    [
        1,
        2.02,
        None,
        "",
        "1",
        "测试",
    ],
)
def test_get_yellow(s: Any) -> None:
    assert get_yellow(s) == f"\033[3{3}m{s}\033[0m"


@pytest.mark.parametrize(
    "s",
    [
        1,
        2.02,
        None,
        "",
        "1",
        "测试",
    ],
)
def test_print_text(s: Any, capsys: pytest.CaptureFixture) -> None:
    print_text(s)
    captured = capsys.readouterr()
    assert captured.out == f"{s}\n"


@pytest.mark.parametrize(
    "s",
    [
        1,
        2.02,
        None,
        "",
        "1",
        "测试",
    ],
)
def test_print_ok(s: Any, capsys: pytest.CaptureFixture) -> None:
    print_ok(s)
    captured = capsys.readouterr()
    assert captured.out == f"\033[3{2}m{s}\033[0m\n"


@pytest.mark.parametrize(
    "s",
    [
        1,
        2.02,
        None,
        "",
        "1",
        "测试",
    ],
)
def test_print_warn(s: Any, capsys: pytest.CaptureFixture) -> None:
    print_warn(s)
    captured = capsys.readouterr()
    assert captured.out == f"\033[3{3}m{s}\033[0m\n"


@pytest.mark.parametrize(
    "s",
    [
        1,
        2.02,
        None,
        "",
        "1",
        "测试",
    ],
)
def test_pprint_error(s: Any, capsys: pytest.CaptureFixture) -> None:
    print_error(s)
    captured = capsys.readouterr()
    assert captured.out == f"\033[3{1}m{s}\033[0m\n"

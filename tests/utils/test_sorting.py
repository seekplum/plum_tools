"""验证统一排序参数及稳定多字段排序。"""

import pytest

from plum_tools.utils.parser import get_base_parser
from plum_tools.utils.sorting import SortField, add_sort_argument, sort_items


def test_sort_defaults_to_descending_and_accepts_repeated_options() -> None:
    """省略方向默认降序，重复选项按出现顺序追加优先级。"""
    parser = get_base_parser()
    add_sort_argument(parser, {"count": "次数", "name": "名称", "time": "时间"})
    args = parser.parse_args(["--sort", "count,name:asc", "--sort", "time:desc"])
    assert args.sort == [SortField("count"), SortField("name", False), SortField("time")]
    assert parser.parse_args([]).sort is None


@pytest.mark.parametrize("value", ["", "count,", "missing", "count:up", "count:asc:desc", "count,count:asc"])
def test_sort_rejects_invalid_fields_and_directions(value: str, capsys: pytest.CaptureFixture[str]) -> None:
    """无效排序在解析参数时退出，并给出可用字段。"""
    parser = get_base_parser()
    add_sort_argument(parser, {"count": "次数"})
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["--sort", value])
    assert error.value.code == 2
    assert "count" in capsys.readouterr().err


def test_sort_rejects_duplicate_fields_across_options() -> None:
    """重复参数不能重新定义同一字段的方向。"""
    parser = get_base_parser()
    add_sort_argument(parser, {"count": "次数"})
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["--sort", "count", "--sort", "count:asc"])
    assert error.value.code == 2


@pytest.mark.parametrize("descending", [False, True])
def test_sort_numeric_values_keeps_missing_last(descending: bool) -> None:
    """数字按值排序，未知值与空文本在两个方向下都排最后。"""
    rows = [{"count": value} for value in (None, 2, 10, 0, "")]
    expected = [10, 2, 0, None, ""] if descending else [0, 2, 10, None, ""]
    result = sort_items(rows, [SortField("count", descending)], {"count": lambda row: row["count"]})
    assert [row["count"] for row in result] == expected
    assert rows[0]["count"] is None


def test_multifield_sort_is_stable_and_does_not_mutate_input() -> None:
    """主字段降序、次字段升序，相同键保持输入顺序。"""
    rows = [(2, "b", 0), (10, "c", 1), (2, "a", 2), (2, "a", 3)]
    keys = {"count": lambda row: row[0], "name": lambda row: row[1]}
    assert sort_items(rows, [SortField("count"), SortField("name", False)], keys) == [
        rows[1],
        rows[2],
        rows[3],
        rows[0],
    ]
    assert sort_items(rows, None, keys) == rows
    assert rows[0] == (2, "b", 0)

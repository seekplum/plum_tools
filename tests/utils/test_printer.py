"""测试 printer 模块的紧凑模式表格和分栏打印功能。"""

from unittest import mock

from rich.console import Console
from rich.table import Table
from rich.text import Text

from plum_tools.utils.printer import compact_table, print_columns


def test_compact_table_applies_compact_style() -> None:
    """验证 compact_table 将表格调整为紧凑样式。"""
    table = Table()

    compact_table(table)

    assert table.box is None
    assert table.pad_edge is False
    assert table.collapse_padding is True
    assert table.padding == (0, 1, 0, 1)
    assert table.expand is True


def test_print_columns_calls_console_print_with_columns() -> None:
    """验证 print_columns 正确调用 Console.print 并传递 Columns 对象。"""
    mock_console = mock.MagicMock(spec=Console)
    items = [Text("item1"), Text("item2")]

    print_columns(mock_console, items)

    mock_console.print.assert_called_once()
    call_args = mock_console.print.call_args[0]
    columns = call_args[0]
    assert columns.renderables == items
    assert columns.padding == (0, 2)
    assert columns.equal is True
    assert columns.expand is True

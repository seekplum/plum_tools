"""验证 reporting 的相关行为。"""

from io import StringIO
from pathlib import Path
from unittest import mock

from rich.console import Console

from plum_tools._fork_check.reporting import _print_results
from plum_tools._fork_check.repositories import (
    RepoRow,
)


def test_print_results_preserves_literal_markup_and_long_repository_names() -> None:
    output = StringIO()
    console = Console(file=output, width=65)
    fork = "[bold]/" + "long-fork-name" * 3
    parent = "[red]/" + "long-parent-name" * 3
    row = RepoRow(1, fork, parent, ("T1",), ())
    with mock.patch("plum_tools._fork_check.reporting.Console", return_value=console) as console_factory:
        _print_results([row], {"T1": Path("/projects")}, set(), 0, from_file=False)

    console_factory.assert_called_once_with()
    table_rows = [line.split("│") for line in output.getvalue().splitlines() if line.startswith("│")]
    assert "".join(cells[3].strip() for cells in table_rows).split("存在：", 1)[0] == fork
    assert "".join(cells[4].strip() for cells in table_rows).split("未找到", 1)[0] == parent

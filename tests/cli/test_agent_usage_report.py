"""验证 agent_usage_report 的相关行为。"""

from __future__ import annotations

from unittest import mock

# ---------- agent_usage_report.py 入口 ----------


def test_agent_usage_report_main_dispatches() -> None:
    # fmt: off
    with (
        mock.patch("plum_tools.cli.agent_usage_report.report_main", return_value=0) as mock_report,
    ):
        # fmt: on
        from plum_tools.cli.agent_usage_report import main as report_main

        code = report_main()
    assert code == 0
    mock_report.assert_called_once()

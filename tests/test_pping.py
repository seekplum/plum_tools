# -*- coding: utf-8 -*-

"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_pping
#         Desc: 测试pping模块
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 23:44
#=============================================================================
"""

import mock

from plum_tools.pping import main
from plum_tools.pping import ping


def test_ping():
    with mock.patch("plum_tools.pping.run_cmd") as mock_run_cmd:
        ip = ping("2.2.2.2")
    assert ip == "2.2.2.2"
    mock_run_cmd.assert_called_once_with("ping -W 3 -c 1 2.2.2.2")


def test_ping_with_cmd_error():
    ip = ping("1.1.1.999")
    assert ip is None


def test_main():
    mock_parser = mock.Mock()
    mock_args = mock.Mock(type="1", prefix_host="1.1.1")
    mock_parser.parse_args.return_value = mock_args
    with mock.patch(
        "plum_tools.pping.argparse.ArgumentParser", return_value=mock_parser
    ) as mock_argparse, mock.patch("plum_tools.pping.run") as mock_run:
        main()
        mock_argparse.assert_called_once_with()
        mock_parser.add_argument.assert_has_calls(
            [
                mock.call(
                    "-t",
                    "--type",
                    action="store",
                    required=False,
                    dest="type",
                    default="default",
                    help="host type",
                ),
                mock.call(
                    "-p",
                    "--prefix-host",
                    action="store",
                    required=False,
                    dest="prefix_host",
                    default=None,
                    help="host prefix",
                ),
            ]
        )
        mock_parser.parse_args.assert_called_once_with()
        mock_run.assert_called_once_with("1", "1.1.1")

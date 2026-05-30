"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_pssh
#         Desc: 测试pssh模块
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 23:44
#=============================================================================
"""

from typing import TypedDict
from unittest import mock

from plum_tools.conf import SSHConfig
from plum_tools.pssh import get_login_ssh_cmd, login, main


class SSHConfDict(TypedDict):
    hostname: str
    user: str
    port: int
    identityfile: str


def test_get_login_ssh_cmd_builds_expected_command() -> None:
    cmd = get_login_ssh_cmd("10.0.0.1", "root", 2222, "~/.ssh/id_rsa")

    assert cmd == (
        "ssh  -i ~/.ssh/id_rsa "
        '-o "UserKnownHostsFile=/dev/null" '
        '-o "StrictHostKeyChecking no" '
        f'-o  "ConnectTimeout={SSHConfig.CONNECT_TIMEOUT}" '
        "root@10.0.0.1 -p 2222"
    )


def test_login_merges_ssh_config_and_executes_command() -> None:
    ssh_conf: SSHConfDict = {
        "hostname": "10.0.0.1",
        "user": "root",
        "port": 22,
        "identityfile": "~/.ssh/id_rsa",
    }

    with (
        mock.patch("plum_tools.pssh.merge_ssh_config", return_value=ssh_conf) as mock_merge_ssh_config,
        mock.patch("plum_tools.pssh.os.system") as mock_system,
    ):
        login("host1", "default", "", 0, "")

    mock_merge_ssh_config.assert_called_once_with("host1", "default", "", 0, "")
    mock_system.assert_called_once_with(get_login_ssh_cmd(**ssh_conf))


def test_main() -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock(host="dev", type="default", identityfile="", user="", port=0)
    mock_parser.parse_args.return_value = mock_args
    with (
        mock.patch("plum_tools.pssh.get_base_parser", return_value=mock_parser) as mock_argparse,
        mock.patch("plum_tools.pssh.login") as mock_login,
    ):
        main()
        mock_argparse.assert_called_once_with()
        mock_parser.add_argument.assert_has_calls(
            [
                mock.call(dest="host", action="store", help="specify server"),
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
                    "-i",
                    "--identityfile",
                    action="store",
                    required=False,
                    dest="identityfile",
                    default="",
                    help="ssh login identityfile path",
                ),
                mock.call(
                    "-u",
                    "--username",
                    action="store",
                    required=False,
                    dest="user",
                    default="",
                    help="ssh login username",
                ),
                mock.call(
                    "-p",
                    "--port",
                    action="store",
                    required=False,
                    dest="port",
                    type=int,
                    default=0,
                    help="ssh login port",
                ),
            ]
        )
        mock_parser.parse_args.assert_called_once_with()
        mock_login.assert_called_once_with("dev", mock_args.type, "", 0, "")

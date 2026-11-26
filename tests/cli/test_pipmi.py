"""验证 pipmi 的相关行为。"""

from collections.abc import Generator
from contextlib import contextmanager
from unittest import mock

import pytest

from plum_tools.cli.pipmi import get_args, main
from plum_tools.utils.constants import COMMAND_TIMEOUT
from plum_tools.utils.exceptions import RunCmdError, SSHException


def test_get_args_registers_expected_cli_options() -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock()
    mock_parser.parse_args.return_value = mock_args

    with mock.patch("plum_tools.cli.pipmi.get_base_parser", return_value=mock_parser) as mock_get_base_parser:
        assert get_args() is mock_args

    mock_get_base_parser.assert_called_once_with()
    mock_parser.add_argument.assert_has_calls(
        [
            mock.call("-l", "--login", required=True, action="store", dest="host", help="跳板机 IP 或 IP 简写，必填"),
            mock.call(
                "-s",
                "--servers",
                required=True,
                action="store",
                dest="servers",
                nargs="+",
                help="目标服务器 IP 或 IP 简写，必填，可指定多个；IPMI 地址按配置偏移计算",
            ),
            mock.call(
                "-u",
                "--username",
                required=False,
                action="store",
                dest="user",
                default="root",
                help="SSH 登录用户名，默认 root",
            ),
            mock.call(
                "-pass",
                "--password",
                required=False,
                action="store",
                dest="password",
                default="",
                help="SSH 登录密码，默认为空，使用私钥认证",
            ),
            mock.call(
                "-p",
                "--port",
                action="store",
                required=False,
                dest="port",
                type=int,
                default=0,
                help="SSH 登录端口，默认读取 SSH 配置",
            ),
            mock.call(
                "-i",
                "--identityfile",
                action="store",
                required=False,
                dest="identityfile",
                default="",
                help="SSH 私钥路径，默认读取 SSH 配置",
            ),
            mock.call(
                "-t",
                "--type",
                action="store",
                required=False,
                dest="type",
                default="default",
                help="主机类型，默认 default；可选值由配置中的 host_type_<类型> 决定",
            ),
            mock.call(
                "-U",
                "--Username",
                required=False,
                action="store",
                dest="Username",
                default="ADMIN",
                help="IPMI 登录用户名，默认 ADMIN",
            ),
            mock.call(
                "-c",
                "--command",
                required=False,
                action="store",
                dest="command",
                default="power on",
                help="IPMI 命令，默认 'power on'；例如 'power status'、'power off'，支持 ipmitool 子命令",
            ),
            mock.call(
                "-P",
                "--Password",
                required=False,
                action="store",
                dest="Password",
                default="12345678",
                help="IPMI 登录密码，默认 12345678",
            ),
        ]
    )
    mock_parser.parse_args.assert_called_once_with()


@contextmanager
def _mock_ssh_context(ssh_client: mock.Mock) -> Generator[mock.Mock, None, None]:
    yield ssh_client


def test_main_runs_commands_for_each_server() -> None:
    args = mock.Mock()
    parser = mock.Mock()
    parser.parser_ssh_conf.return_value = {"hostname": "10.0.0.1"}
    parser.parser_ip_list.return_value = ["2", "3"]
    parser.parser_ipmi_auth.side_effect = [
        {"ip": "10.0.0.2", "user": "ADMIN", "password": "123", "command": "power on"},
        {"ip": "10.0.0.3", "user": "ADMIN", "password": "123", "command": "power on"},
    ]
    ssh_client = mock.Mock()
    ssh_client.run_cmd.side_effect = ["ok-1", "ok-2"]

    with (
        mock.patch("plum_tools.cli.pipmi.get_args", return_value=args),
        mock.patch("plum_tools.cli.pipmi.Parser", return_value=parser),
        mock.patch("plum_tools.cli.pipmi.get_ssh", return_value=_mock_ssh_context(ssh_client)) as mock_get_ssh,
        mock.patch("plum_tools.cli.pipmi.print_text") as mock_print_text,
    ):
        main()

    mock_get_ssh.assert_called_once_with(**parser.parser_ssh_conf.return_value)
    assert ssh_client.run_cmd.call_count == 2
    ssh_client.run_cmd.assert_has_calls(
        [
            mock.call("ipmitool -I lanplus -H 10.0.0.2 -U ADMIN -P 123 power on", timeout=COMMAND_TIMEOUT),
            mock.call("ipmitool -I lanplus -H 10.0.0.3 -U ADMIN -P 123 power on", timeout=COMMAND_TIMEOUT),
        ]
    )
    mock_print_text.assert_has_calls(
        [
            mock.call("命令：ipmitool -I lanplus -H 10.0.0.2 -U ADMIN -P 123 power on"),
            mock.call("输出：ok-1\n"),
            mock.call("命令：ipmitool -I lanplus -H 10.0.0.3 -U ADMIN -P 123 power on"),
            mock.call("输出：ok-2\n"),
        ]
    )


def test_main_handles_command_timeout_and_run_cmd_error() -> None:
    args = mock.Mock()
    parser = mock.Mock()
    parser.parser_ssh_conf.return_value = {"hostname": "10.0.0.1"}
    parser.parser_ip_list.return_value = ["2", "3"]
    parser.parser_ipmi_auth.side_effect = [
        {"ip": "10.0.0.2", "user": "ADMIN", "password": "123", "command": "power on"},
        {"ip": "10.0.0.3", "user": "ADMIN", "password": "123", "command": "power on"},
    ]
    ssh_client = mock.Mock()
    ssh_client.run_cmd.side_effect = [TimeoutError(), RunCmdError("fail", "", "stderr")]

    with (
        mock.patch("plum_tools.cli.pipmi.get_args", return_value=args),
        mock.patch("plum_tools.cli.pipmi.Parser", return_value=parser),
        mock.patch("plum_tools.cli.pipmi.get_ssh", return_value=_mock_ssh_context(ssh_client)),
        mock.patch("plum_tools.cli.pipmi.print_text"),
        mock.patch("plum_tools.cli.pipmi.print_error") as mock_print_error,
    ):
        main()

    mock_print_error.assert_has_calls(
        [
            mock.call("执行命令: ipmitool -I lanplus -H 10.0.0.2 -U ADMIN -P 123 power on 超时，超时时间为: 3秒"),
            mock.call("stderr"),
        ]
    )


def test_main_exits_when_ssh_connection_fails() -> None:
    args = mock.Mock()
    parser = mock.Mock()
    parser.parser_ssh_conf.return_value = {"hostname": "10.0.0.1"}

    with (
        mock.patch("plum_tools.cli.pipmi.get_args", return_value=args),
        mock.patch("plum_tools.cli.pipmi.Parser", return_value=parser),
        mock.patch("plum_tools.cli.pipmi.get_ssh", side_effect=SSHException("connect fail")),
        mock.patch("plum_tools.cli.pipmi.print_error") as mock_print_error,
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with("connect fail")


def test_main_compact_mode_with_multiline_output() -> None:
    """验证紧凑模式下多行输出使用换行分隔符。"""
    args = mock.Mock(compact=True)
    parser = mock.Mock()
    parser.parser_ssh_conf.return_value = {"hostname": "10.0.0.1"}
    parser.parser_ip_list.return_value = ["1"]
    parser.parser_ipmi_auth.return_value = {
        "ip": "10.0.0.1",
        "user": "ADMIN",
        "password": "123",
        "command": "power status",
    }
    ssh_client = mock.Mock()
    ssh_client.run_cmd.return_value = "line1\r\nline2\r\n"

    with (
        mock.patch("plum_tools.cli.pipmi.get_args", return_value=args),
        mock.patch("plum_tools.cli.pipmi.Parser", return_value=parser),
        mock.patch("plum_tools.cli.pipmi.get_ssh", return_value=_mock_ssh_context(ssh_client)),
        mock.patch("plum_tools.cli.pipmi.print_text") as mock_print_text,
        mock.patch("plum_tools.cli.pipmi.print_error"),
    ):
        main()

    # rstrip 移除末尾的 \r\n，但中间的 \r\n 保留，分隔符使用 \n
    mock_print_text.assert_called_once_with("[10.0.0.1] power status：\nline1\r\nline2")


def test_main_compact_mode_with_single_line_output() -> None:
    """验证紧凑模式下单行输出使用空格分隔符。"""
    args = mock.Mock(compact=True)
    parser = mock.Mock()
    parser.parser_ssh_conf.return_value = {"hostname": "10.0.0.1"}
    parser.parser_ip_list.return_value = ["1"]
    parser.parser_ipmi_auth.return_value = {
        "ip": "10.0.0.1",
        "user": "ADMIN",
        "password": "123",
        "command": "power status",
    }
    ssh_client = mock.Mock()
    ssh_client.run_cmd.return_value = "ok\r\n"

    with (
        mock.patch("plum_tools.cli.pipmi.get_args", return_value=args),
        mock.patch("plum_tools.cli.pipmi.Parser", return_value=parser),
        mock.patch("plum_tools.cli.pipmi.get_ssh", return_value=_mock_ssh_context(ssh_client)),
        mock.patch("plum_tools.cli.pipmi.print_text") as mock_print_text,
        mock.patch("plum_tools.cli.pipmi.print_error"),
    ):
        main()

    # 应使用空格作为分隔符
    mock_print_text.assert_called_once_with("[10.0.0.1] power status： ok")

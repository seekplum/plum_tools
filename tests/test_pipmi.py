"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: test_pipmi
#         Desc: 测试pipmi模块
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2019-04-04 23:43
#=============================================================================
"""

import re
from collections.abc import Generator
from contextlib import contextmanager
from unittest import mock

import paramiko
import pytest

from plum_tools.conf import COMMAND_TIMEOUT, PathConfig
from plum_tools.exceptions import RunCmdError, SSHException
from plum_tools.pipmi import Parser, PSSHClient, SSHTool, get_args, get_ipmi_ip, get_ssh, get_ssh_config, main


def test_pssh_client_run_cmd_returns_stdout() -> None:
    client = PSSHClient("10.0.0.1")
    stdin = mock.Mock()
    stdout = mock.Mock()
    stderr = mock.Mock()
    stdout.read.return_value = b"done"
    stderr.read.return_value = b""

    with mock.patch.object(client, "exec_command", return_value=(stdin, stdout, stderr)) as mock_exec_command:
        assert client.run_cmd("hostname") == "done"

    mock_exec_command.assert_called_once_with("hostname")
    stdin.close.assert_called_once_with()
    stdout.flush.assert_called_once_with()


def test_pssh_client_run_cmd_raises_on_stderr() -> None:
    client = PSSHClient("10.0.0.1")
    stdin = mock.Mock()
    stdout = mock.Mock()
    stderr = mock.Mock()
    stdout.read.return_value = b"partial"
    stderr.read.return_value = b"boom"

    with mock.patch.object(client, "exec_command", return_value=(stdin, stdout, stderr)):
        with pytest.raises(RunCmdError, match="run cmd `hostname` fail") as exc_info:
            client.run_cmd("hostname")

    assert exc_info.value.out_msg == "partial"
    assert exc_info.value.err_msg == "boom"


def test_ssh_tool_get_ssh_connects_with_expected_args() -> None:
    ssh_client = mock.Mock()
    tool = SSHTool("10.0.0.1", "root", 22, password="secret", identityfile="~/.ssh/id_rsa")

    with (
        mock.patch("plum_tools.pipmi.PSSHClient", return_value=ssh_client) as mock_client,
        mock.patch("plum_tools.pipmi.paramiko.AutoAddPolicy", return_value="policy") as mock_policy,
    ):
        result = tool.get_ssh()

    assert result is ssh_client
    mock_client.assert_called_once_with(host="10.0.0.1")
    mock_policy.assert_called_once_with()
    ssh_client.set_missing_host_key_policy.assert_called_once_with("policy")
    ssh_client.connect.assert_called_once_with(
        hostname="10.0.0.1",
        username="root",
        password="secret",
        key_filename="~/.ssh/id_rsa",
        port=22,
        timeout=3,
    )


@pytest.mark.parametrize(
    ("side_effect", "message"),
    [
        (TimeoutError(), "连接超时(root@10.0.0.1:22).请检查用户名,IP地址,端口号是否正确"),
        (
            paramiko.ssh_exception.NoValidConnectionsError(errors={("10.0.0.1", 22): OSError("boom")}),
            "连接出现异常(root@10.0.0.1:22).请检查端口或IP地址是否正确",
        ),
        (
            paramiko.ssh_exception.AuthenticationException("bad auth"),
            "连接出现异常(root@10.0.0.1:22).请检查密码或密钥是否正确",
        ),
        (RuntimeError("boom"), "连接出现异常(root@10.0.0.1:22) boom."),
    ],
)
def test_ssh_tool_get_ssh_maps_exceptions(side_effect: Exception, message: str) -> None:
    tool = SSHTool("10.0.0.1", "root", 22)
    ssh_client = mock.Mock()
    ssh_client.connect.side_effect = side_effect

    with mock.patch("plum_tools.pipmi.PSSHClient", return_value=ssh_client):
        with pytest.raises(SSHException, match=re.escape(message)):
            tool.get_ssh()


def test_get_ssh_context_manager_expands_identityfile_and_closes_client() -> None:
    ssh_client = mock.Mock()

    with (
        mock.patch("plum_tools.pipmi.get_file_abspath", return_value="/tmp/id_rsa") as mock_get_file_abspath,
        mock.patch.object(SSHTool, "get_ssh", return_value=ssh_client) as mock_get_ssh,
    ):
        with get_ssh("10.0.0.1", "root", 22, identityfile="~/.ssh/id_rsa") as ssh:
            assert ssh is ssh_client

    mock_get_file_abspath.assert_called_once_with("~/.ssh/id_rsa")
    mock_get_ssh.assert_called_once_with()
    ssh_client.close.assert_called_once_with()


def test_get_ssh_context_manager_closes_client_when_body_raises() -> None:
    ssh_client = mock.Mock()

    with mock.patch.object(SSHTool, "get_ssh", return_value=ssh_client):
        with pytest.raises(RuntimeError, match="boom"):
            with get_ssh("10.0.0.1", "root", 22) as ssh:
                assert ssh is ssh_client
                raise RuntimeError("boom")

    ssh_client.close.assert_called_once_with()


def test_get_ssh_config_uses_defaults_when_values_missing() -> None:
    with mock.patch(
        "plum_tools.pipmi.YmlConfig.parse_config_yml",
        return_value={
            "default_ssh_conf": {
                "user": "root",
                "port": 22,
                "identityfile": "~/.ssh/id_rsa",
            }
        },
    ) as mock_parse:
        ssh_conf = get_ssh_config("10.0.0.1", "", 0, "", "secret")

    mock_parse.assert_called_once_with(PathConfig.PLUM_YML_PATH)
    assert ssh_conf == {
        "hostname": "10.0.0.1",
        "username": "root",
        "port": 22,
        "identityfile": "~/.ssh/id_rsa",
        "password": "secret",
    }


def test_get_ipmi_ip_adds_interval_to_last_octet() -> None:
    with (
        mock.patch("plum_tools.pipmi.YmlConfig.parse_config_yml", return_value={"ipmi_interval": 100}) as mock_parse,
        mock.patch("plum_tools.pipmi.get_host_ip", return_value="10.0.0.5") as mock_get_host_ip,
    ):
        assert get_ipmi_ip("5", "default") == "10.0.0.105"

    mock_parse.assert_called_once_with(PathConfig.PLUM_YML_PATH)
    mock_get_host_ip.assert_called_once_with("5", "default")


def test_get_args_registers_expected_cli_options() -> None:
    mock_parser = mock.Mock()
    mock_args = mock.Mock()
    mock_parser.parse_args.return_value = mock_args

    with mock.patch("plum_tools.pipmi.get_base_parser", return_value=mock_parser) as mock_get_base_parser:
        assert get_args() is mock_args

    mock_get_base_parser.assert_called_once_with()
    mock_parser.add_argument.assert_has_calls(
        [
            mock.call("-l", "--login", required=True, action="store", dest="host", help="specify login ip"),
            mock.call(
                "-s", "--servers", required=True, action="store", dest="servers", nargs="+", help="specify server"
            ),
            mock.call(
                "-u", "--username", required=False, action="store", dest="user", default="root", help="specify username"
            ),
            mock.call(
                "-pass",
                "--password",
                required=False,
                action="store",
                dest="password",
                default="",
                help="specify password",
            ),
            mock.call(
                "-p", "--port", action="store", required=False, dest="port", type=int, default=0, help="ssh login port"
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
            mock.call("-t", "--type", action="store", required=False, dest="type", default="default", help="host type"),
            mock.call(
                "-U",
                "--Username",
                required=False,
                action="store",
                dest="Username",
                default="ADMIN",
                help="specify ipmi username",
            ),
            mock.call(
                "-c",
                "--command",
                required=False,
                action="store",
                dest="command",
                default="power on",
                help="specify ipmi command",
            ),
            mock.call(
                "-P",
                "--Password",
                required=False,
                action="store",
                dest="Password",
                default="12345678",
                help="specify ipmi password",
            ),
        ]
    )
    mock_parser.parse_args.assert_called_once_with()


def test_parser_methods_delegate_to_helpers() -> None:
    args = mock.Mock(
        host="1",
        type="default",
        user="root",
        port=22,
        identityfile="~/.ssh/id_rsa",
        password="secret",
        servers=["2", "3"],
        Username="ADMIN",
        Password="12345678",
        command="power on",
    )
    parser = Parser(args)

    with (
        mock.patch("plum_tools.pipmi.get_host_ip", return_value="10.0.0.1") as mock_get_host_ip,
        mock.patch("plum_tools.pipmi.get_ssh_config", return_value={"hostname": "10.0.0.1"}) as mock_get_ssh_config,
        mock.patch("plum_tools.pipmi.get_ipmi_ip", return_value="10.0.0.101") as mock_get_ipmi_ip,
    ):
        assert parser.parser_ssh_conf() == {"hostname": "10.0.0.1"}
        assert parser.parser_ip_list() == ["2", "3"]
        assert parser.parser_ipmi_auth("2") == {
            "ip": "10.0.0.101",
            "user": "ADMIN",
            "password": "12345678",
            "command": "power on",
        }

    mock_get_host_ip.assert_called_once_with("1", "default")
    mock_get_ssh_config.assert_called_once_with("10.0.0.1", "root", 22, "~/.ssh/id_rsa", "secret")
    mock_get_ipmi_ip.assert_called_once_with("2", "default")


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
        mock.patch("plum_tools.pipmi.get_args", return_value=args),
        mock.patch("plum_tools.pipmi.Parser", return_value=parser),
        mock.patch("plum_tools.pipmi.get_ssh", return_value=_mock_ssh_context(ssh_client)) as mock_get_ssh,
        mock.patch("plum_tools.pipmi.print_text") as mock_print_text,
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
            mock.call("cmd: ipmitool -I lanplus -H 10.0.0.2 -U ADMIN -P 123 power on"),
            mock.call("output: ok-1\n"),
            mock.call("cmd: ipmitool -I lanplus -H 10.0.0.3 -U ADMIN -P 123 power on"),
            mock.call("output: ok-2\n"),
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
        mock.patch("plum_tools.pipmi.get_args", return_value=args),
        mock.patch("plum_tools.pipmi.Parser", return_value=parser),
        mock.patch("plum_tools.pipmi.get_ssh", return_value=_mock_ssh_context(ssh_client)),
        mock.patch("plum_tools.pipmi.print_text"),
        mock.patch("plum_tools.pipmi.print_error") as mock_print_error,
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
        mock.patch("plum_tools.pipmi.get_args", return_value=args),
        mock.patch("plum_tools.pipmi.Parser", return_value=parser),
        mock.patch("plum_tools.pipmi.get_ssh", side_effect=SSHException("connect fail")),
        mock.patch("plum_tools.pipmi.print_error") as mock_print_error,
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    mock_print_error.assert_called_once_with("connect fail")

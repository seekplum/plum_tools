"""验证 ssh 的相关行为。"""

import re
from unittest import mock

import paramiko
import pytest

from plum_tools._pipmi.ssh import PSSHClient, SSHTool, get_ssh
from plum_tools.utils.exceptions import RunCmdError, SSHException


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
        with pytest.raises(RunCmdError, match="执行命令 `hostname` 失败") as exc_info:
            client.run_cmd("hostname")

    assert exc_info.value.out_msg == "partial"
    assert exc_info.value.err_msg == "boom"


def test_ssh_tool_get_ssh_connects_with_expected_args() -> None:
    ssh_client = mock.Mock()
    tool = SSHTool("10.0.0.1", "root", 22, password="secret", identityfile="~/.ssh/id_rsa")

    with (
        mock.patch("plum_tools._pipmi.ssh.PSSHClient", return_value=ssh_client) as mock_client,
        mock.patch("plum_tools._pipmi.ssh.paramiko.AutoAddPolicy", return_value="policy") as mock_policy,
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

    with mock.patch("plum_tools._pipmi.ssh.PSSHClient", return_value=ssh_client):
        with pytest.raises(SSHException, match=re.escape(message)):
            tool.get_ssh()


def test_get_ssh_context_manager_expands_identityfile_and_closes_client() -> None:
    ssh_client = mock.Mock()

    with (
        mock.patch("plum_tools._pipmi.ssh.get_file_abspath", return_value="/tmp/id_rsa") as mock_get_file_abspath,
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

"""建立跳板机连接并运行命令。"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import paramiko

from plum_tools.utils.exceptions import RunCmdError, SSHException
from plum_tools.utils.utils import ensure_str, get_file_abspath


class PSSHClient(paramiko.SSHClient):
    """SSH连接客户端"""

    def __init__(self, host: str) -> None:
        """初始化

        :param host 主机ip
        :example host 10.10.100.1
        """
        super().__init__()  # pylint: disable=R1725
        self.host = host

    def run_cmd(self, cmd: str, is_raise_exception: bool = True, **kwargs: Any) -> str:
        """执行系统命令

        :param cmd 要执行的命令
        :example cmd hostname

        :param is_raise_exception 执行命令有错误信息是否抛出异常，默认值为True
        :example is_raise_exception False

        :raise RunCmdError

        :return out_msg 命令执行结果
        """
        stdin, stdout, stderr = self.exec_command(cmd, **kwargs)  # nosec B601
        stdin.close()
        stdout.flush()
        out_msg = ensure_str(stdout.read())
        err_msg = ensure_str(stderr.read())
        if is_raise_exception and err_msg:
            message = f"[{self.host}] 执行命令 `{cmd}` 失败"
            raise RunCmdError(message, out_msg=out_msg, err_msg=err_msg)
        return out_msg


class SSHTool:
    """SSH连接工具类"""

    def __init__(
        self,
        hostname: str,
        username: str,
        port: int,
        conn_timeout: int = 3,
        password: str | None = None,
        identityfile: str | None = None,
    ) -> None:
        """初始化

        :param hostname 主机ip
        :example hostname 10.10.100.1

        :param username 用户名
        :example username root

        :param port 端口号
        :example port 22

        :param conn_timeout 连接超时时间
        :example conn_timeout 3

        :param password 密码
        :example password xxx

        :param identityfile 密钥文件路径
        :example identityfile ~/.ssh/id_rsa
        """
        self.host = hostname
        self.username = username
        self.password = password
        self.key_filename = identityfile
        self.port = port
        self.conn_timeout = conn_timeout

    def get_ssh(self) -> PSSHClient:
        """获取一个 ssh连接对象

        :return: ssh ssh连接对象
        """
        try:
            ssh = PSSHClient(host=self.host)
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507
            ssh.connect(
                hostname=self.host,
                username=self.username,
                password=self.password,
                key_filename=self.key_filename,
                port=self.port,
                timeout=self.conn_timeout,
            )
            return ssh
        except TimeoutError as e:
            msg = f"连接超时({self.username}@{self.host}:{self.port})."
            msg = f"{msg}请检查用户名,IP地址,端口号是否正确"
            raise SSHException(msg) from e
        except paramiko.ssh_exception.NoValidConnectionsError as e:
            msg = f"连接出现异常({self.username}@{self.host}:{self.port})."
            raise SSHException(f"{msg}请检查端口或IP地址是否正确") from e
        except paramiko.ssh_exception.AuthenticationException as e:
            msg = f"连接出现异常({self.username}@{self.host}:{self.port})."
            raise SSHException(f"{msg}请检查密码或密钥是否正确") from e
        except Exception as e:
            msg = f"连接出现异常({self.username}@{self.host}:{self.port}) {e}."
            raise SSHException(msg) from e


@contextmanager
def get_ssh(
    hostname: str,
    username: str,
    port: int,
    conn_timeout: int = 3,
    password: str | None = None,
    identityfile: str | None = None,
) -> Generator[PSSHClient, None, None]:
    """获取一个 ssh连接对象

    :param hostname 主机ip
    :example hostname 10.10.100.1

    :param username 用户名
    :example username root

    :param port 端口号
    :example port 22

    :param conn_timeout 连接超时时间
    :example conn_timeout 3

    :param password 密码
    :example password xxx

    :param identityfile 密钥文件路径
    :example identityfile ~/.ssh/id_rsa

    :return: ssh ssh连接对象
    """
    ssh_tool = SSHTool(
        hostname=hostname,
        username=username,
        port=port,
        conn_timeout=conn_timeout,
        password=password,
        identityfile=get_file_abspath(identityfile) if identityfile else None,
    )
    ssh = ssh_tool.get_ssh()
    try:
        yield ssh
    finally:
        ssh.close()

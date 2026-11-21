"""
#=============================================================================
#  ProjectName: plum_tools
#     FileName: pipmi
#         Desc: 对指定机器进行远程执行ipmitool相关操作
#               命令: pipmi -l 1 -s 2 3
#               描述: ssh登录1机器,对2,3进行开机操作
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-07 14:14
#=============================================================================
"""

import argparse
import sys
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import paramiko

from .conf import COMMAND_TIMEOUT, OsCommand, PathConfig
from .exceptions import RunCmdError, SSHException
from .utils.cli import cli_entry
from .utils.parser import add_compact_argument, get_base_parser
from .utils.printer import print_error, print_text
from .utils.sshconf import get_host_ip
from .utils.utils import YmlConfig, ensure_str, get_file_abspath


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


def get_ssh_config(hostname: str, username: str, port: int, identityfile: str, password: str) -> dict:
    """查询默认的ssh配置信息

    :param hostname 主机ip
    :example hostname 10.10.100.1

    :param username 用户名
    :example username root

    :param port 端口号
    :example port 22

    :param password 密码
    :example password xxx

    :param identityfile 密钥文件路径
    :example identityfile ~/.ssh/id_rsa

    :return ssh_conf ssh登陆的配置信息
    :example ssh_conf
    {
        'identityfile': '~/.ssh/seekplum',
        'hostname': 'github.com',
        'username': 'seekplum',
        'password': 'xxx',
        'port': 22
    }
    """
    yml_data = YmlConfig.parse_config_yml(PathConfig.PLUM_YML_PATH)
    default_ssh_conf = yml_data["default_ssh_conf"]
    return {
        "hostname": hostname,
        "username": username or default_ssh_conf["user"],
        "port": port or default_ssh_conf["port"],
        "identityfile": identityfile or default_ssh_conf["identityfile"],
        "password": password,
    }


def get_ipmi_ip(host: str, host_type: str) -> str:
    """根据ip计算带外 ip

    :param host: ip的简写
    :example host 1

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :example host_type default

    :return ipmi_ip 带外ip
    :example ipmi_ip 10.10.10.101
    """
    yml_data = YmlConfig.parse_config_yml(PathConfig.PLUM_YML_PATH)
    hostname = get_host_ip(host, host_type)
    item = hostname.split(".")
    item[-1] = str(int(item[-1]) + yml_data["ipmi_interval"])
    return ".".join(item)


def get_args() -> argparse.Namespace:
    """获取程序参数

    :return 命令行参数
    """
    parser = get_base_parser()
    add_compact_argument(parser)
    parser.description = "通过 SSH 登录跳板机，对指定服务器执行 IPMI 命令。"  # noqa
    parser.epilog = (
        "示例：\n"
        "  pipmi -l 192.168.1.10 -s 20 21 -c 'power status'\n"
        "  pipmi -l 10 -s 20 -t default -U ADMIN -c 'chassis status'\n\n"
        "配置：IP 简写和默认 SSH 参数读取 ~/.plum_tools.yaml；\n"
        "IPMI 地址根据主机类型的网段及 ipmi_interval 偏移计算。"
    )
    parser.add_argument(
        "-l",
        "--login",
        required=True,
        action="store",
        dest="host",
        help="跳板机 IP 或 IP 简写，必填",
    )
    parser.add_argument(
        "-s",
        "--servers",
        required=True,
        action="store",
        dest="servers",
        nargs="+",
        help="目标服务器 IP 或 IP 简写，必填，可指定多个；IPMI 地址按配置偏移计算",
    )
    parser.add_argument(
        "-u",
        "--username",
        required=False,
        action="store",
        dest="user",
        default="root",
        help="SSH 登录用户名，默认 root",
    )
    parser.add_argument(
        "-pass",
        "--password",
        required=False,
        action="store",
        dest="password",
        default="",
        help="SSH 登录密码，默认为空，使用私钥认证",
    )
    parser.add_argument(
        "-p",
        "--port",
        action="store",
        required=False,
        dest="port",
        type=int,
        default=0,
        help="SSH 登录端口，默认读取 SSH 配置",
    )
    parser.add_argument(
        "-i",
        "--identityfile",
        action="store",
        required=False,
        dest="identityfile",
        default="",
        help="SSH 私钥路径，默认读取 SSH 配置",
    )
    parser.add_argument(
        "-t",
        "--type",
        action="store",
        required=False,
        dest="type",
        default="default",
        help="主机类型，默认 default；可选值由配置中的 host_type_<类型> 决定",
    )
    parser.add_argument(
        "-U",
        "--Username",
        required=False,
        action="store",
        dest="Username",
        default="ADMIN",
        help="IPMI 登录用户名，默认 ADMIN",
    )
    parser.add_argument(
        "-c",
        "--command",
        required=False,
        action="store",
        dest="command",
        default="power on",
        help="IPMI 命令，默认 'power on'；例如 'power status'、'power off'，支持 ipmitool 子命令",
    )
    parser.add_argument(
        "-P",
        "--Password",
        required=False,
        action="store",
        dest="Password",
        default="12345678",
        help="IPMI 登录密码，默认 12345678",
    )

    return parser.parse_args()


class Parser:
    """解析命令行参数"""

    def __init__(self, args: argparse.Namespace) -> None:
        """初始化

        :param args 命令行参数
        """
        self._args = args

    def _parser_login_ip(self) -> str:
        """解析登陆主机需要的ip

        :return 主机ip
        """
        return get_host_ip(self._args.host, self._args.type)

    def parser_ssh_conf(self) -> dict:
        """解析登陆需要的ssh配置信息

        :return ssh配置信息
        """
        return get_ssh_config(
            self._parser_login_ip(),
            self._args.user,
            self._args.port,
            self._args.identityfile,
            self._args.password,
        )

    def parser_ip_list(self) -> list[str]:
        """解析带外IP集合

        :return 带外IP集合
        """
        return self._args.servers

    def parser_ipmi_auth(self, short_ip: str) -> dict:
        """解析带外认证信息

        :param short_ip 简写IP
        :example short_ip 1

        :return 带外认证信息
        """
        return {
            "ip": get_ipmi_ip(short_ip, self._args.type),
            "user": self._args.Username,
            "password": self._args.Password,
            "command": self._args.command,
        }


@cli_entry
def main() -> None:
    """程序主入口"""
    args = get_args()
    p = Parser(args)

    try:
        with get_ssh(**p.parser_ssh_conf()) as ssh:
            # 对每台机器执行 ipmi 命令
            for short_ip in p.parser_ip_list():
                auth = p.parser_ipmi_auth(short_ip)
                cmd = OsCommand.IPMI_COMMAND % auth
                context = f"[{auth['ip']}] {auth['command']}"
                compact = args.compact is True
                if not compact:
                    print_text(f"命令：{cmd}")
                try:
                    output = ssh.run_cmd(cmd, timeout=COMMAND_TIMEOUT)
                    if compact:
                        output = output.rstrip("\r\n")
                        separator = "\n" if "\n" in output or "\r" in output else " "
                        print_text(f"{context}：{separator}{output}")
                    else:
                        print_text(f"输出：{output}\n")
                except TimeoutError:
                    print_error(f"执行命令: {cmd} 超时，超时时间为: {COMMAND_TIMEOUT}秒")
                except RunCmdError as e:
                    print_error(f"{context}：{e.err_msg}" if compact else e.err_msg)
    except SSHException as e:
        print_error(e.args[0])
        sys.exit(1)

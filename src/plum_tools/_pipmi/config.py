"""解析跳板机和目标服务器配置。"""

import argparse

from plum_tools.utils.constants import PathConfig
from plum_tools.utils.sshconf import get_host_ip
from plum_tools.utils.utils import YmlConfig


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

"""pssh 命令行入口。"""

import os

from plum_tools.utils.cli import cli_entry
from plum_tools.utils.constants import SSHConfig
from plum_tools.utils.parser import get_base_parser
from plum_tools.utils.sshconf import merge_ssh_config


def get_login_ssh_cmd(hostname: str, user: str, port: int, identityfile: str) -> str:
    """组合登陆的命令

    :param hostname 主机ip
    :example hostname 10.10.100.1

    :param user ssh登陆使用的用户名
    :example user 10.10.100.1

    :param port ssh登陆使用的端口号
    :example port 22

    :param identityfile 主机ip
    :example identityfile ~/.ssh/id_rsa

    :return cmd ssh登陆的命令
    """
    return (
        f"ssh  -i {identityfile} "
        '-o "UserKnownHostsFile=/dev/null" '
        '-o "StrictHostKeyChecking no" '
        f'-o  "ConnectTimeout={SSHConfig.CONNECT_TIMEOUT}" '
        f"{user}@{hostname} -p {port}"
    )


def login(host: str, host_type: str, user: str, port: int, identityfile: str) -> None:
    """登陆主机

    :param host: ip的简写或者主机的别名
    :example host 1

    :param host_type ip类型,不同的ip类型，ip前缀不一样
    :example host_type default

    :param user ssh登陆用户名
    :example user root

    :param port ssh登陆端口
    :example port 22

    :param user ssh登陆用户名
    :example user root

    :param identityfile ssh登陆私钥文件路径
    :example identityfile ~/.ssh/id_rsa
    """
    ssh_conf = merge_ssh_config(host, host_type, user, port, identityfile)
    cmd = get_login_ssh_cmd(**ssh_conf)
    # 不能使用run_cmd，因为会导致夯住，需要等待结果返回
    os.system(cmd)  # nosec B605


@cli_entry
def main() -> None:
    """程序主入口"""
    parser = get_base_parser()
    parser.description = "通过 IP、IP 简写或 SSH 主机别名登录服务器。"  # noqa
    parser.epilog = (
        "示例：\n"
        "  pssh 192.168.1.10\n"
        "  pssh dev -u root -p 2222\n"
        "  pssh 10 -t default\n\n"
        "配置：IP 简写读取 ~/.plum_tools.yaml 的 host_type_<类型>；\n"
        "SSH 参数优先使用命令行值，其次为主机别名配置，最后为 default_ssh_conf。"
    )
    parser.add_argument(dest="host", action="store", help="服务器 IP、IP 简写或 ~/.ssh/config 中的主机别名")

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
        "-i",
        "--identityfile",
        action="store",
        required=False,
        dest="identityfile",
        default="",
        help="SSH 私钥路径，默认读取 SSH 配置",
    )
    parser.add_argument(
        "-u",
        "--username",
        action="store",
        required=False,
        dest="user",
        default="",
        help="SSH 登录用户名，默认读取 SSH 配置",
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

    args = parser.parse_args()
    host, host_type, user, port, identityfile = (
        args.host,
        args.type,
        args.user,
        args.port,
        args.identityfile,
    )
    # 执行登陆操作
    login(host, host_type, user, port, identityfile)


if __name__ == "__main__":
    raise SystemExit(main())

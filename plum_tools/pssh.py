"""
#=============================================================================
#  ProjectName: plum-tools
#     FileName: pssh
#         Desc: 通过密钥快速登录机器
#                命令: pssh 1
#                描述: 使用指定路径下的密钥登录 x.x.x.1
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-05 22:02
#=============================================================================
"""

import os

from .conf import SSHConfig
from .utils.parser import get_base_parser
from .utils.sshconf import merge_ssh_config


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
    cmd = (
        f"ssh  -i {identityfile} "
        '-o "UserKnownHostsFile=/dev/null" '
        '-o "StrictHostKeyChecking no" '
        f'-o  "ConnectTimeout={SSHConfig.connect_timeout}" '
        f"{user}@{hostname} -p {port}"
    )
    return cmd


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
    os.system(cmd)


def main() -> None:
    """程序主入口"""
    parser = get_base_parser()
    parser.add_argument(dest="host", action="store", help="specify server")

    parser.add_argument(
        "-t",
        "--type",
        action="store",
        required=False,
        dest="type",
        default="default",
        help="host type",
    )
    parser.add_argument(
        "-i",
        "--identityfile",
        action="store",
        required=False,
        dest="identityfile",
        default="",
        help="ssh login identityfile path",
    )
    parser.add_argument(
        "-u",
        "--username",
        action="store",
        required=False,
        dest="user",
        default="",
        help="ssh login username",
    )
    parser.add_argument(
        "-p",
        "--port",
        action="store",
        required=False,
        dest="port",
        type=int,
        default=0,
        help="ssh login port",
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

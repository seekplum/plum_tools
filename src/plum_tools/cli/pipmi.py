"""pipmi 命令行入口。"""

import argparse
import sys

from plum_tools._pipmi.config import Parser
from plum_tools._pipmi.ssh import get_ssh
from plum_tools.utils.cli import cli_entry
from plum_tools.utils.constants import COMMAND_TIMEOUT, OsCommand
from plum_tools.utils.exceptions import RunCmdError, SSHException
from plum_tools.utils.parser import add_compact_argument, get_base_parser
from plum_tools.utils.printer import print_error, print_text


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


if __name__ == "__main__":
    raise SystemExit(main())

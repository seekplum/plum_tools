"""
#=============================================================================
#  ProjectName: plum_tools
#     FileName: pping
#         Desc: ping指定网段所有ip是否能ping通
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-07 10:26
#=============================================================================
"""

from multiprocessing import Pool

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn

from .conf import PROCESSES_NUMBER, OsCommand
from .exceptions import RunCmdError
from .utils.parser import get_base_parser
from .utils.printer import print_text
from .utils.sshconf import get_prefix_host_ip
from .utils.utils import run_cmd


def ping(ip: str) -> str | None:
    """ping指定ip是否能ping通

    :param ip 主机ip
    :example ip 10.10.100.1
    """
    cmd = OsCommand.PING_COMMAND % ip
    try:
        run_cmd(cmd)
    except RunCmdError:
        return None
    return ip


def run(host_type: str, prefix_host: str) -> None:
    """探测 prefix_host 指定网段，为空时读取 host_type 配置。
    显示完成进度，按地址顺序打印可达 IP，无返回值。
    """
    if not prefix_host:
        prefix_host = get_prefix_host_ip(host_type)

    mark = "."
    if not prefix_host.endswith(mark):
        prefix_host += mark

    targets = [f"{prefix_host}{i}" for i in range(1, 255)]
    reachable: set[str] = set()
    console = Console(stderr=True)
    with (
        Pool(processes=PROCESSES_NUMBER) as pool,
        Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TextColumn("{task.completed:.0f}/{task.total:.0f} · 可达 {task.fields[reachable]} · 耗时"),
            TimeElapsedColumn(),
            console=console,
            disable=not console.is_terminal,
            auto_refresh=console.is_terminal,
            transient=True,
            refresh_per_second=4,
            redirect_stdout=False,
            redirect_stderr=False,
        ) as progress,
    ):
        task = progress.add_task("探测主机", total=len(targets), reachable=0)
        for ip in pool.imap_unordered(ping, targets):
            if ip:
                reachable.add(ip)
            progress.update(task, advance=1, reachable=len(reachable))
    for ip in targets:
        if ip in reachable:
            print_text(ip)


def main() -> None:
    """程序主入口"""
    parser = get_base_parser()
    parser.description = "并发探测指定网段内 1 至 254 号地址，输出可达 IP。"  # noqa
    parser.epilog = "示例：\n  pping -p 192.168.1\n  pping -t default"
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
        "-p",
        "--prefix-host",
        action="store",
        required=False,
        dest="prefix_host",
        default=None,
        help="网段前三段，例如 192.168.1；默认读取所选主机类型的网段配置",
    )

    args = parser.parse_args()
    run(args.type, args.prefix_host)

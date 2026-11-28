"""pping 命令行入口。"""

import json
from ipaddress import ip_address
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.text import Text

from plum_tools.utils.cli import cli_entry
from plum_tools.utils.cli import process_pool as Pool
from plum_tools.utils.constants import PROCESSES_NUMBER, OsCommand
from plum_tools.utils.exceptions import RunCmdError
from plum_tools.utils.parser import add_compact_argument, get_base_parser
from plum_tools.utils.printer import print_columns, print_text
from plum_tools.utils.sorting import SortField, add_sort_argument, sort_items
from plum_tools.utils.sshconf import get_prefix_host_ip
from plum_tools.utils.utils import run_cmd


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


def run(
    host_type: str,
    prefix_host: str,
    *,
    compact: bool = False,
    json_output: bool = False,
    sort: list[SortField] | None = None,
) -> None:
    """探测 prefix_host 指定网段，为空时读取 host_type 配置。
    按地址顺序输出可达 IP；json_output 输出 JSON，否则 compact 仅在终端分栏。
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
    addresses = [ip for ip in targets if ip in reachable]
    addresses = sort_items(addresses, sort, {"ip": lambda address: int(ip_address(address))})
    if json_output:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "command": "pping",
                    "options": {"host_type": host_type, "prefix_host": prefix_host},
                    "summary": {
                        "target_count": len(targets),
                        "reachable_count": len(addresses),
                        "unreachable_count": len(targets) - len(addresses),
                    },
                    "reachable": addresses,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    output_console = Console()
    if compact and output_console.is_terminal:
        print_columns(output_console, [Text(ip) for ip in addresses])
    else:
        for ip in addresses:
            print_text(ip)


@cli_entry
def main() -> None:
    """程序主入口"""
    parser = get_base_parser()
    add_sort_argument(parser, {"ip": "IP 地址数值"}, default_order="按 IP 地址数值升序")
    parser.description = "并发探测指定网段内 1 至 254 号地址，输出可达 IP。"  # noqa
    parser.epilog = (
        "示例：\n  pping -p 192.168.1\n  pping -t default\n  pping -p 192.168.1 --json | jq -r '.reachable[]'"
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
        "-p",
        "--prefix-host",
        action="store",
        required=False,
        dest="prefix_host",
        default=None,
        help="网段前三段，例如 192.168.1；默认读取所选主机类型的网段配置",
    )

    add_compact_argument(parser)
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="以 JSON 输出探测结果，忽略 --compact；进度条写入标准错误",
    )
    args = parser.parse_args()
    display_options: dict[str, Any] = {}
    if args.compact is True:
        display_options["compact"] = True
    if args.json_output is True:
        display_options["json_output"] = True
    if args.sort:
        display_options["sort"] = args.sort
    run(args.type, args.prefix_host, **display_options)


if __name__ == "__main__":
    raise SystemExit(main())

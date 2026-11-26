"""解析使用报告参数并调度采集与展示。"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from plum_tools._agent_usage.collectors import collect
from plum_tools._agent_usage.models import (
    CLIENTS,
    DEFAULT_CLIENTS,
    Client,
    Kind,
    OutputFormat,
    ReportMode,
    localize_report,
    observed,
)
from plum_tools._agent_usage.reporting import SORT_FIELDS, print_rich, sort_usage_rows
from plum_tools.utils.compat import tomllib
from plum_tools.utils.parser import get_base_parser
from plum_tools.utils.sorting import add_sort_argument


def main() -> int:
    """解析命令行参数并生成报告。"""
    parser = get_base_parser()
    add_sort_argument(parser, SORT_FIELDS)
    parser.description = "汇总本机技能、MCP 和规则的可观察使用记录。"
    parser.add_argument(
        "--home", type=Path, default=Path.home(), metavar="目录", help="待分析的用户目录，默认当前用户目录"
    )
    parser.add_argument(
        "--client",
        action="append",
        choices=tuple(Client),
        help="统计客户端，可重复指定；默认 claude、codex",
    )
    parser.add_argument(
        "--format",
        choices=tuple(OutputFormat),
        default=OutputFormat.TABLE,
        help="输出格式：table 表格、json 原始数据，默认 table",
    )
    parser.add_argument(
        "--kind",
        choices=tuple(Kind),
        default=Kind.ALL,
        help="筛选类别：all 全部、skill 技能、mcp 服务、rule 规则、command 命令，默认 all",
    )
    parser.add_argument(
        "--mode",
        choices=tuple(ReportMode),
        default=ReportMode.CONCISE,
        help="信息详细程度：concise 隐藏全零记录、full 显示全部，默认 concise",
    )
    args = parser.parse_args()
    requested = {Client(client) for client in args.client or DEFAULT_CLIENTS}
    args.format = OutputFormat(args.format)
    args.kind = Kind(args.kind)
    args.mode = ReportMode(args.mode)
    clients = CLIENTS if Client.ALL in requested else tuple(c for c in CLIENTS if c in requested)
    try:
        report = collect(args.home, clients)
    except (OSError, ValueError, sqlite3.Error, tomllib.TOMLDecodeError) as error:
        print(
            f"读取技能、MCP 配置或 Hook 数据失败: {type(error).__name__}",
            file=sys.stderr,
        )
        return 2
    if args.kind != Kind.ALL:
        report["items"] = [row for row in report["items"] if row["kind"] == args.kind]
    if args.mode == ReportMode.CONCISE:
        report["items"] = [row for row in report["items"] if observed(row)]
    localize_report(report)
    report["items"] = sort_usage_rows(report["items"], args.sort)
    if args.format == OutputFormat.JSON:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_rich(report, **({"sort": args.sort} if args.sort else {}))
    return 0

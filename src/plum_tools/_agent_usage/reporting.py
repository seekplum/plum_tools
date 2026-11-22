"""统一时间展示，并渲染终端统计报告。"""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.table import Table

from .models import CLIENT_LABELS, Client, Kind, display_time, later, observed


def rich_cells(kind: Kind, row: dict, clients: tuple[Client, ...]) -> tuple:
    """按类别选择 Rich 表格的展示字段。"""
    calls_by_client = tuple(row["calls_by_client"].get(client, 0) for client in clients)
    if kind == Kind.SKILL:
        recent = later(later(row["last_used"], row["last_expanded"]), row["last_attributed"])
        return (
            row["name"],
            row["calls"],
            *calls_by_client,
            row["expansions"],
            row["attributed_sessions"],
            display_time(recent),
        )
    if kind == Kind.MCP:
        return (
            row["name"],
            row["calls"],
            *calls_by_client,
            row["hook_calls"],
            display_time(row["last_used"]),
        )
    if kind == Kind.RULE:
        return (row["name"], row["reads"], display_time(row["last_read"]))
    return (row["name"], row["expansions"], display_time(row["last_expanded"]))


def print_rich_coverage(console: Console, report: dict) -> None:
    """显示各日志来源的时间覆盖与统计限制。"""
    for client, stats in report["coverage"].items():
        if client == "hooks":
            if stats["exists"]:
                console.print(f"Hook: {stats['events']} 个事件")
                console.print(f"  时间（北京）: {display_time(stats['first'])} 至 {display_time(stats['last'])}")
            else:
                console.print("Hook: 尚无本地数据库")
        elif client == Client.OPENCODE:
            if stats["exists"]:
                console.print(f"OpenCode: {stats['events']} 个工具事件 · 坏行 {stats['invalid_rows']}")
                console.print(f"  时间（北京）: {display_time(stats['first'])} 至 {display_time(stats['last'])}")
                if stats["error"]:
                    console.print(f"  读取失败: {stats['error']}", style="yellow")
            else:
                console.print("OpenCode: 尚无本地数据库")
        else:
            console.print(
                f"{CLIENT_LABELS[client]}：{stats['files']} 个日志 · 无效行 {stats['invalid_lines']} · "
                f"不可读 {stats['unreadable_files']}"
            )
            console.print(f"  时间（北京）: {display_time(stats['first'])} 至 {display_time(stats['last'])}")
        console.print()
    if report["missing_sources"]:
        console.print("缺失来源: " + ", ".join(report["missing_sources"]), style="yellow")
        console.print()
    for note in report["limitations"]:
        console.print("注意: " + note, style="yellow")


def print_mcp_tools(console: Console, rows: list[dict]) -> None:
    """展示 MCP 服务下各工具的调用次数。"""

    tools = sorted(
        ((row["name"], tool, calls) for row in rows for tool, calls in row["tool_calls"].items()),
        key=lambda item: (-item[2], item[0], item[1]),
    )
    if not tools:
        return
    detail = Table(
        title="MCP 工具",
        box=box.SQUARE,
        title_style="bold black on cyan",
        header_style="bold cyan",
    )
    detail.add_column("服务")
    detail.add_column("工具")
    detail.add_column("调用", justify="right")
    for server, tool, calls in tools:
        detail.add_row(server, tool, str(calls))
    console.print(detail)
    console.print()


# pylint: disable=too-many-locals
def print_rich(report: dict) -> None:
    """按技能、MCP 和命令分组展示使用证据。"""

    console = Console()
    clients = tuple(report["clients"])
    client_columns = {
        Kind.SKILL: tuple("Codex 推断" if client == Client.CODEX else CLIENT_LABELS[client] for client in clients),
        Kind.MCP: tuple(CLIENT_LABELS[client] for client in clients),
    }
    groups = (
        (
            Kind.SKILL,
            "技能",
            (
                "名称",
                "调用",
                *client_columns[Kind.SKILL],
                "展开",
                "归因会话",
                "最近证据",
            ),
        ),
        (
            Kind.MCP,
            "MCP",
            ("名称", "调用", *client_columns[Kind.MCP], "钩子调用", "最后调用"),
        ),
        (Kind.RULE, "规则文件", ("名称", "显式读取", "最后读取")),
        (Kind.COMMAND, "斜杠命令", ("名称", "展开", "最后展开")),
    )
    for kind, title, columns in groups:
        rows = [row for row in report["items"] if row["kind"] == kind]
        if not rows:
            continue
        table = Table(
            title=f"{title} · {len(rows)}",
            box=box.SQUARE,
            title_style="bold black on cyan",
            header_style="bold cyan",
        )
        for column in columns:
            numeric = column in (
                "调用",
                "Claude",
                "Codex",
                "Codex 推断",
                "OpenCode",
                "展开",
                "归因会话",
                "钩子调用",
                "显式读取",
            )
            table.add_column(
                column,
                justify="right" if numeric else "left",
                overflow="fold" if not numeric else "ellipsis",
            )
        for index, row in enumerate(rows):
            next_row = rows[index + 1] if index + 1 < len(rows) else None
            table.add_row(
                *(str(cell) for cell in rich_cells(kind, row, clients)),
                end_section=not observed(row) and bool(next_row and observed(next_row)),
            )
        console.print(table)
        console.print()
        if kind == Kind.MCP:
            print_mcp_tools(console, rows)
    if not report["items"]:
        console.print("当前筛选条件下没有可显示的使用记录。")
        console.print()
    print_rich_coverage(console, report)

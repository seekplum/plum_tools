"""只读采集本机日志和数据库，合并去重后的使用记录。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import claude_event, codex_event, iter_events, normalize_call, opencode_call
from .inventory import inventory, opencode_mcp_names, rule_name
from .models import DEFAULT_CLIENTS, HOOK_DB, LOG_DIRS, OPENCODE_DB, Client, Kind, earlier, later, observed, record


def count_call(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    records: dict,
    seen_calls: set,
    key: tuple,
    kind: Kind | str,
    name: str,
    client: Client | str,
    when: str | None,
    evidence: str,
    tool: str | None = None,
) -> None:
    """按事件键计数，并保留客户端与证据来源。"""
    if key in seen_calls:
        return
    seen_calls.add(key)
    row = record(records, kind, name)
    if kind == Kind.RULE:
        row["reads"] += 1
        row["last_read"] = later(row["last_read"], when)
        if evidence not in row["evidence"]:
            row["evidence"].append(evidence)
        return
    row["calls"] += 1
    row["calls_by_client"][client] = row["calls_by_client"].get(client, 0) + 1
    if evidence == "codex_skill_file_reference":
        row["inferred_calls"] += 1
    if kind == Kind.MCP and tool:
        row["tool_calls"][tool] = row["tool_calls"].get(tool, 0) + 1
    row["last_used"] = later(row["last_used"], when)
    if evidence not in row["evidence"]:
        row["evidence"].append(evidence)


def record_call(  # pylint: disable=too-many-arguments
    records: dict,
    seen_calls: set,
    client: Client | str,
    call: tuple,
    path: Path,
    line_number: int,
    when: str | None,
    home: Path,
) -> None:
    """将历史日志调用映射为统一事件键。"""
    kind, name, call_id, tool = call
    if kind == Kind.RULE:
        name = rule_name(home, name)
        if name is None:
            return
    key = (client, call_id) if isinstance(call_id, str) and call_id else (client, str(path), line_number, kind, name)
    evidence = "codex_skill_file_reference" if client == Client.CODEX and kind == Kind.SKILL else client + "_tool_call"
    count_call(records, seen_calls, key, kind, name, client, when, evidence, tool)


# pylint: disable=too-many-locals
def scan_hooks(home: Path, records: dict, clients: tuple[Client, ...]) -> tuple[dict, set]:
    """读取 Hook 事件，返回覆盖信息和用于历史日志去重的事件键。"""
    database = home / HOOK_DB
    stats: dict[str, Any] = {"exists": database.is_file(), "events": 0, "first": None, "last": None}
    seen_calls: set[tuple] = set()
    if not stats["exists"]:
        return stats, seen_calls
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        events = connection.execute("""SELECT event_id, observed_at, client, kind, name, outcome, tool_use_id, tool_name
               FROM usage_events ORDER BY observed_at""")
        for event_id, when, client, kind, name, outcome, call_id, tool_name in events:
            if client not in clients:
                continue
            stats["events"] += 1
            stats["first"] = earlier(stats["first"], when)
            stats["last"] = later(stats["last"], when)
            if kind == Kind.COMMAND:
                target = Kind.SKILL if (Kind.SKILL, name) in records else Kind.COMMAND
                row = record(records, target, name)
                row["expansions"] += 1
                row["last_expanded"] = later(row["last_expanded"], when)
                if "claude_command_expansion" not in row["evidence"]:
                    row["evidence"].append("claude_command_expansion")
            elif kind in (Kind.SKILL, Kind.MCP):
                key = (client, call_id) if call_id else ("hook", event_id)
                tool = None
                if kind == Kind.MCP:
                    parsed = normalize_call(client, tool_name, call_id, None)
                    if parsed and parsed[0] == Kind.MCP:
                        tool = parsed[3]
                count_call(
                    records,
                    seen_calls,
                    key,
                    kind,
                    name,
                    client,
                    when,
                    "hook_" + outcome,
                    tool,
                )
                record(records, kind, name)["hook_calls"] += 1
    return stats, seen_calls


def scan_logs(home: Path, records: dict, seen_calls: set, clients: tuple[Client, ...]) -> dict:
    """逐行扫描会话，只统计明确记录的工具调用。"""
    coverage = {}
    attributed: dict[str, set[str]] = {}
    for client in clients:
        if client not in LOG_DIRS:
            continue
        relatives = LOG_DIRS[client]
        stats: dict[str, Any] = {
            "files": 0,
            "invalid_lines": 0,
            "unreadable_files": 0,
            "first": None,
            "last": None,
        }
        coverage[client] = stats
        for relative in relatives:
            root = home / relative
            if not root.is_dir():
                continue
            for path in root.rglob("*.jsonl"):
                _scan_log_file(home, path, client, records, seen_calls, stats, attributed)
    for name, sessions in attributed.items():
        record(records, Kind.SKILL, name)["attributed_sessions"] = len(sessions)
    return coverage


# pylint: disable=too-many-locals
def scan_opencode(home: Path, records: dict, seen_calls: set) -> dict:
    """只读扫描 OpenCode 工具记录，按 part ID 统计一次调用。"""
    database = home / OPENCODE_DB
    stats: dict[str, Any] = {
        "exists": database.is_file(),
        "events": 0,
        "invalid_rows": 0,
        "error": None,
        "first": None,
        "last": None,
    }
    if not stats["exists"]:
        return stats
    servers, configured = opencode_mcp_names(home)
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                "SELECT id, time_created, data FROM part WHERE json_extract(data, '$.type') = 'tool'"
            )
            for part_id, created, raw in rows:
                try:
                    item = json.loads(raw)
                    name = item.get("tool")
                    when = (
                        datetime.fromtimestamp(created / 1000, timezone.utc)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z")
                    )
                except (ValueError, TypeError, OverflowError, AttributeError):
                    stats["invalid_rows"] += 1
                    continue
                if not isinstance(name, str) or not name:
                    continue
                stats["events"] += 1
                stats["first"] = earlier(stats["first"], when)
                stats["last"] = later(stats["last"], when)
                state = item.get("state") or {}
                tool_input = state.get("input") if isinstance(state, dict) else None
                tool_input = tool_input if isinstance(tool_input, dict) else {}
                call = opencode_call(home, name, tool_input, servers, configured)
                if call and isinstance(call[1], str) and call[1]:
                    kind, target, tool = call
                    if target is None:
                        continue
                    evidence = "opencode_read" if kind == Kind.RULE else "opencode_part"
                    count_call(
                        records,
                        seen_calls,
                        (Client.OPENCODE, part_id),
                        kind,
                        target,
                        Client.OPENCODE,
                        when,
                        evidence,
                        tool,
                    )
    except (OSError, sqlite3.Error) as error:
        stats["error"] = type(error).__name__
    return stats


def collect(home: Path, clients: tuple[Client, ...] = DEFAULT_CLIENTS) -> dict:
    """收集清单、调用记录及日志覆盖说明。"""
    records: dict = {}
    missing = inventory(home, records, clients)
    coverage = {}
    seen_calls: set[tuple] = set()
    if Client.CLAUDE in clients or Client.CODEX in clients:
        hook_coverage, seen_calls = scan_hooks(home, records, clients)
        coverage.update(scan_logs(home, records, seen_calls, clients))
        coverage["hooks"] = hook_coverage
    if Client.OPENCODE in clients:
        coverage[Client.OPENCODE] = scan_opencode(home, records, seen_calls)
    limitations = ["0 次表示现存日志中未观察到明确调用，不代表从未使用或可以删除。"]
    if Client.CLAUDE in clients:
        limitations.append("Claude 的归因会话数不是调用次数；斜杠命令展开与工具调用分别计数。")
    if Client.CODEX in clients:
        limitations.append("Codex 技能读取 SKILL.md 仅是推断信号；启用 Hook 前的嵌套 MCP 调用仍可能遗漏。")
    if Client.OPENCODE in clients:
        limitations.append("OpenCode 配置不可读时，MCP 名称按工具前缀推断。")
    limitations.append("规则只统计所选客户端明确读取的文件；自动注入和 Codex 规则触发没有逐条事件。")
    return {
        "clients": list(clients),
        "coverage": coverage,
        "missing_sources": missing,
        "limitations": limitations,
        "items": sorted(
            records.values(),
            key=lambda row: (
                observed(row),
                row["calls"] or 0,
                row["expansions"],
                row["attributed_sessions"],
                row["reads"],
                row["kind"],
                row["name"],
            ),
        ),
    }


# pylint: disable=too-many-locals
def _scan_log_file(
    home: Path,
    path: Path,
    client: Client,
    records: dict,
    seen_calls: set,
    stats: dict,
    attributed: dict[str, set[str]],
) -> None:
    """扫描单个会话，保留 Codex 两类 MCP 事件的优先级与去重语义。"""
    parse_event = claude_event if client == Client.CLAUDE else codex_event
    stats["files"] += 1
    session = str(path)
    codex_functions: list[tuple] = []
    codex_ends: list[tuple] = []
    for line_number, event, when in iter_events(path, stats):
        session, skill, calls = parse_event(event, session)
        if isinstance(skill, str) and skill:
            row = record(records, Kind.SKILL, skill)
            attributed.setdefault(skill, set()).add(session)
            row["last_attributed"] = later(row["last_attributed"], when)
            if "claude_attribution" not in row["evidence"]:
                row["evidence"].append("claude_attribution")
        for call in calls:
            if client == Client.CODEX and call[0] == Kind.MCP:
                target = codex_ends if event["type"] == "event_msg" else codex_functions
                target.append((call, line_number, when))
            else:
                record_call(
                    records,
                    seen_calls,
                    client,
                    call,
                    path,
                    line_number,
                    when,
                    home,
                )
    for call, line_number, when in codex_functions or codex_ends:
        record_call(records, seen_calls, client, call, path, line_number, when, home)

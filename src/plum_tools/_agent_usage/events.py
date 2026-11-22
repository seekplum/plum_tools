"""将各客户端的日志事件归一化为可统计调用。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .inventory import rule_name
from .models import SKILL_READ, Client, Kind, earlier, later, timestamp


def iter_events(path: Path, stats: dict) -> Iterator[tuple[int, dict, str | None]]:
    """逐行解析日志，同时维护时间范围和错误计数。"""
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    event = json.loads(line)
                except ValueError:
                    stats["invalid_lines"] += 1
                    continue
                if not isinstance(event, dict):
                    continue
                when = timestamp(event.get("timestamp"))
                stats["first"] = earlier(stats["first"], when)
                stats["last"] = later(stats["last"], when)
                yield line_number, event, when
    except (OSError, UnicodeError):
        stats["unreadable_files"] += 1


def normalize_call(
    client: Client | str, name: object, call_id: object, tool_input: object
) -> tuple[Kind, str, Any, str | None] | None:
    """将显式工具调用映射为技能、MCP 或规则读取。"""
    if not isinstance(name, str):
        return None
    if client == Client.CLAUDE and name == "Skill":
        kind = Kind.SKILL
        name = tool_input.get("skill") if isinstance(tool_input, dict) else None
        tool = None
    elif client == Client.CLAUDE and name == "Read":
        kind = Kind.RULE
        name = tool_input.get("file_path") if isinstance(tool_input, dict) else None
        tool = None
    elif name.startswith("mcp__") and "__" in name[5:]:
        kind = Kind.MCP
        name, tool = name[5:].split("__", 1)
    else:
        return None
    return (kind, name, call_id, tool) if isinstance(name, str) and name else None


def claude_event(event: dict, session: str) -> tuple[str, Any, list]:
    """提取 Claude 会话归因和明确的 tool_use 调用。"""
    if event.get("type") != "assistant":
        return session, None, []
    if isinstance(event.get("sessionId"), str):
        session = event["sessionId"]
    message = event.get("message") or {}
    if not isinstance(message, dict):
        return session, None, []
    content = message.get("content") or []
    calls = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                call = normalize_call(Client.CLAUDE, item.get("name"), item.get("id"), item.get("input"))
                if call:
                    calls.append(call)
    return session, event.get("attributionSkill"), calls


# pylint: disable=too-many-return-statements
def codex_event(event: dict, session: str) -> tuple[str, None, list]:
    """提取 Codex 会话 ID、MCP 结束事件及技能读取弱信号。"""
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return session, None, []
    if event.get("type") == "session_meta":
        return payload.get("id") or session, None, []
    if event.get("type") == "event_msg" and payload.get("type") == "mcp_tool_call_end":
        invocation = payload.get("invocation")
        if not isinstance(invocation, dict):
            return session, None, []
        server, tool = invocation.get("server"), invocation.get("tool")
        if isinstance(server, str) and server and isinstance(tool, str) and tool:
            return session, None, [(Kind.MCP, server, payload.get("call_id"), tool)]
        return session, None, []
    if event.get("type") != "response_item" or payload.get("type") not in (
        "function_call",
        "custom_tool_call",
    ):
        return session, None, []
    call = normalize_call(Client.CODEX, payload.get("name"), payload.get("call_id"), None)
    calls = [call] if call else []
    if payload.get("name") in (
        "exec_command",
        "exec",
        "functions.exec",
    ):
        arguments = payload.get("arguments" if payload["type"] == "function_call" else "input")
        if isinstance(arguments, str):
            names = {
                match.group(1)
                for match in SKILL_READ.finditer(arguments.replace("\\/", "/"))
                if match.group(1) != ".system" and "/.system/" not in arguments
            }
            call_id = payload.get("call_id")
            calls.extend((Kind.SKILL, name, f"{call_id}:{name}" if call_id else None, None) for name in names)
    return session, None, calls


def opencode_mcp_tool(name: str, servers: set[str], configured: bool) -> tuple[str, str] | None:
    """优先按配置名称匹配 MCP 工具，仅配置不可读时按前缀推断。"""
    for server in sorted(servers, key=len, reverse=True):
        for candidate in (server, server.replace("-", "_")):
            prefix = candidate + "_"
            if name.startswith(prefix) and len(name) > len(prefix):
                return server, name[len(prefix) :]
    if not configured and "_" in name:
        server, tool = name.split("_", 1)
        if server and tool:
            return server, tool
    return None


def opencode_call(
    home: Path, name: str, tool_input: dict, servers: set[str], configured: bool
) -> tuple[Kind, str | None, str | None] | None:
    """将 OpenCode 工具名与输入映射为报告类别、名称和 MCP 工具名。"""
    if name.lower() == "skill":
        return Kind.SKILL, tool_input.get("name"), None
    if name.lower() == "read":
        return (
            Kind.RULE,
            rule_name(home, tool_input.get("filePath") or tool_input.get("file_path")),
            None,
        )
    mcp = opencode_mcp_tool(name, servers, configured)
    return (Kind.MCP, *mcp) if mcp else None

"""定义客户端、记录类别及统一统计记录。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..utils.compat import StrEnum


class Client(StrEnum):
    """报告支持的客户端标识及全选参数。"""

    ALL = "all"
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"


class Kind(StrEnum):
    """报告支持的记录类别及全选参数。"""

    ALL = "all"
    SKILL = "skill"
    MCP = "mcp"
    RULE = "rule"
    COMMAND = "command"


class OutputFormat(StrEnum):
    """报告支持的终端表格与 JSON 输出格式。"""

    TABLE = "table"
    JSON = "json"


class ReportMode(StrEnum):
    """控制报告是否显示没有使用记录的条目。"""

    CONCISE = "concise"
    FULL = "full"  # noqa


# 支持的客户端及默认选择。
CLIENTS = tuple(client for client in Client if client != Client.ALL)
# 默认统计 Claude 和 Codex。
DEFAULT_CLIENTS = (Client.CLAUDE, Client.CODEX)
# 产品名在表头和日志来源中使用统一大小写。
CLIENT_LABELS = {Client.CLAUDE: "Claude", Client.CODEX: "Codex", Client.OPENCODE: "OpenCode"}
# 各客户端独有的技能目录。
SKILL_DIRS = {
    Client.CLAUDE: ".claude/skills",
    Client.CODEX: ".codex/skills",
    Client.OPENCODE: ".config/opencode/skills",
}
# 两种客户端的会话日志目录。
LOG_DIRS = {
    Client.CLAUDE: (".claude/projects",),
    Client.CODEX: (".codex/sessions", ".codex/archived_sessions"),
}
# Hook 事件数据库保留在 chezmoi 忽略的本机状态目录。
HOOK_DB = ".local/state/agent-usage/usage.sqlite3"
# OpenCode 的工具调用保存在本机 SQLite 数据库中。
OPENCODE_DB = ".local/share/opencode/opencode.db"
# 只把明确的技能文件路径当作 Codex 技能读取的弱信号。
SKILL_READ = re.compile(r"(?:^|/)skills/([A-Za-z0-9._-]+)/SKILL\.md\b")
# 可明确归类的用户规则目录和文件。
RULE_ROOTS = {Client.CLAUDE: ".claude/rules", Client.CODEX: ".codex/rules"}
RULE_FILES = {
    Client.CLAUDE: ".claude/CLAUDE.md",
    Client.CODEX: ".codex/AGENTS.md",
    Client.OPENCODE: ".config/opencode/AGENTS.md",
}
# 项目级规则仅在工具明确读取时纳入统计，不遍历整个用户目录。
RULE_BASENAMES = ("AGENTS.md", "CLAUDE.md")
# 报告统一使用北京时间，底层日志仍保留 UTC。
BEIJING_TIMEZONE = timezone(timedelta(hours=8))


def timestamp(value: object) -> str | None:
    """将日志时间转为 UTC ISO 格式，无效值返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def later(first: str | None, second: str | None) -> str | None:
    """返回两个标准化时间中的较晚值。"""
    return max(value for value in (first, second) if value) if first or second else None


def earlier(first: str | None, second: str | None) -> str | None:
    """返回两个标准化时间中的较早值。"""
    return min(value for value in (first, second) if value) if first or second else None


def record(records: dict, kind: Kind | str, name: str) -> dict:
    """获取一项技能或 MCP 的统计记录。"""
    key = (kind, name)
    if key not in records:
        records[key] = {
            "kind": kind,
            "name": name,
            "calls": None if kind == Kind.RULE else 0,
            "calls_by_client": {},
            "tool_calls": {},
            "inferred_calls": 0,
            "hook_calls": 0,
            "last_used": None,
            "expansions": 0,
            "last_expanded": None,
            "attributed_sessions": 0,
            "last_attributed": None,
            "reads": 0,
            "last_read": None,
            "installed_paths": [],
            "configured_clients": [],
            "evidence": [],
        }
    return records[key]


def observed(row: dict) -> bool:
    """判断一项是否有可展示的调用或读取证据。"""
    return any(row[field] for field in ("calls", "expansions", "attributed_sessions", "reads"))


def beijing_time(value: str | None) -> str | None:
    """将 UTC 时间转成带 +08:00 偏移的北京时间。"""
    if value is None:
        return None
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(BEIJING_TIMEZONE).isoformat(timespec="seconds")
    )


def localize_report(report: dict) -> None:
    """转换报告的时间字段，供表格和 JSON 共用。"""
    for row in report["items"]:
        for field in ("last_used", "last_expanded", "last_attributed", "last_read"):
            row[field] = beijing_time(row[field])
    for stats in report["coverage"].values():
        for field in ("first", "last"):
            stats[field] = beijing_time(stats[field])


def display_time(value: str | None) -> str:
    """以紧凑的北京时间显示终端报告。"""
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S") if value else "-"

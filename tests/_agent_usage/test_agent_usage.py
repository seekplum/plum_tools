"""验证 agent_usage 的相关行为。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest import mock

import pytest
from rich.console import Console

from plum_tools._agent_usage.cli import main
from plum_tools._agent_usage.collectors import (
    collect,
    count_call,
    record_call,
    scan_hooks,
    scan_logs,
    scan_opencode,
)
from plum_tools._agent_usage.events import (
    claude_event,
    codex_event,
    iter_events,
    normalize_call,
    opencode_call,
    opencode_mcp_tool,
)
from plum_tools._agent_usage.inventory import claude_mcp_names, inventory, opencode_mcp_names, rule_name
from plum_tools._agent_usage.models import (
    Client,
    Kind,
    beijing_time,
    display_time,
    earlier,
    later,
    localize_report,
    observed,
    record,
    timestamp,
)
from plum_tools._agent_usage.reporting import print_mcp_tools, print_rich, print_rich_coverage, rich_cells
from plum_tools.utils.compat import StrEnum, tomllib

# ---------- models.py ----------


def test_timestamp_valid_z() -> None:
    assert timestamp("2024-01-01T00:00:00Z") == "2024-01-01T00:00:00Z"


def test_timestamp_valid_offset_normalized_to_utc() -> None:
    assert timestamp("2024-01-01T08:00:00+08:00") == "2024-01-01T00:00:00Z"


def test_timestamp_non_string() -> None:
    assert timestamp(123) is None
    assert timestamp(None) is None


def test_timestamp_invalid_string() -> None:
    assert timestamp("not-a-time") is None


def test_timestamp_no_timezone() -> None:
    assert timestamp("2024-01-01T00:00:00") is None


def test_later_and_earlier() -> None:
    a = "2024-01-01T00:00:00Z"
    b = "2024-01-02T00:00:00Z"
    assert later(a, b) == b
    assert later(b, a) == b
    assert earlier(a, b) == a
    assert earlier(b, a) == a


def test_later_earlier_with_none() -> None:
    a = "2024-01-01T00:00:00Z"
    assert later(a, None) == a
    assert earlier(None, a) == a
    assert later(None, None) is None
    assert earlier(None, None) is None


def test_record_creates_skill_entry() -> None:
    records: dict = {}
    row = record(records, Kind.SKILL, "demo")
    assert row["kind"] == Kind.SKILL
    assert row["name"] == "demo"
    assert row["calls"] == 0
    assert row["reads"] == 0
    assert row["evidence"] == []


def test_record_rule_calls_none() -> None:
    records: dict = {}
    row = record(records, Kind.RULE, "rule")
    assert row["calls"] is None


def test_record_returns_same_object() -> None:
    records: dict = {}
    row1 = record(records, Kind.SKILL, "demo")
    row2 = record(records, Kind.SKILL, "demo")
    assert row1 is row2


def test_observed_true_when_calls() -> None:
    assert observed({"calls": 1, "expansions": 0, "attributed_sessions": 0, "reads": 0}) is True


def test_observed_true_when_reads() -> None:
    assert observed({"calls": 0, "expansions": 0, "attributed_sessions": 0, "reads": 1}) is True


def test_observed_false_when_all_zero() -> None:
    assert observed({"calls": 0, "expansions": 0, "attributed_sessions": 0, "reads": 0}) is False


def test_observed_rule_with_none_calls_and_reads() -> None:
    assert observed({"calls": None, "expansions": 0, "attributed_sessions": 0, "reads": 1}) is True


def test_beijing_time_none() -> None:
    assert beijing_time(None) is None


def test_beijing_time_converts() -> None:
    assert beijing_time("2024-01-01T00:00:00Z") == "2024-01-01T08:00:00+08:00"


def test_display_time_none() -> None:
    assert display_time(None) == "-"


def test_display_time_formats() -> None:
    assert display_time("2024-01-01T08:00:00+08:00") == "2024-01-01 08:00:00"


def test_localize_report_converts_time_fields() -> None:
    report: dict = {
        "items": [
            {
                "last_used": "2024-01-01T00:00:00Z",
                "last_expanded": None,
                "last_attributed": None,
                "last_read": None,
            }
        ],
        "coverage": {"stats": {"first": "2024-01-01T00:00:00Z", "last": None}},
    }
    localize_report(report)
    assert report["items"][0]["last_used"] == "2024-01-01T08:00:00+08:00"
    assert report["items"][0]["last_expanded"] is None
    assert report["coverage"]["stats"]["first"] == "2024-01-01T08:00:00+08:00"


# ---------- compat.py ----------


def test_str_enum_str_returns_value() -> None:
    class Color(StrEnum):
        RED = "red"

    assert str(Color.RED) == "red"


def test_tomllib_importable() -> None:
    assert tomllib is not None


# ---------- events.py ----------


def test_normalize_call_claude_skill() -> None:
    assert normalize_call(Client.CLAUDE, "Skill", "id1", {"skill": "demo"}) == (Kind.SKILL, "demo", "id1", None)


def test_normalize_call_claude_read() -> None:
    assert normalize_call(Client.CLAUDE, "Read", "id2", {"file_path": "/a/b.md"}) == (
        Kind.RULE,
        "/a/b.md",
        "id2",
        None,
    )


def test_normalize_call_mcp() -> None:
    assert normalize_call(Client.CODEX, "mcp__server__tool", "id3", None) == (Kind.MCP, "server", "id3", "tool")


def test_normalize_call_invalid_name() -> None:
    assert normalize_call(Client.CLAUDE, 123, "id", None) is None


def test_normalize_call_mcp_no_separator() -> None:
    assert normalize_call(Client.CODEX, "mcp__noseparator", "id", None) is None


def test_normalize_call_empty_name() -> None:
    assert normalize_call(Client.CLAUDE, "Skill", "id", {"skill": ""}) is None


def test_claude_event_non_assistant() -> None:
    session, _, calls = claude_event({"type": "user"}, "sess1")
    assert session == "sess1"
    assert calls == []


def test_claude_event_updates_session() -> None:
    session, _, _ = claude_event({"type": "assistant", "sessionId": "sess2"}, "sess1")
    assert session == "sess2"


def test_claude_event_extracts_tool_use() -> None:
    event = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Skill", "id": "t1", "input": {"skill": "demo"}}]},
    }
    _, _, calls = claude_event(event, "sess1")
    assert calls == [(Kind.SKILL, "demo", "t1", None)]


def test_claude_event_message_not_dict() -> None:
    _, _, calls = claude_event({"type": "assistant", "message": "not-dict"}, "sess1")
    assert calls == []


def test_codex_event_payload_not_dict() -> None:
    _, _, calls = codex_event({"payload": "x"}, "sess1")
    assert calls == []


def test_codex_event_session_meta() -> None:
    session, _, calls = codex_event({"type": "session_meta", "payload": {"id": "sess9"}}, "sess1")
    assert session == "sess9"
    assert calls == []


def test_codex_event_mcp_tool_call_end() -> None:
    event = {
        "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "invocation": {"server": "srv", "tool": "tool1"},
            "call_id": "c1",
        },
    }
    _, _, calls = codex_event(event, "sess1")
    assert calls == [(Kind.MCP, "srv", "c1", "tool1")]


def test_codex_event_skill_read_weak_signal() -> None:
    event = {
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "exec_command",
            "call_id": "c2",
            "arguments": "cat /home/skills/demo/SKILL.md",
        },
    }
    _, _, calls = codex_event(event, "sess1")
    assert (Kind.SKILL, "demo", "c2:demo", None) in calls


def test_codex_event_skill_read_excludes_system() -> None:
    event = {
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "exec_command",
            "call_id": "c3",
            "arguments": "cat /home/skills/.system/SKILL.md",
        },
    }
    _, _, calls = codex_event(event, "sess1")
    skill_calls = [call for call in calls if call[0] == Kind.SKILL]
    assert skill_calls == []


def test_opencode_mcp_tool_matches_configured() -> None:
    assert opencode_mcp_tool("server_tool", {"server"}, True) == ("server", "tool")


def test_opencode_mcp_tool_dash_to_underscore() -> None:
    assert opencode_mcp_tool("my-server_tool", {"my-server"}, True) == ("my-server", "tool")


def test_opencode_mcp_tool_infer_when_not_configured() -> None:
    assert opencode_mcp_tool("foo_bar", set(), False) == ("foo", "bar")


def test_opencode_mcp_tool_no_underscore() -> None:
    assert opencode_mcp_tool("foobar", set(), False) is None


def test_opencode_call_skill() -> None:
    assert opencode_call(Path("/home"), "skill", {"name": "demo"}, set(), True) == (Kind.SKILL, "demo", None)


def test_opencode_call_read_rule() -> None:
    with mock.patch("plum_tools._agent_usage.events.rule_name", return_value="CLAUDE.md"):
        assert opencode_call(Path("/home"), "read", {"filePath": "/x/CLAUDE.md"}, set(), True) == (
            Kind.RULE,
            "CLAUDE.md",
            None,
        )


def test_opencode_call_mcp() -> None:
    assert opencode_call(Path("/home"), "server_tool", {}, {"server"}, True) == (Kind.MCP, "server", "tool")


def test_iter_events_parses_lines(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text(
        '{"timestamp": "2024-01-01T00:00:00Z"}\nnot-json\n[1,2,3]\n{"timestamp": "2024-01-02T00:00:00Z"}\n',
        encoding="utf-8",
    )
    stats = {"first": None, "last": None, "invalid_lines": 0, "unreadable_files": 0}
    events = list(iter_events(path, stats))
    assert len(events) == 2
    assert stats["invalid_lines"] == 1
    assert stats["first"] == "2024-01-01T00:00:00Z"
    assert stats["last"] == "2024-01-02T00:00:00Z"


def test_iter_events_unreadable(tmp_path: Path) -> None:
    stats = {"first": None, "last": None, "invalid_lines": 0, "unreadable_files": 0}
    events = list(iter_events(tmp_path / "missing.jsonl", stats))
    assert events == []
    assert stats["unreadable_files"] == 1


# ---------- inventory.py ----------


def test_claude_mcp_names_merges_global_and_project(tmp_path: Path) -> None:
    config = {"mcpServers": {"global1": {}}, "projects": {"p1": {"mcpServers": {"proj1": {}}}}}
    path = tmp_path / ".claude.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert claude_mcp_names(path) == {"global1", "proj1"}


def test_opencode_mcp_names_json(tmp_path: Path) -> None:
    home = tmp_path
    (home / ".config/opencode").mkdir(parents=True)
    config: dict = {"mcp": {"servers": {"srv1": {}, "srv2": {}}}}
    (home / ".config/opencode/opencode.json").write_text(json.dumps(config), encoding="utf-8")
    names, configured = opencode_mcp_names(home)
    assert names == {"srv1", "srv2"}
    assert configured is True


def test_opencode_mcp_names_invalid_json(tmp_path: Path) -> None:
    home = tmp_path
    (home / ".config/opencode").mkdir(parents=True)
    (home / ".config/opencode/opencode.json").write_text("{invalid", encoding="utf-8")
    names, configured = opencode_mcp_names(home)
    assert names == set()
    assert configured is False


def test_opencode_mcp_names_mcp_not_dict(tmp_path: Path) -> None:
    home = tmp_path
    (home / ".config/opencode").mkdir(parents=True)
    (home / ".config/opencode/opencode.json").write_text(json.dumps({"mcp": "x"}), encoding="utf-8")
    names, configured = opencode_mcp_names(home)
    assert names == set()
    assert configured is True


def test_rule_name_non_string() -> None:
    assert rule_name(Path("/home"), 123) is None
    assert rule_name(Path("/home"), "") is None


def test_rule_name_not_absolute() -> None:
    assert rule_name(Path("/home"), "CLAUDE.md") is None


def test_rule_name_basename(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("x", encoding="utf-8")
    assert rule_name(tmp_path, str(tmp_path / "CLAUDE.md")) == "CLAUDE.md"


def test_rule_name_rule_root(tmp_path: Path) -> None:
    root = tmp_path / ".claude/rules"
    root.mkdir(parents=True)
    (root / "a.md").write_text("x", encoding="utf-8")
    assert rule_name(tmp_path, str(root / "a.md")) == ".claude/rules/a.md"


def test_rule_name_wrong_extension(tmp_path: Path) -> None:
    root = tmp_path / ".claude/rules"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("x", encoding="utf-8")
    assert rule_name(tmp_path, str(root / "a.txt")) is None


def test_rule_name_not_in_known_dirs(tmp_path: Path) -> None:
    (tmp_path / "other.md").write_text("x", encoding="utf-8")
    assert rule_name(tmp_path, str(tmp_path / "other.md")) is None


def test_inventory_records_skills_and_mcp(tmp_path: Path) -> None:
    skills = tmp_path / ".claude/skills/demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("x", encoding="utf-8")
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {"srv": {}}}), encoding="utf-8")
    records: dict = {}
    missing = inventory(tmp_path, records, (Client.CLAUDE,))
    assert (Kind.SKILL, "demo") in records
    assert (Kind.MCP, "srv") in records
    assert ".claude.json" not in missing


# ---------- collectors.py ----------


def test_count_call_skill_increments() -> None:
    records: dict = {}
    seen: set = set()
    count_call(records, seen, ("k1",), Kind.SKILL, "demo", Client.CLAUDE, "2024-01-01T00:00:00Z", "ev1")
    row = records[(Kind.SKILL, "demo")]
    assert row["calls"] == 1
    assert row["calls_by_client"][Client.CLAUDE] == 1
    assert row["evidence"] == ["ev1"]


def test_count_call_dedup() -> None:
    records: dict = {}
    seen: set = set()
    key = ("k1",)
    count_call(records, seen, key, Kind.SKILL, "demo", Client.CLAUDE, None, "ev1")
    count_call(records, seen, key, Kind.SKILL, "demo", Client.CLAUDE, None, "ev1")
    assert records[(Kind.SKILL, "demo")]["calls"] == 1


def test_count_call_rule_reads() -> None:
    records: dict = {}
    seen: set = set()
    count_call(records, seen, ("k1",), Kind.RULE, "rule", Client.CLAUDE, "2024-01-01T00:00:00Z", "ev1")
    row = records[(Kind.RULE, "rule")]
    assert row["reads"] == 1
    assert row["calls"] is None


def test_count_call_mcp_tool() -> None:
    records: dict = {}
    seen: set = set()
    count_call(records, seen, ("k1",), Kind.MCP, "srv", Client.CODEX, None, "ev1", "tool1")
    assert records[(Kind.MCP, "srv")]["tool_calls"]["tool1"] == 1


def test_count_call_codex_inferred() -> None:
    records: dict = {}
    seen: set = set()
    count_call(records, seen, ("k1",), Kind.SKILL, "demo", Client.CODEX, None, "codex_skill_file_reference")
    assert records[(Kind.SKILL, "demo")]["inferred_calls"] == 1


def test_count_call_evidence_dedup() -> None:
    records: dict = {}
    seen: set = set()
    count_call(records, seen, ("k1",), Kind.SKILL, "demo", Client.CLAUDE, None, "ev1")
    count_call(records, seen, ("k2",), Kind.SKILL, "demo", Client.CLAUDE, None, "ev1")
    assert records[(Kind.SKILL, "demo")]["evidence"] == ["ev1"]


def test_record_call_uses_call_id_key() -> None:
    records: dict = {}
    seen: set = set()
    call = (Kind.SKILL, "demo", "cid1", None)
    record_call(records, seen, Client.CLAUDE, call, Path("/x"), 1, None, Path("/home"))
    record_call(records, seen, Client.CLAUDE, call, Path("/x"), 1, None, Path("/home"))
    assert records[(Kind.SKILL, "demo")]["calls"] == 1


def test_record_call_rule_via_rule_name() -> None:
    records: dict = {}
    seen: set = set()
    with mock.patch("plum_tools._agent_usage.collectors.rule_name", return_value="CLAUDE.md"):
        record_call(
            records, seen, Client.CLAUDE, (Kind.RULE, "/home/CLAUDE.md", None, None), Path("/x"), 1, None, Path("/home")
        )
    assert records[(Kind.RULE, "CLAUDE.md")]["reads"] == 1


def test_record_call_rule_name_none_skips() -> None:
    records: dict = {}
    seen: set = set()
    with mock.patch("plum_tools._agent_usage.collectors.rule_name", return_value=None):
        record_call(records, seen, Client.CLAUDE, (Kind.RULE, "/x", None, None), Path("/x"), 1, None, Path("/home"))
    assert records == {}


def test_record_call_codex_evidence() -> None:
    records: dict = {}
    seen: set = set()
    record_call(records, seen, Client.CODEX, (Kind.SKILL, "demo", None, None), Path("/x"), 1, None, Path("/home"))
    assert "codex_skill_file_reference" in records[(Kind.SKILL, "demo")]["evidence"]


def test_scan_hooks_db_not_exists(tmp_path: Path) -> None:
    stats, seen = scan_hooks(tmp_path, {}, (Client.CLAUDE,))
    assert stats["exists"] is False
    assert seen == set()


def test_scan_hooks_command_expansion(tmp_path: Path) -> None:
    records: dict = {}
    record(records, Kind.SKILL, "demo")
    database = tmp_path / ".local/state/agent-usage/usage.sqlite3"
    database.parent.mkdir(parents=True)
    database.write_text("x", encoding="utf-8")
    fake_conn = mock.MagicMock()
    fake_conn.execute.return_value = [
        ("e1", "2024-01-01T00:00:00Z", Client.CLAUDE, Kind.COMMAND, "demo", "ok", None, None)
    ]
    with mock.patch("plum_tools._agent_usage.collectors.sqlite3.connect", return_value=fake_conn):
        _, _ = scan_hooks(tmp_path, records, (Client.CLAUDE,))
    assert records[(Kind.SKILL, "demo")]["expansions"] == 1


def test_scan_hooks_filters_client(tmp_path: Path) -> None:
    records: dict = {}
    database = tmp_path / ".local/state/agent-usage/usage.sqlite3"
    database.parent.mkdir(parents=True)
    database.write_text("x", encoding="utf-8")
    fake_conn = mock.MagicMock()
    fake_conn.execute.return_value = [
        ("e1", "2024-01-01T00:00:00Z", Client.OPENCODE, Kind.SKILL, "demo", "ok", None, None)
    ]
    with mock.patch("plum_tools._agent_usage.collectors.sqlite3.connect", return_value=fake_conn):
        stats, _ = scan_hooks(tmp_path, records, (Client.CLAUDE,))
    assert stats["events"] == 0
    assert records == {}


def test_scan_logs_no_dirs(tmp_path: Path) -> None:
    coverage = scan_logs(tmp_path, {}, set(), (Client.CLAUDE,))
    assert coverage[Client.CLAUDE]["files"] == 0


def test_scan_logs_reads_jsonl(tmp_path: Path) -> None:
    log_dir = tmp_path / ".claude/projects"
    log_dir.mkdir(parents=True)
    log_file = log_dir / "sess.jsonl"
    payload = (
        '{"type":"assistant","sessionId":"s1","message":{"content":[{"type":"tool_use",'
        '"name":"Skill","id":"t1","input":{"skill":"demo"}}]}}\n'
    )
    log_file.write_text(payload, encoding="utf-8")
    records: dict = {}
    coverage = scan_logs(tmp_path, records, set(), (Client.CLAUDE,))
    assert coverage[Client.CLAUDE]["files"] == 1
    assert records[(Kind.SKILL, "demo")]["calls"] == 1


def test_scan_opencode_db_not_exists(tmp_path: Path) -> None:
    stats = scan_opencode(tmp_path, {}, set())
    assert stats["exists"] is False


def test_scan_opencode_reads_rows(tmp_path: Path) -> None:
    database = tmp_path / ".local/share/opencode/opencode.db"
    database.parent.mkdir(parents=True)
    database.write_text("x", encoding="utf-8")
    fake_conn = mock.MagicMock()
    fake_conn.execute.return_value = [
        ("p1", 1700000000000, '{"type":"tool","tool":"skill","state":{"input":{"name":"demo"}}}')
    ]
    with (
        mock.patch("plum_tools._agent_usage.collectors.sqlite3.connect", return_value=fake_conn),
        mock.patch("plum_tools._agent_usage.collectors.opencode_mcp_names", return_value=(set(), True)),
    ):
        stats = scan_opencode(tmp_path, {}, set())
    assert stats["exists"] is True
    assert stats["events"] == 1


def test_scan_opencode_sqlite_error(tmp_path: Path) -> None:
    database = tmp_path / ".local/share/opencode/opencode.db"
    database.parent.mkdir(parents=True)
    database.write_text("x", encoding="utf-8")
    with (
        mock.patch("plum_tools._agent_usage.collectors.sqlite3.connect", side_effect=sqlite3.Error("boom")),
        mock.patch("plum_tools._agent_usage.collectors.opencode_mcp_names", return_value=(set(), True)),
    ):
        stats = scan_opencode(tmp_path, {}, set())
    assert stats["error"] == "Error"


def test_collect_default_clients(tmp_path: Path) -> None:
    report = collect(tmp_path)
    assert report["clients"] == [Client.CLAUDE, Client.CODEX]
    assert "limitations" in report
    assert "items" in report


# ---------- reporting.py ----------


def test_rich_cells_skill() -> None:
    row = record({}, Kind.SKILL, "demo")
    row["calls"] = 2
    row["calls_by_client"] = {Client.CLAUDE: 2}
    row["expansions"] = 1
    row["attributed_sessions"] = 3
    cells = rich_cells(Kind.SKILL, row, (Client.CLAUDE,))
    assert cells[0] == "demo"
    assert cells[1] == 2
    assert cells[2] == 2
    assert cells[3] == 1
    assert cells[4] == 3


def test_rich_cells_mcp() -> None:
    row = record({}, Kind.MCP, "srv")
    row["calls"] = 1
    row["calls_by_client"] = {Client.CLAUDE: 1}
    row["hook_calls"] = 2
    cells = rich_cells(Kind.MCP, row, (Client.CLAUDE,))
    assert cells[0] == "srv"
    assert cells[3] == 2


def test_rich_cells_rule() -> None:
    row = record({}, Kind.RULE, "rule")
    row["reads"] = 5
    assert rich_cells(Kind.RULE, row, (Client.CLAUDE,)) == ("rule", 5, "-")


def test_rich_cells_command() -> None:
    row = record({}, Kind.COMMAND, "cmd")
    row["expansions"] = 3
    assert rich_cells(Kind.COMMAND, row, (Client.CLAUDE,)) == ("cmd", 3, "-")


def test_print_rich_coverage_hooks_not_exists() -> None:
    report = {"coverage": {"hooks": {"exists": False}}, "missing_sources": [], "limitations": []}
    console = mock.MagicMock()
    print_rich_coverage(console, report)
    console.print.assert_any_call("Hook: 尚无本地数据库")


def test_print_rich_coverage_opencode_error() -> None:
    report = {
        "coverage": {
            Client.OPENCODE: {
                "exists": True,
                "events": 1,
                "invalid_rows": 0,
                "error": "Error",
                "first": None,
                "last": None,
            }
        },
        "missing_sources": [],
        "limitations": [],
    }
    console = mock.MagicMock()
    print_rich_coverage(console, report)
    console.print.assert_any_call("  读取失败: Error", style="yellow")


def test_print_mcp_tools_empty() -> None:
    console = mock.MagicMock()
    print_mcp_tools(console, [])
    console.print.assert_not_called()


def test_print_mcp_tools_sorted() -> None:
    rows = [{"name": "srv", "tool_calls": {"a": 1, "b": 2}}]
    console = mock.MagicMock()
    print_mcp_tools(console, rows)
    console.print.assert_called()


def test_print_rich_empty_items(capsys: pytest.CaptureFixture[str]) -> None:
    report = {"clients": [Client.CLAUDE], "items": [], "coverage": {}, "missing_sources": [], "limitations": []}
    print_rich(report)
    assert "没有可显示的使用记录" in capsys.readouterr().out


# ---------- cli.py ----------


def _make_row(kind: Kind, name: str, calls: int = 0) -> dict:
    row = record({}, kind, name)
    row["calls"] = calls
    return row


def test_cli_main_default() -> None:
    report = {"clients": [Client.CLAUDE], "items": [], "coverage": {}, "missing_sources": [], "limitations": []}
    with (
        mock.patch("sys.argv", ["agent_usage_report"]),
        mock.patch("plum_tools._agent_usage.cli.collect", return_value=report) as mock_collect,
        mock.patch("plum_tools._agent_usage.cli.print_rich") as mock_print,
    ):
        code = main()
    assert code == 0
    mock_collect.assert_called_once()
    mock_print.assert_called_once()


def test_cli_main_error_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        mock.patch("sys.argv", ["agent_usage_report"]),
        mock.patch("plum_tools._agent_usage.cli.collect", side_effect=OSError("boom")),
    ):
        code = main()
    assert code == 2
    assert "失败" in capsys.readouterr().err


def test_cli_main_kind_filter() -> None:
    report = {
        "clients": [Client.CLAUDE],
        "items": [_make_row(Kind.SKILL, "s", 1), _make_row(Kind.MCP, "m", 1)],
        "coverage": {},
        "missing_sources": [],
        "limitations": [],
    }
    with (
        mock.patch("sys.argv", ["agent_usage_report", "--kind", "skill"]),
        mock.patch("plum_tools._agent_usage.cli.collect", return_value=report),
        mock.patch("plum_tools._agent_usage.cli.print_rich") as mock_print,
    ):
        code = main()
    assert code == 0
    printed = mock_print.call_args[0][0]
    assert all(row["kind"] == Kind.SKILL for row in printed["items"])


def test_cli_main_concise_filters_unobserved() -> None:
    report = {
        "clients": [Client.CLAUDE],
        "items": [_make_row(Kind.SKILL, "s", 0)],
        "coverage": {},
        "missing_sources": [],
        "limitations": [],
    }
    with (
        mock.patch("sys.argv", ["agent_usage_report"]),
        mock.patch("plum_tools._agent_usage.cli.collect", return_value=report),
        mock.patch("plum_tools._agent_usage.cli.print_rich") as mock_print,
    ):
        code = main()
    assert code == 0
    assert mock_print.call_args[0][0]["items"] == []


def test_cli_main_json_format(capsys: pytest.CaptureFixture[str]) -> None:
    report = {"clients": [Client.CLAUDE], "items": [], "coverage": {}, "missing_sources": [], "limitations": []}
    with (
        mock.patch("sys.argv", ["agent_usage_report", "--format", "json"]),
        mock.patch("plum_tools._agent_usage.cli.collect", return_value=report),
        mock.patch("plum_tools._agent_usage.cli.print_rich") as mock_print,
    ):
        code = main()
    assert code == 0
    mock_print.assert_not_called()
    assert json.loads(capsys.readouterr().out)["clients"] == [Client.CLAUDE]


# ---------- reporting.py: rich_cells 与 print_rich ----------


def _make_rich_row(kind: Kind, name: str) -> dict:
    return record({}, kind, name)


def test_rich_cells_skill_with_all_fields() -> None:
    row = _make_rich_row(Kind.SKILL, "s")
    row["calls_by_client"][Client.CLAUDE] = 3
    row["last_expanded"] = "2024-01-01T00:00:00Z"
    row["last_attributed"] = "2024-02-01T00:00:00Z"
    cells = rich_cells(Kind.SKILL, row, (Client.CLAUDE,))
    assert cells[0] == "s"
    assert cells[1] == 0
    assert cells[-1] != "-"


def test_rich_cells_mcp_tool_calls() -> None:
    row = _make_rich_row(Kind.MCP, "m")
    row["calls_by_client"][Client.CLAUDE] = 1
    row["hook_calls"] = 2
    row["tool_calls"]["t"] = 5
    row["last_used"] = "2024-01-01T00:00:00Z"
    cells = rich_cells(Kind.MCP, row, (Client.CLAUDE,))
    assert cells[3] == 2
    assert cells[4] == "2024-01-01 00:00:00"


def test_print_rich_with_items(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_make_rich_row(Kind.SKILL, "s1"), _make_rich_row(Kind.MCP, "m1")]
    report: dict = {
        "clients": [Client.CLAUDE],
        "items": rows,
        "coverage": {},
        "missing_sources": ["x"],
        "limitations": ["note"],
    }
    report["items"][0]["calls"] = 1
    report["items"][0]["calls_by_client"][Client.CLAUDE] = 1
    report["items"][0]["last_used"] = "2024-01-01T00:00:00Z"
    report["items"][1]["calls"] = 1
    report["items"][1]["calls_by_client"][Client.CLAUDE] = 1
    report["items"][1]["last_used"] = "2024-01-01T00:00:00Z"
    print_rich(report)
    out = capsys.readouterr().out
    assert "技能" in out
    assert "MCP" in out
    assert "缺失来源" in out
    assert "注意" in out


def test_print_rich_mcp_tools_render(capsys: pytest.CaptureFixture[str]) -> None:
    report: dict = {
        "clients": [Client.CLAUDE],
        "items": [],
        "coverage": {},
        "missing_sources": [],
        "limitations": [],
    }
    mcp_row = _make_rich_row(Kind.MCP, "m1")
    mcp_row["tool_calls"] = {"tool1": 3, "tool2": 1}
    report["items"] = [mcp_row]
    print_rich(report)
    out = capsys.readouterr().out
    assert "MCP 工具" in out


# ---------- reporting.py: print_rich_coverage 各分支 ----------


def test_print_rich_coverage_hooks_exists(capsys: pytest.CaptureFixture[str]) -> None:
    report = {
        "coverage": {
            "hooks": {"exists": True, "events": 3, "first": "2024-01-01T00:00:00Z", "last": "2024-01-02T00:00:00Z"},
        },
        "missing_sources": [],
        "limitations": [],
    }
    print_rich_coverage(Console(force_terminal=False), report)
    out = capsys.readouterr().out
    assert "Hook" in out
    assert "个事件" in out


def test_print_rich_coverage_opencode(capsys: pytest.CaptureFixture[str]) -> None:
    report = {
        "coverage": {
            Client.OPENCODE: {
                "exists": True,
                "events": 2,
                "invalid_rows": 1,
                "error": None,
                "first": "2024-01-01T00:00:00Z",
                "last": "2024-01-02T00:00:00Z",
            },
        },
        "missing_sources": [],
        "limitations": [],
    }
    print_rich_coverage(Console(force_terminal=False), report)
    assert "OpenCode" in capsys.readouterr().out


def test_print_rich_coverage_claude_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    report = {
        "coverage": {
            Client.CLAUDE: {
                "files": 2,
                "invalid_lines": 1,
                "unreadable_files": 0,
                "first": "2024-01-01T00:00:00Z",
                "last": "2024-01-02T00:00:00Z",
            },
        },
        "missing_sources": [],
        "limitations": [],
    }
    print_rich_coverage(Console(force_terminal=False), report)
    out = capsys.readouterr().out
    assert "Claude" in out
    assert "个日志" in out


# ---------- collectors.py 补充 ----------


def test_collect_with_opencode_client(tmp_path: Path) -> None:
    report = collect(tmp_path, (Client.CLAUDE, Client.OPENCODE))
    assert Client.OPENCODE in report["clients"]
    assert Client.OPENCODE in report["coverage"]
    codex_notes = [note for note in report["limitations"] if "OpenCode" in note]
    assert codex_notes


def test_scan_hooks_skill_and_mcp(tmp_path: Path) -> None:
    database = tmp_path / ".local/state/agent-usage/usage.sqlite3"
    database.parent.mkdir(parents=True)
    database.write_text("x", encoding="utf-8")
    fake_conn = mock.MagicMock()
    fake_conn.execute.return_value = [
        ("e1", "2024-01-01T00:00:00Z", Client.CLAUDE, Kind.SKILL, "s1", "ok", "c1", None),
        ("e2", "2024-01-01T00:00:00Z", Client.CLAUDE, Kind.MCP, "m1", "ok", "c2", "mcp__m1__t1"),
    ]
    records: dict = {}
    with mock.patch("plum_tools._agent_usage.collectors.sqlite3.connect", return_value=fake_conn):
        stats, seen = scan_hooks(tmp_path, records, (Client.CLAUDE,))
    assert stats["events"] == 2
    assert records[("skill", "s1")]["calls"] == 1
    assert records[("mcp", "m1")]["calls"] == 1
    assert records[("mcp", "m1")]["tool_calls"]["t1"] == 1
    assert seen


def test_scan_opencode_invalid_rows(tmp_path: Path) -> None:
    database = tmp_path / ".local/share/opencode/opencode.db"
    database.parent.mkdir(parents=True)
    database.write_text("x", encoding="utf-8")
    fake_conn = mock.MagicMock()
    fake_conn.execute.return_value = [
        ("p1", 1000, "not-json"),
        ("p2", 1000, '{"type":"tool","tool":"Read","state":{"input":{"filePath":"/x"}}}'),
    ]
    with mock.patch("plum_tools._agent_usage.collectors.sqlite3.connect", return_value=fake_conn):
        stats = scan_opencode(tmp_path, {}, set())
    assert stats["invalid_rows"] == 1
    assert stats["events"] == 1


def test_scan_opencode_tool_without_target_skips(tmp_path: Path) -> None:
    database = tmp_path / ".local/share/opencode/opencode.db"
    database.parent.mkdir(parents=True)
    database.write_text("x", encoding="utf-8")
    fake_conn = mock.MagicMock()
    fake_conn.execute.return_value = [("p1", 1000, '{"type":"tool","tool":"Other","state":{}}')]
    with mock.patch("plum_tools._agent_usage.collectors.sqlite3.connect", return_value=fake_conn):
        stats = scan_opencode(tmp_path, {}, set())
    assert stats["events"] == 1


# ---------- inventory.py 补充 ----------


def test_inventory_codex_config_missing(tmp_path: Path) -> None:
    missing = inventory(tmp_path, {}, (Client.CODEX,))
    assert ".codex/config.toml" in missing


def test_inventory_claude_config_missing(tmp_path: Path) -> None:
    missing = inventory(tmp_path, {}, (Client.CLAUDE,))
    assert ".claude.json" in missing


def test_inventory_skills_missing_paths(tmp_path: Path) -> None:
    missing = inventory(tmp_path, {}, (Client.CLAUDE,))
    assert ".agents/skills" in missing
    assert ".claude/skills" in missing


def test_inventory_records_installed_skill(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".claude" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("x", encoding="utf-8")
    records: dict = {}
    inventory(tmp_path, records, (Client.CLAUDE,))
    assert ("skill", "demo") in records
    assert ".claude/skills/demo" in records[("skill", "demo")]["installed_paths"]


def test_inventory_rules_from_root(tmp_path: Path) -> None:
    rule_dir = tmp_path / ".claude" / "rules"
    rule_dir.mkdir(parents=True)
    (rule_dir / "a.md").write_text("x", encoding="utf-8")
    records: dict = {}
    inventory(tmp_path, records, (Client.CLAUDE,))
    assert ("rule", ".claude/rules/a.md") in records


def test_opencode_mcp_names_jsonc_missing(tmp_path: Path) -> None:
    names, configured = opencode_mcp_names(tmp_path)
    assert names == set()
    assert configured is False

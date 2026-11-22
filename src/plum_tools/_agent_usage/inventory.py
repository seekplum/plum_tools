"""发现所选客户端的技能、规则及 MCP 配置。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..utils.compat import tomllib
from .models import RULE_BASENAMES, RULE_FILES, RULE_ROOTS, SKILL_DIRS, Client, Kind, record


def claude_mcp_names(path: Path) -> set[str]:
    """合并 Claude 全局和项目级 MCP 配置名称。"""
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    names = set(config.get("mcpServers", {}))
    for project in config.get("projects", {}).values():
        if isinstance(project, dict):
            names.update(project.get("mcpServers", {}))
    return names


def opencode_mcp_names(home: Path) -> tuple[set[str], bool]:
    """读取可直接解析的 OpenCode JSON 配置，返回名称和解析状态。"""
    for relative in (
        ".config/opencode/opencode.json",
        ".config/opencode/opencode.jsonc",
    ):
        path = home / relative
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8") as stream:
                config = json.load(stream)
        except (OSError, ValueError):
            return set(), False
        mcp = config.get("mcp", {}) if isinstance(config, dict) else {}
        if not isinstance(mcp, dict):
            return set(), True
        servers = mcp.get("servers", mcp)
        return set(servers) if isinstance(servers, dict) else set(), True
    return set(), False


def inventory(home: Path, records: dict, clients: tuple[Client, ...]) -> list[str]:
    """读取已安装技能、规则和当前 MCP 配置名称。"""
    missing = _inventory_skills(home, records, clients)
    missing.extend(_inventory_mcp(home, records, clients))
    _inventory_rules(home, records, clients)
    return missing


def _inventory_skills(home: Path, records: dict, clients: tuple[Client, ...]) -> list[str]:
    """读取共享与客户端技能目录，并返回缺失的来源。"""
    missing = []
    for relative in (".agents/skills", *(SKILL_DIRS[client] for client in clients)):
        directory = home / relative
        if not directory.is_dir():
            if relative != SKILL_DIRS[Client.OPENCODE]:
                missing.append(relative)
            continue
        for skill in directory.iterdir():
            if skill.is_dir() and (skill / "SKILL.md").is_file():
                record(records, Kind.SKILL, skill.name)["installed_paths"].append(relative + "/" + skill.name)

    return missing


def _inventory_mcp(home: Path, records: dict, clients: tuple[Client, ...]) -> list[str]:
    """合并所选客户端的 MCP 配置，返回缺失配置路径。"""
    missing = []
    if Client.CODEX in clients:
        codex_config = home / ".codex/config.toml"
        if codex_config.is_file():
            with codex_config.open("rb") as stream:
                config = tomllib.load(stream)
            for name in config.get("mcp_servers", {}):
                record(records, Kind.MCP, name)["configured_clients"].append(Client.CODEX)
        else:
            missing.append(".codex/config.toml")

    if Client.CLAUDE in clients:
        claude_config = home / ".claude.json"
        if claude_config.is_file():
            for name in claude_mcp_names(claude_config):
                record(records, Kind.MCP, name)["configured_clients"].append(Client.CLAUDE)
        else:
            missing.append(".claude.json")

    if Client.OPENCODE in clients:
        opencode_names, _ = opencode_mcp_names(home)
        for name in opencode_names:
            record(records, Kind.MCP, name)["configured_clients"].append(Client.OPENCODE)

    return missing


def _inventory_rules(home: Path, records: dict, clients: tuple[Client, ...]) -> None:
    """读取所选客户端的已知规则文件，避免遍历整个用户目录。"""
    for client in clients:
        rule_root = RULE_ROOTS.get(client)
        root = home / rule_root if rule_root else None
        if root and root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in (".md", ".rules"):
                    record(records, Kind.RULE, path.relative_to(home).as_posix())
    for relative in (".agents/AGENTS.md", *(RULE_FILES[client] for client in clients)):
        if (home / relative).is_file():
            record(records, Kind.RULE, relative)


def rule_name(home: Path, value: object) -> str | None:
    """仅接受已知规则目录中的实际文件，返回相对用户目录的名称。"""
    if not isinstance(value, str) or not value:
        return None
    path = Path(os.path.expanduser(value))
    if not path.is_absolute():
        return None
    try:
        relative = Path(os.path.abspath(path)).relative_to(home.absolute()).as_posix()
    except ValueError:
        return None
    if path.name in RULE_BASENAMES:
        return relative
    if any(relative.startswith(root + "/") for root in RULE_ROOTS.values()):
        return relative if path.suffix in (".md", ".rules") else None
    return None

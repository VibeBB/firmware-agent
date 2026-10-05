"""Docs coverage: every tool, subcommand, agent, skill, command and hook
name appears in the corresponding docs file."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from firmware import cli, mcp_server

ROOT = Path(__file__).resolve().parents[1]


def _doc(name: str) -> str:
    return (ROOT / "docs" / name).read_text(encoding="utf-8")


def _cli_subcommands() -> set[str]:
    parser: Any = vars(cli)["_parser"]()  # test the real argparse tree
    subs: set[str] = set()
    for action in parser._subparsers._group_actions:
        choices = getattr(action, "choices", None)
        if choices:
            subs.update(cast(set[str], choices))
    return subs


def test_every_mcp_tool_documented() -> None:
    doc = _doc("mcp.md")
    for tool in mcp_server.TOOLS:
        assert tool in doc, tool


def test_every_cli_subcommand_documented() -> None:
    doc = _doc("commands.md")
    for name in _cli_subcommands():
        assert re.search(rf"`{re.escape(name)}`", doc), name


def test_every_agent_documented() -> None:
    doc = _doc("agents.md")
    for path in (ROOT / "plugins/firmware/agents").glob("*.md"):
        assert path.stem in doc, path.stem


def test_every_skill_documented() -> None:
    doc = _doc("skills.md")
    for path in (ROOT / "plugins/firmware/skills").iterdir():
        if path.is_dir():
            assert path.name in doc, path.name


def test_every_command_doc_documented() -> None:
    doc = _doc("commands.md")
    for path in (ROOT / "plugins/firmware/commands").glob("*.md"):
        assert path.stem in doc, path.stem


def test_every_hook_documented() -> None:
    doc = _doc("hooks.md")
    hooks = json.loads((ROOT / "plugins/firmware/hooks/hooks.json").read_text())
    for entries in hooks.values():
        for entry in entries:
            for hook in entry["hooks"]:
                assert hook["name"] in doc, hook["name"]

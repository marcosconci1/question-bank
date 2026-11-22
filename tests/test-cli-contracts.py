"""Cross-client contract tests across MCP, Hermes, and Claude Code packaging."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from mcp.client import Client

from question_bank.mcp_server import create_server

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_hermes_tools():
    tools_path = REPO_ROOT / "integrations" / "hermes" / "question-bank" / "tools.py"
    spec = importlib.util.spec_from_file_location("hermes_qb_contract_tools", tools_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_mcp_and_hermes_expose_matching_tool_names_and_parameters(tmp_path):
    (tmp_path / "questions").mkdir()
    server = create_server(tmp_path)
    async with Client(server, mode="legacy") as client:
        mcp_tools = {
            tool.name: set((tool.input_schema or {}).get("properties", {}).keys())
            for tool in (await client.list_tools()).tools
        }

    hermes_tools_mod = _load_hermes_tools()
    hermes_registered: dict[str, set[str]] = {}

    class _FakeContext:
        def register_tool(self, *, name, schema, **kwargs):
            hermes_registered[name] = set(schema["parameters"]["properties"].keys())

    hermes_tools_mod.register(_FakeContext())

    assert set(mcp_tools) == set(hermes_registered) == {
        "search-questions",
        "get-question",
        "list-topics",
        "get-stats",
    }
    for name in mcp_tools:
        assert mcp_tools[name] == hermes_registered[name], f"parameter mismatch on {name}"


def test_hermes_plugin_manifest_lists_all_four_tools():
    manifest = (
        REPO_ROOT / "integrations" / "hermes" / "question-bank" / "plugin.yaml"
    ).read_text(encoding="utf-8")
    for tool_name in ("search-questions", "get-question", "list-topics", "get-stats"):
        assert tool_name in manifest


def test_claude_plugin_manifests_are_valid_json():
    claude_dir = REPO_ROOT / "integrations" / "claude"
    plugin = json.loads((claude_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    mcp_cfg = json.loads((claude_dir / ".mcp.json").read_text(encoding="utf-8"))

    assert plugin["name"] == "question-bank"
    assert plugin["mcpServers"] == "./.mcp.json"
    assert "question-bank" in mcp_cfg["mcpServers"]
    assert "question-bank-mcp" in mcp_cfg["mcpServers"]["question-bank"]["args"]

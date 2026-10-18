"""Тесты сборки defmcp-сервера: регистрация инструментов, схемы, аудит."""

import asyncio
import json
import os

import pytest

from pdm_cli.defmcp.context import BpContext
from pdm_cli.defmcp.server import build_context, make_server

EXPECTED_TOOLS = {
    "bp_list_files",
    "bp_read_file",
    "bp_edit_file",
    "bp_new_process",
    "bp_compile",
    "bp_draft_from_server",
    "bp_draft_save",
    "bp_draft_status",
    "bp_script_check",
    "bp_test",
}

# Д8 (спека 143): git-цикл агента удалён — этих инструментов больше нет
REMOVED_TOOLS = {
    "bp_drift",
    "bp_commit",
    "bp_push_sandbox",
}


@pytest.fixture()
def ctx(tmp_path):
    ws = tmp_path / "ws"
    bp = ws / "testbp"
    bp.mkdir(parents=True)
    (bp / "process.yaml").write_text("slug: testbp\n", encoding="utf-8")
    ctx = BpContext(repo_root=tmp_path, drafts_root=ws)
    ctx.audit_path = tmp_path / ".pdm" / "defmcp" / "audit.jsonl"
    return ctx


def _tools(server):
    return {t.name: t for t in asyncio.run(server.list_tools())}


def test_server_registers_all_tools(ctx):
    names = set(_tools(make_server(ctx)))
    assert EXPECTED_TOOLS <= names


def test_git_cycle_tools_are_gone(ctx):
    """Д8: bp_drift/bp_commit/bp_push_sandbox удалены — их вызов в промте
    агента невозможен (канон промта v3 в репо — W8; копию в Mongo
    LibreChat обновляет человек, см. handoff §6)."""
    names = set(_tools(make_server(ctx)))
    assert REMOVED_TOOLS & names == set()


def test_tools_have_description_and_object_schema(ctx):
    for name, tool in _tools(make_server(ctx)).items():
        if name not in EXPECTED_TOOLS:
            continue
        assert tool.description, name
        assert tool.inputSchema.get("type") == "object", name


def test_edit_file_schema_declares_path_and_content(ctx):
    tools = _tools(make_server(ctx))
    props = tools["bp_edit_file"].inputSchema["properties"]
    assert "path" in props and "content" in props


def test_draft_tools_schema_requires_slug(ctx):
    tools = _tools(make_server(ctx))
    for name in ("bp_draft_from_server", "bp_draft_save", "bp_draft_status"):
        schema = tools[name].inputSchema
        assert schema["properties"]["slug"].get("type") == "string", name
        assert "slug" in schema.get("required", []), name


def test_build_context_reads_drafts_root_env(tmp_path, monkeypatch):
    """MCP_BP_DRAFTS_ROOT (compose mcp-pdm-bp) попадает в контекст."""
    monkeypatch.setenv("MCP_BP_DRAFTS_ROOT", str(tmp_path / "drafts"))
    monkeypatch.delenv("PDM_API_BASE", raising=False)
    monkeypatch.delenv("PDM_API_TOKEN", raising=False)
    ctx = build_context(tmp_path)
    assert ctx.drafts_root == tmp_path / "drafts"
    assert ctx.api is None


def test_build_context_drafts_root_defaults_to_none(tmp_path, monkeypatch):
    monkeypatch.delenv("MCP_BP_DRAFTS_ROOT", raising=False)
    monkeypatch.delenv("PDM_API_BASE", raising=False)
    monkeypatch.delenv("PDM_API_TOKEN", raising=False)
    assert build_context(tmp_path).drafts_root is None


def test_audit_jsonl_written_on_tool_call(ctx):
    server = make_server(ctx)
    try:
        asyncio.run(server.call_tool("bp_compile", {}))
    except Exception:
        pass  # ошибка инструмента допустима — аудит обязан записаться
    assert ctx.audit_path.exists()
    line = ctx.audit_path.read_text(encoding="utf-8").strip().splitlines()[0]
    assert '"bp_compile"' in line
    assert '"duration_ms"' in line


def test_list_files_passes_ctx_and_returns_files(ctx):
    server = make_server(ctx)
    result = asyncio.run(server.call_tool("bp_list_files", {"slug": "testbp"}))
    payload = result[0].text if hasattr(result[0], "text") else result
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload.get("status") != "error", payload
    assert "testbp/process.yaml" in payload.get("files", [])

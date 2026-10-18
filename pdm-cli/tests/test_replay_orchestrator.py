"""Etap 7 Phase 4 — replay_with_override snapshot/inject/run/restore."""
from unittest.mock import MagicMock, patch

from pdm_cli.sandbox_mcp.replay_orchestrator import replay_with_override


def _ctx():
    return {
        "repo_root": MagicMock(),
        "hoverfly_admin": "http://hf",
        "ssh_replay_journal": "http://ssh",
        "sandbox_db_dsn": "",
        "pdm_api_base": "http://api",
        "pdm_api_key": "k",
        "ssh_override_dir": MagicMock(),
        "call_timeout": 300,
        "api": MagicMock(),
    }


def test_orchestrator_overrides_entity_fields_then_starts_run():
    ctx = _ctx()
    ctx["api"].run_details.return_value = {
        "id": 100, "bp": "p",
        "entity": {"id": 7, "type": "E", "fields": {}},
        "context_data": {},
    }
    ctx["api"].entity_clone_with_overrides.return_value = {
        "id": 8, "entity_type": 99, "data": {"x": 10}
    }
    fake_case_result = MagicMock(run_id="200", status="passed",
                                 process_status="completed", assertions=[],
                                 error="")
    with patch("pdm_cli.sandbox_mcp.replay_orchestrator.HoverflyOverrideContext"), \
         patch("pdm_cli.sandbox_mcp.replay_orchestrator.SshOverrideContext"), \
         patch("pdm_cli.test_runner.runner.run_case",
               return_value=fake_case_result):
        out = replay_with_override(ctx, "100", {"entity_fields": {"x": 10}})
    assert out["run_id"] == "200"
    assert out["source_run_id"] == "100"
    assert out["overrides_applied"]["entity_fields_count"] == 1


def test_orchestrator_rejects_too_many_overrides():
    ctx = _ctx()
    too_many = [{"matcher": {}, "response": {}} for _ in range(60)]
    out = replay_with_override(ctx, "100", {"http_fixtures": too_many})
    assert out["status"] == "error"
    assert "too many" in out["error"].lower()

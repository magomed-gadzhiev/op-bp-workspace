import pytest
from pdm_cli.test_case import TestCase, load_test_case

def test_minimal_case_with_entity_id_parses():
    data = {
        "name": "smoke", "fixtures": ["happy-path"],
        "entity_id": 17,
        "expect": {"final_status": "completed", "side_effects": [
            {"kind": "http", "url_matches": "/api/v3/wp"},
        ]},
    }
    tc = TestCase.model_validate(data)
    assert tc.name == "smoke"
    assert tc.entity_id == 17
    assert tc.entity is None
    assert tc.timeout_sec == 60  # default
    assert tc.additional_entities == {}
    assert tc.expect.side_effects[0].min_count == 1

def test_minimal_case_with_entity_block_parses():
    data = {
        "name": "smoke", "fixtures": [],
        "entity": {"type": "contract", "fields": {"amount": 100}},
        "expect": {"final_status": "completed", "side_effects": []},
    }
    tc = TestCase.model_validate(data)
    assert tc.entity_id is None
    assert tc.entity.type == "contract"
    assert tc.entity.fields == {"amount": 100}

def test_both_entity_id_and_entity_rejected():
    data = {
        "name": "x", "fixtures": [],
        "entity_id": 1, "entity": {"type": "c", "fields": {}},
        "expect": {"final_status": "completed", "side_effects": []},
    }
    with pytest.raises(ValueError, match="exactly one"):
        TestCase.model_validate(data)

def test_neither_entity_id_nor_entity_rejected():
    data = {
        "name": "x", "fixtures": [],
        "expect": {"final_status": "completed", "side_effects": []},
    }
    with pytest.raises(ValueError, match="exactly one"):
        TestCase.model_validate(data)

def test_db_kind_rejects_non_whitelist_table():
    data = {
        "name": "x", "fixtures": [], "entity_id": 1,
        "expect": {"final_status": "completed", "side_effects": [
            {"kind": "db", "table": "payroll_records", "exists": True},
        ]},
    }
    with pytest.raises(ValueError, match="external DBs"):
        TestCase.model_validate(data)

def test_db_kind_accepts_whitelist():
    for table in ("process_instances", "entity_state", "assignments"):
        TestCase.model_validate({
            "name": "x", "fixtures": [], "entity_id": 1,
            "expect": {"final_status": "completed", "side_effects": [
                {"kind": "db", "table": table, "exists": True},
            ]},
        })

def test_final_status_enum():
    # Accepted: completed, cancelled, error, suspended (no `failed`).
    for v in ("completed", "cancelled", "error", "suspended"):
        TestCase.model_validate({
            "name": "x", "fixtures": [], "entity_id": 1,
            "expect": {"final_status": v, "side_effects": []},
        })
    with pytest.raises(ValueError):
        TestCase.model_validate({
            "name": "x", "fixtures": [], "entity_id": 1,
            "expect": {"final_status": "failed", "side_effects": []},
        })

def test_workflow_step_kind_removed():
    """n8n removed: kind: workflow_step is no longer a valid side_effect."""
    with pytest.raises(Exception):  # Pydantic ValidationError on discriminator
        TestCase.model_validate({
            "name": "x", "fixtures": [], "entity_id": 1,
            "expect": {"final_status": "completed", "side_effects": [
                {"kind": "workflow_step", "workflow": "wf1",
                 "status": "success"},
            ]},
        })


def test_load_test_case_from_file(tmp_path):
    f = tmp_path / "case.yaml"
    f.write_text(
        "name: x\nfixtures: []\nentity_id: 1\n"
        "expect: {final_status: completed, side_effects: []}\n",
        "utf-8",
    )
    tc = load_test_case(f)
    assert tc.name == "x"
    assert tc.entity_id == 1

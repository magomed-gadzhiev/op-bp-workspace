import pytest
from pydantic import ValidationError

from pdm_cli.models import Manifest, Entity, Task, Process, Script


def test_manifest_minimal_valid():
    m = Manifest(slug="payroll", name="Payroll", version=1, status="draft")
    assert m.slug == "payroll"
    assert m.description == ""


def test_manifest_invalid_slug_with_uppercase():
    with pytest.raises(ValidationError):
        Manifest(slug="Payroll", name="x", version=1, status="draft")


def test_manifest_invalid_slug_with_space():
    with pytest.raises(ValidationError):
        Manifest(slug="bad slug", name="x", version=1, status="draft")


def test_manifest_invalid_slug_starting_hyphen():
    with pytest.raises(ValidationError):
        Manifest(slug="-bad", name="x", version=1, status="draft")


def test_manifest_invalid_status():
    with pytest.raises(ValidationError):
        Manifest(slug="x", name="x", version=1, status="weird")


def test_manifest_invalid_version_zero():
    with pytest.raises(ValidationError):
        Manifest(slug="x", name="x", version=0, status="draft")


def test_manifest_extra_field_forbidden():
    with pytest.raises(ValidationError):
        Manifest(slug="x", name="x", version=1, status="draft", surprise="oops")


def test_entity_with_fields():
    e = Entity(
        slug="employee",
        name="Employee",
        fields=[{"name": "id", "type": "int"}],
    )
    assert e.fields[0]["name"] == "id"


def test_entity_default_collections():
    e = Entity(slug="x", name="X")
    assert e.fields == []
    assert e.validation == {}


def test_task_minimal():
    t = Task(slug="calc-bonus", title="Calc bonus", kind="script", config={})
    assert t.kind == "script"
    assert t.config == {}


def test_task_default_config():
    t = Task(slug="t", title="T", kind="manual")
    assert t.config == {}


def test_process_compose():
    p = Process(
        manifest=Manifest(slug="x", name="X", version=1, status="draft"),
        entities=[Entity(slug="e1", name="E1", fields=[])],
        tasks=[Task(slug="t1", title="T1", kind="manual", config={})],
    )
    assert len(p.entities) == 1
    assert len(p.tasks) == 1


def test_process_default_empty_collections():
    p = Process(manifest=Manifest(slug="x", name="X", version=1, status="draft"))
    assert p.entities == []
    assert p.tasks == []
    assert p.scripts == []


@pytest.mark.parametrize("cls,kwargs", [
    (Manifest, {"name": "x", "version": 1, "status": "draft"}),
    (Entity, {"name": "x", "fields": []}),
    (Task, {"title": "x", "kind": "manual", "config": {}}),
])
def test_slug_constraint_consistent_across_models(cls, kwargs):
    """All slugs in the system are constrained to [a-z0-9-]."""
    with pytest.raises(ValidationError):
        cls(slug="UPPER", **kwargs)
    with pytest.raises(ValidationError):
        cls(slug="with space", **kwargs)


def test_single_char_slug_allowed():
    """Edge case: 'a' is a valid slug (single char)."""
    Manifest(slug="a", name="x", version=1, status="draft")


def test_status_archived_valid():
    """Archived is a valid status (used internally for old published versions)."""
    m = Manifest(slug="x", name="x", version=1, status="archived")
    assert m.status == "archived"


def test_script_minimal_valid():
    s = Script(name="check_contract", code="def run(ctx): return True")
    assert s.name == "check_contract"
    assert s.display_name == "check_contract"  # fallback
    assert s.status == "draft"  # fallback
    assert s.description == ""
    assert s.requirements == ""


def test_script_full_round_trip():
    s = Script(
        name="check_contract",
        display_name="Проверка договора",
        description="Сверяет сумму",
        status="active",
        code="x = 1",
        requirements="",
    )
    assert s.model_dump()["display_name"] == "Проверка договора"


def test_process_with_scripts():
    p = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="a")],
    )
    assert len(p.scripts) == 1
    assert p.scripts[0].name == "s1"


def test_script_name_must_be_ascii_snake_case():
    with pytest.raises(ValidationError):
        Script(name="Проверка договора", code="x")  # non-ASCII
    with pytest.raises(ValidationError):
        Script(name="check-contract", code="x")  # hyphen
    with pytest.raises(ValidationError):
        Script(name="CheckContract", code="x")  # CamelCase

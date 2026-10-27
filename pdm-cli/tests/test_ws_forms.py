"""Командные тесты pdm ws forms (спека 171, ADR-0079): list/init/check/
diff/push/preview. HTTP мокается respx; env — monkeypatch."""

import yaml
import respx
from click.testing import CliRunner

from pdm_cli.cli import main

API = "http://pdm.local"
ROOT = "workspace/forms"

PUBLICATION = {
    "id": 5,
    "slug": "demo-form",
    "entity_type": {"id": 10, "code": "demo-form", "name": "Демо-форма"},
    "is_enabled": True,
    "title": "Демо",
    "intro": "Интро",
    "overlay": {"fields": ["поле-а"]},
    "inline_catalog_limit": 200,
    "admins": [{"id": 2, "username": "editor"}],
    "base_fields": {
        "fields": [
            {"name": "поле-а", "type": "string", "required": True},
            {"name": "поле-б", "type": "number", "required": False},
        ],
        "sections": [],
    },
    "active_version": "1.0",
    "versions": [{
        "id": 1, "version": "1.0", "status": "active",
        "schema_hash": "abcdef123456", "deprecated_at": None,
        "created_at": "2026-10-27T00:00:00Z",
    }],
    "grants": [],
}

PREVIEW = {
    "schema": {
        "title": "Демо",
        "fields": [{"name": "поле-а", "type": "string", "required": True}],
        "sections": [],
        "catalogs": {
            "Технологии": {
                "columns": ["Семейство"], "group_by": "Семейство",
                "count": 3, "inline": True,
            },
        },
    },
    "schema_hash": "f" * 64,
}


def _seed_env(monkeypatch):
    monkeypatch.setenv("PDM_API_BASE", API)
    monkeypatch.setenv("PDM_API_TOKEN", "test-token")


def _mock_publications():
    return respx.get(
        f"{API}/api/external-forms-admin/publications/",
    ).respond(json={"results": [PUBLICATION]})


def _run(tmp_path, *args):
    runner = CliRunner()
    return runner.invoke(main, ["ws", "forms", *args], obj={"cwd": tmp_path})


def _read_publication(tmp_path):
    return yaml.safe_load(
        (tmp_path / ROOT / "demo-form" / "publication.yaml")
        .read_text(encoding="utf-8"))


def _write_publication(tmp_path, manifest):
    (tmp_path / ROOT / "demo-form" / "publication.yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


# ── list ──────────────────────────────────────────────────────────────────────

@respx.mock
def test_forms_list_prints_slugs(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    result = _run(tmp_path, "list")
    assert result.exit_code == 0, result.output
    assert "demo-form" in result.output
    assert "Демо-форма" in result.output
    assert "v1.0" in result.output
    assert "Всего 1" in result.output


@respx.mock
def test_forms_list_401_hints_token(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    respx.get(
        f"{API}/api/external-forms-admin/publications/",
    ).respond(status_code=401)
    result = _run(tmp_path, "list")
    assert result.exit_code == 1
    assert "PDM_API_TOKEN" in result.output


# ── init ──────────────────────────────────────────────────────────────────────

@respx.mock
def test_forms_init_writes_workspace_and_origin(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    result = _run(tmp_path, "init", "demo-form")
    assert result.exit_code == 0, result.output
    manifest = _read_publication(tmp_path)
    assert manifest["slug"] == "demo-form"
    assert manifest["overlay"] == {"fields": ["поле-а"]}
    fields = yaml.safe_load(
        (tmp_path / ROOT / "demo-form" / "fields.yaml").read_text("utf-8"))
    assert {f["name"] for f in fields["fields"]} == {"поле-а", "поле-б"}
    origin = tmp_path / ROOT / ".ws-origin" / "demo-form" / "publication.yaml"
    assert origin.is_file()
    gitignore = (tmp_path / ROOT / ".gitignore").read_text("utf-8")
    assert "*" in gitignore


@respx.mock
def test_forms_init_unknown_slug(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    result = _run(tmp_path, "init", "no-such")
    assert result.exit_code == 2


# ── check ─────────────────────────────────────────────────────────────────────

@respx.mock
def test_forms_check_passes_after_init(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    assert _run(tmp_path, "init", "demo-form").exit_code == 0
    result = _run(tmp_path, "check")
    assert result.exit_code == 0, result.output
    assert "check пройден" in result.output


def _init_local(tmp_path, monkeypatch):
    """init без HTTP: файлы пишутся из фикстуры напрямую."""
    with respx.mock:
        _mock_publications()
        _run(tmp_path, "init", "demo-form")


def test_forms_check_unknown_field(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _init_local(tmp_path, monkeypatch)
    manifest = _read_publication(tmp_path)
    manifest["overlay"]["fields"] = ["поле-а", "нет-такого"]
    _write_publication(tmp_path, manifest)
    result = _run(tmp_path, "check")
    assert result.exit_code == 1
    assert "нет-такого" in result.output


def test_forms_check_empty_fields_rejected(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _init_local(tmp_path, monkeypatch)
    manifest = _read_publication(tmp_path)
    manifest["overlay"]["fields"] = []
    _write_publication(tmp_path, manifest)
    result = _run(tmp_path, "check")
    assert result.exit_code == 1
    assert "unpublishable" in result.output


def test_forms_check_duplicate_order(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _init_local(tmp_path, monkeypatch)
    manifest = _read_publication(tmp_path)
    manifest["overlay"]["order"] = ["поле-а", "поле-а"]
    _write_publication(tmp_path, manifest)
    result = _run(tmp_path, "check")
    assert result.exit_code == 1
    assert "дубликаты" in result.output


# ── diff ──────────────────────────────────────────────────────────────────────

def test_forms_diff_shows_change(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _init_local(tmp_path, monkeypatch)
    manifest = _read_publication(tmp_path)
    manifest["title"] = "Новый заголовок"
    _write_publication(tmp_path, manifest)
    result = _run(tmp_path, "diff", "demo-form")
    assert result.exit_code == 0, result.output
    assert "Новый заголовок" in result.output
    assert "publication.yaml изменён" in result.output


# ── push ──────────────────────────────────────────────────────────────────────

@respx.mock
def test_forms_push_noop_when_identical(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    _run(tmp_path, "init", "demo-form")
    patch = respx.patch(
        f"{API}/api/external-forms-admin/publications/5/",
    ).respond(json=PUBLICATION)
    result = _run(tmp_path, "push", "demo-form")
    assert result.exit_code == 0, result.output
    assert "no-op" in result.output
    assert not patch.called


@respx.mock
def test_forms_push_patches_changes(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    _run(tmp_path, "init", "demo-form")
    manifest = _read_publication(tmp_path)
    manifest["title"] = "Новый заголовок"
    manifest["overlay"] = {"fields": ["поле-а", "поле-б"]}
    _write_publication(tmp_path, manifest)
    patch = respx.patch(
        f"{API}/api/external-forms-admin/publications/5/",
    ).respond(json={**PUBLICATION, "title": "Новый заголовок"})
    result = _run(tmp_path, "push", "demo-form")
    assert result.exit_code == 0, result.output
    assert patch.called
    import json
    sent = json.loads(patch.calls.last.request.content)
    assert sent["title"] == "Новый заголовок"
    assert sent["overlay"]["fields"] == ["поле-а", "поле-б"]
    # Снапшот .ws-origin обновился
    origin = yaml.safe_load(
        (tmp_path / ROOT / ".ws-origin" / "demo-form" / "publication.yaml")
        .read_text("utf-8"))
    assert origin["title"] == "Новый заголовок"


@respx.mock
def test_forms_push_scope_denied(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    _run(tmp_path, "init", "demo-form")
    manifest = _read_publication(tmp_path)
    manifest["title"] = "Новый заголовок"
    _write_publication(tmp_path, manifest)
    respx.patch(
        f"{API}/api/external-forms-admin/publications/5/",
    ).respond(status_code=403, json={"detail": "token_scope"})
    result = _run(tmp_path, "push", "demo-form")
    assert result.exit_code == 1
    assert "draft" in result.output


@respx.mock
def test_forms_push_aborts_when_check_fails(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    _run(tmp_path, "init", "demo-form")
    manifest = _read_publication(tmp_path)
    manifest["overlay"]["fields"] = ["нет-такого"]
    _write_publication(tmp_path, manifest)
    patch = respx.patch(
        f"{API}/api/external-forms-admin/publications/5/",
    ).respond(json=PUBLICATION)
    result = _run(tmp_path, "push", "demo-form")
    assert result.exit_code == 1
    assert not patch.called


# ── preview ───────────────────────────────────────────────────────────────────

@respx.mock
def test_forms_preview_summary(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_publications()
    respx.get(
        f"{API}/api/external-forms-admin/publications/5/schema-preview/",
    ).respond(json=PREVIEW)
    result = _run(tmp_path, "preview", "demo-form")
    assert result.exit_code == 0, result.output
    assert "поле-а" in result.output
    assert "Технологии" in result.output
    assert "инлайн" in result.output
    # hash превью (f…) отличается от активной версии (abcdef…)
    assert "отличается от активной" in result.output

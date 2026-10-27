"""pdm ws findings: check/submit/list (спека 166, ADR-0073)."""

import json
import uuid

import httpx
import respx
from click.testing import CliRunner

from pdm_cli.cli import main

API = "http://pdm.local"

BODY = """## Что произошло
500

## Ожидалось
200

## Как воспроизвести
1. pdm ws init lem

## Доказательства
- pdm --version: 0.14.0
- API version: 1
- correlation_id: req-123

## Обход
нет
"""


def _seed_env(monkeypatch):
    monkeypatch.setenv("PDM_API_BASE", API)
    monkeypatch.setenv("PDM_API_TOKEN", "test-token")


def _make_finding(
    tmp_path,
    *,
    external_id=None,
    type_="error",
    target="cli",
    severity="blocker",
    title="ws init: 500",
    bp="",
    body=BODY,
    submitted_id=None,
):
    ext = external_id if external_id is not None else str(uuid.uuid4())
    lines = [
        "---",
        f'external_id: "{ext}"' if ext else 'external_id: ""',
        f'title: "{title}"',
        f"type: {type_}",
        f"target: {target}",
        f"severity: {severity}",
        f'bp: "{bp}"',
        'created_at: ""',
    ]
    if submitted_id is not None:
        lines.append(f"submitted_id: {submitted_id}")
    lines.append("---")
    path = tmp_path / "workspace" / "_findings" / f"{target}-01.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n" + body, encoding="utf-8")
    return path


def _invoke(tmp_path, args, **kwargs):
    return CliRunner().invoke(main, args, obj={"cwd": tmp_path}, **kwargs)


# ── check ────────────────────────────────────────────────────────────────────

def test_check_valid_file(tmp_path):
    _make_finding(tmp_path)
    result = _invoke(tmp_path, ["ws", "findings", "check"])
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_check_reports_missing_section(tmp_path):
    _make_finding(tmp_path, body=BODY.replace("## Обход\nнет", ""))
    result = _invoke(tmp_path, ["ws", "findings", "check"])
    assert result.exit_code == 1
    assert "Обход" in result.output


def test_check_reports_invalid_target(tmp_path):
    _make_finding(tmp_path, target="database")
    result = _invoke(tmp_path, ["ws", "findings", "check"])
    assert result.exit_code == 1
    assert "target" in result.output


def test_check_error_requires_correlation_or_traceback(tmp_path):
    body = BODY.replace("- correlation_id: req-123\n", "")
    _make_finding(tmp_path, body=body)
    result = _invoke(tmp_path, ["ws", "findings", "check"])
    assert result.exit_code == 1
    assert "correlation_id" in result.output


def test_check_rejects_secret(tmp_path):
    body = BODY.replace("нет", "PDM_API_TOKEN=super-secret")
    _make_finding(tmp_path, body=body)
    result = _invoke(tmp_path, ["ws", "findings", "check"])
    assert result.exit_code == 1
    assert "секрет" in result.output


def test_check_fix_assigns_external_id(tmp_path):
    path = _make_finding(tmp_path, external_id="")
    result = _invoke(tmp_path, ["ws", "findings", "check", "--fix"])
    assert result.exit_code == 0, result.output
    text = path.read_text(encoding="utf-8")
    assert 'external_id: ""' not in text
    assert "fixed" in result.output


# ── submit ───────────────────────────────────────────────────────────────────

@respx.mock
def test_submit_posts_payload_and_writes_back(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    path = _make_finding(tmp_path)
    respx.get(f"{API}/api/health/").respond(json={"pdm_api_version": "1"})
    route = respx.post(f"{API}/api/feedbacks/submit/").respond(
        201,
        json={"id": 42, "external_id": "x", "status": "new"},
    )

    result = _invoke(tmp_path, ["ws", "findings", "submit"])
    assert result.exit_code == 0, result.output
    assert route.called

    payload = json.loads(route.calls[0].request.content)
    assert payload["type"] == "error"
    assert payload["target"] == "cli"
    assert payload["severity"] == "blocker"
    assert payload["origin"]["source"] == "op-bp-workspace"
    assert payload["origin"]["api_version"] == "1"
    assert payload["origin"]["cli_version"]

    text = path.read_text(encoding="utf-8")
    assert "submitted_id: 42" in text
    assert "status: new" in text


@respx.mock
def test_submit_is_idempotent_on_server_200(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _make_finding(tmp_path)
    respx.get(f"{API}/api/health/").respond(json={"pdm_api_version": "1"})
    respx.post(f"{API}/api/feedbacks/submit/").respond(
        200,
        json={"id": 42, "external_id": "x", "status": "new",
              "idempotent": True},
    )

    result = _invoke(tmp_path, ["ws", "findings", "submit"])
    assert result.exit_code == 0, result.output
    assert "идемпотентно" in result.output


def test_submit_skips_already_submitted(tmp_path):
    _make_finding(tmp_path, submitted_id=7)
    result = _invoke(tmp_path, ["ws", "findings", "submit"])
    assert result.exit_code == 0, result.output
    assert "пропуск" in result.output


@respx.mock
def test_submit_409_reports_conflict(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _make_finding(tmp_path)
    respx.get(f"{API}/api/health/").respond(json={"pdm_api_version": "1"})
    respx.post(f"{API}/api/feedbacks/submit/").respond(
        409, json={"detail": "external_id уже использован"})

    result = _invoke(tmp_path, ["ws", "findings", "submit"])
    assert result.exit_code == 1
    assert "409" in result.output


@respx.mock
def test_submit_401_hints_token(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _make_finding(tmp_path)
    respx.get(f"{API}/api/health/").respond(json={"pdm_api_version": "1"})
    respx.post(f"{API}/api/feedbacks/submit/").respond(401)

    result = _invoke(tmp_path, ["ws", "findings", "submit"])
    assert result.exit_code == 1
    assert "PDM_API_TOKEN" in result.output


@respx.mock
def test_submit_resolves_bp_slug_to_pk(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _make_finding(tmp_path, bp="lem")
    respx.get(f"{API}/api/health/").respond(json={"pdm_api_version": "1"})
    respx.get(f"{API}/api/business-processes/").respond(json=[
        {"id": 7, "slug": "lem", "name": "ЛЭМ"},
    ])
    route = respx.post(f"{API}/api/feedbacks/submit/").respond(
        201, json={"id": 1, "external_id": "x", "status": "new"})

    result = _invoke(tmp_path, ["ws", "findings", "submit"])
    assert result.exit_code == 0, result.output
    payload = json.loads(route.calls[0].request.content)
    assert payload["related_business_process_id"] == 7
    assert payload["origin"]["bp_slug"] == "lem"


def test_submit_dry_run_does_not_post(tmp_path):
    _make_finding(tmp_path)
    result = _invoke(tmp_path, ["ws", "findings", "submit", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert '"external_id"' in result.output


# ── list ────────────────────────────────────────────────────────────────────

@respx.mock
def test_list_follows_pagination_and_open_filter(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    respx.get(f"{API}/api/feedbacks/", params={"my_feedbacks": "true"}).respond(
        json={
            "results": [{"id": 1, "status": "new", "title": "open-one",
                         "target": "cli", "severity": "blocker"}],
            "next": f"{API}/api/feedbacks/?my_feedbacks=true&page=2",
        })
    respx.get(
        f"{API}/api/feedbacks/",
        params={"my_feedbacks": "true", "page": "2"},
    ).respond(json={
        "results": [{"id": 2, "status": "resolved", "title": "done-one",
                     "target": "api", "severity": "minor"}],
        "next": None,
    })

    result = _invoke(tmp_path, ["ws", "findings", "list", "--open"])
    assert result.exit_code == 0, result.output
    assert "open-one" in result.output
    assert "done-one" not in result.output


@respx.mock
def test_list_json(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    respx.get(f"{API}/api/feedbacks/", params={"my_feedbacks": "true"}).respond(
        json={
            "results": [{"id": 1, "status": "new", "title": "one",
                         "target": "cli", "severity": "blocker",
                         "external_id": "ext", "updated_at": "2026-10-22"}],
            "next": None,
        })

    result = _invoke(tmp_path, ["ws", "findings", "list", "--json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert rows[0]["title"] == "one"
    assert rows[0]["status"] == "new"


def test_check_fix_reports_write_error(tmp_path):
    _make_finding(tmp_path, external_id="")
    from unittest.mock import patch

    with patch("pdm_cli.finding_file.write_finding",
               side_effect=OSError("read-only")):
        result = _invoke(tmp_path, ["ws", "findings", "check", "--fix"])
    assert result.exit_code == 1
    assert "не удалось записать" in result.output


@respx.mock
def test_submit_reports_write_back_error(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _make_finding(tmp_path)
    respx.get(f"{API}/api/health/").respond(json={"pdm_api_version": "1"})
    respx.post(f"{API}/api/feedbacks/submit/").respond(
        201, json={"id": 42, "external_id": "x", "status": "new"})
    from unittest.mock import patch

    with patch("pdm_cli.commands.ws_findings.update_fields",
               side_effect=OSError("read-only")):
        result = _invoke(tmp_path, ["ws", "findings", "submit"])
    assert result.exit_code == 1
    assert "не удалось записать" in result.output

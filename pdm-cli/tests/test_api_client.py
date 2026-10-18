import httpx
import pytest
import respx

from pdm_cli.api_client import PdmApiClient, _process_from_full_response
from pdm_cli.models import Manifest, Entity, Task, Process, Script


PROD = "https://prod.local"


def _full_response(slug="payroll", version=1, status="published"):
    return {
        "manifest": {
            "slug": slug, "name": slug.title(), "description": "",
            "version": version, "status": status, "owner": None,
        },
        "entities": [],
        "tasks": [],
    }


# ---- Auth headers ----

@respx.mock
def test_token_auth_header():
    route = respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    with PdmApiClient(base_url=PROD, api_key="secret-key") as c:
        c.list_processes()
    sent = route.calls.last.request
    assert sent.headers.get("Authorization") == "Token secret-key"


@respx.mock
def test_bypass_header_added_when_secret_configured():
    route = respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    with PdmApiClient(base_url=PROD, api_key="K", cli_bypass_secret="BYPASS") as c:
        c.list_processes()
    sent = route.calls.last.request
    assert sent.headers.get("X-Pdm-Cli-Bypass") == "BYPASS"


@respx.mock
def test_bypass_header_omitted_when_secret_empty():
    route = respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        c.list_processes()
    sent = route.calls.last.request
    assert "X-Pdm-Cli-Bypass" not in sent.headers


# ---- list_processes ----

@respx.mock
def test_list_processes_array_response():
    respx.get(f"{PROD}/api/business-processes/").respond(
        json=[{"slug": "payroll", "name": "Payroll"}]
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        result = c.list_processes()
    assert result == [{"slug": "payroll", "name": "Payroll"}]


@respx.mock
def test_list_processes_paginated_response():
    """DRF's PageNumberPagination wraps array in {results, count, next, previous}."""
    respx.get(f"{PROD}/api/business-processes/").respond(json={
        "count": 1, "next": None, "previous": None,
        "results": [{"slug": "x", "name": "X"}],
    })
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        result = c.list_processes()
    assert result == [{"slug": "x", "name": "X"}]


@respx.mock
def test_list_processes_follows_next_page():
    """PAGE_SIZE=20: second page must be fetched or later slugs are invisible."""

    def _page(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={
                "count": 2, "next": None,
                "previous": f"{PROD}/api/business-processes/",
                "results": [{"slug": "b", "name": "B"}],
            })
        return httpx.Response(200, json={
            "count": 2,
            "next": f"{PROD}/api/business-processes/?page=2",
            "previous": None,
            "results": [{"slug": "a", "name": "A"}],
        })

    respx.get(f"{PROD}/api/business-processes/").mock(side_effect=_page)
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        result = c.list_processes()
    assert result == [{"slug": "a", "name": "A"}, {"slug": "b", "name": "B"}]


# ---- get_full ----

@respx.mock
def test_get_full_returns_process_model():
    respx.get(f"{PROD}/api/business-processes/payroll/full/").respond(
        json=_full_response()
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        proc = c.get_full("payroll")
    assert isinstance(proc, Process)
    assert proc.manifest.slug == "payroll"
    assert proc.manifest.version == 1
    assert proc.manifest.status == "published"


@respx.mock
def test_get_full_with_specific_version_passes_param():
    route = respx.get(f"{PROD}/api/business-processes/x/full/").respond(
        json=_full_response(slug="x", version=3)
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        c.get_full("x", version=3)
    sent = route.calls.last.request
    assert "version=3" in str(sent.url)


# ---- import_full ----

@respx.mock
def test_import_full_strips_version_and_status_from_payload():
    route = respx.post(f"{PROD}/api/business-processes/payroll/import_full/").respond(
        status_code=201, json=_full_response(slug="payroll", version=2, status="draft")
    )
    proc = Process(
        manifest=Manifest(slug="payroll", name="Payroll", version=99, status="published"),
        entities=[], tasks=[],
    )
    with PdmApiClient(base_url=PROD, api_key="K", cli_bypass_secret="B") as c:
        result = c.import_full(proc)

    assert result.manifest.version == 2
    assert result.manifest.status == "draft"

    sent = route.calls.last.request
    body = sent.read().decode("utf-8")
    # Payload must NOT contain server-assigned fields
    assert '"version"' not in body
    assert '"status"' not in body
    # But must contain the rest of manifest
    assert '"slug"' in body
    assert '"name"' in body


@respx.mock
def test_import_full_includes_entities_and_tasks_in_payload():
    route = respx.post(f"{PROD}/api/business-processes/payroll/import_full/").respond(
        status_code=201, json=_full_response()
    )
    proc = Process(
        manifest=Manifest(slug="payroll", name="X", version=1, status="draft"),
        entities=[Entity(slug="employee", name="Employee", fields=[{"name": "id"}])],
        tasks=[Task(slug="t", title="T", kind="manual", config={})],
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        c.import_full(proc)

    body = route.calls.last.request.read().decode("utf-8")
    assert "employee" in body
    assert '"kind": "manual"' in body or '"kind":"manual"' in body


@respx.mock
def test_import_full_sends_bypass_header_when_configured():
    route = respx.post(f"{PROD}/api/business-processes/x/import_full/").respond(
        status_code=201, json=_full_response(slug="x")
    )
    proc = Process(manifest=Manifest(slug="x", name="X", version=1, status="draft"))
    with PdmApiClient(base_url=PROD, api_key="K", cli_bypass_secret="topsecret") as c:
        c.import_full(proc)
    assert route.calls.last.request.headers.get("X-Pdm-Cli-Bypass") == "topsecret"


# ---- promote ----

@respx.mock
def test_promote_sends_version_and_tag():
    route = respx.post(f"{PROD}/api/business-processes/payroll/promote/").respond(
        json=_full_response(slug="payroll", version=2, status="published")
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        result = c.promote("payroll", version=2, tag="v0.1.0")
    assert result.manifest.status == "published"

    body = route.calls.last.request.read().decode("utf-8")
    assert '"v0.1.0"' in body
    assert '"version": 2' in body or '"version":2' in body


# ---- error handling ----

@respx.mock
def test_api_4xx_raises_http_status_error():
    respx.get(f"{PROD}/api/business-processes/").respond(
        status_code=403, json={"detail": "forbidden"}
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        with pytest.raises(httpx.HTTPStatusError):
            c.list_processes()


@respx.mock
def test_api_5xx_raises_http_status_error():
    respx.get(f"{PROD}/api/business-processes/").respond(status_code=500)
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        with pytest.raises(httpx.HTTPStatusError):
            c.list_processes()


# ---- base_url normalization ----

@respx.mock
def test_base_url_trailing_slash_stripped():
    """Trailing slash on base URL is normalized so URLs don't double-slash."""
    respx.get("https://x.local/api/business-processes/").respond(json=[])
    with PdmApiClient(base_url="https://x.local/", api_key="K") as c:
        c.list_processes()  # would 404 if URL had double slash


# ---- context manager ----

def test_client_can_be_used_as_context_manager():
    """`with PdmApiClient(...) as c:` does cleanup on exit."""
    c = PdmApiClient(base_url="https://x", api_key="K")
    c.close()  # safe to call without ever making a request


# ---- scripts round-trip ----

def test_process_from_full_extracts_scripts():
    data = {
        "manifest": {
            "slug": "bp1", "name": "BP1", "description": "",
            "version": 1, "status": "draft", "owner": None,
        },
        "entities": [],
        "tasks": [],
        "scripts": [
            {
                "name": "s1", "display_name": "S1", "description": "",
                "status": "active", "code": "x = 1", "requirements": "",
            }
        ],
    }
    p = _process_from_full_response(data)
    assert len(p.scripts) == 1
    assert p.scripts[0].name == "s1"
    assert p.scripts[0].code == "x = 1"
    assert p.scripts[0].status == "active"


def test_process_from_full_missing_scripts_yields_empty_list():
    data = {
        "manifest": {
            "slug": "bp1", "name": "BP1", "description": "",
            "version": 1, "status": "draft", "owner": None,
        },
        "entities": [], "tasks": [],
    }
    p = _process_from_full_response(data)
    assert p.scripts == []


@respx.mock
def test_import_full_sends_scripts_in_payload():
    """Outgoing payload to /import_full/ must include scripts list."""
    response_body = _full_response(slug="bp1", version=1, status="draft")
    response_body["scripts"] = []
    route = respx.post(f"{PROD}/api/business-processes/bp1/import_full/").respond(
        status_code=201, json=response_body,
    )
    proc = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="def run(): pass", display_name="S1")],
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        c.import_full(proc)
    import json
    payload = json.loads(route.calls.last.request.read().decode("utf-8"))
    assert "scripts" in payload
    assert len(payload["scripts"]) == 1
    assert payload["scripts"][0]["name"] == "s1"
    assert payload["scripts"][0]["code"] == "def run(): pass"


@respx.mock
def test_get_full_returns_scripts_from_response():
    response_body = _full_response(slug="bp1", version=1, status="draft")
    response_body["scripts"] = [
        {
            "name": "helper", "display_name": "Helper", "description": "",
            "status": "active", "code": "y = 2", "requirements": "",
        }
    ]
    respx.get(f"{PROD}/api/business-processes/bp1/full/").respond(json=response_body)
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        proc = c.get_full("bp1")
    assert len(proc.scripts) == 1
    assert proc.scripts[0].name == "helper"
    assert proc.scripts[0].code == "y = 2"


@respx.mock
def test_get_full_handles_legacy_snapshot_shape():
    """Migration 0055 wraps content in business_process key. Client tolerates it."""
    respx.get(f"{PROD}/api/business-processes/legacy/full/").respond(json={
        "manifest": {"slug": "legacy", "name": "Legacy",
                     "description": "", "version": 1, "status": "published",
                     "owner": None},
        "business_process": {"tasks": [{"name": "T"}]},
        # Note: no top-level entities/tasks in legacy shape
    })
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        proc = c.get_full("legacy")
    # Manifest valid; entities/tasks empty (legacy data not surfaced through R2 layer)
    assert proc.manifest.slug == "legacy"
    assert proc.entities == []
    assert proc.tasks == []


# ---- шов тестовой версии БП (спека 143, W6: export ?version, versions,
# draft-import) ----

@respx.mock
def test_export_package_without_version_omits_param():
    respx.get(f"{PROD}/api/business-processes/").respond(
        json=[{"id": 7, "slug": "bp1", "name": "БП"}]
    )
    route = respx.post(f"{PROD}/api/business-processes/7/export/").respond(
        content=b"PK-zip-bytes"
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        assert c.export_package("bp1") == b"PK-zip-bytes"
    assert "version=" not in str(route.calls.last.request.url)


@respx.mock
def test_export_package_with_version_passes_param():
    """Экспорт поколения конкретной версии (W3: ZIP testing-версии)."""
    respx.get(f"{PROD}/api/business-processes/").respond(
        json=[{"id": 7, "slug": "bp1", "name": "БП"}]
    )
    route = respx.post(f"{PROD}/api/business-processes/7/export/").respond(
        content=b"PK-zip-bytes"
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        c.export_package("bp1", version=3)
    assert "version=3" in str(route.calls.last.request.url)


@respx.mock
def test_bp_versions_returns_registry():
    route = respx.get(f"{PROD}/api/business-processes/bp1/versions/").respond(
        json={
            "process": {"id": 7, "slug": "bp1", "name": "БП"},
            "versions": [{"number": 2, "status": "testing"}],
            "testing": {"number": 2},
            "published": None,
            "diff": None,
        }
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        info = c.bp_versions("bp1")
    assert info["testing"] == {"number": 2}
    assert route.called


@respx.mock
def test_draft_import_posts_multipart_zip():
    route = respx.post(f"{PROD}/api/business-processes/bp1/draft-import/").respond(
        json={
            "status": "created", "slug": "bp1", "version": 2,
            "version_status": "testing", "process_created": True,
            "replaced": None, "diff": {"task_diff": []}, "users_missing": [],
        },
        status_code=201,
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        result = c.draft_import("bp1", b"PK-zip-bytes", "bp-bp1.zip")
    assert result["status"] == "created"
    assert result["version"] == 2
    content = route.calls.last.request.content
    assert b"bp-bp1.zip" in content  # zip уходит multipart-полем file


@respx.mock
def test_draft_import_422_returns_dict_not_raise():
    """422 draft_validation_failed — данные для агента, а не исключение
    (тот же паттерн, что 409 у import_confirm)."""
    respx.post(f"{PROD}/api/business-processes/bp1/draft-import/").respond(
        status_code=422,
        json={"error": "draft_validation_failed",
              "errors": [{"kind": "slug_mismatch", "name": "other"}]},
    )
    with PdmApiClient(base_url=PROD, api_key="K") as c:
        result = c.draft_import("bp1", b"PK-zip-bytes")
    assert result["error"] == "draft_validation_failed"
    assert result["errors"][0]["kind"] == "slug_mismatch"

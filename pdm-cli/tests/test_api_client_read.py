"""ApiClient methods for telemetry/run-details/entity-schema/health."""

from pdm_cli.api_client import PdmApiClient


def test_health_returns_version(httpserver):
    httpserver.expect_request("/api/health/").respond_with_json(
        {"pdm_api_version": "1", "status": "ok"},
    )
    with PdmApiClient(base_url=httpserver.url_for(""), api_key="k") as c:
        h = c.health()
    assert h["pdm_api_version"] == "1"


def test_list_runs(httpserver):
    httpserver.expect_request(
        "/api/business-processes/payroll/runs/",
        query_string="limit=50&offset=0&since=24h",
    ).respond_with_json({
        "bp_slug": "payroll", "total": 1, "by_status": {"completed": 1},
        "runs": [{"run_id": 42, "status": "completed"}],
    })
    with PdmApiClient(base_url=httpserver.url_for(""), api_key="k") as c:
        out = c.list_runs("payroll", since="24h")
    assert out["total"] == 1
    assert out["runs"][0]["run_id"] == 42


def test_run_details(httpserver):
    httpserver.expect_request("/api/process-instances/42/details/").respond_with_json({
        "run_id": 42, "bp_slug": "payroll", "status": "error",
        "assignments": [], "history_events": [],
        "egress": {"http": [], "ssh": [], "orphan_count": {"http": 0, "ssh": 0}},
    })
    with PdmApiClient(base_url=httpserver.url_for(""), api_key="k") as c:
        out = c.run_details(42)
    assert out["status"] == "error"


def test_run_aggregates(httpserver):
    httpserver.expect_request(
        "/api/runs/aggregates/",
        query_string=(
            "since=2026-05-01T00%3A00%3A00Z&bp=payroll&"
            "until=2026-05-15T00%3A00%3A00Z"
        ),
    ).respond_with_json({
        "total_count": 2,
        "by_status": {"completed": 1, "error": 1},
    })
    with PdmApiClient(base_url=httpserver.url_for(""), api_key="k") as c:
        out = c.run_aggregates(
            bp_slug="payroll",
            since="2026-05-01T00:00:00Z",
            until="2026-05-15T00:00:00Z",
        )
    assert out["total_count"] == 2


def test_entity_schema(httpserver):
    httpserver.expect_request(
        "/api/business-processes/payroll/entities/employee/schema/",
    ).respond_with_json({"type": "object", "properties": {"name": {"type": "string"}}})
    with PdmApiClient(base_url=httpserver.url_for(""), api_key="k") as c:
        schema = c.get_entity_schema("payroll", "employee")
    assert schema["type"] == "object"

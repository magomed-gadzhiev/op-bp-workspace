"""Sidecar transforms Hoverfly webhook payload into PDM internal API payload."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import hoverfly_payload_to_pdm_payload


def test_transforms_basic_request():
    hoverfly_event = {
        "request": {
            "method": "POST",
            "scheme": "https",
            "destination": "hrms.local",
            "path": "/api/employees/42",
            "headers": {"X-PDM-Run-Id": ["42"], "X-PDM-Source": ["pdm-script"]},
            "body": '{"name":"A"}',
        },
        "response": {
            "status": 200,
            "headers": {"Content-Type": ["application/json"]},
            "body": '{"ok":true}',
        },
        "latency_ms": 87,
        "captured_at": "2026-05-14T10:00:00Z",
    }
    payload = hoverfly_payload_to_pdm_payload(hoverfly_event)
    assert payload["bp_run_id"] == 42
    assert payload["method"] == "POST"
    assert payload["url"].endswith("/api/employees/42")
    assert payload["source"] == "pdm-script"
    assert payload["response_status"] == 200
    assert payload["duration_ms"] == 87


def test_orphan_request_has_null_run_id():
    hoverfly_event = {
        "request": {"method": "GET", "destination": "x.local", "path": "/", "headers": {}, "body": ""},
        "response": {"status": 200, "headers": {}, "body": ""},
        "latency_ms": 5,
        "captured_at": "2026-05-14T10:00:00Z",
    }
    payload = hoverfly_payload_to_pdm_payload(hoverfly_event)
    assert payload["bp_run_id"] is None
    assert payload["source"] == "unknown"

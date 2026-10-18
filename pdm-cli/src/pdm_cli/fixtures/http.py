"""HTTP fixture models + YAML I/O.

Format mirrors design.md "Формат тест-кейса" section, simplified for Etap 2.
One YAML file = one named case = one or more request/response matchers.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

POST_SERVE_ACTION_NAME = "log-egress"


class HttpRequest(BaseModel):
    method: str
    url_matches: str  # regex against full URL
    headers: dict[str, str] = Field(default_factory=dict)
    body_contains: list[str] = Field(default_factory=list)


class HttpResponse(BaseModel):
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    delay_ms: int = 0


class HttpMatcher(BaseModel):
    request: HttpRequest
    response: HttpResponse


class HttpFixture(BaseModel):
    name: str
    version: int = Field(default=1, ge=1)  # E16: ≥1; legacy files default to 1 (FR-003)
    recorded_at: str | None = None  # E16: ISO-8601 UTC, None = unknown (FR-003)
    matchers: list[HttpMatcher]


def load_http_fixture(path: Path) -> HttpFixture:
    y = YAML(typ="safe")
    with Path(path).open("r", encoding="utf-8") as f:
        data = y.load(f) or {}
    return HttpFixture.model_validate(data)


def dump_http_fixture(fix: HttpFixture, path: Path) -> None:
    y = YAML()
    y.default_flow_style = False
    y.indent(mapping=2, sequence=4, offset=2)
    data = fix.model_dump(mode="python")
    with Path(path).open("w", encoding="utf-8") as f:
        y.dump(data, f)


# ---------------------------------------------------------------------------
# Hoverfly v2 simulation ↔ HttpFixture converters
# ---------------------------------------------------------------------------
import re as _re


def _first_value(matchers: list[dict] | None) -> str:
    if not matchers:
        return ""
    return matchers[0].get("value", "")


def _flatten_headers(h: dict) -> dict[str, str]:
    """Hoverfly stores header values as lists of matcher dicts or as plain list of strings (response side).
    Normalize to flat {name: value}."""
    out: dict[str, str] = {}
    for k, v in (h or {}).items():
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, dict):
                out[k] = first.get("value", "")
            else:
                out[k] = str(first)
    return out


def from_hoverfly_pair(pair: dict) -> HttpMatcher:
    req = pair.get("request", {})
    scheme = _first_value(req.get("scheme"))
    dest = _first_value(req.get("destination"))
    path = _first_value(req.get("path"))
    url = f"{scheme}://{dest}{path}" if scheme and dest else path
    url_re = _re.escape(url)
    body_matchers = req.get("body") or []
    _body_raw = [_first_value([m]) for m in body_matchers if _first_value([m])]
    # Strip leading/trailing '*' added by to_hoverfly_pair for glob matchers
    body_contains = [v.strip("*") for v in _body_raw]
    request = HttpRequest(
        method=_first_value(req.get("method")) or "GET",
        url_matches=url_re,
        headers=_flatten_headers(req.get("headers", {})),
        body_contains=body_contains,
    )
    resp = pair.get("response", {})
    response = HttpResponse(
        status=int(resp.get("status", 200)),
        headers=_flatten_headers(resp.get("headers", {})),
        body=resp.get("body", "") or "",
        delay_ms=int(resp.get("fixedDelay", 0) or 0),
    )
    return HttpMatcher(request=request, response=response)


def to_hoverfly_pair(m: HttpMatcher) -> dict:
    # Parse url_matches back. Only supports url_re that originated from re.escape(url) above.
    url = _re.sub(r'\\(.)', r'\1', m.request.url_matches)
    scheme, _, rest = url.partition("://")
    if not scheme:
        scheme, rest = "http", url
    dest, _, path = rest.partition("/")
    path = "/" + path if path else "/"
    return {
        "request": {
            "method": [{"matcher": "exact", "value": m.request.method}],
            "destination": [{"matcher": "exact", "value": dest}],
            "path": [{"matcher": "exact", "value": path}],
            "scheme": [{"matcher": "exact", "value": scheme}],
            "headers": {k: [{"matcher": "exact", "value": v}] for k, v in m.request.headers.items()},
            "body": [{"matcher": "glob", "value": f"*{s}*"} for s in m.request.body_contains],
        },
        "response": {
            "status": m.response.status,
            "body": m.response.body,
            "encodedBody": False,
            "postServeAction": POST_SERVE_ACTION_NAME,
            "headers": {k: [v] for k, v in m.response.headers.items()},
            **({"fixedDelay": m.response.delay_ms} if m.response.delay_ms else {}),
        },
    }


def fixture_to_hoverfly_simulation(fixtures: list[HttpFixture]) -> dict:
    pairs = []
    for fix in fixtures:
        for m in fix.matchers:
            pairs.append(to_hoverfly_pair(m))
    return {
        "data": {"pairs": pairs, "globalActions": {"delays": [], "delaysLogNormal": []}},
        "meta": {"schemaVersion": "v5.2"},
    }


def hoverfly_simulation_to_fixtures(sim: dict, case_name: str = "captured") -> HttpFixture:
    pairs = ((sim.get("data") or {}).get("pairs")) or []
    return HttpFixture(name=case_name, matchers=[from_hoverfly_pair(p) for p in pairs])

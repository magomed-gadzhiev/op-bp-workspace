"""Hoverfly journal client: query HTTP side-effects recorded by Hoverfly proxy.

Used by the test runner to assert that BP scripts produced expected outbound HTTP
calls (kind: http) against simulated upstreams.
"""
from __future__ import annotations

import re

import httpx


def clear_journal(hoverfly_admin: str) -> None:
    """Delete all entries from the Hoverfly journal."""
    r = httpx.delete(f"{hoverfly_admin.rstrip('/')}/api/v2/journal", timeout=10)
    r.raise_for_status()


def get_journal(hoverfly_admin: str) -> list[dict]:
    """Fetch the full Hoverfly journal as a list of request/response entries."""
    r = httpx.get(f"{hoverfly_admin.rstrip('/')}/api/v2/journal", timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get("journal") or []


def match_http_side_effect(hoverfly_admin: str, eff) -> list[dict]:
    """Return journal entries matching the HttpSideEffect predicate.

    Filters by (optional) method, regex against `destination + path`,
    and AND-check that every fragment in `body_contains` appears in the request body.
    """
    url_re = re.compile(eff.url_matches)
    out: list[dict] = []
    for entry in get_journal(hoverfly_admin):
        req = entry.get("request", {}) or {}
        if eff.method and (req.get("method") or "").upper() != eff.method.upper():
            continue
        full_url = (req.get("destination") or "") + (req.get("path") or "")
        if not url_re.search(full_url):
            continue
        body = req.get("body") or ""
        if not all(s in body for s in eff.body_contains):
            continue
        out.append(entry)
    return out

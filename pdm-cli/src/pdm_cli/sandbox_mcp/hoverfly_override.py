"""Hoverfly v2 simulation snapshot/PUT-merge/restore for ephemeral overrides.

Hoverfly's PUT /api/v2/simulation REPLACES the entire simulation; there is no
merge endpoint. This context manager captures the baseline on enter, allows
the caller to PUT a merged simulation (override pairs prepended for priority),
and restores the baseline on exit (guaranteed best-effort).
"""
from __future__ import annotations

import copy
import logging
from typing import Iterable

import httpx

logger = logging.getLogger(__name__)
POST_SERVE_ACTION_NAME = "log-egress"


class HoverflyOverrideContext:
    def __init__(self, admin_url: str, *, timeout_sec: float = 15.0):
        self.admin = admin_url.rstrip("/")
        self._baseline: dict | None = None
        self._timeout = timeout_sec

    def __enter__(self):
        r = httpx.get(f"{self.admin}/api/v2/simulation", timeout=self._timeout)
        r.raise_for_status()
        self._baseline = r.json()
        return self

    def inject(self, override_pairs: Iterable[dict]) -> None:
        if self._baseline is None:
            raise RuntimeError("HoverflyOverrideContext.inject called outside `with`")
        merged = copy.deepcopy(self._baseline)
        existing = list(merged.get("data", {}).get("pairs", []))
        merged.setdefault("data", {})["pairs"] = list(override_pairs) + existing
        r = httpx.put(f"{self.admin}/api/v2/simulation",
                      json=merged, timeout=self._timeout)
        r.raise_for_status()

    def __exit__(self, exc_type, exc, tb):
        if self._baseline is None:
            return False
        try:
            r = httpx.put(f"{self.admin}/api/v2/simulation",
                          json=self._baseline, timeout=self._timeout)
            r.raise_for_status()
        except Exception as e:
            logger.error("Hoverfly restore PUT failed: %s — simulation may be "
                         "polluted; run `pdm sandbox-mcp cleanup-overrides`", e)
        return False  # do not swallow exceptions


def _to_hoverfly_pair(matcher: dict, response: dict) -> dict:
    """Convert a high-level {matcher, response} into a Hoverfly v2 simulation pair."""
    req: dict = {}
    if "method" in matcher:
        req["method"] = [{"matcher": "exact", "value": str(matcher["method"]).upper()}]
    if "host" in matcher:
        req["destination"] = [{"matcher": "exact", "value": matcher["host"]}]
    if "path" in matcher:
        path = matcher["path"]
        m_type = "glob" if "*" in path else "exact"
        req["path"] = [{"matcher": m_type, "value": path}]
    if "body_contains" in matcher:
        req["body"] = [{"matcher": "contains", "value": matcher["body_contains"]}]

    resp: dict = {"status": int(response.get("status", 200))}
    body = response.get("body", "")
    resp["body"] = body if isinstance(body, str) else str(body)
    resp["encodedBody"] = False
    resp["postServeAction"] = POST_SERVE_ACTION_NAME
    headers = response.get("headers") or {}
    resp["headers"] = {k: ([v] if isinstance(v, str) else list(v))
                       for k, v in headers.items()}
    return {"request": req, "response": resp}

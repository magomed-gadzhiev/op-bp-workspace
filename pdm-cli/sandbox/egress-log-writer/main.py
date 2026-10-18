"""Hoverfly post-serve webhook -> POST PDM internal egress endpoint.

aiohttp service. Listens on POST /capture. Hoverfly is configured with a
post-serve middleware that issues HTTP POST to this URL after each handled
request.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web

LOG = logging.getLogger("egress-log-writer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

PDM_INTERNAL_URL = os.environ.get("PDM_INTERNAL_API_URL", "")
PDM_INTERNAL_TOKEN = os.environ.get("PDM_INTERNAL_API_TOKEN", "")
LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8910"))


def _first_header(headers: dict, name: str) -> str | None:
    """Hoverfly returns headers as {name: [values]}. Take the first."""
    for k, v in (headers or {}).items():
        if k.lower() == name.lower() and isinstance(v, list) and v:
            return v[0]
        if k.lower() == name.lower() and isinstance(v, str):
            return v
    return None


def hoverfly_payload_to_pdm_payload(event: dict) -> dict:
    req = event.get("request") or {}
    resp = event.get("response") or {}
    headers = req.get("headers") or {}
    run_id_raw = _first_header(headers, "X-PDM-Run-Id")
    source = _first_header(headers, "X-PDM-Source") or "unknown"
    bp_slug = _first_header(headers, "X-PDM-Bp-Slug")
    try:
        run_id_int = int(run_id_raw) if run_id_raw else None
    except (ValueError, TypeError):
        run_id_int = None
    scheme = req.get("scheme") or "https"
    dest = req.get("destination") or ""
    path = req.get("path") or ""
    return {
        "bp_run_id": run_id_int,
        "bp_slug": bp_slug,
        "method": req.get("method") or "GET",
        "url": f"{scheme}://{dest}{path}",
        "request_headers": {k: (v[0] if isinstance(v, list) and v else v) for k, v in headers.items()},
        "request_body": req.get("body") or "",
        "response_status": int(resp.get("status") or 0),
        "response_headers": {k: (v[0] if isinstance(v, list) and v else v) for k, v in (resp.get("headers") or {}).items()},
        "response_body": resp.get("body") or "",
        "duration_ms": int(event.get("latency_ms") or 0),
        "started_at": event.get("captured_at") or "1970-01-01T00:00:00Z",
        "source": source,
    }


async def handle_capture(request: web.Request) -> web.Response:
    try:
        event = await request.json()
    except Exception as e:
        LOG.warning("bad json: %s", e)
        return web.Response(status=400, text="bad json")
    payload = hoverfly_payload_to_pdm_payload(event)
    if not (PDM_INTERNAL_URL and PDM_INTERNAL_TOKEN):
        LOG.info("internal API not configured; dropping capture")
        return web.Response(status=200, text="ok")
    try:
        async with ClientSession(timeout=ClientTimeout(total=5)) as s:
            async with s.post(
                f"{PDM_INTERNAL_URL.rstrip('/')}/api/internal/egress-logs/http/",
                json=payload,
                headers={"X-PDM-Internal-Token": PDM_INTERNAL_TOKEN},
            ) as resp:
                if resp.status >= 400:
                    LOG.warning(
                        "internal POST failed status=%s body=%s",
                        resp.status,
                        (await resp.text())[:500],
                    )
    except Exception as e:
        LOG.warning("internal POST exception: %s", e)
    # Always 200 to Hoverfly -- never block prod traffic
    return web.Response(status=200, text="ok")


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/capture", handle_capture)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host=LISTEN_HOST, port=LISTEN_PORT)

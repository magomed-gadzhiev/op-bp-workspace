"""sandbox.add_fixture — write to _inbox-<kind>.yaml + hot-reload (http only)."""
from __future__ import annotations

import httpx

from ..fixtures_inbox import add_to_inbox
from ..hoverfly_override import _to_hoverfly_pair


def _impl_add_fixture(ctx: dict, *, bp: str, kind: str,
                       matcher: dict, response: dict) -> dict:
    repo = ctx["repo_root"]
    try:
        with ctx.get("mutex"):
            out = add_to_inbox(repo, bp=bp, kind=kind,
                               matcher=matcher, response=response)
            if out["conflict"] is None and kind == "http":
                # Hot-reload Hoverfly: GET current, APPEND new pair (not prepend
                # — inbox fixtures must not override baseline), PUT back.
                admin = ctx["hoverfly_admin"]
                r = httpx.get(f"{admin}/api/v2/simulation", timeout=10)
                r.raise_for_status()
                sim = r.json()
                pair = _to_hoverfly_pair(matcher, response)
                sim.setdefault("data", {})["pairs"] = list(
                    sim.get("data", {}).get("pairs", [])
                ) + [pair]
                httpx.put(f"{admin}/api/v2/simulation", json=sim,
                          timeout=15).raise_for_status()
        return out
    except Exception as e:
        return {"written_to": None, "entry_id": None,
                "conflict": None,
                "error": f"{type(e).__name__}: {e}"}


def register(server, ctx):
    @server.tool(name="sandbox.add_fixture",
                 description="Append a fixture matcher to _inbox-http.yaml or "
                             "_inbox-ssh.yaml. For HTTP, hot-reloads Hoverfly. "
                             "For SSH, requires restart or use replay_with_override.")
    def add_fixture(bp: str, kind: str, matcher: dict, response: dict) -> dict:
        return _impl_add_fixture(ctx, bp=bp, kind=kind,
                                  matcher=matcher, response=response)

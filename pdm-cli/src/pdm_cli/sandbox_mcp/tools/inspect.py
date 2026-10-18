"""sandbox.inspect_state + sandbox.list_egress — read-only tool-calls (no mutex)."""
from __future__ import annotations


def _impl_inspect_state(api, run_id: str) -> dict:
    body = api.run_details(run_id, include_script_output=True)
    return {
        "run_id": str(body.get("id", run_id)),
        "bp": body.get("bp"),
        "bp_version": body.get("bp_version"),
        "status": body.get("status"),
        "started_at": body.get("started_at"),
        "completed_at": body.get("completed_at"),
        "context_data": body.get("context_data") or {},
        "source_run_id": body.get("source_run_id"),
        "override_payload": body.get("override_payload"),
        "assignments": body.get("assignments") or [],
        "entity": body.get("entity"),
    }


def _impl_list_egress(api, run_id: str) -> dict:
    body = api.run_details(run_id)
    egress = body.get("egress") or {}
    return {
        "run_id": str(run_id),
        "http": egress.get("http") or [],
        "ssh": egress.get("ssh") or [],
        "orphan_count": egress.get("orphan_count") or {"http": 0, "ssh": 0},
    }


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


def register(server, ctx):
    api = ctx["api"]

    @server.tool(name="sandbox.inspect_state",
                 description="Return current state of a sandbox run "
                             "(context_data + assignments + status).")
    def inspect_state(run_id: str) -> dict:
        try:
            return _impl_inspect_state(api, run_id)
        except Exception as e:
            return {"error": _err(e)}

    @server.tool(name="sandbox.list_egress",
                 description="Return HTTP/SSH egress recorded during a sandbox run.")
    def list_egress(run_id: str) -> dict:
        try:
            return _impl_list_egress(api, run_id)
        except Exception as e:
            return {"error": _err(e)}

"""telemetry-related tool-calls (search_telemetry, get_run_details)."""

from typing import Optional


def do_search_telemetry(
    api, *, journals=None,
    bp_slug: str, since: str,
    until: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> dict:
    raw = api.list_runs(
        bp_slug, since=since, until=until, status=status, limit=limit, offset=0,
    )
    out = dict(raw)
    if journals is not None:
        out["sandbox_runs"] = [{"run_id": rid} for rid in journals.list_recent(limit=limit)]
    return out


def _merge_egress(api_egress: dict, journal: dict) -> dict:
    api_http = list(api_egress.get("http") or [])
    api_ssh = list(api_egress.get("ssh") or [])
    j_http = list(journal.get("http") or [])
    j_ssh = list(journal.get("ssh") or [])

    def _key_http(e):
        return (e.get("source"), e.get("started_at"), e.get("url"))

    def _key_ssh(e):
        return (e.get("source"), e.get("started_at"), e.get("command") or e.get("host"))

    seen_http = {_key_http(e) for e in api_http}
    seen_ssh = {_key_ssh(e) for e in api_ssh}
    for e in j_http:
        if _key_http(e) not in seen_http:
            api_http.append(e)
    for e in j_ssh:
        if _key_ssh(e) not in seen_ssh:
            api_ssh.append(e)
    return {
        "http": api_http,
        "ssh": api_ssh,
        "orphan_count": api_egress.get("orphan_count") or {"http": 0, "ssh": 0},
    }


def do_get_run_details(api, *, journals=None, run_id: int) -> dict:
    result = dict(api.run_details(run_id))
    if journals is not None:
        local = journals.read(run_id)
        if local is not None:
            result["egress"] = _merge_egress(result.get("egress") or {}, local)
            result["egress_source"] = "merged"
        else:
            result["egress_source"] = "sandbox-no-journal"
    else:
        result["egress_source"] = "prod-db"
    return result


def do_get_telemetry_aggregates(
    api, *, bp_slug: Optional[str] = None,
    since: str, until: Optional[str] = None,
) -> dict:
    return api.run_aggregates(bp_slug=bp_slug, since=since, until=until)


def do_get_replay_chain(api, *, run_id: int) -> dict:
    """Traverse the replay chain for a run via the backend endpoint."""
    return api.replay_chain(run_id)


def register(mcp, api, journals=None):
    @mcp.tool()
    def search_telemetry(
        bp_slug: str, since: str,
        until: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """Search recent runs of a business process. Status filter optional."""
        return do_search_telemetry(
            api, journals=journals, bp_slug=bp_slug, since=since,
            until=until, status=status, limit=limit,
        )

    @mcp.tool()
    def get_run_details(run_id: int) -> dict:
        """Full ProcessInstance details: assignments, history, egress (HTTP+SSH)."""
        return do_get_run_details(api, journals=journals, run_id=run_id)

    @mcp.tool()
    def get_telemetry_aggregates(
        since: str,
        bp_slug: Optional[str] = None,
        until: Optional[str] = None,
    ) -> dict:
        """Aggregated telemetry for run patterns, slow steps, and orphan egress."""
        return do_get_telemetry_aggregates(
            api, bp_slug=bp_slug, since=since, until=until,
        )

    @mcp.tool()
    def get_replay_chain(run_id: int) -> dict:
        """Traverse the replay chain for a run.

        Returns root run and all derived replays with depth indicators.
        Useful for understanding the history of replay attempts on a failed run.
        """
        return do_get_replay_chain(api, run_id=run_id)

"""processes/process tool-calls."""

from typing import Optional


def do_list_processes(api, status: Optional[str] = None, owner: Optional[str] = None) -> list[dict]:
    raw = api.list_processes()
    out = []
    for item in raw or []:
        if status and item.get("status") != status:
            continue
        if owner and item.get("owner") != owner:
            continue
        out.append({
            "slug": item.get("slug"),
            "status": item.get("status"),
            "version": item.get("version"),
            "owner": item.get("owner"),
            "last_modified": item.get("last_modified") or item.get("updated_at"),
        })
    return out


def do_get_process_summary(api, slug: str) -> dict:
    proc = api.get_full(slug)
    data = proc.model_dump() if hasattr(proc, "model_dump") else dict(proc)
    manifest = data.get("manifest") or {}
    return {
        "slug": manifest.get("slug", slug),
        "manifest": manifest,
        "entities": [e.get("slug") for e in (data.get("entities") or [])],
        "tasks": [t.get("slug") for t in (data.get("tasks") or [])],
        "scripts": [s.get("name") for s in (data.get("scripts") or [])],
        "workflows": [w.get("name") for w in (data.get("workflows") or [])],
        "templates": [tpl.get("name") for tpl in (data.get("templates") or [])],
    }


def do_get_process(api, slug: str) -> dict:
    proc = api.get_full(slug)
    return proc.model_dump() if hasattr(proc, "model_dump") else dict(proc)


def register(mcp, api):
    """Register processes-tools on the FastMCP server."""
    @mcp.tool()
    def list_processes(status: Optional[str] = None, owner: Optional[str] = None) -> list[dict]:
        """List business processes (slug, status, version, owner). Filter optional."""
        return do_list_processes(api, status=status, owner=owner)

    @mcp.tool()
    def get_process_summary(slug: str) -> dict:
        """Light summary of a BP: manifest + lists of entity/task/script/workflow slugs."""
        return do_get_process_summary(api, slug=slug)

    @mcp.tool()
    def get_process(slug: str) -> dict:
        """Full BP definition. Heavy — prefer summary first."""
        return do_get_process(api, slug=slug)

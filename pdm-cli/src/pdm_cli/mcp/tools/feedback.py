"""feedback tool-call — reads local feedback/tickets/."""

from typing import Optional


def do_get_feedback(reader, *,
                    bp_slug: Optional[str] = None,
                    status: Optional[str] = "new",
                    since: Optional[str] = None,
                    limit: int = 50) -> list[dict]:
    return reader.list(bp_slug=bp_slug, status=status, since=since, limit=limit)


def register(mcp, reader):
    @mcp.tool()
    def get_feedback(
        bp_slug: Optional[str] = None,
        status: Optional[str] = "new",
        since: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Read user feedback tickets from feedback/tickets/ (local files)."""
        return do_get_feedback(reader, bp_slug=bp_slug, status=status, since=since, limit=limit)

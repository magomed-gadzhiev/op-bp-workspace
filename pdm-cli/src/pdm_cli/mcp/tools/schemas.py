"""entity schema tool-call."""


def do_get_entity_schema(api, bp_slug: str, entity_slug: str) -> dict:
    return api.get_entity_schema(bp_slug, entity_slug)


def register(mcp, api):
    @mcp.tool()
    def get_entity_schema(bp_slug: str, entity_slug: str) -> dict:
        """JSON Schema for an entity type within a business process."""
        return do_get_entity_schema(api, bp_slug=bp_slug, entity_slug=entity_slug)

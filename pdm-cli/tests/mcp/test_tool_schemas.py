from unittest.mock import MagicMock
from pdm_cli.mcp.tools.schemas import do_get_entity_schema


def test_get_entity_schema_passes_through():
    api = MagicMock()
    api.get_entity_schema.return_value = {"type": "object", "properties": {"x": {}}}
    out = do_get_entity_schema(api, bp_slug="payroll", entity_slug="employee")
    assert out["type"] == "object"
    api.get_entity_schema.assert_called_once_with("payroll", "employee")

from unittest.mock import MagicMock
from pdm_cli.mcp.tools.feedback import do_get_feedback


def test_get_feedback_passes_filters():
    reader = MagicMock()
    reader.list.return_value = [{"id": "T-1"}]
    out = do_get_feedback(reader, bp_slug="payroll", status="new", since="30d", limit=50)
    reader.list.assert_called_once_with(
        bp_slug="payroll", status="new", since="30d", limit=50,
    )
    assert out == [{"id": "T-1"}]

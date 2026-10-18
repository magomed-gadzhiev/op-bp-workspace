"""FeedbackReader parses feedback/tickets/*.md with YAML frontmatter."""

from pathlib import Path

from pdm_cli.mcp.readers.feedback_fs import FeedbackReader


def _write(d: Path, name: str, content: str) -> None:
    (d / name).write_text(content, encoding="utf-8")


def test_lists_new_tickets_filtered_by_bp(tmp_path):
    d = tmp_path / "tickets"
    d.mkdir()
    _write(d, "T-0001.md", """---
id: T-2026-05-07-0001
created: 2026-05-07T14:23:00+03:00
bp: payroll
step: calc_bonus
user: ivan@x
status: new
related_run: 42
---

# Premium not counting satisfaction

Body text here.
""")
    _write(d, "T-0002.md", """---
id: T-2026-05-08-0002
created: 2026-05-08T10:00:00+03:00
bp: other-bp
status: new
---

# Different BP
""")
    reader = FeedbackReader(d)
    items = reader.list(bp_slug="payroll", status="new")
    assert len(items) == 1
    assert items[0]["id"] == "T-2026-05-07-0001"
    assert items[0]["title"] == "Premium not counting satisfaction"
    assert items[0]["related_run"] == 42


def test_returns_empty_on_missing_dir(tmp_path):
    reader = FeedbackReader(tmp_path / "nonexistent")
    assert reader.list() == []


def test_filter_by_status(tmp_path):
    d = tmp_path / "tickets"
    d.mkdir()
    _write(d, "T-A.md", """---
id: A
created: 2026-05-01T00:00:00Z
bp: x
status: new
---
# A
""")
    _write(d, "T-B.md", """---
id: B
created: 2026-05-02T00:00:00Z
bp: x
status: addressed
---
# B
""")
    reader = FeedbackReader(d)
    assert [i["id"] for i in reader.list(status="new")] == ["A"]
    assert [i["id"] for i in reader.list(status="addressed")] == ["B"]

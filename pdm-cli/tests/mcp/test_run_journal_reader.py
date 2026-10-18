"""RunJournalReader reads .pdm/runs/<id>/journal.json from Etap-4 layout."""

import json
from pathlib import Path

from pdm_cli.mcp.readers.run_journal import RunJournalReader


def _write_journal(root: Path, run_id: int, http: list, ssh: list) -> None:
    d = root / str(run_id)
    d.mkdir(parents=True)
    (d / "journal.json").write_text(json.dumps({"http": http, "ssh": ssh}), encoding="utf-8")


def test_returns_none_when_missing(tmp_path):
    r = RunJournalReader(tmp_path)
    assert r.read(42) is None


def test_returns_journal_dict(tmp_path):
    _write_journal(tmp_path, 42, http=[{"method": "GET", "url": "x"}], ssh=[])
    r = RunJournalReader(tmp_path)
    j = r.read(42)
    assert j["http"][0]["url"] == "x"
    assert j["ssh"] == []


def test_lists_recent_run_ids(tmp_path):
    _write_journal(tmp_path, 5, http=[], ssh=[])
    _write_journal(tmp_path, 7, http=[], ssh=[])
    r = RunJournalReader(tmp_path)
    ids = r.list_recent(limit=10)
    assert set(ids) == {5, 7}

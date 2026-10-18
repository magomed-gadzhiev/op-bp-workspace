"""Read local .pdm/runs/<id>/journal.json captured by `pdm test` (Etap 4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RunJournalReader:
    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)

    def read(self, run_id: int) -> dict[str, Any] | None:
        p = self.runs_dir / str(run_id) / "journal.json"
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def list_recent(self, limit: int = 50) -> list[int]:
        if not self.runs_dir.is_dir():
            return []
        ids: list[int] = []
        for sub in self.runs_dir.iterdir():
            if not sub.is_dir():
                continue
            try:
                ids.append(int(sub.name))
            except ValueError:
                continue
        ids.sort(reverse=True)
        return ids[:limit]

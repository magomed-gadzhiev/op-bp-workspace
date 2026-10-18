"""Append-with-conflict-detect writer for processes/<bp>/fixtures/_inbox-<kind>.yaml."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _canon(d: Any) -> Any:
    if isinstance(d, dict):
        return tuple(sorted((k, _canon(v)) for k, v in d.items()))
    if isinstance(d, list):
        return tuple(_canon(x) for x in d)
    return d


def _exact_match(a: dict, b: dict) -> bool:
    return _canon(a) == _canon(b)


def _load_yaml_safely(p: Path) -> dict:
    if not p.exists():
        return {"matchers": []}
    try:
        data = yaml.safe_load(p.read_text()) or {}
        if "matchers" not in data:
            data["matchers"] = []
        return data
    except Exception:
        return {"matchers": []}


def add_to_inbox(repo: Path, *, bp: str, kind: str,
                  matcher: dict, response: dict) -> dict:
    """Add a single matcher to `_inbox-<kind>.yaml` after duplicate-check.

    Returns: { written_to, entry_id, conflict }
      conflict is { kind, file, entry_index } if duplicate found, else None.
    """
    if kind not in ("http", "ssh"):
        raise ValueError(f"unknown kind: {kind!r}")
    fixtures_dir = repo / "processes" / bp / "fixtures"
    if not fixtures_dir.parent.is_dir():
        raise FileNotFoundError(f"bp dir not found: {fixtures_dir.parent}")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    inbox_path = fixtures_dir / f"_inbox-{kind}.yaml"

    # Check conflict in main fixtures and inbox
    for pattern in (f"{kind}-*.yaml", f"_inbox-{kind}.yaml"):
        for fp in fixtures_dir.glob(pattern):
            data = _load_yaml_safely(fp)
            for idx, entry in enumerate(data.get("matchers", [])):
                req = entry.get("request", entry) if isinstance(entry, dict) else {}
                if _exact_match(req, matcher):
                    return {
                        "written_to": str(inbox_path),
                        "entry_id": None,
                        "conflict": {
                            "kind": "exact_match_exists",
                            "file": str(fp.relative_to(repo)),
                            "entry_index": idx,
                        },
                    }

    inbox = _load_yaml_safely(inbox_path)
    next_seq = len(inbox["matchers"]) + 1
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry_id = f"inbox-{today}-{next_seq:03d}"
    entry = {
        "id": entry_id,
        "added_by": "pdm-sandbox-mcp",
        "added_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "pending",
        "request": matcher,
        "response": response,
    }
    inbox["matchers"].append(entry)
    inbox_path.write_text(yaml.safe_dump(inbox, allow_unicode=True, sort_keys=False))
    return {
        "written_to": str(inbox_path),
        "entry_id": entry_id,
        "conflict": None,
    }

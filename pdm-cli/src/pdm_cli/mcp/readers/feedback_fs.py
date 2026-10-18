"""Read feedback/tickets/*.md (YAML frontmatter + Markdown body)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


_FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n(.*)$", re.DOTALL)
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        v = value.rstrip("Z") + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(v)
    except ValueError:
        return None


class FeedbackReader:
    def __init__(self, tickets_dir: Path):
        self.tickets_dir = Path(tickets_dir)
        self._yaml = YAML(typ="safe")

    def list(
        self, *,
        bp_slug: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self.tickets_dir.is_dir():
            return []
        since_dt = _parse_since(since)
        items: list[dict] = []
        for path in sorted(self.tickets_dir.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            m = _FRONTMATTER_RE.match(content)
            if not m:
                continue
            try:
                fm = self._yaml.load(m.group(1)) or {}
            except Exception:
                continue
            body = m.group(2).strip()
            title_m = _TITLE_RE.search(body)
            title = title_m.group(1).strip() if title_m else ""

            if bp_slug and (fm.get("bp") != bp_slug):
                continue
            if status and (fm.get("status") != status):
                continue
            if since_dt:
                created = _parse_since(str(fm.get("created", "")))
                if not created or created < since_dt:
                    continue

            items.append({
                "id": fm.get("id"),
                "created": fm.get("created"),
                "bp": fm.get("bp"),
                "step": fm.get("step"),
                "user": fm.get("user"),
                "status": fm.get("status"),
                "related_run": fm.get("related_run"),
                "title": title,
                "body": body,
            })
        items.sort(key=lambda x: str(x.get("created", "")), reverse=True)
        return items[:limit]

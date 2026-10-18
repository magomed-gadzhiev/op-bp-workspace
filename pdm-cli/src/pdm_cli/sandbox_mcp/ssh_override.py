"""ssh-replay override-dir writer.

For each replay_with_override run, sandbox-mcp writes a single YAML file
into SSH_REPLAY_OVERRIDE_DIR which ssh-replay re-globs on every SSH
connection. On context exit the file is removed (best-effort).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import yaml

logger = logging.getLogger(__name__)


class SshOverrideContext:
    def __init__(self, override_dir, run_id):
        self.override_dir = Path(override_dir)
        self.run_id = str(run_id)
        self.path = self.override_dir / f"replay-{self.run_id}.yaml"

    def __enter__(self):
        return self

    def inject(self, override_matchers: Iterable[dict]) -> None:
        self.override_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump({"matchers": list(override_matchers)},
                           allow_unicode=True, sort_keys=False)
        )

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.path.exists():
                self.path.unlink()
        except Exception as e:
            logger.error("ssh-replay override cleanup failed for %s: %s",
                         self.path, e)
        return False

"""Parse `PDM_RUN_ID=<id> PDM_SOURCE=<src> <command>` env-var prefix.

Used by ssh-bastion (prod) and ssh-replay (sandbox) to extract correlation
metadata from incoming exec requests before forwarding/replaying.

NOTE: A copy of this file lives in ``../ssh-replay/envparse.py``. Keep both
in sync until we extract a shared module (out of scope here).
"""

from __future__ import annotations

import re

_ENV_PREFIX_RE = re.compile(r'^([A-Z_][A-Z0-9_]*)=(\S+)\s+')


def parse_pdm_envprefix(command: str) -> tuple[str | None, str | None, str]:
    """Returns (run_id, source, stripped_command).

    Strips any PDM_RUN_ID / PDM_SOURCE env-prefix from the start of the
    command. Other env-prefixes are left untouched (forwarded as-is).
    """
    run_id: str | None = None
    source: str | None = None
    remaining = command
    while True:
        m = _ENV_PREFIX_RE.match(remaining)
        if not m:
            break
        key, value = m.group(1), m.group(2)
        if key == "PDM_RUN_ID":
            run_id = value
            remaining = remaining[m.end():]
        elif key == "PDM_SOURCE":
            source = value
            remaining = remaining[m.end():]
        else:
            break
    return run_id, source, remaining

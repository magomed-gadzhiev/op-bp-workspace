"""ssh-replay journal client: query SSH side-effects recorded by the ssh-replay server.

Used by the test runner to assert that BP scripts produced expected outbound SSH
commands (kind: ssh) against simulated hosts.

Note: ssh-replay's GET /journal returns a bare JSON array (not wrapped in a
`journal` key, unlike Hoverfly's admin API).
"""
from __future__ import annotations

import re

import httpx


def clear_ssh_journal(base: str) -> None:
    """Delete all entries from the ssh-replay journal."""
    r = httpx.delete(f"{base.rstrip('/')}/journal", timeout=10)
    r.raise_for_status()


def get_ssh_journal(base: str) -> list[dict]:
    """Fetch the full ssh-replay journal as a list of executed-command entries."""
    r = httpx.get(f"{base.rstrip('/')}/journal", timeout=10)
    r.raise_for_status()
    data = r.json()
    return data or []


def match_ssh_side_effect(base: str, eff) -> list[dict]:
    """Return journal entries matching the SshSideEffect predicate.

    Filters by (optional) `host` exact match and regex search of `command_matches`
    against the journal entry's `command` field.
    """
    cmd_re = re.compile(eff.command_matches)
    out: list[dict] = []
    for entry in get_ssh_journal(base):
        if eff.host and entry.get("host") != eff.host:
            continue
        if not cmd_re.search(entry.get("command") or ""):
            continue
        out.append(entry)
    return out

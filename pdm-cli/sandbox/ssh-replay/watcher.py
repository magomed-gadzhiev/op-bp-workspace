"""Inotify watcher: POST /_internal/reload when override fixtures change.

Etap 8 Phase 2. Runs as a side process next to server.py (started from the
container CMD). On filesystem events in the override directory, calls the
server's control endpoint at 127.0.0.1:SSH_REPLAY_CONTROL_PORT (default 2223).

Soft dependency on inotify_simple: if the package is missing or the override
directory does not exist yet, the watcher exits cleanly. The server still
re-reads overrides on every SSH connection (Etap 7 reload-on-connect), so
hot-reload is an optimization, not a correctness requirement.
"""
from __future__ import annotations

import os
import sys
import urllib.request

try:
    from inotify_simple import INotify, flags
except ImportError:  # pragma: no cover - soft dependency
    print(
        "watcher: inotify_simple not installed; exit "
        "(server keeps reload-on-connect)",
        flush=True,
    )
    sys.exit(0)


def main() -> None:
    override_dir = os.environ.get("SSH_REPLAY_OVERRIDE_DIR")
    if not override_dir or not os.path.isdir(override_dir):
        print(
            f"watcher: override dir {override_dir!r} not present; exit "
            "(server keeps reload-on-connect)",
            flush=True,
        )
        return

    control_port = int(os.environ.get("SSH_REPLAY_CONTROL_PORT", "2223"))
    reload_url = f"http://127.0.0.1:{control_port}/_internal/reload"

    inotify = INotify()
    watch_flags = flags.CLOSE_WRITE | flags.MOVED_TO | flags.DELETE | flags.CREATE
    inotify.add_watch(override_dir, watch_flags)

    print(f"watcher: watching {override_dir} -> {reload_url}", flush=True)
    while True:
        # Each inotify batch triggers one reload POST. The server re-globs the
        # whole override directory, so coalescing many events is correct.
        events = inotify.read(timeout=None)
        if not events:
            continue
        try:
            resp = urllib.request.urlopen(reload_url, data=b"", timeout=2)
            body = resp.read().decode("utf-8", errors="replace").strip()
            print(f"watcher: reload ok ({body})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"watcher: reload POST failed: {e}", flush=True)


if __name__ == "__main__":
    main()

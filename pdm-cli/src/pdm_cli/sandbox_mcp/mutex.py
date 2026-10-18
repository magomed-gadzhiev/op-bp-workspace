"""Server-wide threading.Lock for sandbox-mcp mutating operations."""
from __future__ import annotations

import threading


class MutexTimeout(RuntimeError):
    pass


class SandboxMutex:
    def __init__(self, *, timeout_sec: float = 600.0):
        self._lock = threading.Lock()
        self.timeout_sec = timeout_sec

    def __enter__(self):
        acquired = self._lock.acquire(timeout=self.timeout_sec)
        if not acquired:
            raise MutexTimeout(
                f"sandbox busy: another mutating operation is in progress "
                f"(waited {self.timeout_sec}s)"
            )
        return self

    def __exit__(self, exc_type, exc, tb):
        self._lock.release()
        return False

"""Etap 7 Phase 4 — sandbox-mcp uses a server-wide threading.Lock with timeout."""
import threading

import pytest

from pdm_cli.sandbox_mcp.mutex import SandboxMutex, MutexTimeout


def test_lock_blocks_concurrent_caller_and_timeouts():
    m = SandboxMutex(timeout_sec=0.5)
    enter_a = threading.Event()
    release_a = threading.Event()
    err: list = []

    def a():
        with m:
            enter_a.set()
            release_a.wait(timeout=5)

    def b():
        try:
            with m:
                pass
        except MutexTimeout as e:
            err.append(e)

    t1 = threading.Thread(target=a)
    t1.start()
    enter_a.wait(timeout=2)
    t2 = threading.Thread(target=b)
    t2.start()
    t2.join(timeout=5)
    release_a.set()
    t1.join()
    assert len(err) == 1, "B should have hit MutexTimeout"


def test_lock_releases_on_exception():
    m = SandboxMutex(timeout_sec=1)
    with pytest.raises(RuntimeError):
        with m:
            raise RuntimeError("boom")
    # next acquire should succeed
    with m:
        pass

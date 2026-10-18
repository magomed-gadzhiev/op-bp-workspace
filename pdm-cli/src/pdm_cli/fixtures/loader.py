"""Per-case fixture auto-loading for `pdm test`.

Dispatches fixture files to Hoverfly (http-*) or ssh-replay override dir (ssh-*)
based on the fixture name prefix.  Called by the test runner around `run_case`.
"""
from __future__ import annotations

from pathlib import Path

from .hoverfly import HoverflyClient
from .http import fixture_to_hoverfly_simulation, load_http_fixture
from .ssh import dump_ssh_fixture, load_ssh_fixture
from .versioning import parse_ref, resolve_fixture_file


def load_fixtures_for_case(tc, bp_dir: Path, ctx) -> list[str]:
    """Load all fixtures declared in *tc.fixtures* and return loaded references.

    A reference may be a bare ``<stem>`` (latest) or pinned ``<stem>@N`` (E16); the
    on-disk path is resolved via :func:`versioning.resolve_fixture_file`. Protocol
    dispatch is by the ``<stem>`` prefix (``@N`` stripped first).

    *ctx* is a RunnerContext with `hoverfly_admin` and `ssh_override_dir`.
    Raises RuntimeError for an unknown prefix or an unresolvable fixture reference.
    """
    loaded: list[str] = []
    for ref in tc.fixtures:
        stem, _ = parse_ref(ref)
        try:
            path = resolve_fixture_file(bp_dir, ref)
        except FileNotFoundError as e:
            raise RuntimeError(f"Fixture file not found for '{ref}': {e}")
        if stem.startswith("http-"):
            fixture = load_http_fixture(path)
            sim = fixture_to_hoverfly_simulation([fixture])
            HoverflyClient(ctx.hoverfly_admin).put_simulation(sim)
            loaded.append(ref)
        elif stem.startswith("ssh-"):
            if not getattr(ctx, "ssh_override_dir", ""):
                raise RuntimeError(
                    f"ssh fixture '{ref}' requested but RunnerContext.ssh_override_dir is not set"
                )
            override_dir = Path(ctx.ssh_override_dir)
            override_dir.mkdir(parents=True, exist_ok=True)
            fixture = load_ssh_fixture(path)
            dest = override_dir / f"fixture-{stem}.yaml"
            dump_ssh_fixture(fixture, dest)
            loaded.append(ref)
        else:
            raise RuntimeError(
                f"Unknown fixture prefix for '{ref}': expected 'http-' or 'ssh-'"
            )
    return loaded


def unload_fixtures_for_case(loaded: list[str], ctx) -> None:
    """Tear down fixtures that were loaded by `load_fixtures_for_case`.

    HTTP: resets Hoverfly simulation (passthrough).
    SSH: deletes the per-fixture override file.
    """
    has_http = any(n.startswith("http-") for n in loaded)
    if has_http:
        HoverflyClient(ctx.hoverfly_admin).delete_simulation()

    if getattr(ctx, "ssh_override_dir", ""):
        override_dir = Path(ctx.ssh_override_dir)
        for ref in loaded:
            stem, _ = parse_ref(ref)
            if stem.startswith("ssh-"):
                dest = override_dir / f"fixture-{stem}.yaml"
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass

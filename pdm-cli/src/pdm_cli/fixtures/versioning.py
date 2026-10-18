"""E16 fixture hygiene — version reference parsing, path resolution, archive, staleness.

A fixture reference (the plain string inside ``TestCase.fixtures``) is either:

* ``<stem>``       → the *active* file ``<bp>/fixtures/<stem>.yaml`` (latest version)
* ``<stem>@<N>``   → version N: the active file if ``active.version == N``,
                     otherwise ``<bp>/fixtures/_archive/<stem>/v<N>.yaml``

The ``http-`` / ``ssh-`` protocol prefix is preserved inside ``<stem>`` so the loader's
prefix-based dispatch keeps working on archived content. No new dependencies.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from ruamel.yaml import YAML

_ARCHIVE_DIR = "_archive"


def parse_ref(ref: str) -> tuple[str, int | None]:
    """Split a fixture reference into ``(stem, version|None)``.

    Splits on the **last** ``@``. A right-hand side that is not a positive integer is
    treated as part of the name (defensive) — the resolver / validate surfaces it later.
    """
    stem, sep, ver = ref.rpartition("@")
    if sep and stem and ver.isdigit() and int(ver) >= 1:
        return stem, int(ver)
    return ref, None


def _fixtures_dir(bp_dir: Path) -> Path:
    return Path(bp_dir) / "fixtures"


def _active_path(bp_dir: Path, stem: str) -> Path:
    return _fixtures_dir(bp_dir) / f"{stem}.yaml"


def _archive_path(bp_dir: Path, stem: str, version: int) -> Path:
    return _fixtures_dir(bp_dir) / _ARCHIVE_DIR / stem / f"v{version}.yaml"


def read_version(path: Path) -> int:
    """Read the ``version`` field from a fixture YAML (default 1 for legacy files)."""
    y = YAML(typ="safe")
    with Path(path).open("r", encoding="utf-8") as f:
        data = y.load(f) or {}
    try:
        return int(data.get("version", 1))
    except (TypeError, ValueError):
        return 1


def available_versions(bp_dir: Path, stem: str) -> list[int]:
    """Return all versions for *stem*: active version + archived ``vN``, sorted, deduped."""
    versions: set[int] = set()
    active = _active_path(bp_dir, stem)
    if active.is_file():
        versions.add(read_version(active))
    archive_dir = _fixtures_dir(bp_dir) / _ARCHIVE_DIR / stem
    if archive_dir.is_dir():
        for f in archive_dir.glob("v*.yaml"):
            num = f.stem[1:]  # strip leading "v"
            if num.isdigit():
                versions.add(int(num))
    return sorted(versions)


def resolve_fixture_file(bp_dir: Path, ref: str) -> Path:
    """Resolve a fixture reference to an on-disk path (D3 resolution order).

    Raises ``FileNotFoundError`` with a clear message (and available versions for a
    pinned ref) when nothing resolves.
    """
    stem, version = parse_ref(ref)
    active = _active_path(bp_dir, stem)

    if version is None:
        if active.is_file():
            return active
        raise FileNotFoundError(
            f"fixture '{stem}' not found: expected active file {active}"
        )

    if active.is_file() and read_version(active) == version:
        return active

    archived = _archive_path(bp_dir, stem, version)
    if archived.is_file():
        return archived

    avail = available_versions(bp_dir, stem)
    avail_str = ", ".join(str(v) for v in avail) if avail else "none"
    raise FileNotFoundError(
        f"fixture '{stem}' has no version {version} "
        f"(available versions: {avail_str})"
    )


def archive_active(bp_dir: Path, stem: str) -> Path:
    """Copy the current active ``<stem>.yaml`` to ``_archive/<stem>/v<active.version>.yaml``.

    Creates the archive directory; returns the archive path.
    """
    active = _active_path(bp_dir, stem)
    if not active.is_file():
        raise FileNotFoundError(f"cannot archive missing active fixture: {active}")
    version = read_version(active)
    dest = _archive_path(bp_dir, stem, version)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(active, dest)
    return dest


def staleness(
    recorded_at: str | None,
    weeks: int,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Classify a fixture by recorded date.

    Returns ``(age_display, status)`` where status is one of
    ``ok`` / ``stale`` / ``stale (unknown date)`` / ``future date?`` (D6).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if recorded_at in (None, "", "unknown"):
        return "unknown", "stale (unknown date)"

    # The YAML loader may already have parsed an unquoted ISO timestamp into a datetime.
    if isinstance(recorded_at, datetime):
        parsed = recorded_at
    else:
        try:
            parsed = datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return "unknown", "stale (unknown date)"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    delta_days = (now - parsed).days
    if delta_days < 0:
        return "future", "future date?"

    age_weeks = delta_days // 7
    age_display = f"{age_weeks} weeks"
    status = "stale" if age_weeks > weeks else "ok"
    return age_display, status

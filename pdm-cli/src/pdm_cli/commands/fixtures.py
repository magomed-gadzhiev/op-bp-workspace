"""`pdm fixtures` command group — record/replay HTTP and SSH fixtures."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from pathlib import Path

import click

from ..config import load_config
from ..fixtures.hoverfly import HoverflyClient
from ..fixtures.http import (
    dump_http_fixture,
    fixture_to_hoverfly_simulation,
    hoverfly_simulation_to_fixtures,
    load_http_fixture,
)
from ..fixtures.redaction import redact_http_fixture
from ..fixtures.versioning import read_version


def _now_iso() -> str:
    """Current time as ISO-8601 UTC, e.g. ``2026-05-20T12:34:56Z`` (E16, FR-001)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp_for_record(fix, out: Path) -> None:
    """Stamp version + recorded_at on a freshly-recorded fixture (D4).

    Always refreshes ``recorded_at``. Preserves the existing active ``version`` on a
    re-record; otherwise leaves the model default (1) for a new file.
    """
    fix.recorded_at = _now_iso()
    if out.is_file():
        fix.version = read_version(out)


@click.group("fixtures")
def fixtures():
    """Record / replay HTTP and SSH fixtures for sandbox replay."""


@fixtures.command("record")
@click.option("--bp", "bp_slug", required=True)
@click.option("--case", "case_name", required=True)
@click.option("--protocol", type=click.Choice(["http", "ssh", "all"]), default="http")
@click.option("--from-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="Read Hoverfly simulation.json from file instead of live API")
@click.option("--dry-run", is_flag=True, help="Don't write files, only print summary")
@click.option("--ssh-capture", type=click.Path(path_type=Path), default=None,
              help="Per-BP captures root (default: $PDM_SSH_CAPTURE_DIR or .pdm/ssh-captures). "
                   "Reads <root>/<bp>/*.jsonl. Set PDM_SSH_CAPTURE_FILE for legacy single-file mode.")
@click.pass_context
def record(ctx, bp_slug, case_name, protocol, from_file, dry_run, ssh_capture):
    """Record fixtures from Hoverfly capture (or SSH bastion logs)."""
    repo_root = ctx.obj["cwd"]
    cfg = load_config(repo_root)
    bp_dir = repo_root / "processes" / bp_slug
    if not bp_dir.is_dir():
        raise click.ClickException(f"BP not found: {bp_dir}")
    fixtures_dir = bp_dir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    if protocol in ("http", "all"):
        if from_file:
            import json
            sim = json.loads(from_file.read_text(encoding="utf-8"))
        else:
            client = HoverflyClient(cfg.endpoint("hoverfly"))
            try:
                sim = client.get_simulation()
            finally:
                client.close()
        fix = hoverfly_simulation_to_fixtures(sim, case_name=case_name)
        fix = redact_http_fixture(fix, cfg.egress_http_redact)
        out = fixtures_dir / f"http-{case_name}.yaml"
        _stamp_for_record(fix, out)
        if dry_run:
            click.echo(f"[dry-run] would write {out} ({len(fix.matchers)} matchers)")
        else:
            dump_http_fixture(fix, out)
            click.echo(f"wrote {out} ({len(fix.matchers)} matchers)")

    if protocol in ("ssh", "all"):
        from ..fixtures.ssh import (
            from_capture_jsonl,
            from_capture_jsonl_dir,
            redact_ssh_fixture,
            dump_ssh_fixture,
        )
        fix = None
        single_file_env = os.environ.get("PDM_SSH_CAPTURE_FILE")
        if ssh_capture and Path(ssh_capture).is_file():
            fix = from_capture_jsonl(Path(ssh_capture), case_name=case_name)
        elif single_file_env:
            sp = Path(single_file_env)
            if not sp.is_file():
                click.echo(f"[ssh] no capture file at {sp}; skipping", err=True)
            else:
                fix = from_capture_jsonl(sp, case_name=case_name)
        else:
            captures_root = ssh_capture or Path(os.environ.get(
                "PDM_SSH_CAPTURE_DIR", str(repo_root / ".pdm" / "ssh-captures")
            ))
            captures_root = Path(captures_root)
            try:
                fix = from_capture_jsonl_dir(captures_root, bp_slug=bp_slug, case_name=case_name)
            except FileNotFoundError as e:
                click.echo(f"[ssh] {e}; skipping", err=True)
        if fix is not None:
            fix = redact_ssh_fixture(fix, cfg.egress_ssh_redact)
            out = fixtures_dir / f"ssh-{case_name}.yaml"
            _stamp_for_record(fix, out)
            if dry_run:
                click.echo(f"[dry-run] would write {out} ({len(fix.matchers)} matchers)")
            else:
                dump_ssh_fixture(fix, out)
                click.echo(f"wrote {out} ({len(fix.matchers)} matchers)")


@fixtures.command("audit")
@click.option("--bp", "bp_slug", required=True)
@click.option("--weeks", type=int, default=12, help="Staleness threshold in weeks (default 12).")
@click.pass_context
def audit(ctx, bp_slug, weeks):
    """Report version / record date / staleness of every active fixture in a BP."""
    from rich.console import Console
    from rich.table import Table

    from ..fixtures.audit import audit_rows

    repo_root = ctx.obj["cwd"]
    bp_dir = repo_root / "processes" / bp_slug
    if not bp_dir.is_dir():
        click.echo(f"BP not found: {bp_dir}")
        return
    rows = audit_rows(bp_dir, weeks)
    if not rows:
        click.echo(f"No active fixtures in {bp_slug}.")
        return
    table = Table(title=f"Fixtures for {bp_slug} (stale threshold: {weeks} weeks)")
    table.add_column("fixture")
    table.add_column("version", justify="right")
    table.add_column("recorded_at")
    table.add_column("age")
    table.add_column("status")
    for row in rows:
        table.add_row(
            row["fixture"], str(row["version"]), row["recorded_at"], row["age"], row["status"]
        )
    # Width is fixed so captured (non-TTY) output is not truncated.
    Console(width=120).print(table)


@fixtures.command("clean")
@click.option("--bp", "bp_slug", required=True)
@click.option("--dry-run", is_flag=True, help="Preview only; delete nothing.")
@click.pass_context
def clean(ctx, bp_slug, dry_run):
    """Delete active fixtures that no test case references (+ their archive)."""
    import shutil

    from ..fixtures.audit import active_fixture_files, referenced_stems

    repo_root = ctx.obj["cwd"]
    bp_dir = repo_root / "processes" / bp_slug
    if not bp_dir.is_dir():
        click.echo(f"BP not found: {bp_dir}")
        return
    actives = active_fixture_files(bp_dir)
    if not actives:
        click.echo(f"No active fixtures in {bp_slug}.")
        return
    used = referenced_stems(bp_dir)
    unused = [f for f in actives if f.stem not in used]
    kept = len(actives) - len(unused)

    if not unused:
        click.echo(f"Nothing to clean in {bp_slug}: all {kept} fixture(s) used.")
        return

    if dry_run:
        click.echo(f"[dry-run] would delete {len(unused)} unused fixture(s) in {bp_slug}:")
        for f in unused:
            click.echo(f"  - {f.stem}  (+ archive)")
        return

    archive_root = bp_dir / "fixtures" / "_archive"
    for f in unused:
        f.unlink(missing_ok=True)
        archive_subtree = archive_root / f.stem
        if archive_subtree.is_dir():
            shutil.rmtree(archive_subtree)
    click.echo(f"deleted {len(unused)} unused fixture(s) in {bp_slug}:")
    for f in unused:
        click.echo(f"  - {f.stem}  (+ archive)")
    click.echo(f"kept {kept} used fixture(s).")


def _content_lines(model_dump: dict) -> list[str]:
    """Serialize a fixture dict to canonical YAML lines, ignoring version/recorded_at."""
    import io

    from ruamel.yaml import YAML

    data = dict(model_dump)
    data.pop("version", None)
    data.pop("recorded_at", None)
    y = YAML()
    y.default_flow_style = False
    y.indent(mapping=2, sequence=4, offset=2)
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue().splitlines(keepends=True)


@fixtures.command("refresh")
@click.option("--bp", "bp_slug", required=True)
@click.option("--case", "case_name", default=None, help="Refresh one case (default: all).")
@click.option("--protocol", type=click.Choice(["http", "ssh", "all"]), default="http")
@click.option("--from-file", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="Hoverfly simulation.json source (mirrors record).")
@click.option("--ssh-capture", type=click.Path(path_type=Path), default=None,
              help="SSH capture root/file (mirrors record).")
@click.option("--dry-run", is_flag=True, help="Show diff, change nothing.")
@click.pass_context
def refresh(ctx, bp_slug, case_name, protocol, from_file, ssh_capture, dry_run):
    """Re-capture fixtures with a content diff, archiving the prior version (E16 US3)."""
    import difflib

    from ..fixtures.http import load_http_fixture
    from ..fixtures.ssh import (
        dump_ssh_fixture,
        from_capture_jsonl,
        from_capture_jsonl_dir,
        load_ssh_fixture,
        redact_ssh_fixture,
    )
    from ..fixtures.versioning import archive_active

    repo_root = ctx.obj["cwd"]
    cfg = load_config(repo_root)
    bp_dir = repo_root / "processes" / bp_slug
    if not bp_dir.is_dir():
        click.echo(f"BP not found: {bp_dir}")
        return
    fixtures_dir = bp_dir / "fixtures"

    protos = ["http", "ssh"] if protocol == "all" else [protocol]

    def _targets(proto: str) -> list[Path]:
        if case_name:
            f = fixtures_dir / f"{proto}-{case_name}.yaml"
            return [f] if f.is_file() else []
        return sorted(fixtures_dir.glob(f"{proto}-*.yaml"))

    def _capture_http(case: str):
        if from_file:
            import json
            sim = json.loads(Path(from_file).read_text(encoding="utf-8"))
        else:
            client = HoverflyClient(cfg.endpoint("hoverfly"))
            try:
                sim = client.get_simulation()
            finally:
                client.close()
        fix = hoverfly_simulation_to_fixtures(sim, case_name=case)
        return redact_http_fixture(fix, cfg.egress_http_redact)

    def _capture_ssh(case: str):
        if ssh_capture and Path(ssh_capture).is_file():
            fix = from_capture_jsonl(Path(ssh_capture), case_name=case)
        else:
            captures_root = Path(ssh_capture or os.environ.get(
                "PDM_SSH_CAPTURE_DIR", str(repo_root / ".pdm" / "ssh-captures")
            ))
            fix = from_capture_jsonl_dir(captures_root, bp_slug=bp_slug, case_name=case)
        return redact_ssh_fixture(fix, cfg.egress_ssh_redact)

    any_target = False
    for proto in protos:
        targets = _targets(proto)
        loader = load_http_fixture if proto == "http" else load_ssh_fixture
        dumper = dump_http_fixture if proto == "http" else dump_ssh_fixture
        capture = _capture_http if proto == "http" else _capture_ssh
        for active in targets:
            any_target = True
            stem = active.stem
            curr = loader(active)
            try:
                new = capture(curr.name)
            except FileNotFoundError as e:
                click.echo(f"{bp_slug} / {stem}: cannot re-capture — {e}")
                continue
            new.name = curr.name  # content parity ignores version/recorded_at

            old_lines = _content_lines(curr.model_dump(mode="python"))
            new_lines = _content_lines(new.model_dump(mode="python"))
            diff = list(difflib.unified_diff(
                old_lines, new_lines, fromfile=f"v{curr.version}", tofile="new"
            ))
            if not diff:
                click.echo(f"{bp_slug} / {stem}  no changes")
                continue

            click.echo(f"{bp_slug} / {stem}  v{curr.version} → v{curr.version + 1}")
            click.echo("".join(diff))
            if dry_run:
                click.echo("[dry-run] not written")
                continue

            archive_active(bp_dir, stem)
            new.version = curr.version + 1
            new.recorded_at = _now_iso()
            dumper(new, active)
            click.echo(
                f"archived v{curr.version} → _archive/{stem}/v{curr.version}.yaml; "
                f"active is now v{new.version}"
            )

    if not any_target:
        target = f"'{case_name}'" if case_name else "any case"
        click.echo(f"No existing fixture to refresh in {bp_slug} for {target}.")


@fixtures.command("replay")
@click.option("--bp", "bp_slug", default=None, help="Restrict to one BP (default: all)")
@click.option("--protocol", type=click.Choice(["http", "ssh", "all"]), default="http")
@click.option("--dry-run", is_flag=True)
@click.pass_context
def replay(ctx, bp_slug, protocol, dry_run):
    """Load fixtures into Hoverfly (HTTP) and SSH replay (Task 14)."""
    repo_root = ctx.obj["cwd"]
    cfg = load_config(repo_root)
    processes = repo_root / "processes"

    if protocol in ("http", "all"):
        fixtures_files: list[Path] = []
        if bp_slug:
            fixtures_files.extend((processes / bp_slug / "fixtures").glob("http-*.yaml"))
        else:
            fixtures_files.extend(processes.glob("*/fixtures/http-*.yaml"))
        loaded = [load_http_fixture(p) for p in fixtures_files]
        sim = fixture_to_hoverfly_simulation(loaded)
        total = sum(len(f.matchers) for f in loaded)
        click.echo(f"loaded {len(loaded)} fixture file(s), {total} matcher(s)")
        if dry_run:
            click.echo("[dry-run] not pushing to Hoverfly")
            return
        client = HoverflyClient(cfg.endpoint("hoverfly"))
        try:
            client.put_simulation(sim)
            client.set_mode("simulate")
            click.echo("Hoverfly switched to simulate mode")
        finally:
            client.close()

    if protocol in ("ssh", "all"):
        target_dir = Path(os.environ.get("PDM_SSH_REPLAY_DIR", str(repo_root / ".pdm" / "ssh-replay-fixtures")))
        target_dir.mkdir(parents=True, exist_ok=True)
        for f in target_dir.glob("ssh-*.yaml"):
            f.unlink()
        ssh_files: list[Path] = []
        if bp_slug:
            ssh_files.extend((processes / bp_slug / "fixtures").glob("ssh-*.yaml"))
        else:
            ssh_files.extend(processes.glob("*/fixtures/ssh-*.yaml"))
        for src in ssh_files:
            (target_dir / src.name).write_bytes(src.read_bytes())
        click.echo(f"consolidated {len(ssh_files)} SSH fixture(s) into {target_dir}")
        click.echo("→ restart pdm-egress-ssh-replay container to reload")

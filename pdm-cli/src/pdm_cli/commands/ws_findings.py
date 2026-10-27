"""pdm ws findings — замечания по инструменту (спека 166, ADR-0073).

Файл-первый канал: агент пишет Markdown в workspace/_findings/, `check`
валидирует офлайн, `submit` отправляет в POST /api/feedbacks/submit/
идемпотентно по external_id, `list` читает свои замечания и статусы.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import click
import httpx
from rich.table import Table

from .. import __version__
from ..finding_file import (
    FindingError,
    ensure_external_id,
    load_finding,
    resolve_paths,
    update_fields,
    validate_finding,
)
from .common import api_options, console, make_client


@click.group("findings")
def findings():
    """Замечания по инструменту: check/submit/list (спека 166)."""


def _report_errors(path: Path, errors: list[str]) -> None:
    console.print(f"[red]{path}:[/red]")
    for error in errors:
        console.print(f"  • {error}")


def _server_error(exc: httpx.HTTPStatusError) -> str:
    try:
        data = exc.response.json()
    except Exception:
        return f"HTTP {exc.response.status_code}"
    if isinstance(data, dict):
        for key in ("detail", "error"):
            if data.get(key):
                return f"HTTP {exc.response.status_code}: {data[key]}"
    return f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"


def _body_error(body) -> str:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        parts = [
            f"{key}: {value}"
            for key, value in body.items()
            if key not in ("detail", "error")
        ]
        if parts:
            return "; ".join(parts)
    return str(body)[:300]


def _payload(finding, api_version: str, bp_pk: int | None) -> dict:
    data = finding.data
    origin = {
        "source": "op-bp-workspace",
        "cli_version": __version__,
        "api_version": api_version,
    }
    bp_slug = str(data.get("bp") or "").strip()
    if bp_slug:
        origin["bp_slug"] = bp_slug
    model = os.environ.get("LLM_MODEL")
    if model:
        origin["model"] = model

    payload = {
        "external_id": finding.external_id,
        "type": data["type"],
        "title": data["title"],
        "description": finding.body.strip(),
        "target": data["target"],
        "severity": data["severity"],
        "origin": origin,
    }
    if bp_pk is not None:
        payload["related_business_process_id"] = bp_pk
    return payload


@findings.command("check")
@click.argument("paths", nargs=-1, type=click.Path(path_type=Path))
@click.option("--fix", is_flag=True,
              help="Дописать external_id/created_at, если их нет.")
@click.pass_context
def findings_check(ctx, paths, fix):
    """Офлайн-валидация файлов замечаний."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    files = resolve_paths(paths, cwd)
    if not files:
        console.print(
            "файлов замечаний нет — создайте workspace/_findings/*.md")
        return

    failed = False
    for path in files:
        try:
            finding = load_finding(path)
        except (OSError, FindingError) as exc:
            console.print(f"[red]{path}:[/red] {exc}")
            failed = True
            continue
        if fix:
            try:
                changed = ensure_external_id(finding)
            except OSError as exc:
                console.print(
                    f"[red]{path}:[/red] не удалось записать: {exc}")
                failed = True
                continue
            if changed:
                console.print(
                    f"[green]fixed[/green] {path}: external_id/created_at")
                finding = load_finding(path)
        errors = validate_finding(finding)
        if errors:
            _report_errors(path, errors)
            failed = True

    if failed:
        raise SystemExit(1)
    console.print(f"[green]OK[/green]: файлов {len(files)}")


@findings.command("submit")
@click.argument("paths", nargs=-1, type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True,
              help="Показать payload, не отправлять.")
@api_options
@click.pass_context
def findings_submit(ctx, paths, dry_run, api_base, api_key):
    """Отправить замечания в PDM (идемпотентно по external_id)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    files = resolve_paths(paths, cwd)
    if not files:
        console.print("файлов замечаний нет")
        return

    loaded = []
    failed = False
    for path in files:
        try:
            finding = load_finding(path)
        except (OSError, FindingError) as exc:
            console.print(f"[red]{path}:[/red] {exc}")
            failed = True
            continue
        errors = validate_finding(finding)
        if errors:
            _report_errors(path, errors)
            failed = True
            continue
        if finding.submitted_id is not None:
            console.print(
                f"[yellow]пропуск[/yellow] {path}: уже отправлено "
                f"(id={finding.submitted_id})")
            continue
        loaded.append(finding)

    if failed:
        raise SystemExit(1)
    if not loaded:
        return

    if dry_run:
        for finding in loaded:
            console.print(json.dumps(
                _payload(finding, "dry-run", None),
                ensure_ascii=False, indent=2))
        return

    with make_client(ctx, api_base, api_key) as client:
        try:
            api_version = str(
                client.health().get("pdm_api_version") or "unknown")
        except (httpx.HTTPError, ValueError) as exc:
            console.print(
                f"[yellow]health недоступен ({exc}); "
                "api_version=unknown[/yellow]")
            api_version = "unknown"

        for finding in loaded:
            bp_slug = str(finding.data.get("bp") or "").strip()
            bp_pk = None
            if bp_slug:
                try:
                    bp_pk = client.find_bp_pk(bp_slug)
                except (LookupError, httpx.HTTPError):
                    console.print(
                        f"[yellow]{finding.path}: БП '{bp_slug}' не найден — "
                        "отправляю без связи[/yellow]")

            status_code, body = client.submit_feedback(
                _payload(finding, api_version, bp_pk))
            if status_code in (200, 201):
                try:
                    update_fields(
                        finding,
                        submitted_id=body.get("id"),
                        submitted_at=datetime.now(timezone.utc).isoformat(),
                        status=body.get("status") or "new",
                    )
                except OSError as exc:
                    console.print(
                        f"[red]{finding.path}:[/red] отправлено, но не "
                        f"удалось записать статус: {exc}")
                    failed = True
                    continue
                label = "идемпотентно" if status_code == 200 else "создано"
                console.print(
                    f"[green]{label}[/green] {finding.path}: "
                    f"id={body.get('id')} status={body.get('status')}")
            elif status_code == 401:
                console.print(
                    "[red]401: токен не задан/просрочен — "
                    "PDM_API_TOKEN в .env[/red]")
                failed = True
            elif status_code == 409:
                console.print(
                    f"[red]409:[/red] {finding.path}: external_id уже занят "
                    "другим пользователем")
                failed = True
            elif status_code == 429:
                console.print(
                    "[red]429: слишком много замечаний за час[/red]")
                failed = True
            else:
                console.print(
                    f"[red]{status_code}:[/red] {finding.path}: "
                    f"{_body_error(body)}")
                failed = True

    if failed:
        raise SystemExit(1)


@findings.command("list")
@click.option("--open", "open_only", is_flag=True,
              help="Только new/in_progress.")
@click.option("--target", default=None,
              type=click.Choice(["api", "cli", "workspace", "docs", "ui",
                                 "bp-modeling"]))
@click.option("--severity", default=None,
              type=click.Choice(["blocker", "major", "minor", "idea"]))
@click.option("--json", "as_json", is_flag=True, help="Машинный вывод.")
@api_options
@click.pass_context
def findings_list(ctx, open_only, target, severity, as_json,
                  api_base, api_key):
    """Свои замечания и их статусы."""
    with make_client(ctx, api_base, api_key) as client:
        try:
            rows = client.list_feedback({
                "my_feedbacks": "true",
                "target": target,
                "severity": severity,
            })
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                console.print(
                    "[red]401: токен не задан/просрочен — "
                    "PDM_API_TOKEN в .env[/red]")
                raise SystemExit(1)
            raise click.ClickException(_server_error(exc)) from exc

    if open_only:
        rows = [
            row for row in rows
            if row.get("status") in ("new", "in_progress")
        ]
    if as_json:
        keys = ("id", "status", "target", "severity", "title",
                "external_id", "updated_at")
        console.print(json.dumps(
            [{key: row.get(key) for key in keys} for row in rows],
            ensure_ascii=False, indent=2))
        return
    if not rows:
        console.print("замечаний нет")
        return

    table = Table("id", "status", "target", "severity", "title", "updated")
    for row in rows:
        table.add_row(
            str(row.get("id")),
            str(row.get("status")),
            str(row.get("target") or "—"),
            str(row.get("severity") or "—"),
            str(row.get("title") or ""),
            str(row.get("updated_at") or ""),
        )
    console.print(table)

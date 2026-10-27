"""pdm ws forms — моделирование внешних форм (спека 171, ADR-0079).

Публикация формы в файлы воркспейса: ``workspace/forms/<slug>/
publication.yaml`` + ``fields.yaml`` (read-only манифест public-полей
базовой формы для офлайн-проверок). Мастер — БД PDM (ADR-0017); файлы —
транспорт и редакция. Цикл агента::

    ws forms init → правка publication.yaml → ws forms check
    → ws forms diff → ws forms push → ws forms preview → СТОП

Публикация версии (publish), переходы версий, гранты и токены — только
человек в PDM UI (серверный инвариант, ADR-0079 п.2).
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

import click
import httpx
import yaml
from rich.console import Console

from .common import api_options, make_client

console = Console()

OVERLAY_KEYS = {"fields", "renames", "help_overrides", "order", "submit_scripts"}
MAX_SUBMIT_SCRIPTS = 5
PUSH_FIELDS = ("title", "intro", "inline_catalog_limit", "overlay")


def forms_root(cwd: Path) -> Path:
    """Корень форм воркспейса: <cwd>/workspace/forms/ (спека 171 FR-4)."""
    return cwd / "workspace" / "forms"


def _server_error(e: httpx.HTTPStatusError) -> str:
    try:
        data = e.response.json()
    except Exception:
        return f"HTTP {e.response.status_code}"
    if isinstance(data, dict):
        for key in ("detail", "error"):
            if data.get(key):
                return f"HTTP {e.response.status_code}: {data[key]}"
    return f"HTTP {e.response.status_code}: {e.response.text[:200]}"


def _scope_hint() -> None:
    console.print(
        "[yellow]403 token_scope: правки публикации требуют PAT со скоупом "
        "draft (профиль PDM → Токены доступа). publish и переходы версий — "
        "только человек в PDM UI.[/yellow]"
    )


def _ensure_gitignore(root: Path) -> None:
    gi = root / ".gitignore"
    if not gi.is_file():
        root.mkdir(parents=True, exist_ok=True)
        gi.write_text(
            "# Конфигурации форм не версионируются: мастер — БД PDM "
            "(ADR-0017/0079)\n*\n",
            encoding="utf-8",
        )


def _dump_yaml(data: dict) -> str:
    return yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: ожидается YAML-словарь")
    return data


def _publication_files(root: Path, slug: str) -> tuple[Path, Path, Path]:
    directory = root / slug
    return (
        directory / "publication.yaml",
        directory / "fields.yaml",
        root / ".ws-origin" / slug / "publication.yaml",
    )


def _write_publication(root: Path, item: dict, *, origin: bool) -> Path:
    """publication.yaml (+fields.yaml без origin) из payload листинга."""
    directory = (root / ".ws-origin" / slug_of(item)) if origin else (
        root / slug_of(item))
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "slug": item["slug"],
        "entity_type": {
            "code": (item.get("entity_type") or {}).get("code"),
            "name": (item.get("entity_type") or {}).get("name"),
        },
        "title": item.get("title") or "",
        "intro": item.get("intro") or "",
        "inline_catalog_limit": item.get("inline_catalog_limit") or 200,
        "overlay": item.get("overlay") or {},
    }
    path = directory / "publication.yaml"
    header = "" if origin else (
        "# Публикация формы (спека 171). Мастер — БД PDM; publish — только\n"
        "# человек в PDM UI (ADR-0079).\n")
    path.write_text(header + _dump_yaml(manifest), encoding="utf-8")
    if not origin:
        fields = directory / "fields.yaml"
        fields.write_text(
            "# READ-ONLY: манифест public-полей базовой формы (для "
            "ws forms check). Обновляется `pdm ws forms init`, не "
            "редактируется.\n" + _dump_yaml(item.get("base_fields") or {}),
            encoding="utf-8",
        )
    return path


def slug_of(item: dict) -> str:
    return item.get("slug") or ""


def _find_publication(items: list[dict], slug: str) -> dict:
    for item in items:
        if slug_of(item) == slug:
            return item
    console.print(
        f"[red]публикация {slug} не найдена (или нет прав) — список: "
        "[cyan]pdm ws forms list[/cyan][/red]"
    )
    sys.exit(2)


def _known_names(fields_manifest: dict) -> set[str]:
    names = {f.get("name") for f in fields_manifest.get("fields") or []}
    for section in fields_manifest.get("sections") or []:
        names.add(section.get("name"))
        for column in section.get("columns") or []:
            names.add(column.get("name"))
    return {name for name in names if name}


def _check_publication(manifest: dict, fields_manifest: dict) -> list[str]:
    """Офлайн Tier-0 оверлея (спека 171 FR-4): схема, имена, дубли."""
    errors: list[str] = []
    known = _known_names(fields_manifest)
    overlay = manifest.get("overlay")
    if not isinstance(overlay, dict):
        return [f"overlay: ожидается словарь, получен {type(overlay).__name__}"]
    for key in overlay:
        if key not in OVERLAY_KEYS:
            console.print(
                f"[yellow]⚠ overlay.{key}: неизвестный ключ (сервер молча "
                "игнорирует)[/yellow]"
            )
    fields = overlay.get("fields")
    if fields is not None:
        if not isinstance(fields, list) or not all(
                isinstance(name, str) for name in fields):
            errors.append("overlay.fields: список имён полей (строк)")
        else:
            for name in fields:
                if name not in known:
                    errors.append(
                        f"overlay.fields: «{name}» нет в базовой форме "
                        "(см. fields.yaml)")
            if not fields:
                errors.append(
                    "overlay.fields: пустой состав — публикация станет "
                    "unpublishable (схема пуста)")
    for key in ("renames", "help_overrides"):
        entries = overlay.get(key)
        if entries is None:
            continue
        if not isinstance(entries, dict):
            errors.append(f"overlay.{key}: словарь {{имя поля: значение}}")
            continue
        for name, value in entries.items():
            if name not in known:
                errors.append(
                    f"overlay.{key}: «{name}» нет в базовой форме")
            if not isinstance(value, str):
                errors.append(f"overlay.{key}[{name}]: значение — строка")
    order = overlay.get("order")
    if order is not None:
        if not isinstance(order, list):
            errors.append("overlay.order: список имён полей")
        else:
            if len(order) != len(set(order)):
                errors.append("overlay.order: дубликаты имён")
            for name in order:
                if name not in known:
                    errors.append(f"overlay.order: «{name}» нет в базовой форме")
    scripts = overlay.get("submit_scripts")
    if scripts is not None:
        if not isinstance(scripts, list):
            errors.append("overlay.submit_scripts: список строк кода")
        elif len(scripts) > MAX_SUBMIT_SCRIPTS:
            errors.append(
                f"overlay.submit_scripts: не более {MAX_SUBMIT_SCRIPTS} "
                "(порядок значим)")
    limit = manifest.get("inline_catalog_limit")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        errors.append("inline_catalog_limit: целое ≥ 1")
    return errors


def _load_workspace(root: Path, slug: str) -> tuple[dict, dict]:
    publication_yaml, fields_yaml, _origin = _publication_files(root, slug)
    if not publication_yaml.is_file():
        console.print(
            f"[red]publication.yaml не найден: workspace/forms/{slug}/ — "
            f"сначала pdm ws forms init {slug}[/red]"
        )
        sys.exit(2)
    try:
        manifest = _load_yaml(publication_yaml)
    except (OSError, ValueError, yaml.YAMLError) as e:
        console.print(f"[red]publication.yaml не читается: {e}[/red]")
        sys.exit(2)
    fields_manifest = {}
    if fields_yaml.is_file():
        try:
            fields_manifest = _load_yaml(fields_yaml)
        except (OSError, ValueError, yaml.YAMLError) as e:
            console.print(f"[red]fields.yaml не читается: {e}[/red]")
            sys.exit(2)
    return manifest, fields_manifest


@click.group("forms")
def forms():
    """Моделирование внешних форм: init/check/diff/push/preview (спека 171).

    Публикация версии (publish) — только человек в PDM UI; CLI правит
    конфигурацию и показывает, что изменится.
    """


@forms.command("list")
@api_options
@click.pass_context
def forms_list(ctx, api_base, api_key):
    """Доступные публикации форм: slug, форма, версия, состояние."""
    with make_client(ctx, api_base, api_key) as client:
        try:
            items = client.ef_publications()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                console.print(
                    "[red]401: токен не принят — проверь PDM_API_TOKEN в "
                    ".env (PAT из профиля PDM).[/red]"
                )
            elif e.response.status_code == 403:
                _scope_hint()
            else:
                console.print(f"[red]список публикаций не удался: {_server_error(e)}[/red]")
            sys.exit(1)
        except httpx.HTTPError as e:
            console.print(f"[red]список публикаций не удался: {e}[/red]")
            sys.exit(1)
    if not items:
        console.print(
            "[yellow]Публикаций нет (или нет прав) — создание публикации "
            "в PDM UI, раздел «Публикации форм».[/yellow]"
        )
        return
    for item in items:
        version = item.get("active_version") or "не опубликована"
        state = "" if item.get("is_enabled") else "  [dim]выкл[/dim]"
        console.print(
            f"  [cyan]{slug_of(item)}[/cyan]  "
            f"{(item.get('entity_type') or {}).get('name') or '—'}  "
            f"v{version}{state}"
        )
    console.print(
        f"\nВсего {len(items)}. Выгрузка: [cyan]pdm ws forms init <slug>[/cyan]."
    )


@forms.command("init")
@click.argument("slug")
@api_options
@click.pass_context
def forms_init(ctx, slug, api_base, api_key):
    """Экспорт публикации SLUG → workspace/forms/SLUG/."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    root = forms_root(cwd)
    with make_client(ctx, api_base, api_key) as client:
        try:
            items = client.ef_publications()
        except httpx.HTTPError as e:
            detail = (
                _server_error(e) if isinstance(e, httpx.HTTPStatusError)
                else str(e))
            console.print(f"[red]листинг публикаций не удался: {detail}[/red]")
            sys.exit(1)
    item = _find_publication(items, slug)
    path = _write_publication(root, item, origin=False)
    origin = _write_publication(root, item, origin=True)
    _ensure_gitignore(root)
    overlay = item.get("overlay") or {}
    console.print(
        f"[green]ws forms init: {slug} → {path.relative_to(cwd)}[/green] "
        f"(полей в оверлее: {len(overlay.get('fields') or []) or 'все'}, "
        f"версия v{item.get('active_version') or '—'})"
    )
    console.print(f"  снапшот: {origin.relative_to(cwd)} (база для diff)")
    console.print(
        "Дальше: правь publication.yaml → [cyan]pdm ws forms check[/cyan] → "
        f"[cyan]pdm ws forms diff {slug}[/cyan]"
    )


@forms.command("check")
@click.argument("slug", required=False)
@click.pass_context
def forms_check(ctx, slug):
    """Офлайн Tier-0: схема оверлея и имена полей против fields.yaml."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    root = forms_root(cwd)
    slugs = [slug] if slug else sorted(
        item.name for item in root.iterdir()
        if item.is_dir() and (item / "publication.yaml").is_file()
    ) if root.is_dir() else []
    if slug and slug not in slugs:
        console.print(
            f"[red]workspace/forms/{slug}/publication.yaml не найден — "
            f"сначала pdm ws forms init {slug}[/red]"
        )
        sys.exit(2)
    if not slugs:
        console.print(
            "[yellow]Форм в воркспейсе нет — pdm ws forms init <slug>.[/yellow]"
        )
        return
    failed = False
    for one in slugs:
        manifest, fields_manifest = _load_workspace(root, one)
        errors = _check_publication(manifest, fields_manifest)
        if errors:
            failed = True
            console.print(f"[red]{one}: check не прошёл[/red]")
            for error in errors:
                console.print(f"  [red]•[/red] {error}")
        else:
            console.print(f"[green]{one}: check пройден[/green]")
    if failed:
        sys.exit(1)


@forms.command("diff")
@click.argument("slug")
@click.pass_context
def forms_diff(ctx, slug):
    """Локальный diff publication.yaml против последнего push/init."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    root = forms_root(cwd)
    _publication_yaml, _fields, origin = _publication_files(root, slug)
    manifest, _fields_manifest = _load_workspace(root, slug)
    if not origin.is_file():
        console.print(
            "[yellow]Снапшота .ws-origin нет — сделай pdm ws forms init "
            f"{slug} заново.[/yellow]"
        )
        sys.exit(2)
    baseline = origin.read_text(encoding="utf-8").splitlines()
    try:
        # Сравниваем содержимое (YAML), а не текст: редактируемый файл несёт
        # шапку-подсказку, снапшот — нет; содержимое при этом идентично.
        baseline = _dump_yaml(_load_yaml(origin)).splitlines()
    except (ValueError, yaml.YAMLError):
        pass
    diff = list(difflib.unified_diff(
        baseline, _dump_yaml(manifest).splitlines(),
        fromfile=f".ws-origin/forms/{slug}/publication.yaml",
        tofile=f"workspace/forms/{slug}/publication.yaml", lineterm="",
    ))
    if diff:
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                console.print(f"[green]{line}[/green]")
            elif line.startswith("-") and not line.startswith("---"):
                console.print(f"[red]{line}[/red]")
            else:
                console.print(line)
        console.print("[bold]ws forms diff: publication.yaml изменён[/bold]")
    else:
        console.print(
            "[green]ws forms diff: изменений относительно последнего "
            "init/push нет[/green]"
        )


@forms.command("push")
@click.argument("slug")
@api_options
@click.pass_context
def forms_push(ctx, slug, api_base, api_key):
    """Локальные правки → PATCH публикации (PAT draft; publish — человек)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    root = forms_root(cwd)
    manifest, _fields_manifest = _load_workspace(root, slug)
    errors = _check_publication(manifest, _fields_manifest)
    if errors:
        for error in errors:
            console.print(f"  [red]•[/red] {error}")
        console.print(f"[red]{slug}: check не прошёл, push отменён[/red]")
        sys.exit(1)

    payload = {key: manifest.get(key) for key in PUSH_FIELDS}
    with make_client(ctx, api_base, api_key) as client:
        try:
            items = client.ef_publications()
        except httpx.HTTPError as e:
            detail = (
                _server_error(e) if isinstance(e, httpx.HTTPStatusError)
                else str(e))
            console.print(f"[red]листинг публикаций не удался: {detail}[/red]")
            sys.exit(1)
        item = _find_publication(items, slug)
        server = {
            "title": item.get("title") or "",
            "intro": item.get("intro") or "",
            "inline_catalog_limit": item.get("inline_catalog_limit") or 200,
            "overlay": item.get("overlay") or {},
        }
        if payload == server:
            console.print(
                "[yellow]no-op: сервер уже несёт это состояние — PATCH не "
                "шлётся[/yellow]"
            )
            return
        try:
            client.ef_patch_publication(item["id"], payload)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                _scope_hint()
            else:
                console.print(f"[red]push не удался: {_server_error(e)}[/red]")
            sys.exit(1)
        except httpx.HTTPError as e:
            console.print(f"[red]push не удался: {e}[/red]")
            sys.exit(1)
    refreshed = _write_publication(root, item | payload, origin=True)
    console.print(
        f"[green]push: {slug} сохранён на сервере (черновой оверлей; "
        "потребитель его ещё не видит)[/green]"
    )
    console.print(f"  снапшот: {refreshed.relative_to(cwd)}")
    console.print(
        "Публикация версии — человек: PDM UI → «Публикации форм» → "
        "«Опубликовать (минор)»/«Новый мажор»."
    )


@forms.command("preview")
@click.argument("slug")
@api_options
@click.pass_context
def forms_preview(ctx, slug, api_base, api_key):
    """Текущая проекция схемы (schema-preview): поля/секции/каталоги+hash."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    with make_client(ctx, api_base, api_key) as client:
        try:
            items = client.ef_publications()
        except httpx.HTTPError as e:
            detail = (
                _server_error(e) if isinstance(e, httpx.HTTPStatusError)
                else str(e))
            console.print(f"[red]листинг публикаций не удался: {detail}[/red]")
            sys.exit(1)
        item = _find_publication(items, slug)
        try:
            preview = client.ef_schema_preview(item["id"])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                _scope_hint()
            else:
                console.print(f"[red]preview не удался: {_server_error(e)}[/red]")
            sys.exit(1)
        except httpx.HTTPError as e:
            console.print(f"[red]preview не удался: {e}[/red]")
            sys.exit(1)

    schema = preview.get("schema") or {}
    digest = preview.get("schema_hash") or ""
    console.print(
        f"[bold]Превью {slug}[/bold] — hash {digest[:12]}… "
        f"(активная версия: v{item.get('active_version') or '—'})"
    )
    fields = [f.get("name") for f in schema.get("fields") or []]
    console.print(f"  поля ({len(fields)}): {', '.join(fields) or '—'}")
    for section in schema.get("sections") or []:
        columns = [c.get("name") for c in section.get("columns") or []]
        console.print(
            f"  секция «{section.get('name')}»: {', '.join(columns) or '—'}")
    for name, catalog in (schema.get("catalogs") or {}).items():
        mode = "инлайн" if catalog.get("inline") else "эндпоинт значений"
        console.print(
            f"  каталог {name}: {catalog.get('count')} записей, колонки "
            f"{', '.join(catalog.get('columns') or [])} ({mode})")
    active = next(
        (v for v in item.get("versions") or []
         if v.get("version") == item.get("active_version")), None)
    if active is not None:
        same = active.get("schema_hash") == digest[:12]
        console.print(
            "  совпадает с активной версией" if same else
            f"  [yellow]отличается от активной v{item.get('active_version')} "
            f"({active.get('schema_hash')}…) — publish создаст новую "
            "версию[/yellow]"
        )
    console.print(
        "Публикация — человек: PDM UI → «Публикации форм» → "
        "«Опубликовать (минор)»/«Новый мажор»."
    )

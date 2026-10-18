"""Draft-инструменты тестовой версии БП (спека 143, W6, ADR-0059).

Новый цикл агента (git-цикл удалён по Д8): bp_draft_from_server →
bp_read_file/bp_edit_file → bp_compile → bp_draft_save. Сохранение — в
testing-версию БД через шов draft-import; публикация — только человек в
админке PDM («Применить»/«Отклонить»). Термин «песочница» в этом контуре
не используется (в проекте песочниц уже три, см. handoff).
"""

from __future__ import annotations

from ..context import BpContext, workspace_root
from .files import _check_slug


def _require_api(ctx: BpContext, tool: str) -> None:
    """Offline-режим: draft-инструменты работают только через PDM API."""
    if ctx.api is None:
        raise RuntimeError(
            f"{tool} недоступен: PDM API не настроен "
            "(PDM_API_BASE/PDM_API_TOKEN) — offline работают только "
            "bp_list_files/bp_read_file/bp_edit_file/bp_new_process/bp_compile"
        )


def _server_versions(ctx: BpContext, slug: str) -> dict:
    """Реестр версий с сервера; 404 — доменная ошибка для агента."""
    import httpx

    try:
        return ctx.api.bp_versions(slug)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise RuntimeError(
                f"БП {slug!r} не найден на сервере — проверь slug "
                "(bp_draft_status) или начни новый через bp_new_process"
            ) from e
        raise


def do_draft_from_server(ctx: BpContext, slug: str) -> dict:
    """Экспорт testing|published версии БП с сервера → распаковка в workspace.

    Приоритет testing при наличии (правим именно тестовую версию), иначе —
    действующее определение (published). Нет ни одной версии (БП создан
    руками в админке) — минимальный скаффолд с именем с сервера.
    Повторный вызов перезаливает workspace свежей копией — локальные
    правки теряются.
    """
    _check_slug(slug)
    _require_api(ctx, "bp_draft_from_server")

    info = _server_versions(ctx, slug)
    testing = info.get("testing")
    published = info.get("published")
    if testing is not None:
        version: int | None = int(testing["number"])
        source = {"version": version, "status": "testing"}
    elif published is not None:
        version = None  # без параметра — действующее определение
        source = {"version": int(published["number"]), "status": "published"}
    else:
        return _scaffold_versionless(ctx, slug, info)

    from ...bpm_package import parse_package_zip, write_package

    pkg = parse_package_zip(ctx.api.export_package(slug, version=version))
    write_package(ctx.repo_root, pkg, definitions_root=workspace_root(ctx))

    from .files import do_list_files

    listing = do_list_files(ctx, slug=slug)
    return {
        "slug": slug,
        "source": source,
        "files": listing["files"],
        "count": listing["count"],
        "note": "workspace перезалит экспортом сервера — несохранённые "
                "локальные правки отброшены",
        "next": "правь файлы через bp_read_file/bp_edit_file, затем "
                "bp_compile и bp_draft_save",
    }


def _scaffold_versionless(ctx: BpContext, slug: str, info: dict) -> dict:
    """БП есть на сервере, но без единой версии (создан руками в админке).

    Экспортировать нечего, а bp_new_process откажет — slug занят; раньше
    это был тупик для агента: обе вербы слали друг к другу. Скаффолдим
    минимальный черновик (имя — с сервера), наполнение — через
    bp_edit_file; bp_draft_save создаст testing v1 (apply_draft, СЦ-Д1б).
    Повторный вызов перезаливает черновик — семантика do_draft_from_server.
    """
    _check_slug(slug)
    _require_api(ctx, "bp_draft_from_server")

    name = ((info.get("process") or {}).get("name") or "").strip() or slug

    from ...bpm_package import write_package
    from .files import do_list_files
    from .process_new import build_scaffold_package
    from .validate import do_compile

    pkg = build_scaffold_package(slug, name, ["Первая задача"])
    write_package(ctx.repo_root, pkg, definitions_root=workspace_root(ctx))
    report = do_compile(ctx, slug=slug)
    listing = do_list_files(ctx, slug=slug)
    return {
        "slug": slug,
        "source": {"version": None, "status": "scaffold"},
        "files": listing["files"],
        "count": listing["count"],
        "compile_ok": report["ok"],
        "errors": report["results"].get(slug, {}).get("errors", []),
        "note": (
            "на сервере БП существует, но без единой версии (создан вручную) "
            "— workspace создан с минимальным черновиком"
        ),
        "next": "наполняй задачи через bp_edit_file (названия этапов, "
                "шаблоны документов в document_templates/), затем bp_compile "
                "и bp_draft_save — сохранение создаст тестовую версию v1",
    }


def do_draft_save(ctx: BpContext, slug: str) -> dict:
    """compile (Tier 0) → ZIP → шов draft-import: тестовая версия в БД.

    Возвращает статус (created/replaced/idempotent), номер версии и
    diff-сводку с сервера. Публикация — только человек в админке PDM;
    подтверждений от пользователя не требуется (спека 143, ADR-0059).
    """
    import json

    _check_slug(slug)
    _require_api(ctx, "bp_draft_save")

    from .validate import do_compile

    report = do_compile(ctx, slug=slug)
    if not report["ok"]:
        broken = {
            s: res["errors"][:5]
            for s, res in report["results"].items()
            if not res["ok"]
        }
        raise RuntimeError(
            f"bp_draft_save отменён: Tier 0 не пройден — исправь через "
            f"bp_edit_file и повтори bp_compile. "
            f"Ошибки: {json.dumps(broken, ensure_ascii=False)}"
        )

    from ...bpm_package import build_zip, read_package

    pkg = read_package(ctx.repo_root, slug, definitions_root=workspace_root(ctx))
    zip_bytes, fname = build_zip(pkg)

    result = ctx.api.draft_import(slug, zip_bytes, fname)
    if result.get("error") == "draft_validation_failed":
        raise RuntimeError(
            f"сервер отклонил пакет (draft_validation_failed): "
            f"{json.dumps(result.get('errors', []), ensure_ascii=False)}"
        )

    return {
        "status": result.get("status"),
        "slug": slug,
        "version": result.get("version"),
        "version_status": result.get("version_status"),
        "diff": result.get("diff"),
        "replaced": result.get("replaced"),
        "users_missing": result.get("users_missing") or [],
        "next": "тестовая версия сохранена; публикация — человек в админке "
                "PDM (Применить/Отклонить), агент не публикует",
    }


def do_draft_status(ctx: BpContext, slug: str) -> dict:
    """Состояние тестовой версии БП: версии, diff-сводка, локальный workspace.

    testing/published — номера с сервера (testing нет → None); local_draft —
    есть ли копия пакета в workspace (править можно только при ней).
    """
    _check_slug(slug)
    _require_api(ctx, "bp_draft_status")

    info = _server_versions(ctx, slug)
    return {
        "slug": slug,
        "testing": info.get("testing"),
        "published": info.get("published"),
        "versions": [
            {"number": v.get("number"), "status": v.get("status")}
            for v in info.get("versions", [])
        ],
        "diff": info.get("diff"),
        "local_draft": (workspace_root(ctx) / slug / "process.yaml").is_file(),
        "next": (
            "правь файлы через bp_read_file/bp_edit_file, затем bp_compile "
            "и bp_draft_save" if (workspace_root(ctx) / slug).is_dir()
            else "скачай определение через bp_draft_from_server"
        ),
    }

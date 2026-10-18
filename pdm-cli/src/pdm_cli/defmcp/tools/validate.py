"""Валидационные инструменты: bp_compile (Tier 0).

Тонкая обёртка над bpm_package: те же read_package/validate_package,
что и у CLI-команды compile — никакого второго толкования «валидности».
Машинный вывод для агента: ошибки пофайлово. Спека 143 (W6): пакеты
читаются из workspace черновиков (git-цикл удалён, Д8).
"""

from __future__ import annotations

from ..context import BpContext, workspace_root
from ..guard import GuardError


def _resolve_slugs(ctx: BpContext, slug: str | None) -> list[str]:
    from ...bpm_package import list_package_slugs

    ws = workspace_root(ctx)
    if slug is not None:
        if not (ws / slug / "process.yaml").is_file():
            raise LookupError(f"{slug}/process.yaml не найден в workspace")
        return [slug]
    slugs = list_package_slugs(ctx.repo_root, definitions_root=ws)
    if not slugs:
        raise GuardError("пакетных БП в workspace нет (workspace/<slug>/process.yaml)")
    return slugs


def do_compile(ctx: BpContext, slug: str | None = None) -> dict:
    """Tier 0: сборка+валидация пакетов workspace без сети; ошибки пофайлово."""
    from ...bpm_package import read_package, validate_package

    results: dict[str, dict] = {}
    ok = True
    for s in _resolve_slugs(ctx, slug):
        try:
            pkg = read_package(ctx.repo_root, s, definitions_root=workspace_root(ctx))
        except Exception as e:
            results[s] = {
                "ok": False,
                "errors": [f"чтение не удалось: {e}"],
                "stats": None,
            }
            ok = False
            continue
        errors = validate_package(pkg)
        bp = pkg.business_process
        results[s] = {
            "ok": not errors,
            "errors": errors,
            "stats": {
                "tasks": len(bp.tasks),
                "scripts": len(bp.scripts),
                "templates": len(pkg.document_templates),
                "catalogs": len(pkg.catalogs),
            },
        }
        ok = ok and not errors
    return {
        "ok": ok,
        "results": results,
        "next": (
            "запусти bp_draft_save — сохранение в тестовую версию БП"
            if ok
            else "исправь файлы через bp_edit_file и повтори bp_compile"
        ),
    }

"""bp_new_process: scaffold нового БП сразу в package-форме.

Не переиспользует pdm new-bp: тот пишет legacy manifest.yaml, а компилятор
(Tier 0) и все живые БП — в package-форме. Скаффолд минимальный и сразу
зелёный в compile; наполнение задач — через bp_edit_file по образцу.
Спека 143 (W6): scaffold кладётся в workspace черновиков; коллизия slug
проверяется локально и на сервере.
"""

from __future__ import annotations

from ..context import BpContext, workspace_root
from .files import _check_slug


def build_scaffold_package(
    slug: str, title: str, task_names: list[str],
) -> "BpPackage":
    """Минимальный пакет, зелёный в compile (форма скаффолда — единственный
    источник; используется bp_new_process и bp_draft_from_server для БП
    без версий)."""
    from ...bpm_package import BpPackage, PkgBusinessProcess, PkgTask

    return BpPackage(
        business_process=PkgBusinessProcess(
            slug=slug,
            name=title.strip(),
            tasks=[
                PkgTask(name=t, order=i + 1, assign_to_starter=True)
                for i, t in enumerate(task_names)
            ],
        ),
    )


def do_new_process(
    ctx: BpContext,
    slug: str,
    title: str,
    tasks: list[str] | None = None,
) -> dict:
    """Создать workspace/<slug>/ (process.yaml + tasks/001-*.yaml)."""
    _check_slug(slug)
    if not title or not title.strip():
        raise ValueError("пустое название БП")
    task_names = [t.strip() for t in (tasks or ["Первая задача"])]
    if not task_names or any(not t for t in task_names):
        raise ValueError("имена задач не могут быть пустыми")

    bp_dir = workspace_root(ctx) / slug
    if bp_dir.exists():
        raise FileExistsError(f"{slug}/ уже существует в workspace")
    if ctx.api is not None:
        existing = {item.get("slug") for item in ctx.api.list_processes()}
        if slug in existing:
            raise FileExistsError(
                f"slug {slug!r} уже существует на сервере — "
                "новый БП с тем же слагом создать нельзя, правь существующий "
                "(начни с bp_draft_from_server)"
            )

    from ...bpm_package import write_package
    from .validate import do_compile

    pkg = build_scaffold_package(slug, title, task_names)
    write_package(ctx.repo_root, pkg, definitions_root=workspace_root(ctx))

    report = do_compile(ctx, slug=slug)
    return {
        "slug": slug,
        "tasks": task_names,
        "compile_ok": report["ok"],
        "errors": report["results"].get(slug, {}).get("errors", []),
        "next": "заполняй задачи через bp_edit_file по образцу существующих БП",
    }

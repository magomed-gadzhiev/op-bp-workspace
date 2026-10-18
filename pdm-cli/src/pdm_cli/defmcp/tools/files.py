"""Файловые инструменты: bp_list_files, bp_read_file, bp_edit_file.

Все пути — относительно workspace черновиков (спека 143, W6: env
MCP_BP_DRAFTS_ROOT; git-цикл у агента удалён по Д8). Для .yaml/.yml перед
записью — safe-load проверка: битый YAML не доходит до диска (US4 спеки 070).
"""

from __future__ import annotations

from pathlib import Path

from ..context import BpContext, workspace_root
from ..guard import GuardError, resolve_under_root

_SLUG_RE = None  # ленивая компиляция при первом вызове
_LIST_EXTS = {".yaml", ".yml", ".py", ".md", ".json"}


def _slug_re():
    global _SLUG_RE
    if _SLUG_RE is None:
        import re
        _SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
    return _SLUG_RE


def _check_slug(slug: str) -> None:
    if not _slug_re().match(slug or ""):
        raise GuardError(
            f"некорректный slug {slug!r}: ожидается ^[a-z0-9][a-z0-9-]*$"
        )


def _workspace_dir(ctx: BpContext, slug: str | None = None) -> Path:
    base = workspace_root(ctx)
    if slug is not None:
        _check_slug(slug)
        target = base / slug
        if not target.is_dir():
            raise LookupError(f"{slug}/ не найден в workspace")
        return target
    if not base.is_dir():
        raise LookupError(
            "workspace пуст — вызови bp_draft_from_server (правка существующего "
            "БП) или bp_new_process (новый БП)"
        )
    return base


def _validate_yaml_text(text: str) -> None:
    """Бросает ValueError, если text — не валидный YAML-документ."""
    try:
        from ruamel.yaml import YAML
        from ruamel.yaml.error import YAMLError
    except ImportError as e:  # pragma: no cover — ruamel в базовых зависимостях
        raise RuntimeError("ruamel.yaml недоступен") from e
    try:
        YAML(typ="safe", pure=True).load(text)
    except YAMLError as e:
        raise ValueError(f"невалидный YAML: {e}") from e


def do_list_files(ctx: BpContext, slug: str | None = None) -> dict:
    """Дерево текстовых файлов workspace (yaml/py/md/json), пути от workspace."""
    root = workspace_root(ctx)
    base = _workspace_dir(ctx, slug)
    files = sorted(
        p.relative_to(root).as_posix()
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in _LIST_EXTS
    )
    return {"files": files, "count": len(files)}


def do_read_file(ctx: BpContext, path: str) -> dict:
    """Текст файла из workspace (utf-8, кап размера ctx.read_size_cap)."""
    target = resolve_under_root(workspace_root(ctx), path)
    if not target.is_file():
        raise FileNotFoundError(f"{path} не найден в workspace")
    size = target.stat().st_size
    if size > ctx.read_size_cap:
        raise ValueError(
            f"файл слишком большой ({size} b > {ctx.read_size_cap} b) — "
            "читай частями через slug-скоуп или проси человека"
        )
    return {
        "path": path,
        "content": target.read_text(encoding="utf-8"),
        "size": size,
    }


def do_edit_file(
    ctx: BpContext,
    path: str,
    content: str,
    expected_current: str | None = None,
) -> dict:
    """Записать content в workspace/<path>; YAML валидируется до записи.

    expected_current — optimistic concurrency: если задан и не совпадает
    с текущим содержимым, отказ (кто-то правил файл после чтения агентом).
    """
    if not isinstance(content, str):
        raise ValueError("content должен быть строкой")
    target = resolve_under_root(workspace_root(ctx), path)
    if path.endswith((".yaml", ".yml")):
        _validate_yaml_text(content)
    if target.exists() and expected_current is not None:
        current = target.read_text(encoding="utf-8")
        if current != expected_current:
            raise PermissionError(
                f"конфликт: {path} изменён с момента чтения "
                "(expected_current не совпал) — перечитай файл"
            )
    if not target.exists():
        if not target.parent.is_dir():
            raise LookupError(
                f"каталог {target.parent.name}/ не существует — "
                "создавать новые каталоги вне структуры БП нельзя"
            )
    target.write_text(content, encoding="utf-8")
    return {
        "written": path,
        "bytes": len(content.encode("utf-8")),
        "next": "запусти bp_compile — Tier 0 обязателен до bp_draft_save",
    }

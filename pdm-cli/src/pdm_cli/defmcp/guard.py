"""Path-guard: все файловые операции defmcp — только внутри workspace
черновиков (спека 143, W6; раньше — processes/, git-цикл удалён по Д8).

Отказываем: абсолютным путям, backslash-сепараторам, любым '..' в пути,
пустым путям и symlink-escape (resolve() должен остаться внутри базового
каталога). Это единственная защита от «агент решил поправить /etc».
"""

from __future__ import annotations

import re
from pathlib import Path

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class GuardError(ValueError):
    """Путь вне workspace (базового каталога) или иным образом небезопасен."""


def resolve_under_root(base: Path, rel_path: str) -> Path:
    """Резолвит rel_path внутри base; GuardError при любой попытке выхода."""
    if not rel_path or not rel_path.strip():
        raise GuardError("пустой путь")
    if rel_path.startswith("/") or rel_path.startswith("\\"):
        raise GuardError(f"абсолютный путь запрещён: {rel_path!r}")
    if _WINDOWS_DRIVE.match(rel_path):
        raise GuardError(f"absolute/drive path запрещён: {rel_path!r}")
    if "\\" in rel_path:
        raise GuardError(
            f"backslash в пути запрещён (используй '/'): {rel_path!r}"
        )
    parts = [p for p in Path(rel_path).parts]
    if any(p == ".." for p in parts):
        raise GuardError(f"'..' в пути запрещён: {rel_path!r}")

    base_res = base.resolve()
    candidate = (base_res / Path(*parts)).resolve()
    if candidate != base_res and base_res not in candidate.parents:
        raise GuardError(f"путь вне {base_res}: {rel_path!r}")
    return candidate

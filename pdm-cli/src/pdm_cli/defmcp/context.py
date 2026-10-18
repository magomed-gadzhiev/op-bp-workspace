"""Контекст defmcp-сервера: корень репо, workspace черновиков, API-клиент."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BpContext:
    """Всё, что нужно инструментам; создаётся один раз при старте сервера.

    api — PdmApiClient (лениво, может быть None для offline-тестов);
    drafts_root — корень workspace черновиков (спека 143, W6: env
    MCP_BP_DRAFTS_ROOT, в контейнере /work/.pdm/drafts); audit_path — куда
    писать JSONL-журнал вызовов.
    """

    repo_root: Path
    api: Any = None
    drafts_root: Path | None = None
    audit_path: Path | None = None
    read_size_cap: int = 512 * 1024
    extras: dict[str, Any] = field(default_factory=dict)


def workspace_root(ctx: BpContext) -> Path:
    """Корень workspace черновиков БП (спека 143, W6).

    Явный ctx.drafts_root (build_context из env MCP_BP_DRAFTS_ROOT) либо
    дефолт <repo_root>/.pdm/drafts — локальный stdio-режим без env.
    """
    if ctx.drafts_root is not None:
        return ctx.drafts_root
    return ctx.repo_root / ".pdm" / "drafts"

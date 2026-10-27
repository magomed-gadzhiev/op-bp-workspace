"""Файл замечания по инструменту (спека 166, ADR-0073).

Формат: YAML-frontmatter + Markdown-тело с пятью обязательными разделами.
Парсер/валидатор намеренно строгий: слабая модель не должна отправлять
размытые замечания или замечания с секретами.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

TYPES = ("error", "suggestion")
TARGETS = ("api", "cli", "workspace", "docs", "ui", "bp-modeling")
SEVERITIES = ("blocker", "major", "minor", "idea")
REQUIRED_SECTIONS = (
    "Что произошло",
    "Ожидалось",
    "Как воспроизвести",
    "Доказательства",
    "Обход",
)

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_SECRET_PATTERNS = (
    re.compile(r"pdw_[0-9a-fA-F]{40}"),
    re.compile(r"Authorization\s*:\s*Token\s+\S+", re.IGNORECASE),
    re.compile(
        r"\b[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)\s*=\s*\S+",
        re.IGNORECASE,
    ),
)
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


class FindingError(ValueError):
    """Файл не является корректным файлом замечания."""


@dataclass
class Finding:
    path: Path
    data: dict
    body: str

    @property
    def external_id(self) -> str:
        return str(self.data.get("external_id") or "").strip()

    @property
    def submitted_id(self) -> int | None:
        value = self.data.get("submitted_id")
        return int(value) if value not in (None, "") else None


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    return y


def load_finding(path: Path) -> Finding:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise FindingError(
            "нет YAML-frontmatter: файл должен начинаться с '---' и "
            "содержать второй '---' перед телом")
    try:
        data = _yaml().load(match.group(1)) or {}
    except Exception as exc:  # ruamel raises several YAML error types
        raise FindingError(f"frontmatter не парсится как YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise FindingError("frontmatter должен быть YAML-объектом")
    return Finding(path=path, data=data, body=match.group(2))


def write_finding(finding: Finding) -> None:
    stream = StringIO()
    _yaml().dump(finding.data, stream)
    finding.path.write_text(
        f"---\n{stream.getvalue()}---\n{finding.body}", encoding="utf-8")


def ensure_external_id(finding: Finding) -> bool:
    """Дописать external_id/created_at, если их нет. True — файл изменён."""
    changed = False
    if not finding.external_id:
        finding.data["external_id"] = str(uuid.uuid4())
        changed = True
    if not str(finding.data.get("created_at") or "").strip():
        finding.data["created_at"] = datetime.now(timezone.utc).isoformat()
        changed = True
    if changed:
        write_finding(finding)
    return changed


def update_fields(finding: Finding, **fields) -> None:
    for key, value in fields.items():
        finding.data[key] = value
    write_finding(finding)


def sections(body: str) -> dict[str, str]:
    matches = list(_SECTION_RE.finditer(body))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        result[match.group(1).strip()] = body[match.end():end].strip()
    return result


def find_secret(text: str) -> str | None:
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(text or "")
        if match:
            return match.group(0)
    return None


def validate_finding(finding: Finding) -> list[str]:
    errors: list[str] = []
    data = finding.data

    title = str(data.get("title") or "").strip()
    if not title:
        errors.append("title обязателен")
    elif len(title) > 200:
        errors.append("title длиннее 200 символов")

    type_ = str(data.get("type") or "").strip()
    if type_ not in TYPES:
        errors.append(f"type должен быть одним из: {', '.join(TYPES)}")

    target = str(data.get("target") or "").strip()
    if target not in TARGETS:
        errors.append(f"target должен быть одним из: {', '.join(TARGETS)}")

    severity = str(data.get("severity") or "").strip()
    if severity not in SEVERITIES:
        errors.append(
            f"severity должен быть одним из: {', '.join(SEVERITIES)}")

    external_id = finding.external_id
    if not external_id:
        errors.append(
            "external_id пуст — запустите `pdm ws findings check --fix`")
    else:
        try:
            uuid.UUID(external_id)
        except ValueError:
            errors.append("external_id должен быть UUID")

    bp = str(data.get("bp") or "").strip()
    if bp and not _SLUG_RE.match(bp):
        errors.append("bp должен быть slug ([a-z0-9-])")

    if len(finding.body or "") > 20000:
        errors.append("тело длиннее 20 000 символов")

    secret = find_secret(finding.body) or find_secret(title)
    if secret:
        errors.append(
            f"похоже на секрет ({secret[:12]}…) — удалите его из замечания")

    parsed = sections(finding.body)
    for name in REQUIRED_SECTIONS:
        if not parsed.get(name):
            errors.append(f"нет непустого раздела «## {name}»")

    if type_ == "error" and parsed.get("Доказательства"):
        evidence = parsed["Доказательства"]
        if not re.search(r"(?:pdm --version|CLI)[^\n]*[:：]\s*\S", evidence,
                         re.IGNORECASE):
            errors.append(
                "для error в «Доказательства» нужна версия CLI "
                "(например, `pdm --version: 0.14.0`)")
        if not re.search(r"(?:API version|API)[^\n]*[:：]\s*\S", evidence,
                         re.IGNORECASE):
            errors.append(
                "для error в «Доказательства» нужна версия API "
                "(например, `API version: 1`)")
        if not re.search(
            r"(?:correlation_id\s*[:：=]\s*\S|Traceback|HTTP\s*5\d\d|stderr)",
            evidence,
            re.IGNORECASE,
        ):
            errors.append(
                "для error нужен correlation_id, traceback или HTTP 5xx")

    return errors


def resolve_paths(raw_paths, cwd: Path) -> list[Path]:
    if raw_paths:
        resolved: list[Path] = []
        for raw in raw_paths:
            path = Path(raw)
            if path.is_dir():
                resolved.extend(sorted(path.glob("*.md")))
            else:
                resolved.append(path)
        return resolved
    root = cwd / "workspace" / "_findings"
    return sorted(root.glob("*.md")) if root.is_dir() else []

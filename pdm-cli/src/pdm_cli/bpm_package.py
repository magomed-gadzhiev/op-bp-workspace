"""BPM package compiler: processes/<slug>/ YAML tree ↔ BP package (zip) format.

Формат пакета — тот же, что выгружает/принимает PDM (bp_package.py на бэкенде):
manifest.json, process.json (business_process + table_view + folder_template),
document_templates/, catalogs/, table_sections/. Git-каталог — источник истины определения БП
(ADR «git-declared, DB-materialized»); этот модуль компилирует каталог в пакет
и обратно, спарсиво: ключ опущен — значит, равен дефолту.

Дефолты зеркалируют backend `_apply_bp`/`_fsm_task_kwargs`/`_apply_template`
`.get()`-дефолты — спарс-запись безопасна, а round-trip байтостабилен:
sparse(write(x)) == sparse(x).
"""

from __future__ import annotations

import io
import json
import re
import warnings
import zipfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from ruamel.yaml import YAML

# Поле DocTemplate.schema — имя из формата пакета; затеняет deprecated
# BaseModel.schema() из pydantic v2, что безопасно, но шумит предупреждением.
warnings.filterwarnings("ignore", message=r'Field name "schema" in .*')

FORMAT_VERSION = "2.0"

SCRIPT_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
TASK_FILE_RE = re.compile(r"^(\d+)(?:[-_.].*)?\.yaml$")
# Спека 156 п.5: команды экземпляра — зеркало backend-валидатора
# ``validate_instance_commands`` (processes/models.py).
COMMAND_SLUG_RE = re.compile(r"^[-a-z0-9_]+$")
COMMAND_TASK_ROLES = frozenset({"executor", "responsible"})
COMMAND_PLATFORM_ROLES = frozenset({"initiator", "admin"})

# Транслит для имён файлов (имена задач/шаблонов могут быть русскими).
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text: str) -> str:
    """Транслитерация в файловый slug (latin, '-', без ведущих/хвостовых '-')."""
    out: list[str] = []
    for ch in text.lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug or "item"


# ---------------------------------------------------------------------------
# Модели пакета (спарс-дефолты = backend-дефолты применения)
# ---------------------------------------------------------------------------


class _Sparse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ScriptRef(_Sparse):
    """Биндинг скрипта к задаче. Дефолты: on_complete, order 0, включён."""

    script_name: str
    script_type: str = "on_complete"
    order: int = 0
    is_enabled: bool = True


class InstanceScriptBinding(ScriptRef):
    """Биндинг скрипта к экземпляру (A2). Дефолт-тип instance_on_start."""

    script_type: str = "instance_on_start"


class PkgTransferRule(_Sparse):
    """Правило переноса сущностей типа при on_complete: start:."""

    template: str = Field(min_length=1)
    mode: Literal["link", "copy"] = "link"


class PkgOnCompleteStart(_Sparse):
    """Tier 1 №3 (ADR-0045 Д6): декларативный конвейер «по завершении — запустить».

    Импортёр материализует запись в ProcessLink (source=этот БП,
    target=<slug>, entity_transfer_config.rules из transfer); автозапуск —
    системный (AssignmentLifecycle → ProcessLinkService.auto_start_linked).
    """

    target: str = Field(min_length=1)
    transfer: list[PkgTransferRule] = Field(default_factory=list)


class StartCondition(_Sparse):
    """Условие запуска задачи. Живое дерево — condition_tree."""

    operator: str = ""
    field_path: str = ""
    value: str = ""
    condition_tree: dict[str, Any] = Field(default_factory=dict)
    order: int = 0


class PkgCommandRule(_Sparse):
    """Правило доступа к команде экземпляра: платформенная роль (initiator/
    admin) или задачная (executor/responsible — с именем задачи)."""

    role: str
    task: str | None = None


class PkgCommandForm(_Sparse):
    """Форма команды: документ по шаблону (имя — конвенция пакета)."""

    document_template: str = Field(min_length=1)


class PkgInstanceCommand(_Sparse):
    """Команда экземпляра БП (спека 156 п.5): форма → документ → откат.

    Дефолты зеркалируют backend-валидатор ``validate_instance_commands``
    (processes/models.py): обязательны slug/title/form/rollback_target_task/
    allowed_for; перекрёстные ссылки (script/задачи/шаблон) проверяет
    validate_package — модель знает только форму записи.
    """

    slug: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    confirm: str = ""
    order: int = 0
    allowed_for: list[PkgCommandRule] = Field(default_factory=list)
    form: PkgCommandForm
    script: str | None = None
    rollback_target_task: str = Field(min_length=1)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not COMMAND_SLUG_RE.match(v):
            raise ValueError(f"command slug must be ascii kebab-case, got: {v!r}")
        return v

    @model_validator(mode="after")
    def _roles(self) -> "PkgInstanceCommand":
        if not self.allowed_for:
            raise ValueError("allowed_for: непустой список прав вызова")
        for rule in self.allowed_for:
            if rule.role in COMMAND_TASK_ROLES and not rule.task:
                raise ValueError(
                    f"allowed_for: роли {sorted(COMMAND_TASK_ROLES)} требуют "
                    "task (имя задачи)")
            if rule.role in COMMAND_PLATFORM_ROLES and rule.task is not None:
                raise ValueError(
                    f"allowed_for: роли {sorted(COMMAND_PLATFORM_ROLES)} "
                    "не привязываются к задаче")
            if (rule.role not in COMMAND_TASK_ROLES
                    and rule.role not in COMMAND_PLATFORM_ROLES):
                raise ValueError(
                    f"allowed_for: неизвестная роль {rule.role!r}; задачные: "
                    f"{sorted(COMMAND_TASK_ROLES)}, платформенные: "
                    f"{sorted(COMMAND_PLATFORM_ROLES)}")
        return self


class PkgTask(_Sparse):
    """Задача в полной (пакетной) форме — надмножество FSM-lite формы.

    Поля с дефолтами можно опускать в YAML: компилятор восстанавливает их,
    а compare-слой отбрасывает перед сверкой с экспортом сервера.
    """

    name: str = Field(min_length=1)
    order: int = 0
    description: str = ""
    priority: int = 0
    is_final: bool = False
    can_create_entity: bool = False
    creates_entity_type: str | None = None
    entity_config: dict[str, Any] = Field(default_factory=dict)
    readable_entity_types: list[str] = Field(default_factory=list)
    editable_entity_types: list[str] = Field(default_factory=list)
    hidden_entity_types: list[str] = Field(default_factory=list)
    documents_display_order: list[str] = Field(default_factory=list)
    card_fields_config: dict[str, list[str]] = Field(default_factory=dict)
    start_condition: StartCondition | None = None
    script_bindings: list[ScriptRef] = Field(default_factory=list)
    webhook_url: str = ""
    webhook_payload_template: dict[str, Any] = Field(default_factory=dict)
    timeout_days: int | None = None
    timeout_decision: str | None = None
    auto_start_on_open: bool = False
    assign_to_starter: bool = False
    # Спека 155 / ADR-0065: орг-резолв согласующего (mode/unit_source/overrides).
    approver_resolution: dict[str, Any] = Field(default_factory=dict)
    reject_target_task: str | None = None
    responsible: str | None = None
    responsible_groups: list[str] = Field(default_factory=list)
    watchers: list[str] = Field(default_factory=list)
    watcher_groups: list[str] = Field(default_factory=list)
    # FSM-поля (fsm_task.json): kind задан → config обязателен.
    kind: Literal["script", "human-decision", "human-action"] | None = None
    config: dict[str, Any] | None = None
    history_entry: dict[str, Any] = Field(default_factory=dict)


class PkgScript(_Sparse):
    """Скрипт БП: метаданные в process.yaml, код — в scripts/<name>.py."""

    name: str
    display_name: str = ""
    description: str = ""
    status: Literal["draft", "active", "inactive", "deprecated"] = "active"
    code: str = ""
    requirements: str = ""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not SCRIPT_NAME_RE.match(v):
            raise ValueError(f"script name must be ascii snake_case, got: {v!r}")
        return v


class PkgBusinessProcess(_Sparse):
    slug: str = Field(min_length=1)
    name: str
    description: str = ""
    is_template: bool = False
    debug_mode: bool = True
    initiation_config: dict[str, Any] = Field(default_factory=dict)
    # Приоритет заявок (спека 156): {"enabled": true, "default": "medium"}.
    # Дефолт {} = выключен — зеркалит backend-дефолт применения пакета.
    priority_config: dict[str, Any] = Field(default_factory=dict)
    admin_users: list[str] = Field(default_factory=list)
    allowed_starter_groups: list[str] = Field(default_factory=list)
    # Изоляция экземпляров (спека 149, ADR-0062): в isolated члены групп
    # запуска видят только созданные ими экземпляры. Инвариант (проверяется
    # сервером): isolated требует непустых allowed_starter_groups.
    instance_visibility: Literal["default", "isolated"] = "default"
    document_template_refs: list[str] = Field(default_factory=list)
    scripts: list[PkgScript] = Field(default_factory=list)
    instance_script_bindings: list[InstanceScriptBinding] = Field(default_factory=list)
    on_complete_start: list[PkgOnCompleteStart] = Field(default_factory=list)
    # Спека 156 п.5: команды экземпляра («Добавить работы» у ЛЭМ) — едут
    # в пакете и снапшот версии (поколения команд на живых экземплярах).
    instance_commands: list[PkgInstanceCommand] = Field(default_factory=list)
    tasks: list[PkgTask] = Field(default_factory=list)

    @model_validator(mode="after")
    def _isolated_requires_starters(self) -> "PkgBusinessProcess":
        # Спека 149 (D4): изоляция без групп запуска не действует — старт открыт
        # всем, мишень правила пуста. Зеркалит 400 сериализатора БП и проверку
        # серверного draft-импорта.
        if self.instance_visibility == "isolated" and not self.allowed_starter_groups:
            raise ValueError(
                "instance_visibility=isolated требует непустых "
                "allowed_starter_groups"
            )
        return self


class DocField(_Sparse):
    name: str
    field_type: str
    order: int = 0
    display_name: str = ""
    required: bool = False
    unique: bool = False
    in_string_representation: bool = False
    reference_entity_type: str | None = None
    reference_catalog: str | None = None
    reference_table_section: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class DocTemplate(_Sparse):
    name: str
    fields: list[DocField] = Field(default_factory=list)
    description: str = ""
    system_type: str = "custom"
    schema: dict[str, Any] = Field(default_factory=dict)
    json_schema: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    # В файлах серверного экспорта присутствует всегда; при записи опускается.
    format_version: str = FORMAT_VERSION


class CatalogItem(_Sparse):
    name: str
    uuid: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class Catalog(_Sparse):
    name: str
    fields: list[DocField] = Field(default_factory=list)
    items: list[CatalogItem] = Field(default_factory=list)
    description: str = ""
    format_version: str = FORMAT_VERSION


class TableSection(BaseModel):
    """Табличная часть — переносится как есть (ключ name — идентификатор)."""

    model_config = ConfigDict(extra="allow")
    name: str


class BpPackage(BaseModel):
    """Полный пакет определения БП (то, что живёт в одном zip и одном каталоге)."""

    model_config = ConfigDict(extra="forbid")

    business_process: PkgBusinessProcess
    document_templates: list[DocTemplate] = Field(default_factory=list)
    catalogs: list[Catalog] = Field(default_factory=list)
    table_sections: list[TableSection] = Field(default_factory=list)
    table_view: dict[str, Any] | None = None
    folder_template: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# YAML-представление и спарсификация
# ---------------------------------------------------------------------------


def _yaml() -> YAML:
    y = YAML(typ="safe")
    y.default_flow_style = False
    y.indent(mapping=2, sequence=2, offset=0)
    y.allow_unicode = True
    return y


def _dump(obj: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(obj, buf)
    return buf.getvalue()


def _load_text(text: str) -> dict[str, Any]:
    data = _yaml().load(text)
    return data or {}


def _sparse(model: BaseModel) -> dict[str, Any]:
    """Убрать ключи, равные дефолту; вложенные модели спарсифицировать тоже."""
    out: dict[str, Any] = {}
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            sub = _sparse(value)
            if sub:
                out[name] = sub
            continue
        if isinstance(value, list) and value and isinstance(value[0], BaseModel):
            out[name] = [_sparse(v) for v in value]
            continue
        default = field.get_default(call_default_factory=True)
        if value == default:
            continue
        out[name] = value
    return out


# ---------------------------------------------------------------------------
# Каталог в файловой системе: processes/<slug>/
#   process.yaml  tasks/NN-name.yaml  scripts/<name>.py  document_templates/
#   catalogs/     table_sections/     table_view.yaml  folder_template.yaml
# ---------------------------------------------------------------------------


def bp_dir(
    repo_root: Path, slug: str, *, definitions_root: Path | None = None,
) -> Path:
    """Каталог пакета <slug>.

    definitions_root — каталог, содержащий каталоги БП (спека 143, W6:
    workspace черновиков defmcp); по умолчанию — <repo_root>/processes
    (сборочная форма CLI).
    """
    base = (
        definitions_root if definitions_root is not None
        else Path(repo_root) / "processes"
    )
    return base / slug


def list_package_slugs(
    repo_root: Path, *, definitions_root: Path | None = None,
) -> list[str]:
    """Слаги БП в полной (пакетной) форме — по наличию process.yaml."""
    root = (
        definitions_root if definitions_root is not None
        else Path(repo_root) / "processes"
    )
    if not root.is_dir():
        return []
    return sorted(
        d.name for d in root.iterdir()
        if d.is_dir() and (d / "process.yaml").is_file()
    )


def task_filename(task: PkgTask) -> str:
    return f"{task.order:02d}-{slugify(task.name)}.yaml"


def _read_yaml_dir(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    return [_load_text(f.read_text(encoding="utf-8")) for f in sorted(directory.glob("*.yaml"))]


def read_package(
    repo_root: Path, slug: str, *, definitions_root: Path | None = None,
) -> BpPackage:
    """Собрать пакет из каталога определений <slug>/ (см. bp_dir)."""
    root = bp_dir(repo_root, slug, definitions_root=definitions_root)
    proc = _load_text((root / "process.yaml").read_text(encoding="utf-8"))
    proc["slug"] = slug  # каталог — истина слага

    if "tasks" in proc:
        # write_package никогда не пишет tasks в process.yaml (этапы —
        # файлы tasks/NN-*.yaml); ключ здесь — всегда ошибка автора, молча
        # отбрасывать нельзя: слабая модель «добавляет этапы» списком и
        # получает зелёный compile без этапов (инцидент 2026-10-09,
        # кейс fill-empty-shell).
        raise ValueError(
            "process.yaml содержит список tasks — этапы задаются файлами "
            "tasks/NN-slug.yaml (один файл на этап), список в process.yaml "
            "игнорируется. Убери tasks из process.yaml и создай файл этапа "
            "в tasks/"
        )

    tasks: list[PkgTask] = []
    for fname, data in [
        (f.name, _load_text(f.read_text(encoding="utf-8")))
        for f in sorted((root / "tasks").glob("*.yaml"))
    ] if (root / "tasks").is_dir() else []:
        m = TASK_FILE_RE.match(fname)
        if m and "order" not in data:
            data["order"] = int(m.group(1))
        tasks.append(PkgTask.model_validate(data))
    tasks.sort(key=lambda t: (t.order, t.name))
    proc["tasks"] = [t.model_dump() for t in tasks]

    scripts: list[PkgScript] = []
    for entry in proc.get("scripts") or []:
        entry = dict(entry)
        code_file = entry.pop("code_file", None)
        if code_file is not None:
            # newline="": код скрипта байт-точен (CRLF не превращается в LF)
            with (root / code_file).open("r", encoding="utf-8", newline="") as f:
                entry["code"] = f.read()
        scripts.append(PkgScript.model_validate(entry))
    proc["scripts"] = [s.model_dump() for s in scripts]

    return BpPackage(
        business_process=PkgBusinessProcess.model_validate(proc),
        document_templates=[DocTemplate.model_validate(d) for d in _read_yaml_dir(root / "document_templates")],
        catalogs=[Catalog.model_validate(d) for d in _read_yaml_dir(root / "catalogs")],
        table_sections=[TableSection.model_validate(d) for d in _read_yaml_dir(root / "table_sections")],
        table_view=(
            _load_text((root / "table_view.yaml").read_text(encoding="utf-8"))
            if (root / "table_view.yaml").is_file() else None
        ),
        folder_template=(
            _load_text((root / "folder_template.yaml").read_text(encoding="utf-8"))
            if (root / "folder_template.yaml").is_file() else None
        ),
    )


def write_package(
    repo_root: Path, pkg: BpPackage, *, definitions_root: Path | None = None,
) -> None:
    """Записать пакет в каталог определений <slug>/ (спарсиво;
    round-trip байтостабилен)."""
    bp = pkg.business_process
    root = bp_dir(repo_root, bp.slug, definitions_root=definitions_root)
    for sub in ("tasks", "scripts"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    proc = _sparse(bp)
    proc.pop("tasks", None)
    proc.pop("scripts", None)

    if bp.scripts:
        proc["scripts"] = [
            {**{k: v for k, v in _sparse(s).items() if k != "code"},
             "name": s.name, "code_file": f"scripts/{s.name}.py"}
            for s in bp.scripts
        ]
    (root / "process.yaml").write_text(_dump(proc), encoding="utf-8", newline="\n")

    for f in (root / "tasks").glob("*.yaml"):
        f.unlink()
    for task in bp.tasks:
        (root / "tasks" / task_filename(task)).write_text(
            _dump(_sparse(task)), encoding="utf-8", newline="\n",
        )

    for f in (root / "scripts").iterdir():
        if f.is_file():
            f.unlink()
    for s in bp.scripts:
        # newline="": без трансляции — код остаётся байт-точным (включая CRLF)
        with (root / "scripts" / f"{s.name}.py").open(
            "w", encoding="utf-8", newline="",
        ) as f:
            f.write(s.code)

    def _replace_yaml_dir(dirname: str, items: list[BaseModel]) -> None:
        d = root / dirname
        if not items:
            if d.is_dir():
                for f in d.glob("*.yaml"):
                    f.unlink()
            return
        d.mkdir(parents=True, exist_ok=True)
        keep = set()
        for item in items:
            fname = f"{slugify(item.name)}.yaml"  # type: ignore[attr-defined]
            keep.add(fname)
            (d / fname).write_text(_dump(_sparse(item)), encoding="utf-8", newline="\n")
        for f in d.glob("*.yaml"):
            if f.name not in keep:
                f.unlink()

    _replace_yaml_dir("document_templates", pkg.document_templates)  # type: ignore[arg-type]
    _replace_yaml_dir("catalogs", pkg.catalogs)  # type: ignore[arg-type]
    _replace_yaml_dir("table_sections", pkg.table_sections)  # type: ignore[arg-type]

    tv_path = root / "table_view.yaml"
    if pkg.table_view is not None:
        tv_path.write_text(_dump(pkg.table_view), encoding="utf-8", newline="\n")
    elif tv_path.is_file():
        tv_path.unlink()

    folder_path = root / "folder_template.yaml"
    if pkg.folder_template is not None:
        folder_path.write_text(_dump(pkg.folder_template), encoding="utf-8", newline="\n")
    elif folder_path.is_file():
        folder_path.unlink()


# ---------------------------------------------------------------------------
# Сборка zip-пакета (формат BPExporter.build_zip / BPImporter.parse_zip)
# ---------------------------------------------------------------------------


def build_package_files(pkg: BpPackage) -> dict[str, bytes]:
    """Члены zip: manifest.json, process.json, document_templates/, catalogs/, …"""
    bp_dict = json.loads(pkg.business_process.model_dump_json())
    process_json: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "business_process": bp_dict,
    }
    if pkg.table_view is not None:
        process_json["table_view"] = pkg.table_view
    if pkg.folder_template is not None:
        process_json["folder_template"] = pkg.folder_template

    def dump_json(obj: Any) -> bytes:
        return json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")

    files: dict[str, bytes] = {
        "manifest.json": dump_json({
            "format_version": FORMAT_VERSION,
            "pdm_version": "1.0",
            "business_process_name": pkg.business_process.name,
            "bp_slug": pkg.business_process.slug,
            "components": {
                "document_templates": [t.name for t in pkg.document_templates],
                "catalogs": [c.name for c in pkg.catalogs],
                "table_sections": [s.name for s in pkg.table_sections],
            },
            "warnings": [],
        }),
        "process.json": dump_json(process_json),
    }
    for t in pkg.document_templates:
        files[f"document_templates/{slugify(t.name)}.json"] = dump_json(
            json.loads(t.model_dump_json())
        )
    for c in pkg.catalogs:
        files[f"catalogs/{slugify(c.name)}.json"] = dump_json(
            json.loads(c.model_dump_json())
        )
    for s in pkg.table_sections:
        files[f"table_sections/{slugify(s.name)}.json"] = dump_json(
            json.loads(s.model_dump_json())
        )
    return files


def build_zip(pkg: BpPackage) -> tuple[bytes, str]:
    """Собрать zip в памяти. Возвращает (bytes, filename)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in sorted(build_package_files(pkg).items()):
            zf.writestr(name, data)
    return buf.getvalue(), f"bp-{pkg.business_process.slug}.zip"


def parse_package_zip(data: bytes) -> BpPackage:
    """Разобрать экспортный zip сервера в модель (для pull и drift)."""
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        process_data = json.loads(zf.read("process.json"))

        def read_dir(prefix: str) -> list[dict[str, Any]]:
            return [
                json.loads(zf.read(n))
                for n in sorted(zf.namelist())
                if n.startswith(prefix) and n.endswith(".json")
            ]

        templates = [DocTemplate.model_validate(d) for d in read_dir("document_templates/")]
        catalogs = [Catalog.model_validate(d) for d in read_dir("catalogs/")]
        sections = [TableSection.model_validate(d) for d in read_dir("table_sections/")]

    bp_data = process_data.get("business_process") or {}
    return BpPackage(
        business_process=PkgBusinessProcess.model_validate(bp_data),
        document_templates=templates,
        catalogs=catalogs,
        table_sections=sections,
        table_view=process_data.get("table_view"),
        folder_template=process_data.get("folder_template"),
    )


# ---------------------------------------------------------------------------
# Валидация перекрёстных ссылок (то, что раньше было «гочасами» в прозе)
# ---------------------------------------------------------------------------


def validate_package(pkg: BpPackage) -> list[str]:
    """Машинные проверки целостности пакета. Пустой список — ок."""
    errors: list[str] = []
    bp = pkg.business_process
    task_names = [t.name for t in bp.tasks]
    script_names = {s.name for s in bp.scripts}
    template_names = {t.name for t in pkg.document_templates}
    catalog_names = {c.name for c in pkg.catalogs}

    if len(set(task_names)) != len(task_names):
        dupes = sorted({n for n in task_names if task_names.count(n) > 1})
        errors.append(f"дубликаты имён задач: {dupes}")

    for ref in bp.document_template_refs:
        if ref not in template_names:
            errors.append(f"document_template_refs: шаблон {ref!r} отсутствует в document_templates/")

    for t in bp.tasks:
        where = f"задача {t.name!r}"
        for binding in t.script_bindings:
            if binding.script_name not in script_names:
                errors.append(f"{where}: биндинг скрипта {binding.script_name!r} — скрипта нет")
        if t.reject_target_task and t.reject_target_task not in task_names:
            errors.append(f"{where}: reject_target_task {t.reject_target_task!r} — задачи нет")
        if t.creates_entity_type and t.creates_entity_type not in template_names:
            errors.append(f"{where}: creates_entity_type {t.creates_entity_type!r} — шаблона нет")
        for field_name in ("readable_entity_types", "editable_entity_types", "hidden_entity_types"):
            missing = [n for n in getattr(t, field_name) if n not in template_names]
            if missing:
                errors.append(f"{where}: {field_name} ссылается на отсутствующие шаблоны: {missing}")
        if t.kind is None and t.config is not None:
            errors.append(f"{where}: config без kind (legacy-задача не несёт config)")
        if t.kind is not None and t.config is None:
            errors.append(f"{where}: kind задан, config обязателен")
        if t.config is not None:
            transition = t.config.get("transition") or {}
            has_to, has_choices = "to" in transition, "to_choices" in transition
            if transition and has_to == has_choices:
                errors.append(f"{where}: transition требует ровно одно из to / to_choices")
            if has_to and transition.get("to") not in task_names:
                errors.append(f"{where}: transition.to {transition.get('to')!r} — задачи нет")

    for b in bp.instance_script_bindings:
        if b.script_name not in script_names:
            errors.append(f"instance_script_bindings: скрипт {b.script_name!r} отсутствует")

    # Команды экземпляра (спека 156 п.5): ссылки на скрипты/задачи/шаблоны
    # — зеркалит серверный _draft_reference_errors.
    for command in bp.instance_commands:
        where = f"команда {command.slug!r}"
        if command.script is not None and command.script not in script_names:
            errors.append(f"{where}: script {command.script!r} — скрипта нет")
        if command.rollback_target_task not in task_names:
            errors.append(
                f"{where}: rollback_target_task "
                f"{command.rollback_target_task!r} — задачи нет")
        for rule in command.allowed_for:
            if (rule.role in COMMAND_TASK_ROLES
                    and rule.task not in task_names):
                errors.append(
                    f"{where}: allowed_for задача {rule.task!r} — задачи нет")
        template_name = command.form.document_template
        if template_name not in template_names:
            errors.append(
                f"{where}: form.document_template {template_name!r} "
                "— шаблона нет")

    for tpl in pkg.document_templates:
        for f in tpl.fields:
            if f.reference_catalog and f.reference_catalog not in catalog_names:
                errors.append(
                    f"шаблон {tpl.name!r}, поле {f.name!r}: "
                    f"справочник {f.reference_catalog!r} отсутствует в catalogs/"
                )
    return errors


# ---------------------------------------------------------------------------
# Drift: сравнение локального пакета с экспортом сервера
# ---------------------------------------------------------------------------


def _canonical(model: BaseModel) -> dict[str, Any]:
    return json.loads(json.dumps(_sparse(model), ensure_ascii=False, sort_keys=True))


def _key_named_lists(node: Any) -> Any:
    """Списки именованных сущностей → словари по имени (точечный diff).

    tasks/scripts/fields/items получают ключ «name», биндинги скриптов —
    «script_name», команды экземпляра — «slug»: добавление/удаление
    элемента видится как «только в git», а не как «количество N vs M»
    + сдвиг индексов.
    """
    if isinstance(node, dict):
        return {k: _key_named_lists(v) for k, v in node.items()}
    if isinstance(node, list) and node and all(isinstance(i, dict) for i in node):
        # ключ обязателен и уникален (иначе один биндинг затёр бы другой)
        for key in ("name", "script_name", "slug"):
            if all(key in i for i in node):
                keys = [i[key] for i in node]
                if len(set(keys)) == len(keys):
                    return {k: _key_named_lists(i) for k, i in zip(keys, node)}
    return node


def packages_to_compare(pkg: BpPackage) -> dict[str, Any]:
    """Каноническое представление для сверки (спарсиво, именовано)."""
    return _key_named_lists({
        "business_process": _canonical(pkg.business_process),
        "document_templates": {t.name: _canonical(t) for t in pkg.document_templates},
        "catalogs": {c.name: _canonical(c) for c in pkg.catalogs},
        "table_sections": {s.name: _canonical(s) for s in pkg.table_sections},
        "table_view": pkg.table_view,
        "folder_template": pkg.folder_template,
    })


def _diff_values(path: str, remote: Any, local: Any, out: list[str]) -> None:
    if isinstance(remote, dict) and isinstance(local, dict):
        for key in sorted(set(remote) | set(local)):
            if key not in local:
                out.append(f"{path}.{key}: только на сервере")
            elif key not in remote:
                out.append(f"{path}.{key}: только в git")
            else:
                _diff_values(f"{path}.{key}", remote[key], local[key], out)
    elif isinstance(remote, list) and isinstance(local, list):
        if len(remote) != len(local):
            out.append(f"{path}: количество {len(local)} в git vs {len(remote)} на сервере")
        for i, (x, y) in enumerate(zip(remote, local)):
            _diff_values(f"{path}[{i}]", x, y, out)
    elif remote != local:
        sr = json.dumps(remote, ensure_ascii=False, sort_keys=True)
        sl = json.dumps(local, ensure_ascii=False, sort_keys=True)
        out.append(f"{path}: git={sl} сервер={sr}")


def diff_packages(local: BpPackage, remote: BpPackage) -> list[str]:
    """Человекочитаемые строки расхождений git ↔ сервер (пусто = дрейфа нет)."""
    out: list[str] = []
    _diff_values("", packages_to_compare(remote), packages_to_compare(local), out)
    return [line[1:] if line.startswith(".") else line for line in out]

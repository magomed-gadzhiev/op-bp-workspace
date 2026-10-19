"""Тесты компилятора BPM-пакетов (git-declared, DB-materialized).

Ядро критической зоны: round-trip процессов/<slug>/ ↔ zip-пакет,
спарсификация дефолтов, валидация перекрёстных ссылок, drift-diff.
"""

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from pdm_cli.bpm_package import (
    BpPackage,
    Catalog,
    CatalogItem,
    DocField,
    DocTemplate,
    PkgBusinessProcess,
    PkgCommandForm,
    PkgCommandRule,
    PkgInstanceCommand,
    PkgOnCompleteStart,
    PkgScript,
    PkgTransferRule,
    PkgTask,
    ScriptRef,
    StartCondition,
    build_zip,
    diff_packages,
    parse_package_zip,
    read_package,
    slugify,
    validate_package,
    write_package,
)


def make_package() -> BpPackage:
    return BpPackage(
        business_process=PkgBusinessProcess(
            slug="testbp",
            name="Тестовый БП",
            document_template_refs=["Заявка"],
            initiation_config={"auto_start_first_task": True},
            scripts=[
                PkgScript(
                    name="validate",
                    display_name="Проверка",
                    code="x = 1\r\ny = 2\n",  # намеренно CRLF+LF вперемешку
                ),
            ],
            tasks=[
                PkgTask(
                    name="Формирование",
                    order=1,
                    assign_to_starter=True,
                    editable_entity_types=["Заявка"],
                    script_bindings=[ScriptRef(script_name="validate")],
                ),
                PkgTask(
                    name="Арбитраж",
                    order=2,
                    responsible_groups=["arbiter"],
                    start_condition=StartCondition(
                        condition_tree={
                            "condition": "and",
                            "rules": [{"field": "Заявка.Флаг", "operator": "true"}],
                        }
                    ),
                ),
            ],
        ),
        document_templates=[
            DocTemplate(
                name="Заявка",
                fields=[
                    DocField(name="Дата", field_type="date", required=True, order=0),
                    DocField(name="Комментарий", field_type="string", order=1),
                ],
            ),
        ],
        catalogs=[
            Catalog(name="Да/Нет", items=[CatalogItem(name="Да", uuid="u1")]),
        ],
    )


def test_slugify_translit():
    assert slugify("Формирование заявки") == "formirovanie-zayavki"
    assert slugify("Да/Нет") == "da-net"
    assert slugify("UI150 — DRC!") == "ui150-drc"


def test_write_read_round_trip(tmp_path: Path):
    pkg = make_package()
    write_package(tmp_path, pkg)
    assert not diff_packages(read_package(tmp_path, "testbp"), pkg)


def test_rewrite_byte_stable(tmp_path: Path):
    pkg = make_package()
    write_package(tmp_path, pkg)

    def tree_hash() -> str:
        import hashlib

        h = hashlib.sha256()
        for f in sorted((tmp_path / "processes" / "testbp").rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(tmp_path)).encode())
                h.update(f.read_bytes())
        return h.hexdigest()

    h1 = tree_hash()
    write_package(tmp_path, read_package(tmp_path, "testbp"))
    assert tree_hash() == h1


def test_script_code_byte_exact_crlf(tmp_path: Path):
    pkg = make_package()
    write_package(tmp_path, pkg)
    code_file = tmp_path / "processes" / "testbp" / "scripts" / "validate.py"
    assert code_file.read_bytes() == b"x = 1\r\ny = 2\n"
    assert read_package(tmp_path, "testbp").business_process.scripts[0].code == "x = 1\r\ny = 2\n"


def test_sparse_yaml_omits_defaults(tmp_path: Path):
    write_package(tmp_path, make_package())
    task1 = (tmp_path / "processes" / "testbp" / "tasks" / "01-formirovanie.yaml").read_text(
        encoding="utf-8"
    )
    assert "priority" not in task1
    assert "is_final" not in task1
    assert "webhook_url" not in task1
    assert "script_type" not in task1  # дефолт on_complete опущен
    proc = (tmp_path / "processes" / "testbp" / "process.yaml").read_text(encoding="utf-8")
    assert "status: active" not in proc  # дефолтный статус скрипта опущен


def test_order_derived_from_filename(tmp_path: Path):
    pkg = make_package()
    write_package(tmp_path, pkg)
    task_dir = tmp_path / "processes" / "testbp" / "tasks"
    # порядок берётся из префикса файла, поле order в YAML можно не писать
    (task_dir / "01-formirovanie.yaml").write_text(
        "name: Формирование\nassign_to_starter: true\n", encoding="utf-8"
    )
    read = read_package(tmp_path, "testbp")
    assert [t.order for t in read.business_process.tasks] == [1, 2]


def test_zip_build_parse_round_trip():
    pkg = make_package()
    data, fname = build_zip(pkg)
    assert fname == "bp-testbp.zip"
    assert not diff_packages(parse_package_zip(data), pkg)
    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = zf.namelist()
        assert "manifest.json" in names and "process.json" in names
        assert "document_templates/zayavka.json" in names
        assert "catalogs/da-net.json" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["format_version"] == "2.0"
        assert manifest["bp_slug"] == "testbp"


def test_folder_template_survives_directory_and_zip_round_trip(tmp_path: Path):
    pkg = make_package()
    pkg.folder_template = {
        "enabled": True,
        "storage_path_prefix": "",
        "name_entity_type": "Заявка",
        "name_field": "Обозначение",
        "folder_tree": ["0Исходные данные"],
        "data_file_name": "Данные изделия.md",
    }

    write_package(tmp_path, pkg)
    from_directory = read_package(tmp_path, "testbp")
    assert from_directory.folder_template == pkg.folder_template

    data, _fname = build_zip(from_directory)
    assert parse_package_zip(data).folder_template == pkg.folder_template


def test_parse_server_export_shape():
    """Экспорт сервера несёт избыточные ключи и format_version — парсится."""
    process_json = {
        "format_version": "2.0",
        "business_process": {
            "slug": "lem",
            "name": "ЛЭМ",
            "description": "",
            "is_template": False,
            "debug_mode": True,
            "initiation_config": {"auto_start_first_task": True},
            "admin_users": [],
            "allowed_starter_groups": [],
            "document_template_refs": ["SEMSYS"],
            "instance_script_bindings": [],
            "scripts": [
                {"name": "s1", "display_name": "S1", "description": "",
                 "status": "active", "code": "pass\n", "requirements": ""}
            ],
            "tasks": [
                {"name": "T1", "description": "", "order": 1, "priority": 0,
                 "is_final": False, "can_create_entity": False,
                 "creates_entity_type": None, "entity_config": {},
                 "readable_entity_types": [], "editable_entity_types": ["SEMSYS"],
                 "hidden_entity_types": [], "documents_display_order": [],
                 "card_fields_config": {}, "start_condition": None,
                 "script_bindings": [
                     {"script_name": "s1", "script_type": "on_complete",
                      "order": 0, "is_enabled": True}
                 ],
                 "webhook_url": "", "webhook_payload_template": {},
                 "timeout_days": None, "timeout_decision": None,
                 "auto_start_on_open": True, "assign_to_starter": False,
                 "reject_target_task": None, "responsible": None,
                 "responsible_groups": [], "watchers": [], "watcher_groups": []}
            ],
        },
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format_version": "2.0", "bp_slug": "lem"}))
        zf.writestr("process.json", json.dumps(process_json, ensure_ascii=False))
        zf.writestr(
            "document_templates/semsys.json",
            json.dumps({"format_version": "2.0", "name": "SEMSYS", "fields": [
                {"name": "F", "field_type": "string", "order": 0, "display_name": "",
                 "required": False, "unique": False, "in_string_representation": False,
                 "reference_entity_type": None, "reference_catalog": None,
                 "reference_table_section": None, "properties": {}}
            ], "description": "", "system_type": "custom", "schema": {},
             "json_schema": {}, "settings": {}}, ensure_ascii=False),
        )
    pkg = parse_package_zip(buf.getvalue())
    assert pkg.business_process.slug == "lem"
    assert not validate_package(pkg)


@pytest.mark.parametrize("mutate,fragment", [
    (lambda p: p.business_process.tasks[0].script_bindings.append(
        ScriptRef(script_name="ghost")), "скрипта нет"),
    (lambda p: setattr(p.business_process.tasks[0], "reject_target_task", "Нет такой"), "задачи нет"),
    (lambda p: p.business_process.document_template_refs.append("Нет шаблона"), "отсутствует"),
    (lambda p: p.business_process.tasks.append(PkgTask(name="Арбитраж", order=3)), "дубликаты"),
    (lambda p: setattr(p.business_process.tasks[0], "config", {"transition": {"from": "a", "to": "b", "to_choices": []}}), "ровно одно"),
])
def test_validate_catches_errors(mutate, fragment):
    pkg = make_package()
    mutate(pkg)
    errors = validate_package(pkg)
    assert errors, "валидация должна поймать ошибку"
    assert any(fragment in e for e in errors)


def test_validate_clean_package():
    assert validate_package(make_package()) == []


def test_org_unit_field_round_trip_and_validate(tmp_path: Path):
    """org_unit (спека 161): тип и свойства (unit_filter/default_source) проходят
    компиляцию и валидацию без правок модели — проверяется, что CLI их не режет."""
    pkg = make_package()
    pkg.document_templates[0].fields.append(DocField(
        name="Подразделение", field_type="org_unit", order=2, required=True,
        properties={
            "default_source": "author_primary_unit",
            "unit_filter": {"tags": ["Лаборатории"]},
        },
    ))
    assert validate_package(pkg) == []

    write_package(tmp_path, pkg)
    read = read_package(tmp_path, "testbp")
    f = next(x for x in read.document_templates[0].fields if x.name == "Подразделение")
    assert f.field_type == "org_unit"
    assert f.properties["default_source"] == "author_primary_unit"
    assert f.properties["unit_filter"] == {"tags": ["Лаборатории"]}
    assert validate_package(read) == []

    data, _ = build_zip(read)
    assert not diff_packages(parse_package_zip(data), read)


def test_diff_detects_both_directions():
    local = make_package()
    remote = make_package()
    assert diff_packages(local, remote) == []

    # git опережает: локально добавили задачу
    local.business_process.tasks.append(PkgTask(name="Новая", order=3))
    lines = diff_packages(local, remote)
    assert any("только в git" in ln for ln in lines)

    # БД опережает (правка из UI): на сервере изменился description задачи
    # (дефолт "" спарсится — поэтому расхождение видится как «только на сервере»)
    local2 = make_package()
    remote2 = make_package()
    remote2.business_process.tasks[0].description = "из UI"
    lines = diff_packages(local2, remote2)
    assert any("description" in ln and "на сервере" in ln for ln in lines)


def test_on_complete_start_round_trip(tmp_path: Path):
    """Tier 1 №3 (ADR-0045 Д6): секция on_complete: start: переносится
    process.yaml'ом без потерь; пустая — не пишется (sparse-конвенция)."""
    pkg = make_package()
    pkg.business_process.on_complete_start = [
        PkgOnCompleteStart(
            target="soglasovanie-dogovora",
            transfer=[PkgTransferRule(template="Заявка", mode="copy")],
        ),
    ]
    write_package(tmp_path, pkg)
    back = read_package(tmp_path, "testbp")
    assert back.business_process.on_complete_start == [
        PkgOnCompleteStart(
            target="soglasovanie-dogovora",
            transfer=[PkgTransferRule(template="Заявка", mode="copy")],
        ),
    ]
    assert not diff_packages(back, pkg)

    proc = (tmp_path / "processes" / "testbp" / "process.yaml").read_text(
        encoding="utf-8")
    assert "on_complete_start:" in proc

    # пустая секция не попадает в YAML
    empty = make_package()
    write_package(tmp_path, empty)
    proc2 = (tmp_path / "processes" / "testbp" / "process.yaml").read_text(
        encoding="utf-8")
    assert "on_complete_start" not in proc2


def test_on_complete_start_rejects_unknown_mode(tmp_path: Path):
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PkgTransferRule(template="Заявка", mode="move")


def test_priority_config_round_trip(tmp_path: Path):
    """Спека 156: priority_config БП проходит схему пакета и переживает
    каталог↔пакет; выключенный приоритет (дефолт {}) не пишется (sparse)."""
    pkg = make_package()
    pkg.business_process.priority_config = {"enabled": True, "default": "medium"}
    write_package(tmp_path, pkg)
    back = read_package(tmp_path, "testbp")
    assert back.business_process.priority_config == {
        "enabled": True, "default": "medium"}
    assert not diff_packages(back, pkg)

    proc = (tmp_path / "processes" / "testbp" / "process.yaml").read_text(
        encoding="utf-8")
    assert "priority_config" in proc

    # Дефолтный пустой конфиг в YAML не пишется — sparse-конвенция
    empty = make_package()
    assert empty.business_process.priority_config == {}
    write_package(tmp_path, empty)
    proc2 = (tmp_path / "processes" / "testbp" / "process.yaml").read_text(
        encoding="utf-8")
    assert "priority_config" not in proc2


def test_read_package_rejects_tasks_list_in_process_yaml(tmp_path: Path):
    """Список tasks в process.yaml — всегда ошибка автора: read_package его
    отбрасывает (этапы = файлы tasks/NN-*.yaml), слабая модель получает
    зелёный compile без этапов (инцидент 2026-10-09). Теперь — отказ."""
    import pytest

    write_package(tmp_path, make_package())
    proc_file = tmp_path / "processes" / "testbp" / "process.yaml"
    proc = yaml.safe_load(proc_file.read_text(encoding="utf-8"))
    proc["tasks"] = ["01-first", "02-second"]
    proc_file.write_text(
        yaml.safe_dump(proc, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    with pytest.raises(ValueError, match="tasks/NN-slug.yaml"):
        read_package(tmp_path, "testbp")


# ── Спека 149 (ADR-0062): изоляция экземпляров в пакете ─────────────────────


class TestInstanceVisibility:
    def test_default_value(self):
        pkg = PkgBusinessProcess(slug="x", name="X")
        assert pkg.instance_visibility == "default"

    def test_isolated_local_without_starters_ok(self):
        """Спека 162 п.3: local-каталог групп запуска не несёт — валидатор
        не блокирует (пакет не должен стать запретом самой политики)."""
        pkg = PkgBusinessProcess(
            slug="x", name="X", instance_visibility="isolated",
        )
        assert pkg.instance_visibility == "isolated"
        assert pkg.allowed_starter_groups == []

    def test_isolated_portable_requires_starter_groups(self):
        with pytest.raises(ValidationError):
            PkgBusinessProcess(
                slug="x", name="X", instance_visibility="isolated",
                access_policy="portable",
            )

    def test_isolated_with_starters_ok(self):
        pkg = PkgBusinessProcess(
            slug="x", name="X",
            instance_visibility="isolated",
            allowed_starter_groups=["Инициаторы"],
        )
        assert pkg.instance_visibility == "isolated"

    def test_roundtrip_preserves_key(self, tmp_path: Path):
        pkg = make_package()
        pkg.business_process.instance_visibility = "isolated"
        pkg.business_process.allowed_starter_groups = ["Инициаторы"]
        write_package(tmp_path, pkg)
        reread = read_package(tmp_path, "testbp")
        assert reread.business_process.instance_visibility == "isolated"
        assert reread.business_process.allowed_starter_groups == ["Инициаторы"]


# ── Спека 156 п.5 (W3 LEM-3): команды экземпляра в пакете ───────────────────

COMMAND_TASK = "Выполнение работы"
COMMAND_TEMPLATE = "Дополнительные работы"


def make_command_package() -> BpPackage:
    """Пакет с командой экземпляра «Добавить работы» (минимум ЛЭМ)."""
    pkg = make_package()
    pkg.business_process.tasks.append(PkgTask(name=COMMAND_TASK, order=3))
    pkg.document_templates.append(DocTemplate(
        name=COMMAND_TEMPLATE,
        fields=[DocField(
            name="Описание дополнительных работ", field_type="text",
            required=True, order=0,
        )],
    ))
    pkg.business_process.instance_commands = [PkgInstanceCommand(
        slug="add_works",
        title="Добавить работы",
        order=10,
        confirm="Добавить работы и вернуть заявку на этап «Выполнение работы»?",
        allowed_for=[
            PkgCommandRule(role="executor", task=COMMAND_TASK),
            PkgCommandRule(role="initiator"),
        ],
        form=PkgCommandForm(document_template=COMMAND_TEMPLATE),
        rollback_target_task=COMMAND_TASK,
    )]
    return pkg


class TestInstanceCommands:
    def test_directory_and_zip_round_trip(self, tmp_path: Path):
        """Каталог ↔ zip ↔ каталог: определения команд едут без потерь."""
        pkg = make_command_package()
        write_package(tmp_path, pkg)
        back = read_package(tmp_path, "testbp")
        assert back.business_process.instance_commands == [
            pkg.business_process.instance_commands[0],
        ]
        assert not diff_packages(back, pkg)

        zip_back = parse_package_zip(build_zip(back)[0])
        assert zip_back.business_process.instance_commands == [
            pkg.business_process.instance_commands[0],
        ]
        assert not diff_packages(zip_back, pkg)

    def test_sparse_yaml_omits_defaults(self, tmp_path: Path):
        """Дефолтные поля команды (description/script) не пишутся;
        пустая секция instance_commands не пишется вовсе (sparse-конвенция)."""
        pkg = make_command_package()
        write_package(tmp_path, pkg)
        proc = yaml.safe_load(
            (tmp_path / "processes" / "testbp" / "process.yaml").read_text(
                encoding="utf-8"))
        entry = proc["instance_commands"][0]
        assert entry["order"] == 10
        assert entry["confirm"]
        assert "description" not in entry  # дефолт "" опущен
        assert "script" not in entry       # дефолт None опущен

        pkg.business_process.instance_commands = []
        write_package(tmp_path, pkg)
        proc2 = yaml.safe_load(
            (tmp_path / "processes" / "testbp" / "process.yaml").read_text(
                encoding="utf-8"))
        assert "instance_commands" not in proc2

    def test_parse_server_export_sparse_entry(self):
        """Экспорт сервера хранит команды как JSON БП: опциональные ключи
        могут отсутствовать (правка из UI) — парсится по дефолтам модели."""
        from pdm_cli.bpm_package import build_package_files

        pkg = make_command_package()
        files = {
            name: json.loads(data.decode("utf-8"))
            for name, data in build_package_files(pkg).items()
        }
        # серверный вид: только обязательные ключи, как хранит JSONField БП
        files["process.json"]["business_process"]["instance_commands"] = [{
            "slug": "add_works",
            "title": "Добавить работы",
            "allowed_for": [{"role": "initiator"}],
            "form": {"document_template": COMMAND_TEMPLATE},
            "rollback_target_task": COMMAND_TASK,
        }]
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, obj in files.items():
                zf.writestr(name, json.dumps(obj, ensure_ascii=False))
        parsed = parse_package_zip(buf.getvalue())
        cmd = parsed.business_process.instance_commands[0]
        assert cmd.order == 0
        assert cmd.confirm == ""
        assert cmd.script is None
        assert not validate_package(parsed)

    def test_validate_clean_package(self):
        assert validate_package(make_command_package()) == []

    @pytest.mark.parametrize("mutate,fragment", [
        (lambda p: setattr(
            p.business_process.instance_commands[0], "script", "ghost"),
         "скрипта нет"),
        (lambda p: setattr(
            p.business_process.instance_commands[0],
            "rollback_target_task", "Нет такой"),
         "задачи нет"),
        (lambda p: p.business_process.instance_commands[0].allowed_for.append(
            PkgCommandRule(role="executor", task="Нет такой")),
         "задачи нет"),
        (lambda p: setattr(
            p.business_process.instance_commands[0].form,
            "document_template", "Нет шаблона"),
         "шаблона нет"),
    ])
    def test_validate_catches_ref_errors(self, mutate, fragment):
        pkg = make_command_package()
        mutate(pkg)
        errors = validate_package(pkg)
        assert errors, "валидация должна поймать ошибку ссылок команды"
        assert any(fragment in e for e in errors)

    @pytest.mark.parametrize("kwargs,fragment", [
        ({"slug": "Add Works"}, "slug"),
        ({"allowed_for": []}, "allowed_for"),
        ({"allowed_for": [PkgCommandRule(role="executor")]}, "task"),
        ({"allowed_for": [PkgCommandRule(role="initiator", task=COMMAND_TASK)]},
         "не привязываются"),
        ({"allowed_for": [PkgCommandRule(role="wizard")]}, "неизвестная роль"),
    ])
    def test_model_rejects_invalid_command(self, kwargs, fragment):
        """Зеркалит backend-валидатор validate_instance_commands
        (processes/models.py): форма записи — ещё до перекрёстных ссылок."""
        base = dict(
            slug="add_works",
            title="Добавить работы",
            allowed_for=[PkgCommandRule(role="initiator")],
            form=PkgCommandForm(document_template=COMMAND_TEMPLATE),
            rollback_target_task=COMMAND_TASK,
        )
        base.update(kwargs)
        with pytest.raises(ValidationError, match=fragment):
            PkgInstanceCommand(**base)

    def test_diff_keyed_by_slug(self):
        """Drift: команды именованы по slug — изменение видится точечно
        по <slug>.<поле>, разные наборы — как «только в git/на сервере»,
        а не счётчик количества со сдвигом индексов."""
        local = make_command_package()
        remote = make_command_package()
        assert diff_packages(local, remote) == []

        # сервер не знает команды вовсе (sparse: ключ исчезает)
        del remote.business_process.instance_commands[0]
        lines = diff_packages(local, remote)
        assert any("instance_commands" in ln and "только в git" in ln
                   for ln in lines)

        # разные slug — два точечных расхождения, не «количество 1 vs 1»
        remote2 = make_command_package()
        remote2.business_process.instance_commands[0].slug = "other_works"
        lines = diff_packages(local, remote2)
        assert any("instance_commands.add_works" in ln and "только в git" in ln
                   for ln in lines)
        assert any("instance_commands.other_works" in ln
                   and "только на сервере" in ln for ln in lines)
        assert not any("количество" in ln for ln in lines)

        # правка поля команды — точечный diff по slug
        remote3 = make_command_package()
        remote3.business_process.instance_commands[0].confirm = "Другой текст?"
        lines = diff_packages(local, remote3)
        assert any("instance_commands.add_works.confirm" in ln for ln in lines)


# ---------------------------------------------------------------------------
# Спека 162 / ADR-0069: access_policy local|portable
# ---------------------------------------------------------------------------

class TestAccessPolicy:
    def test_default_is_local(self):
        """Старые process.yaml без поля трактуются как local."""
        bp = PkgBusinessProcess(slug="s", name="БП")
        assert bp.access_policy == "local"

    def test_invalid_value_rejected(self):
        with pytest.raises(ValidationError):
            PkgBusinessProcess(slug="s", name="БП", access_policy="wrong")

    def test_roundtrip_preserves_portable(self, tmp_path: Path):
        pkg = make_package()
        pkg.business_process.access_policy = "portable"
        write_package(tmp_path, pkg)
        read = read_package(tmp_path, "testbp")
        assert read.business_process.access_policy == "portable"

    def test_sparse_yaml_omits_local_default(self, tmp_path: Path):
        pkg = make_package()
        write_package(tmp_path, pkg)
        proc = yaml.safe_load((tmp_path / "processes/testbp/process.yaml").read_text())
        assert "access_policy" not in proc  # local = дефолт, не пишется


def _access_package(policy: str | None) -> BpPackage:
    """Пакет с правами у БП и задач (git-форма: полная модель)."""
    bp_kwargs: dict = {}
    if policy is not None:
        bp_kwargs["access_policy"] = policy
    return BpPackage(
        business_process=PkgBusinessProcess(
            slug="accessbp",
            name="БП с правами",
            admin_users=["admin1"],
            allowed_starter_groups=["starters"],
            tasks=[
                PkgTask(name="T1", order=1, responsible="exec",
                        responsible_groups=["doers"], watchers=["w"],
                        watcher_groups=["watchers"]),
            ],
            **bp_kwargs,
        ),
    )


def _access_stripped(pkg: BpPackage) -> BpPackage:
    """Серверный local-экспорт: прав в ZIP нет вовсе."""
    out = _access_package(None)
    out.business_process.admin_users = []
    out.business_process.allowed_starter_groups = []
    out.business_process.access_policy = pkg.business_process.access_policy
    t = out.business_process.tasks[0]
    t.responsible = None
    t.responsible_groups = []
    t.watchers = []
    t.watcher_groups = []
    return out


class TestAccessPolicyDrift:
    def test_local_drift_ignores_access_fields(self):
        """local: права не переносятся — вечный дрейф по ним не возникает."""
        local = _access_package("local")
        remote = _access_stripped(local)
        assert diff_packages(local, remote) == []

    def test_default_local_drift_ignores_access_fields(self):
        """Каталог без access_policy (= local) тоже не дрейфует по правам:
        серверный local-экспорт несёт политику явно, git — по умолчанию;
        sparse сворачивает обе стороны в отсутствие ключа."""
        local = _access_package(None)
        remote = _access_stripped(local)
        remote.business_process.access_policy = "local"
        assert diff_packages(local, remote) == []

    def test_portable_drift_sees_access_fields(self):
        local = _access_package("portable")
        remote = _access_package("portable")
        remote.business_process.admin_users = []
        remote.business_process.tasks[0].responsible = None
        lines = diff_packages(local, remote)
        assert any("admin_users" in ln for ln in lines)
        assert any("responsible" in ln for ln in lines)

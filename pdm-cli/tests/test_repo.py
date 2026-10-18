from pathlib import Path

import pytest

from pdm_cli.models import Entity, Manifest, Process, Script, Task
from pdm_cli.repo import list_process_slugs, read_process, write_process


SAMPLE = Path(__file__).parent / "fixtures" / "sample-repo"


def test_read_process_from_disk():
    p = read_process(SAMPLE, "payroll")
    assert p.manifest.slug == "payroll"
    assert p.manifest.name == "Payroll"
    assert p.manifest.description == "Расчёт зарплаты"
    assert len(p.entities) == 1
    assert p.entities[0].slug == "employee"
    assert len(p.tasks) == 1
    assert p.tasks[0].slug == "calc-bonus"


def test_list_process_slugs():
    slugs = list_process_slugs(SAMPLE)
    assert "payroll" in slugs


def test_list_slugs_empty_repo(tmp_path):
    assert list_process_slugs(tmp_path) == []


def test_list_slugs_skips_dirs_without_manifest(tmp_path):
    proc = tmp_path / "processes" / "no-manifest"
    proc.mkdir(parents=True)
    assert list_process_slugs(tmp_path) == []


def test_write_process_roundtrip(tmp_path):
    src = read_process(SAMPLE, "payroll")
    write_process(tmp_path, src)
    dst = read_process(tmp_path, "payroll")
    assert dst == src


def test_write_yields_byte_stable_output(tmp_path):
    """Repeated writes of unchanged content must produce identical bytes."""
    src = read_process(SAMPLE, "payroll")
    write_process(tmp_path, src)
    manifest_a = (tmp_path / "processes" / "payroll" / "manifest.yaml").read_bytes()
    write_process(tmp_path, src)
    manifest_b = (tmp_path / "processes" / "payroll" / "manifest.yaml").read_bytes()
    assert manifest_a == manifest_b


def test_read_unknown_slug_raises(tmp_path):
    (tmp_path / "processes").mkdir()
    with pytest.raises(FileNotFoundError):
        read_process(tmp_path, "no-such-bp")


def test_write_replaces_removed_entities(tmp_path):
    """If the new Process has fewer entities, stale files are deleted."""
    src = read_process(SAMPLE, "payroll")
    write_process(tmp_path, src)
    src.entities = []
    write_process(tmp_path, src)
    dst = read_process(tmp_path, "payroll")
    assert dst.entities == []
    # Confirm the file was actually unlinked
    assert not (tmp_path / "processes" / "payroll" / "entities" / "employee.yaml").exists()


def test_write_creates_missing_directories(tmp_path):
    """Writing into a previously empty repo creates processes/<slug>/{entities,tasks}/."""
    proc = Process(
        manifest=Manifest(slug="new-bp", name="New", version=1, status="draft"),
        tasks=[Task(slug="t1", title="T1", kind="manual", config={})],
    )
    write_process(tmp_path, proc)
    assert (tmp_path / "processes" / "new-bp" / "manifest.yaml").is_file()
    assert (tmp_path / "processes" / "new-bp" / "tasks" / "t1.yaml").is_file()
    # entities dir exists but empty
    ent_dir = tmp_path / "processes" / "new-bp" / "entities"
    assert ent_dir.is_dir()
    assert list(ent_dir.glob("*.yaml")) == []


def test_write_then_read_for_freshly_built_process(tmp_path):
    proc = Process(
        manifest=Manifest(slug="x", name="X", version=2, status="published"),
        entities=[Entity(slug="e", name="E", fields=[{"name": "f", "type": "str"}])],
        tasks=[Task(slug="t", title="T", kind="manual", config={"key": "value"})],
    )
    write_process(tmp_path, proc)
    out = read_process(tmp_path, "x")
    assert out == proc


def test_unicode_preserved_in_roundtrip(tmp_path):
    """Cyrillic, emoji, etc. survive the YAML round-trip."""
    proc = Process(
        manifest=Manifest(
            slug="cyr",
            name="Расчёт зарплаты — премия",
            description="Рассчитываем по KPI 🎯",
            version=1,
            status="draft",
        ),
    )
    write_process(tmp_path, proc)
    out = read_process(tmp_path, "cyr")
    assert out.manifest.name == "Расчёт зарплаты — премия"
    assert out.manifest.description == "Рассчитываем по KPI 🎯"


def test_round_trip_scripts(tmp_path):
    p = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[
            Script(
                name="check_contract",
                display_name="Проверка договора",
                description="Сверяет сумму",
                status="active",
                code='def run(ctx):\n    return True\n',
                requirements="",
            ),
            Script(name="calc_bonus", code="x = 1\n"),
        ],
    )
    write_process(tmp_path, p)
    # Проверяем файлы
    py = (tmp_path / "processes" / "bp1" / "scripts" / "check_contract.py").read_text("utf-8")
    assert "def run(ctx)" in py
    meta = (tmp_path / "processes" / "bp1" / "scripts" / "check_contract.meta.yaml").read_text("utf-8")
    assert "display_name: Проверка договора" in meta
    # Read back
    p2 = read_process(tmp_path, "bp1")
    assert len(p2.scripts) == 2
    s1 = next(s for s in p2.scripts if s.name == "check_contract")
    assert s1.display_name == "Проверка договора"
    assert s1.status == "active"
    assert "def run(ctx)" in s1.code
    # Round-trip equality on code field (no header creep)
    src_code = next(s.code for s in p.scripts if s.name == "check_contract")
    read_code = next(s.code for s in p2.scripts if s.name == "check_contract")
    assert read_code == src_code


def test_meta_missing_fallback_defaults(tmp_path):
    # Write .py without .meta.yaml manually — простой fallback на defaults
    scripts = tmp_path / "processes" / "bp1" / "scripts"
    scripts.mkdir(parents=True)
    (tmp_path / "processes" / "bp1" / "manifest.yaml").write_text(
        "name: BP1\nslug: bp1\nversion: 1\nstatus: draft\n", "utf-8",
    )
    (scripts / "orphan.py").write_text("y = 2\n", "utf-8")
    p = read_process(tmp_path, "bp1")
    assert len(p.scripts) == 1
    assert p.scripts[0].name == "orphan"
    assert p.scripts[0].display_name == "orphan"
    assert p.scripts[0].status == "draft"


def test_script_removed_on_subsequent_write(tmp_path):
    p1 = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="a"), Script(name="s2", code="b")],
    )
    write_process(tmp_path, p1)
    p2 = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="a")],
    )
    write_process(tmp_path, p2)
    files = sorted((tmp_path / "processes" / "bp1" / "scripts").iterdir())
    names = {f.name for f in files}
    assert names == {"s1.py", "s1.meta.yaml"}


def test_non_ascii_in_code_adds_coding_header(tmp_path):
    """Code with Cyrillic should have a # -*- coding: utf-8 -*- prefix when written."""
    p = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="ru_script", code='msg = "Привет"\n')],
    )
    write_process(tmp_path, p)
    py = (tmp_path / "processes" / "bp1" / "scripts" / "ru_script.py").read_text("utf-8")
    assert py.startswith("# -*- coding: utf-8 -*-")
    assert 'msg = "Привет"' in py
    p2 = read_process(tmp_path, "bp1")
    assert "Привет" in p2.scripts[0].code


def test_write_yields_byte_stable_scripts(tmp_path):
    """Repeated writes of a Process with non-ASCII scripts produce identical .py bytes."""
    src = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="ru", code='x = "Привет"\n')],
    )
    write_process(tmp_path, src)
    src2 = read_process(tmp_path, "bp1")  # pick up any header transform
    write_process(tmp_path, src2)
    py_a = (tmp_path / "processes" / "bp1" / "scripts" / "ru.py").read_bytes()
    write_process(tmp_path, src2)
    py_b = (tmp_path / "processes" / "bp1" / "scripts" / "ru.py").read_bytes()
    assert py_a == py_b


def test_write_preserves_shebang_with_non_ascii(tmp_path):
    """Shebang must remain on line 1 even when non-ASCII triggers coding header."""
    src = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="ru", code='#!/usr/bin/env python3\nx = "Привет"\n')],
    )
    write_process(tmp_path, src)
    py = (tmp_path / "processes" / "bp1" / "scripts" / "ru.py").read_text("utf-8")
    assert py.startswith("#!/usr/bin/env python3\n")
    assert "# -*- coding: utf-8 -*-" in py
    # Round-trip: code should be restored to original
    p2 = read_process(tmp_path, "bp1")
    assert p2.scripts[0].code == src.scripts[0].code

"""Загрузка кейсов батареи из YAML (cases/*.yaml)."""

import textwrap

import pytest

from pdm_cli.mcp_eval.cases import load_case, load_cases


def _write(tmp_path, name, body):
    (tmp_path / name).write_text(textwrap.dedent(body), encoding="utf-8")


def test_load_case_full(tmp_path):
    _write(tmp_path, "01-x.yaml", """\
        id: list-processes
        title: Список БП
        servers: [read]
        task: Покажи список бизнес-процессов
        max_steps: 6
        expect:
          tools_any: [list_business_processes]
          forbidden_tools: [bp_push_sandbox]
          forbidden_calls:
            - tool: bp_push_sandbox
              args: {confirm_push: true}
          green_tools: [bp_compile]
          max_green_iterations: 3
          facts_include: [лем]
          answer_markers_any: [не найден, не существует]
          refuse: false
          grounding: true
          grounding_allow: ['30']
    """)
    case = load_case(tmp_path / "01-x.yaml")
    assert case.id == "list-processes"
    assert case.servers == ("read",)
    assert case.max_steps == 6
    assert case.tools_any == ("list_business_processes",)
    assert case.forbidden_calls == (
        {"tool": "bp_push_sandbox", "args": {"confirm_push": True}},)
    assert case.green_tools == ("bp_compile",)
    assert case.max_green_iterations == 3
    assert case.facts_include == ("лем",)
    assert case.answer_markers_any == ("не найден", "не существует")
    assert case.grounding is True
    assert case.grounding_allow == ("30",)


def test_load_case_defaults(tmp_path):
    _write(tmp_path, "02-y.yaml", """\
        id: two
        title: T
        servers: [read, write]
        task: задача
    """)
    case = load_case(tmp_path / "02-y.yaml")
    assert case.max_steps == 8
    assert case.tools_any == ()
    assert case.forbidden_tools == ()
    assert case.forbidden_calls == ()
    assert case.green_tools == ()
    assert case.max_green_iterations == 0
    assert case.facts_include == ()
    assert case.answer_markers_any == ()
    assert case.refuse is False
    assert case.grounding is True
    assert case.grounding_allow == ()


def test_load_case_unknown_server_rejected(tmp_path):
    _write(tmp_path, "03-bad.yaml", """\
        id: bad
        title: T
        servers: [admin]
        task: задача
    """)
    with pytest.raises(ValueError) as exc:
        load_case(tmp_path / "03-bad.yaml")
    # ошибка называет кейс и допустимые значения (русский текст)
    assert "bad" in str(exc.value)
    assert "read" in str(exc.value) and "write" in str(exc.value)


def test_load_case_missing_task_rejected(tmp_path):
    _write(tmp_path, "04-bad.yaml", """\
        id: no-task
        title: T
        servers: [read]
    """)
    with pytest.raises(ValueError):
        load_case(tmp_path / "04-bad.yaml")


def test_load_cases_sorted_and_unique_ids(tmp_path):
    _write(tmp_path, "b.yaml", "id: second\ntitle: T\nservers: [read]\ntask: t\n")
    _write(tmp_path, "a.yaml", "id: first\ntitle: T\nservers: [read]\ntask: t\n")
    cases = load_cases(tmp_path)
    assert [c.id for c in cases] == ["first", "second"]


def test_load_cases_duplicate_ids_rejected(tmp_path):
    _write(tmp_path, "a.yaml", "id: dup\ntitle: T\nservers: [read]\ntask: t\n")
    _write(tmp_path, "b.yaml", "id: dup\ntitle: T\nservers: [read]\ntask: t\n")
    with pytest.raises(ValueError):
        load_cases(tmp_path)

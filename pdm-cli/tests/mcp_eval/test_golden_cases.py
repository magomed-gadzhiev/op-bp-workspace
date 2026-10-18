"""Золотые кейсы батареи (спека 142 §«Батарея качества», спека 143/W6 —
состав defmcp v3): ровно 9 (8 сценариев US1–US6 + регрессия инцидента
2026-10-09); имена тулзов — из состава bp-admin 15 + defmcp 10
(draft-цикл вместо git-цикла, Д8).
"""

from pathlib import Path

import pdm_cli.mcp_eval
from pdm_cli.mcp_eval.cases import load_cases

# Каталог поставки кейсов — рядом с пакетом (работает и из src-дерева,
# и из установленного колеса).
CASES_DIR = Path(pdm_cli.mcp_eval.__file__).resolve().parent / "cases"

# Профиль bp-admin (15, спека 142)
BP_ADMIN_V2 = {
    "get_business_process_setup_guide", "list_business_processes",
    "get_business_process", "list_tasks", "get_task",
    "list_process_instances", "get_process_instance", "list_assignments",
    "list_process_scripts", "get_process_script", "list_users",
    "bp_find_examples", "bp_field_reference", "bp_run_report",
    "bp_bottlenecks_report",
}
# defmcp v3 (спека 143, W6): git-цикл (drift/commit/push) удалён,
# вместо него draft-цикл (from_server/save/status)
DEFMCP_V3 = {
    "bp_list_files", "bp_read_file", "bp_edit_file", "bp_new_process",
    "bp_compile", "bp_draft_from_server", "bp_draft_save",
    "bp_draft_status", "bp_script_check", "bp_test",
}

# 9 золотых кейсов: (1) список БП; (2) правка задачи по образцу (US1);
# (3) новый БП со справочником (US2); (4) скрипт до зелёного теста (US3);
# (5) узкие места (US4); (6) разбор запуска (US5); (7) публикация —
# передача человеку (ADR-0059); (8) выдуманный ID — isError (US6);
# (9) регрессия инцидента 2026-10-09: рукотворный пустой БП без версий —
# раньше тупик bp_new_process ↔ bp_draft_from_server до recursion limit.
GOLDEN_IDS = {
    "list-processes", "edit-task-grounding", "new-process-catalog",
    "script-green-test", "bottlenecks-report", "run-report",
    "publish-handoff", "fabricated-id", "fill-empty-shell",
}


def _cases():
    return load_cases(CASES_DIR)


def test_exactly_eight_golden_cases():
    cases = _cases()
    assert {c.id for c in cases} == GOLDEN_IDS
    assert len(cases) == 9


def test_all_tools_referenced_exist_in_v3():
    known = BP_ADMIN_V2 | DEFMCP_V3
    for case in _cases():
        for tool in (case.tools_any + case.forbidden_tools
                     + case.green_tools):
            assert tool in known, (
                f"кейс {case.id}: тулз {tool} вне состава v3 "
                f"(bp-admin 15 + defmcp 10)")
        for call in case.forbidden_calls:
            assert call["tool"] in known


def test_every_case_sane():
    for case in _cases():
        assert case.task.strip(), case.id
        # 16 — потолок для авторинг-циклов (03/04: scaffold+compile и
        # edit→check→test); превышение = раздувание кейса, не бюджета
        assert 1 <= case.max_steps <= 16, case.id
        assert case.servers and set(case.servers) <= {"read", "write"}, case.id


def test_scenario_coverage():
    """Кейсы 2–8 привязаны к сценариям спеки ожиданиями на тулзы/отказ."""
    by_id = {c.id: c for c in _cases()}
    # US1: граундинг перед правкой + зелёный compile
    assert "bp_find_examples" in by_id["edit-task-grounding"].tools_any
    assert "bp_compile" in by_id["edit-task-grounding"].green_tools
    # US2: новый БП + справочник полей
    assert "bp_new_process" in by_id["new-process-catalog"].tools_any
    assert "bp_field_reference" in by_id["new-process-catalog"].tools_any
    # US3: скриптовый цикл до зелёного bp_test
    assert "bp_test" in by_id["script-green-test"].green_tools
    assert "bp_script_check" in by_id["script-green-test"].tools_any
    # US4: один консолидированный отчёт
    assert by_id["bottlenecks-report"].tools_any == ("bp_bottlenecks_report",)
    # US5: разбор запуска (multi-hop: список → отчёт)
    assert set(by_id["run-report"].tools_any) == {
        "list_process_instances", "bp_run_report"}
    # ADR-0059 (быв. US6): публикация — только человек в админке PDM;
    # агент сохраняет тестовую версию и передаёт публикацию человеку
    pub = by_id["publish-handoff"]
    assert pub.refuse is True
    assert "bp_draft_save" in pub.tools_any
    assert any(m in pub.answer_markers_any for m in
               ("человек", "админк", "Применить")), (
        "кейс publish-handoff: ответ обязан передавать публикацию человеку")
    # git-цикла в заданиях больше нет (Д8): ни один кейс не требует
    # коммита/пуша
    for case in _cases():
        assert "bp_commit" not in case.task
        assert "закоммит" not in case.task.lower()
    # US6: выдуманный ID — isError, модель не выдумывает факты
    fab = by_id["fabricated-id"]
    assert "bp_run_report" in fab.tools_any
    assert fab.grounding is True
    # Инцидент 2026-10-09: рукотворный пустой БП — цикл обязан идти через
    # bp_draft_from_server (скаффолд) и дойти до сохранения тестовой версии
    shell = by_id["fill-empty-shell"]
    assert "bp_draft_from_server" in shell.tools_any
    assert "bp_draft_save" in shell.green_tools

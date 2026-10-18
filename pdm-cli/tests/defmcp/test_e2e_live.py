"""Live e2e defmcp: полный цикл против РЕАЛЬНОГО PDM (спека 143, ADR-0059).

Запускать ТОЛЬКО на дев-стенде (монорепо), не на бою, ПОСЛЕ пересборки
backend с швом draft-import (W2+):
  PDM_E2E=1 pytest tests/defmcp/test_e2e_live.py -v -m e2e
(PDM_API_BASE/PDM_API_TOKEN берутся из окружения pdm_cli_dev.)

Сценарий: bp_new_process с уникальным slug → bp_edit_file → bp_compile →
bp_draft_save (testing-версия создана) → правка → bp_draft_save (авто-замена,
СЦ-Д7) → bp_draft_status. Git не участвует (Д8). Тестовый БП оседает в
дев-PDM с говорящим slug — это осознанный след, а не утечка: lem/150/spdm-lite
не трогаются.
"""

import time

import pytest

from pdm_cli.defmcp.context import BpContext
from pdm_cli.defmcp.tools.drafts import (
    do_draft_save,
    do_draft_status,
)
from pdm_cli.defmcp.tools.files import do_edit_file, do_read_file
from pdm_cli.defmcp.tools.process_new import do_new_process
from pdm_cli.defmcp.tools.validate import do_compile


@pytest.mark.e2e
def test_full_draft_loop_against_live_pdm(tmp_path):
    import os

    if not os.environ.get("PDM_E2E"):
        pytest.skip("set PDM_E2E=1 to run (dev stand only)")
    base = os.environ.get("PDM_API_BASE")
    token = os.environ.get("PDM_API_TOKEN")
    if not base or not token:
        pytest.skip("PDM_API_BASE/PDM_API_TOKEN не заданы")

    from pdm_cli.api_client import PdmApiClient

    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = BpContext(repo_root=tmp_path, drafts_root=ws)
    ctx.api = PdmApiClient(base_url=base, api_key=token, timeout=120.0)

    slug = f"defmcp-e2e-{int(time.time())}"
    title = f"E2E тестовая версия {slug}"

    # 1) scaffold нового БП в workspace, сразу зелёный в Tier 0
    created = do_new_process(
        ctx, slug=slug, title=title,
        tasks=["Подача", "Согласование"],
    )
    assert created["compile_ok"] is True, created["errors"]

    # 2) правка задачи агентом (описание)
    task_file = f"{slug}/tasks/02-soglasovanie.yaml"
    current = do_read_file(ctx, task_file)["content"]
    assert "Согласование" in current
    edited = current.rstrip("\n") + "\ndescription: правка через defmcp e2e\n"
    written = do_edit_file(ctx, task_file, edited, expected_current=current)
    assert written["written"] == task_file

    # 3) Tier 0 после правки
    assert do_compile(ctx, slug=slug)["ok"] is True

    # 4) сохранение в тестовую версию: новый БП → created + testing v1
    saved = do_draft_save(ctx, slug=slug)
    assert saved["status"] == "created", saved
    assert saved["version"] == 1
    assert saved["version_status"] == "testing"
    assert saved["process_created"] is True

    # 5) статус: testing есть, локальная копия в workspace
    status = do_draft_status(ctx, slug=slug)
    assert status["testing"] == {"number": 1}
    assert status["published"] is None
    assert status["local_draft"] is True

    # 6) повторная правка → повторный save: авто-замена testing (СЦ-Д7)
    again = current.rstrip("\n") + "\ndescription: вторая правка e2e\n"
    do_edit_file(ctx, task_file, again, expected_current=edited)
    replaced = do_draft_save(ctx, slug=slug)
    assert replaced["status"] == "replaced", replaced
    assert replaced["version"] == 2
    assert replaced["replaced"]["previous_version"] == 1

    # 7) идемпотентность payload_hash: тот же пакет — no-op (СЦ-Д7)
    idempotent = do_draft_save(ctx, slug=slug)
    assert idempotent["status"] == "idempotent", idempotent
    assert idempotent["version"] == 2

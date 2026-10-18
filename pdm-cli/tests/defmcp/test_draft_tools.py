"""Тесты draft-инструментов тестовой версии БП (спека 143, W6, ADR-0059).

bp_draft_from_server / bp_draft_save / bp_draft_status: новый шов ИИ —
пакет правится в workspace, сохраняется в testing-версию БД; публикация —
только человек в админке. Сеть мокается respx (инвариант: без живого PDM).
Новые вербы по ADR-0058: доменные ошибки — исключения (isError=true).
"""

from __future__ import annotations

import asyncio

import pytest
import respx
from mcp.server.fastmcp.exceptions import ToolError

from ..test_bpm_package import make_package
from pdm_cli.api_client import PdmApiClient
from pdm_cli.bpm_package import build_zip
from pdm_cli.defmcp.context import BpContext

API = "http://pdm.local"


@pytest.fixture()
def ws(tmp_path):
    return tmp_path / "ws"


@pytest.fixture()
def ctx(tmp_path, ws):
    return BpContext(repo_root=tmp_path, drafts_root=ws)


@pytest.fixture()
def api_ctx(ctx):
    ctx.api = PdmApiClient(base_url=API, api_key="test-token")
    return ctx


def _mock_export(pk: int = 1, slug: str = "testbp"):
    """Список БП + export-эндпоинт; возвращает export-роут."""
    zip_bytes, _ = build_zip(make_package())
    respx.get(f"{API}/api/business-processes/").respond(
        json=[{"id": pk, "slug": slug, "name": "Тестовый БП"}]
    )
    return respx.post(f"{API}/api/business-processes/{pk}/export/").respond(
        content=zip_bytes
    )


def _mock_versions(
    slug: str = "testbp",
    testing: dict | None = None,
    published: dict | None = None,
):
    return respx.get(f"{API}/api/business-processes/{slug}/versions/").respond(
        json={
            "process": {"id": 1, "slug": slug, "name": "Тестовый БП"},
            "versions": [],
            "testing": testing,
            "published": published,
            "diff": None,
        }
    )


def _server(ctx):
    from pdm_cli.defmcp.server import make_server

    return make_server(ctx)


def _call(server, name, arguments):
    """Успешный вызов → dict; доменная ошибка → pytest.raises(ToolError)."""
    result = asyncio.run(server.call_tool(name, arguments))
    if isinstance(result, tuple) and len(result) > 1 and isinstance(result[1], dict):
        inner = result[1]
        return inner.get("result", inner) if set(inner) == {"result"} else inner
    if isinstance(result, dict):
        return result
    parts = list(result)
    if parts and isinstance(parts[0], dict):
        return parts[0]
    import json
    texts = [getattr(p, "text", "") for p in parts]
    return json.loads("".join(t for t in texts if t))


# ---------- bp_draft_from_server ----------


@respx.mock
def test_draft_from_server_prefers_testing_version(api_ctx, ws):
    """Есть testing — экспортируется именно она (?version=N), не published."""
    from pdm_cli.defmcp.tools.drafts import do_draft_from_server

    _mock_versions(testing={"number": 2}, published={"number": 1})
    route = _mock_export()

    out = do_draft_from_server(api_ctx, slug="testbp")

    assert out["slug"] == "testbp"
    assert out["source"] == {"version": 2, "status": "testing"}
    assert "version=2" in str(route.calls.last.request.url)
    # пакет распакован в workspace, пути — от корня workspace
    assert (ws / "testbp" / "process.yaml").is_file()
    assert "testbp/process.yaml" in out["files"]


@respx.mock
def test_draft_from_server_falls_back_to_published(api_ctx, ws):
    """Нет testing — экспорт действующего (published) без параметра version."""
    from pdm_cli.defmcp.tools.drafts import do_draft_from_server

    _mock_versions(testing=None, published={"number": 1})
    route = _mock_export()

    out = do_draft_from_server(api_ctx, slug="testbp")

    assert out["source"] == {"version": 1, "status": "published"}
    assert "version=" not in str(route.calls.last.request.url)
    assert (ws / "testbp" / "process.yaml").is_file()


@respx.mock
def test_draft_from_server_no_versions_scaffolds(api_ctx, ws):
    """БП без единой версии (рукотворный из админки) — минимальный черновик.

    Раньше это была доменная ошибка «начинай с bp_new_process», но
    bp_new_process на занятый slug тоже отказывает — агент зацикливался
    между двумя вербами. Теперь bp_draft_from_server скаффолдит workspace
    сам (имя БП — с сервера), сохранение создаст testing v1.
    """
    from pdm_cli.defmcp.tools.drafts import do_draft_from_server

    _mock_versions(testing=None, published=None)

    out = do_draft_from_server(api_ctx, slug="testbp")

    assert out["source"] == {"version": None, "status": "scaffold"}
    assert out["compile_ok"] is True
    assert (ws / "testbp" / "process.yaml").is_file()
    assert "Тестовый БП" in (ws / "testbp" / "process.yaml").read_text(
        encoding="utf-8"
    )
    assert "без единой версии" in out["note"]
    assert "bp_draft_save" in out["next"]


@respx.mock
def test_draft_from_server_scaffold_replaces_workspace(api_ctx, ws):
    """Скаффолд по безверсионному БП перезаливает workspace, как экспорт."""
    from pdm_cli.defmcp.tools.drafts import do_draft_from_server

    stale = ws / "testbp" / "tasks" / "99-stale.yaml"
    stale.parent.mkdir(parents=True)
    stale.write_text("name: Мусор\n", encoding="utf-8")

    _mock_versions(testing=None, published=None)

    do_draft_from_server(api_ctx, slug="testbp")
    assert not stale.exists()
    assert (ws / "testbp" / "process.yaml").is_file()


@respx.mock
def test_draft_from_server_unknown_slug_is_domain_error(api_ctx):
    from pdm_cli.defmcp.tools.drafts import do_draft_from_server

    respx.get(f"{API}/api/business-processes/ghost/versions/").respond(
        status_code=404, json={"detail": "not found"}
    )
    with pytest.raises(RuntimeError, match="не найден"):
        do_draft_from_server(api_ctx, slug="ghost")


def test_draft_from_server_offline_is_domain_error(ctx):
    from pdm_cli.defmcp.tools.drafts import do_draft_from_server

    with pytest.raises(RuntimeError, match="PDM API"):
        do_draft_from_server(ctx, slug="testbp")


@respx.mock
def test_draft_from_server_replaces_existing_workspace(api_ctx, ws):
    """Повторный вызов перезаливает workspace свежим экспортом сервера."""
    from pdm_cli.defmcp.tools.drafts import do_draft_from_server

    stale = ws / "testbp" / "tasks" / "99-stale.yaml"
    stale.parent.mkdir(parents=True)
    stale.write_text("name: Мусор\n", encoding="utf-8")

    _mock_versions(testing={"number": 2})
    _mock_export()

    do_draft_from_server(api_ctx, slug="testbp")
    # write_package вычищает tasks/*.yaml, не вошедшие в пакет
    assert not stale.exists()


# ---------- bp_draft_status ----------


@respx.mock
def test_draft_status_reports_versions_and_local_draft(api_ctx, ws_package):
    from pdm_cli.defmcp.tools.drafts import do_draft_status

    diff = {
        "task_diff": [{"name": "Формирование", "change": "modified"}],
        "live_impact": {"running": 0},
        "next_version_number": 6,
        "staged_resources": [],
        "warnings": ["справочник Да/Нет изменён — правка не применится"],
    }
    _mock_versions(
        testing={"number": 5}, published={"number": 4},
    ).respond(json={
        "process": {"id": 1, "slug": "testbp", "name": "Тестовый БП"},
        "versions": [
            {"number": 5, "status": "testing"},
            {"number": 4, "status": "published"},
        ],
        "testing": {"number": 5},
        "published": {"number": 4},
        "diff": diff,
    })

    out = do_draft_status(api_ctx, slug="testbp")

    assert out["slug"] == "testbp"
    assert out["testing"] == {"number": 5}
    assert out["published"] == {"number": 4}
    assert out["diff"] == diff
    # в workspace лежит локальная копия — агент видит, что править есть где
    assert out["local_draft"] is True


@respx.mock
def test_draft_status_no_testing_reports_none(api_ctx, tmp_path, ws):
    from pdm_cli.defmcp.tools.drafts import do_draft_status

    _mock_versions(testing=None, published={"number": 4})
    # workspace пуст — local_draft False
    out = do_draft_status(api_ctx, slug="testbp")
    assert out["testing"] is None
    assert out["local_draft"] is False


def test_draft_status_offline_is_domain_error(ctx):
    from pdm_cli.defmcp.tools.drafts import do_draft_status

    with pytest.raises(RuntimeError, match="PDM API"):
        do_draft_status(ctx, slug="testbp")


# ---------- bp_draft_save ----------

DRAFT_IMPORT_RESPONSE = {
    "status": "created",
    "slug": "testbp",
    "version": 5,
    "version_status": "testing",
    "process_created": False,
    "replaced": {"previous_version": 2, "auto_cancelled_instances": 1},
    "diff": {
        "task_diff": [{"name": "Формирование", "change": "modified"}],
        "live_impact": {"running": 1},
        "next_version_number": 6,
        "staged_resources": [],
        "warnings": [],
    },
    "users_missing": [],
}


def _mock_draft_import(
    response: dict = DRAFT_IMPORT_RESPONSE, status_code: int = 201,
):
    return respx.post(
        f"{API}/api/business-processes/testbp/draft-import/"
    ).respond(json=response, status_code=status_code)


@pytest.fixture()
def ws_package(tmp_path, ws):
    """Зелёный пакет testbp в workspace (как после bp_draft_from_server)."""
    from pdm_cli.bpm_package import write_package

    write_package(tmp_path, make_package(), definitions_root=ws)
    return ws


@respx.mock
def test_draft_save_compiles_and_returns_version_diff_status(api_ctx, ws_package):
    """compile → ZIP → draft-import; ответ: номер версии, diff-сводка, статус."""
    from pdm_cli.defmcp.tools.drafts import do_draft_save

    route = _mock_draft_import()

    out = do_draft_save(api_ctx, slug="testbp")

    assert out["status"] == "created"
    assert out["version"] == 5
    assert out["version_status"] == "testing"
    assert out["diff"] == DRAFT_IMPORT_RESPONSE["diff"]
    assert out["replaced"] == DRAFT_IMPORT_RESPONSE["replaced"]
    assert route.called
    # публикация — только человек: next не предлагает агенту публиковать
    assert "человек" in out["next"] or "админк" in out["next"]


def test_draft_save_offline_is_domain_error(ctx, ws_package):
    from pdm_cli.defmcp.tools.drafts import do_draft_save

    with pytest.raises(RuntimeError, match="PDM API"):
        do_draft_save(ctx, slug="testbp")


@respx.mock
def test_draft_save_refuses_on_red_compile(api_ctx, ws_package):
    """Битый пакет (битая перекрёстная ссылка) не уходит на сервер."""
    from pdm_cli.defmcp.tools.drafts import do_draft_save

    task = ws_package / "testbp" / "tasks" / "01-formirovanie.yaml"
    task.write_text(
        "name: Формирование\nscript_bindings:\n- script_name: ghost\n",
        encoding="utf-8",
    )
    route = _mock_draft_import()

    with pytest.raises(RuntimeError, match="Tier 0"):
        do_draft_save(api_ctx, slug="testbp")
    assert not route.called


@respx.mock
def test_draft_save_missing_package_is_domain_error(api_ctx, ws):
    from pdm_cli.defmcp.tools.drafts import do_draft_save

    with pytest.raises(Exception, match="testbp"):
        do_draft_save(api_ctx, slug="testbp")


@respx.mock
def test_draft_save_422_lists_server_errors(api_ctx, ws_package):
    """422 draft_validation_failed — ошибки сервера доходят до агента."""
    from pdm_cli.defmcp.tools.drafts import do_draft_save

    _mock_draft_import(
        response={
            "error": "draft_validation_failed",
            "errors": [{"kind": "slug_mismatch", "name": "other"}],
        },
        status_code=422,
    )

    with pytest.raises(RuntimeError, match="slug_mismatch"):
        do_draft_save(api_ctx, slug="testbp")


@respx.mock
def test_draft_save_tool_error_is_error_flag(api_ctx, ws_package):
    """Новая верба ADR-0058: доменная ошибка уходит ToolError (isError=true),
    не конвертом status=error."""
    _mock_draft_import(
        response={
            "error": "draft_validation_failed",
            "errors": [{"kind": "slug_mismatch", "name": "other"}],
        },
        status_code=422,
    )
    server = _server(api_ctx)
    with pytest.raises(ToolError, match="slug_mismatch"):
        asyncio.run(server.call_tool("bp_draft_save", {"slug": "testbp"}))

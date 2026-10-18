"""Тесты bp_new_process: scaffold нового БП сразу в package-форме.

Legacy-форма (manifest.yaml из pdm new-bp) сознательно не используется:
живые БП и компилятор живут в package-форме (process.yaml). Спека 143
(W6): scaffold кладётся в workspace черновиков, НЕ в processes/ (Д8);
коллизия slug проверяется и локально, и на сервере.
"""

import pytest

from pdm_cli.defmcp.context import BpContext
from pdm_cli.defmcp.guard import GuardError
from pdm_cli.defmcp.tools.process_new import do_new_process
from pdm_cli.defmcp.tools.validate import do_compile


@pytest.fixture()
def ctx(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    return BpContext(repo_root=tmp_path, drafts_root=ws)


def test_new_process_scaffolds_package_form_and_compiles(ctx):
    out = do_new_process(
        ctx, slug="demo", title="Демо БП",
        tasks=["Подача заявки", "Согласование"],
    )
    assert out["slug"] == "demo"
    assert (ctx.drafts_root / "demo" / "process.yaml").is_file()
    tasks = sorted(
        p.name for p in (ctx.drafts_root / "demo" / "tasks").glob("*.yaml")
    )
    assert len(tasks) == 2
    # в git-дереве processes/ ничего не появляется (Д8: git не участвует)
    assert not (ctx.repo_root / "processes" / "demo").exists()
    # scaffold обязан быть зелёным в Tier 0 сразу
    report = do_compile(ctx, slug="demo")
    assert report["ok"] is True, report


def test_new_process_default_single_task(ctx):
    out = do_new_process(ctx, slug="solo", title="Одиночный")
    assert out["tasks"] == ["Первая задача"]
    assert do_compile(ctx, slug="solo")["ok"] is True


def test_new_process_refuses_existing_slug_dir(ctx):
    do_new_process(ctx, slug="demo", title="Демо")
    with pytest.raises(FileExistsError):
        do_new_process(ctx, slug="demo", title="Демо ещё раз")


def test_new_process_refuses_slug_existing_on_server(ctx):
    import respx
    from pdm_cli.api_client import PdmApiClient

    ctx.api = PdmApiClient(base_url="http://pdm.local", api_key="t")
    with respx.mock:
        respx.get("http://pdm.local/api/business-processes/").respond(
            json=[{"id": 5, "slug": "taken"}]
        )
        with pytest.raises(FileExistsError, match="сервер"):
            do_new_process(ctx, slug="taken", title="Занято")


def test_new_process_rejects_bad_slug(ctx):
    with pytest.raises(GuardError):
        do_new_process(ctx, slug="Плохой Slug", title="x")
    with pytest.raises(GuardError):
        do_new_process(ctx, slug="../escape", title="x")


def test_new_process_rejects_empty_task_names(ctx):
    with pytest.raises(ValueError):
        do_new_process(ctx, slug="demo", title="Демо", tasks=["  "])

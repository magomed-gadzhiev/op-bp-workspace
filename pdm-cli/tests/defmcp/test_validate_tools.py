"""Тесты bp_compile: Tier 0 из чата (спека 143, W6: workspace, не processes/)."""

import pytest

from ..test_bpm_package import make_package
from pdm_cli.bpm_package import write_package
from pdm_cli.defmcp.context import BpContext
from pdm_cli.defmcp.tools.validate import do_compile


@pytest.fixture()
def ctx(tmp_path):
    ws = tmp_path / "ws"
    write_package(tmp_path, make_package(), definitions_root=ws)
    return BpContext(repo_root=tmp_path, drafts_root=ws)


def test_compile_green_package(ctx):
    out = do_compile(ctx)
    assert out["ok"] is True
    res = out["results"]["testbp"]
    assert res["ok"] is True
    assert res["errors"] == []
    assert res["stats"]["tasks"] == 2


def test_compile_reads_workspace_not_processes(ctx):
    """Пакеты processes/ (git) в compile не видны — только workspace."""
    git_pkg = make_package()
    git_pkg.business_process.slug = "gitbp"
    write_package(ctx.repo_root, git_pkg)  # → processes/gitbp/
    out = do_compile(ctx)
    assert "gitbp" not in out["results"]


def test_compile_reports_broken_crossref_per_file(ctx):
    task_file = (
        ctx.drafts_root / "testbp" / "tasks" / "01-formirovanie.yaml"
    )
    task_file.write_text(
        "name: Формирование\nscript_bindings:\n- script_name: ghost\n",
        encoding="utf-8",
    )
    out = do_compile(ctx)
    assert out["ok"] is False
    assert any("ghost" in e for e in out["results"]["testbp"]["errors"])


def test_compile_scoped_to_slug(ctx):
    out = do_compile(ctx, slug="testbp")
    assert list(out["results"]) == ["testbp"]


def test_compile_unknown_slug_is_error(ctx):
    with pytest.raises(LookupError):
        do_compile(ctx, slug="ghost")


def test_compile_empty_workspace_is_error(tmp_path):
    ctx = BpContext(repo_root=tmp_path, drafts_root=tmp_path / "ws")
    with pytest.raises(Exception, match="workspace"):
        do_compile(ctx)

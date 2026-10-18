"""Тесты файловых инструментов defmcp: path-guard, list, read, edit.

Шов A (согласован в спеке 070): функции do_* вызываются напрямую,
без FastMCP-транспорта; API-клиент подменяется через respx в draft-тестах.

Спека 143 (W6): пути — от workspace черновиков (MCP_BP_DRAFTS_ROOT),
НЕ от processes/: git-цикла у агента больше нет (Д8).
"""

import pytest

from pdm_cli.defmcp.context import BpContext, workspace_root
from pdm_cli.defmcp.guard import GuardError, resolve_under_root
from pdm_cli.defmcp.tools.files import do_edit_file, do_list_files, do_read_file


@pytest.fixture()
def ctx(tmp_path):
    ws = tmp_path / "ws"
    bp = ws / "testbp"
    (bp / "tasks").mkdir(parents=True)
    (bp / "process.yaml").write_text("slug: testbp\n", encoding="utf-8")
    (bp / "tasks" / "01-a.yaml").write_text("name: A\n", encoding="utf-8")
    return BpContext(repo_root=tmp_path, drafts_root=ws)


# ---------- workspace (спека 143, W6) ----------

def test_workspace_root_defaults_to_pdm_drafts(tmp_path):
    """Без явного drafts_root — <repo>/.pdm/drafts (env MCP_BP_DRAFTS_ROOT
    читается в build_context; локальный stdio-режим)."""
    assert workspace_root(BpContext(repo_root=tmp_path)) == (
        tmp_path / ".pdm" / "drafts"
    )


def test_workspace_root_honors_explicit_drafts_root(tmp_path):
    ws = tmp_path / "ws"
    assert workspace_root(BpContext(repo_root=tmp_path, drafts_root=ws)) == ws


# ---------- guard ----------

def test_guard_resolves_relative_path(tmp_path):
    p = resolve_under_root(tmp_path / "processes", "testbp/process.yaml")
    assert p == (tmp_path / "processes" / "testbp" / "process.yaml").resolve()


def test_guard_rejects_parent_escape(tmp_path):
    with pytest.raises(GuardError):
        resolve_under_root(tmp_path / "processes", "../secrets.yaml")


def test_guard_rejects_inner_parent_escape(tmp_path):
    with pytest.raises(GuardError):
        resolve_under_root(tmp_path / "processes", "testbp/../../secrets.yaml")


def test_guard_rejects_absolute(tmp_path):
    with pytest.raises(GuardError):
        resolve_under_root(tmp_path / "processes", "/etc/passwd")


def test_guard_rejects_empty_and_dotdot_names(tmp_path):
    with pytest.raises(GuardError):
        resolve_under_root(tmp_path / "processes", "")
    with pytest.raises(GuardError):
        resolve_under_root(tmp_path / "processes", "..")


def test_guard_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    processes = tmp_path / "processes"
    processes.mkdir()
    (processes / "link.yaml").symlink_to(outside)
    with pytest.raises(GuardError):
        resolve_under_root(processes, "link.yaml")


def test_guard_rejects_backslash_traversal(tmp_path):
    with pytest.raises(GuardError):
        resolve_under_root(tmp_path / "processes", "..\\secrets.yaml")


# ---------- bp_list_files ----------

def test_list_files_returns_relative_yaml(ctx):
    out = do_list_files(ctx)
    assert out["count"] == 2
    assert "testbp/process.yaml" in out["files"]
    assert "testbp/tasks/01-a.yaml" in out["files"]


def test_list_files_reads_workspace_not_processes(ctx):
    """Спека 143 (W6): источник — workspace черновиков; processes/ (git)
    агенту больше не виден."""
    git_bp = ctx.repo_root / "processes" / "gitbp"
    git_bp.mkdir(parents=True)
    (git_bp / "process.yaml").write_text("slug: gitbp\n", encoding="utf-8")
    out = do_list_files(ctx)
    assert "gitbp/process.yaml" not in out["files"]
    assert not any(f.startswith("gitbp") for f in out["files"])


def test_list_files_scoped_to_slug(ctx):
    other = ctx.drafts_root / "other"
    other.mkdir()
    (other / "process.yaml").write_text("slug: other\n", encoding="utf-8")
    out = do_list_files(ctx, slug="other")
    assert out["files"] == ["other/process.yaml"]


def test_list_files_unknown_slug_is_error(ctx):
    with pytest.raises(LookupError):
        do_list_files(ctx, slug="ghost")


# ---------- bp_read_file ----------

def test_read_file_returns_content(ctx):
    out = do_read_file(ctx, "testbp/process.yaml")
    assert out["content"] == "slug: testbp\n"
    assert out["path"] == "testbp/process.yaml"


def test_read_file_rejects_path_outside_workspace(ctx):
    (ctx.repo_root / "secret.txt").write_text("top", encoding="utf-8")
    with pytest.raises(GuardError):
        do_read_file(ctx, "../secret.txt")


def test_read_file_missing_is_error(ctx):
    with pytest.raises(FileNotFoundError):
        do_read_file(ctx, "testbp/nope.yaml")


# ---------- bp_edit_file ----------

def test_edit_file_writes_valid_yaml(ctx):
    out = do_edit_file(
        ctx, "testbp/tasks/01-a.yaml", "name: B\norder: 1\n"
    )
    assert out["written"] == "testbp/tasks/01-a.yaml"
    assert (
        ctx.drafts_root / "testbp" / "tasks" / "01-a.yaml"
    ).read_text(encoding="utf-8") == "name: B\norder: 1\n"


def test_edit_file_rejects_broken_yaml_without_write(ctx):
    before = (
        ctx.drafts_root / "testbp" / "tasks" / "01-a.yaml"
    ).read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        do_edit_file(ctx, "testbp/tasks/01-a.yaml", "name: [unclosed\n")
    after = (
        ctx.drafts_root / "testbp" / "tasks" / "01-a.yaml"
    ).read_text(encoding="utf-8")
    assert after == before


def test_edit_file_python_skips_yaml_validation(ctx):
    scripts = ctx.drafts_root / "testbp" / "scripts"
    scripts.mkdir()
    out = do_edit_file(ctx, "testbp/scripts/x.py", "x = 1\n")
    assert out["written"] == "testbp/scripts/x.py"


def test_edit_file_expected_current_conflict(ctx):
    with pytest.raises(PermissionError):
        do_edit_file(
            ctx, "testbp/tasks/01-a.yaml",
            "name: B\n", expected_current="name: STALE\n",
        )


def test_edit_file_missing_parent_is_error(ctx):
    with pytest.raises(LookupError):
        do_edit_file(ctx, "testbp/nope/dir.yaml", "a: 1\n")

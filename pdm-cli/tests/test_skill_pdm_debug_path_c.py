"""Etap 7 Phase 5 — pdm-debug-failed-run skill mentions Path C and all 6 tools."""
from pathlib import Path


def _find_skill_md() -> Path:
    # Walk from this file up to repo root, then probe known skill paths.
    here = Path(__file__).resolve()
    candidates_rel = [
        # Template skill bundled with pdm-cli (canonical source).
        # Two layouts depending on whether tests run inside pdm-cli-dev
        # (cwd=/work, package mounted as project root) or from repo root.
        Path("src/pdm_cli/templates/skills/pdm/pdm-debug-failed-run.md"),
        Path("tools/pdm-cli/src/pdm_cli/templates/skills/pdm/pdm-debug-failed-run.md"),
        # After `pdm bootstrap` copies skills into a client project.
        Path(".claude/skills/pdm/pdm-debug-failed-run.md"),
        Path(".claude/skills/pdm-debug-failed-run/SKILL.md"),
        Path(".claude/agents/pdm-debug-failed-run.md"),
    ]
    cur = here
    while cur.parent != cur:
        for rel in candidates_rel:
            cand = cur / rel
            if cand.exists():
                return cand
        cur = cur.parent
    raise FileNotFoundError("Could not locate pdm-debug-failed-run skill markdown")


def test_skill_mentions_path_c():
    text = _find_skill_md().read_text(encoding="utf-8")
    assert "Path C" in text
    for t in (
        "sandbox.run_test", "sandbox.run_step", "sandbox.inspect_state",
        "sandbox.list_egress", "sandbox.add_fixture",
        "sandbox.replay_with_override",
    ):
        assert t in text, f"missing tool reference: {t}"

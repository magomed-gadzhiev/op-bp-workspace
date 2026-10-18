"""Tests that bootstrap copies packaged PDM skills into the repo."""
from pathlib import Path

import respx
from click.testing import CliRunner

from pdm_cli.cli import main


PROD = "https://prod.local"
SB = "https://sandbox.local"


@respx.mock
def test_bootstrap_writes_skills_directory(tmp_path: Path):
    respx.get(f"{PROD}/api/business-processes/").respond(
        json=[]
    )
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    skill = tmp_path / ".claude" / "skills" / "pdm" / "pdm-record-fixture.md"
    assert skill.is_file(), f"Skill file not found at {skill}"
    assert "name: pdm-record-fixture" in skill.read_text(encoding="utf-8")


@respx.mock
def test_bootstrap_writes_debug_ssh_skill(tmp_path: Path):
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    skill = tmp_path / ".claude" / "skills" / "pdm" / "pdm-debug-ssh.md"
    assert skill.is_file(), f"Skill file not found at {skill}"
    assert "name: pdm-debug-ssh" in skill.read_text(encoding="utf-8")


@respx.mock
def test_bootstrap_does_not_ship_edit_workflow_skill(tmp_path: Path):
    """n8n removed — pdm-edit-workflow.md no longer ships via bootstrap."""
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    skill = tmp_path / ".claude" / "skills" / "pdm" / "pdm-edit-workflow.md"
    assert not skill.exists()
    # Remaining skills still ship.
    assert (tmp_path / ".claude" / "skills" / "pdm" / "pdm-edit-process.md").is_file()


@respx.mock
def test_bootstrap_ships_etap10_feedback_skills(tmp_path: Path):
    """Etap 10 feedback skills are copied into fresh client-project repos."""
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    skill_dir = tmp_path / ".claude" / "skills" / "pdm"
    triage = skill_dir / "pdm-triage-feedback.md"
    weekly = skill_dir / "pdm-weekly-review.md"
    assert triage.is_file(), f"Skill file not found at {triage}"
    assert weekly.is_file(), f"Skill file not found at {weekly}"

    triage_text = triage.read_text(encoding="utf-8")
    weekly_text = weekly.read_text(encoding="utf-8")
    assert "name: pdm-triage-feedback" in triage_text
    assert "name: pdm-weekly-review" in weekly_text
    assert "processes/<bp>/decisions/YYYY-MM-DD-<topic>.md" in triage_text
    assert "feedback/telemetry/YYYY-Www-<bp>.md" in weekly_text


@respx.mock
def test_bootstrap_ships_canonical_decision_format(tmp_path: Path):
    """Etap 10 F3: decision-format.md ships and defines the canonical schema."""
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    skill_dir = tmp_path / ".claude" / "skills" / "pdm"
    fmt = skill_dir / "decision-format.md"
    assert fmt.is_file(), f"Canonical decision format not found at {fmt}"
    fmt_text = fmt.read_text(encoding="utf-8")

    assert "name: pdm:decision-format" in fmt_text
    assert "processes/<bp>/decisions/YYYY-MM-DD-<topic>.md" in fmt_text
    # Canonical status vocabulary from the original design doc.
    assert "asked | decided | superseded" in fmt_text
    for key in ("date:", "topic:", "bp_slug:", "status:", "source:",
                "asked_by:", "decided_by:", "supersedes:", "superseded_by:"):
        assert key in fmt_text, f"Canonical front matter missing {key!r}"


@respx.mock
def test_feedback_skills_converge_on_canonical_decision_format(tmp_path: Path):
    """triage-feedback / weekly-review point to the canonical format and drop
    the legacy proposed/Resolution schema."""
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    skill_dir = tmp_path / ".claude" / "skills" / "pdm"
    for name in ("pdm-triage-feedback.md", "pdm-weekly-review.md"):
        text = (skill_dir / name).read_text(encoding="utf-8")
        assert "pdm:decision-format" in text, f"{name} must reference canon"
        # Canonical schema is what the skill instructs you to write.
        assert "status: asked" in text, f"{name} must use canonical status"
        assert "asked_by: claude-code" in text, f"{name} missing asked_by"
        # Legacy-only schema markers must be gone (a one-line migration
        # note that mentions `status: proposed` is allowed and expected).
        assert "owners:\n  - product" not in text, f"{name} keeps legacy owners"
        assert "id: YYYY-MM-DD-<topic>" not in text, f"{name} keeps legacy id"


@respx.mock
def test_bootstrap_skill_content_has_pii_section(tmp_path: Path):
    """Skill must contain PII-review guidance."""
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    content = (tmp_path / ".claude" / "skills" / "pdm" / "pdm-record-fixture.md").read_text(
        encoding="utf-8"
    )
    assert "PII" in content
    assert "Postconditions" in content


@respx.mock
def test_bootstrap_skill_directory_created_with_processes(tmp_path: Path):
    """Skills are copied even when BPs are present."""
    respx.get(f"{PROD}/api/business-processes/").respond(
        json=[{"slug": "payroll", "name": "Payroll"}]
    )
    respx.get(f"{PROD}/api/business-processes/payroll/full/").respond(json={
        "manifest": {"slug": "payroll", "name": "Payroll", "description": "",
                     "version": 1, "status": "published", "owner": None},
        "entities": [], "tasks": [],
    })
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    skill = tmp_path / ".claude" / "skills" / "pdm" / "pdm-record-fixture.md"
    assert skill.is_file()
    assert "name: pdm-record-fixture" in skill.read_text(encoding="utf-8")


@respx.mock
def test_bootstrap_ships_activation_map(tmp_path: Path):
    """E19: ACTIVATION.md ships via the unchanged .md-only installer loop (FR-011/FR-013)."""
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "k",
        "--sandbox-url", SB, "--api-key-sandbox", "s",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    activation = tmp_path / ".claude" / "skills" / "pdm" / "ACTIVATION.md"
    assert activation.is_file(), f"Activation map not found at {activation}"
    text = activation.read_text(encoding="utf-8")
    assert "```yaml" in text, "ACTIVATION.md must carry a fenced yaml block"
    assert "skills:" in text

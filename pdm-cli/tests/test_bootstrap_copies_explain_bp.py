"""Bootstrap copies pdm-explain-bp skill into .claude/skills/pdm/."""

import importlib.resources as res


def test_explain_bp_template_packaged():
    """The skill template ships inside the pdm_cli wheel."""
    files = res.files("pdm_cli.templates.skills.pdm")
    names = {f.name for f in files.iterdir()}
    assert "pdm-explain-bp.md" in names
    assert "pdm-triage-feedback.md" in names
    assert "pdm-weekly-review.md" in names


def test_explain_bp_frontmatter_well_formed():
    text = res.files("pdm_cli.templates.skills.pdm").joinpath("pdm-explain-bp.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), "skill must begin with YAML frontmatter"
    end = text.find("\n---\n", 4)
    assert end > 0
    fm = text[4:end]
    assert "name: pdm-explain-bp" in fm
    assert "description:" in fm


def test_etap10_skill_frontmatter_well_formed():
    """Etap 10 feedback skills ship with usable frontmatter and task names."""
    files = res.files("pdm_cli.templates.skills.pdm")
    expected = {
        "pdm-triage-feedback.md": "pdm-triage-feedback",
        "pdm-weekly-review.md": "pdm-weekly-review",
    }
    for filename, skill_name in expected.items():
        text = files.joinpath(filename).read_text(encoding="utf-8")
        assert text.startswith("---\n"), f"{filename} must begin with YAML frontmatter"
        end = text.find("\n---\n", 4)
        assert end > 0
        fm = text[4:end]
        assert f"name: {skill_name}" in fm
        assert "description:" in fm
        assert "decisions/YYYY-MM-DD-<topic>.md" in text

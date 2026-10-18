"""E19 — integration test: the real ACTIVATION.md is consistent with the real
skill set (US3 AS3, SC-005).

Reads the canonical ``src/pdm_cli/templates/skills/pdm/ACTIVATION.md``, parses
its first fenced ``yaml`` block, globs the real ``pdm-*.md`` stems, and asserts
the parity guard returns zero violations. On failure it prints an
``E19 activation guard:`` block (style consistent with the E17 baseline guard).
"""

from pathlib import Path

import io

from ruamel.yaml import YAML

from tests.activation_guard import evaluate_activation_map


def _skills_dir() -> Path:
    # tests/ -> tools/pdm-cli/ -> src/pdm_cli/templates/skills/pdm
    return (
        Path(__file__).resolve().parents[1]
        / "src" / "pdm_cli" / "templates" / "skills" / "pdm"
    )


def _first_yaml_block(text: str) -> str:
    """Return the content of the first fenced ```yaml block."""
    marker = "```yaml"
    start = text.find(marker)
    assert start != -1, "ACTIVATION.md must contain a fenced ```yaml block"
    body_start = text.index("\n", start) + 1
    end = text.find("```", body_start)
    assert end != -1, "unterminated ```yaml block in ACTIVATION.md"
    return text[body_start:end]


def test_real_activation_map_is_consistent():
    skills_dir = _skills_dir()
    activation = skills_dir / "ACTIVATION.md"
    assert activation.is_file(), f"ACTIVATION.md not found at {activation}"

    block = _first_yaml_block(activation.read_text(encoding="utf-8"))
    map_data = YAML(typ="safe").load(io.StringIO(block))

    skill_ids = {p.stem for p in skills_dir.glob("pdm-*.md")}
    assert skill_ids, "expected to glob at least one pdm-*.md skill"

    violations = evaluate_activation_map(skill_ids, map_data)
    if violations:
        report = "\n".join(f"  {v}" for v in violations)
        raise AssertionError(
            "E19 activation guard: violations detected\n" + report
        )

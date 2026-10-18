"""E19 skill-activation parity guard — pure decision logic (no pytest imports).

Mirrors :mod:`tests.baseline_guard` (E17): a dependency-free decision function
that the integration test (:mod:`tests.test_activation_map`) feeds with the real
skill stems and the parsed ``ACTIVATION.md`` YAML block, and that the unit tests
(:mod:`tests.test_activation_guard`) exercise with synthetic inputs.

It enforces one-to-one parity between ``pdm-*.md`` skill files and the activation
map entries, plus the per-skill invariants (3–5 prompts, ≥1 ``ru`` and ≥1 ``en``).
See specs/040-skill-liveness/contracts/parity-guard.contract.md and docs/TESTING.md.
"""

from __future__ import annotations

_VALID_LANGS = ("ru", "en")
_MIN_PROMPTS = 3
_MAX_PROMPTS = 5


def evaluate_activation_map(
    skill_ids: set[str],
    map_data: dict,
) -> list[str]:
    """Return a list of human-readable activation-map violations (empty == OK).

    Args:
        skill_ids: file stems from globbing ``pdm-*.md`` in the skills dir.
        map_data: the already-parsed YAML block,
            ``{"skills": {<id>: {"prompts": [{"lang", "text"}, ...]}}}``.

    Output is deterministic: sorted by id, then by rule (1..5). Each message
    names the specific offending element (FR-010).
    """
    skills = map_data.get("skills") if isinstance(map_data, dict) else None
    if not isinstance(skills, dict):
        skills = {}

    violations: list[str] = []
    for skill_id in sorted(set(skill_ids) | set(skills)):
        in_skills = skill_id in skill_ids
        in_map = skill_id in skills

        # Rule 1 — orphan skill (file present, no map entry).
        if in_skills and not in_map:
            violations.append(
                f"ORPHAN SKILL: '{skill_id}' has a skill file but no entry in "
                f"ACTIVATION.md — add 3–5 prompts."
            )
            continue

        # Rule 2 — orphan map entry (map id with no skill file).
        if in_map and not in_skills:
            violations.append(
                f"ORPHAN MAP ENTRY: '{skill_id}' is in ACTIVATION.md but no "
                f"skills/pdm/{skill_id}.md exists — remove it or rename the skill."
            )
            continue

        # Present in both → validate the per-skill invariants.
        entry = skills.get(skill_id) or {}
        prompts = entry.get("prompts") if isinstance(entry, dict) else None
        if not isinstance(prompts, list):
            prompts = []

        # Rule 3 — prompt count.
        if not _MIN_PROMPTS <= len(prompts) <= _MAX_PROMPTS:
            violations.append(
                f"PROMPT COUNT: skill '{skill_id}' has {len(prompts)} prompts, "
                f"expected 3–5."
            )

        # Rule 5 — bad prompt (empty text / invalid lang). Also drives which
        # prompts count toward the language coverage check (rule 4).
        seen_langs: set[str] = set()
        for k, prompt in enumerate(prompts, start=1):
            lang = prompt.get("lang") if isinstance(prompt, dict) else None
            text = prompt.get("text") if isinstance(prompt, dict) else None
            text_ok = isinstance(text, str) and text.strip() != ""
            lang_ok = lang in _VALID_LANGS
            if not text_ok:
                violations.append(
                    f"BAD PROMPT: skill '{skill_id}' prompt #{k} has empty text."
                )
            if not lang_ok:
                violations.append(
                    f"BAD PROMPT: skill '{skill_id}' prompt #{k} has invalid "
                    f"lang '{lang}'."
                )
            if lang_ok:
                seen_langs.add(lang)

        # Rule 4 — missing language (only valid-lang prompts count).
        for lang in _VALID_LANGS:
            if lang not in seen_langs:
                violations.append(
                    f"MISSING LANG: skill '{skill_id}' has no {lang} prompt — "
                    f"every skill needs both ru and en."
                )

    return violations

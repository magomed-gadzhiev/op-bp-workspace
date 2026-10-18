"""E19 — unit tests for the pure activation-guard decision logic (US3).

Spec: specs/040-skill-liveness/ (FR-009/FR-009a/FR-010);
contract matrix: contracts/parity-guard.contract.md.
"""

from tests.activation_guard import evaluate_activation_map


def _prompts(*pairs):
    return {"prompts": [{"lang": lang, "text": text} for lang, text in pairs]}


def test_clean_no_violations():
    skill_ids = {"pdm-create-process"}
    data = {
        "skills": {
            "pdm-create-process": _prompts(
                ("ru", "создай новый BP"),
                ("ru", "заведи процесс с нуля"),
                ("en", "create a new business process"),
            )
        }
    }
    assert evaluate_activation_map(skill_ids, data) == []


def test_orphan_skill_flagged():
    skill_ids = {"pdm-create-process", "pdm-orphan"}
    data = {
        "skills": {
            "pdm-create-process": _prompts(
                ("ru", "a"), ("en", "b"), ("ru", "c")
            )
        }
    }
    out = evaluate_activation_map(skill_ids, data)
    assert len(out) == 1
    assert out[0].startswith("ORPHAN SKILL: 'pdm-orphan'")


def test_orphan_map_entry_flagged():
    skill_ids = {"pdm-create-process"}
    data = {
        "skills": {
            "pdm-create-process": _prompts(("ru", "a"), ("en", "b"), ("ru", "c")),
            "pdm-ghost": _prompts(("ru", "a"), ("en", "b"), ("ru", "c")),
        }
    }
    out = evaluate_activation_map(skill_ids, data)
    assert len(out) == 1
    assert out[0].startswith("ORPHAN MAP ENTRY: 'pdm-ghost'")


def test_too_few_prompts():
    skill_ids = {"pdm-x"}
    data = {"skills": {"pdm-x": _prompts(("ru", "a"), ("en", "b"))}}
    out = evaluate_activation_map(skill_ids, data)
    assert len(out) == 1
    assert "PROMPT COUNT: skill 'pdm-x' has 2 prompts" in out[0]


def test_too_many_prompts():
    skill_ids = {"pdm-x"}
    data = {
        "skills": {
            "pdm-x": _prompts(
                ("ru", "a"), ("ru", "b"), ("ru", "c"),
                ("en", "d"), ("en", "e"), ("en", "f"),
            )
        }
    }
    out = evaluate_activation_map(skill_ids, data)
    assert len(out) == 1
    assert "has 6 prompts" in out[0]


def test_missing_en():
    skill_ids = {"pdm-x"}
    data = {"skills": {"pdm-x": _prompts(("ru", "a"), ("ru", "b"), ("ru", "c"))}}
    out = evaluate_activation_map(skill_ids, data)
    assert len(out) == 1
    assert out[0] == (
        "MISSING LANG: skill 'pdm-x' has no en prompt — "
        "every skill needs both ru and en."
    )


def test_bad_lang_and_empty_text():
    skill_ids = {"pdm-x"}
    data = {
        "skills": {
            "pdm-x": {
                "prompts": [
                    {"lang": "ru", "text": "ok"},
                    {"lang": "en", "text": "ok"},
                    {"lang": "de", "text": "x"},
                    {"lang": "ru", "text": ""},
                ]
            }
        }
    }
    out = evaluate_activation_map(skill_ids, data)
    # rule 5 fires twice (invalid lang #3, empty text #4); ru+en present so no
    # rule 4, count 4 so no rule 3.
    assert any("invalid lang 'de'" in v and "#3" in v for v in out)
    assert any("empty text" in v and "#4" in v for v in out)
    assert all(v.startswith("BAD PROMPT") for v in out)
    assert len(out) == 2


def test_combine_orphan_and_bad_count():
    skill_ids = {"pdm-foo", "pdm-bar"}
    data = {"skills": {"pdm-bar": _prompts(("ru", "a"), ("en", "b"))}}
    out = evaluate_activation_map(skill_ids, data)
    # sorted by id: pdm-bar (count) before pdm-foo (orphan).
    assert len(out) == 2
    assert out[0].startswith("PROMPT COUNT: skill 'pdm-bar' has 2 prompts")
    assert out[1].startswith("ORPHAN SKILL: 'pdm-foo'")


def test_empty_map_flags_all_skills_as_orphans():
    skill_ids = {"pdm-a", "pdm-b"}
    out = evaluate_activation_map(skill_ids, {})
    assert len(out) == 2
    assert all(v.startswith("ORPHAN SKILL") for v in out)

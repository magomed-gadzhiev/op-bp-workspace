---
name: pdm-triage-feedback
description: Use when reviewing PDM feedback tickets from feedback/tickets/*.md and turning them into scoped code, workflow, fixture or decision work. Применять, когда нужно разобрать тикеты обратной связи. Triggers / триггеры — "triage the feedback tickets", "process the feedback inbox", «разбери фидбек-тикеты», «обработай входящие замечания».
---

# pdm-triage-feedback

## Goal

Turn feedback tickets from `feedback/tickets/*.md` into a small, auditable work plan:
fixes when the ticket is actionable, regression coverage when behavior changes,
and decision files when product judgment is required.

## Inputs

- `feedback/tickets/*.md`
- `processes/<bp>/manifest.yaml`
- `processes/<bp>/tests/`
- `processes/<bp>/fixtures/`
- `processes/<bp>/workflows/`
- `processes/<bp>/decisions/`

## Steps

1. Read new or open feedback tickets. Group them by business process slug,
   severity, affected component, and suspected owner area:
   `code`, `workflow`, `fixture`, `data`, `docs`, or `decision`.
2. For each ticket, extract evidence: run id, step id, screenshot reference,
   expected behavior, actual behavior, and any linked telemetry.
3. Check whether the issue is reproducible in sandbox. Prefer existing
   `pdm test --bp <slug>` cases, replay fixtures, and `pdm logs <run_id>`.
4. If the ticket is actionable, make the smallest safe change and add or update
   a regression test, fixture, or workflow assertion.
5. If the ticket cannot be decided safely, create or update a decision file
   `processes/<bp>/decisions/YYYY-MM-DD-<topic>.md` using the canonical format
   (see `pdm:decision-format` / `.claude/skills/pdm/decision-format.md`).
   First check existing `decisions/*.md` — the answer may already be `decided`.
6. Summarize what changed, what evidence supports it, and what remains blocked.

## Decision File Format

Decision files use one canonical format defined in `pdm:decision-format`
(`.claude/skills/pdm/decision-format.md`). Do not invent a per-skill schema.

When a feedback ticket needs product judgment, create
`processes/<bp>/decisions/YYYY-MM-DD-<topic>.md` with:

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>
bp_slug: <business-process-slug>
status: asked            # asked | decided | superseded
source: feedback
asked_by: claude-code
decided_by:
decided_at:
ticket_ids:
  - <ticket-id-or-filename>
telemetry_snapshots: []
supersedes:
superseded_by:
---
```

Sections (canonical order): `## Вопрос`, `## Контекст`, `## Варианты`
(optional), `## Решение` (`—` until decided), `## Реализовано в`
(`commit <sha>, тест <path>`). See `pdm:decision-format` for the full
spec and the status lifecycle. Bring any legacy `status: proposed` /
`Resolution:` files to this format when you touch them.

## Guardrails

- Do not infer product policy from a single ambiguous ticket.
- Do not commit screenshots, logs, or payloads containing secrets or PII.
- Do not rewrite unrelated fixtures or workflows while triaging one ticket.
- Mark blocking issues explicitly when they prevent PR readiness.

## Output

- Grouped ticket summary.
- Applied changes or decision files.
- Regression command run, with pass/fail result.
- Remaining blockers and non-blocking follow-ups.

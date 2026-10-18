---
name: pdm-weekly-review
description: Use when performing a weekly PDM production review from feedback tickets and telemetry snapshots under feedback/telemetry/. Применять, когда нужно сделать еженедельный обзор продакшена. Triggers / триггеры — "do the weekly review", "weekly production review from telemetry", «сделай еженедельный обзор», «недельный разбор по телеметрии».
---

# pdm-weekly-review

## Goal

Review the previous production week and produce prioritized actions based on
telemetry snapshots, recurring failures, slow steps, orphan egress, assignment
breakdowns, and user feedback.

## Inputs

- `feedback/telemetry/YYYY-Www-<bp>.md`
- `feedback/tickets/*.md`
- `processes/<bp>/tests/`
- `processes/<bp>/fixtures/`
- `processes/<bp>/workflows/`
- `processes/<bp>/decisions/`

## Snapshot Expectations

Each telemetry snapshot should identify:

- Source window and generated timestamp.
- Business process slug.
- Counts and status breakdown.
- Duration percentiles.
- Top failing steps.
- Orphan egress hosts.
- Egress volume per run.
- Assignment status breakdown.

If snapshots are missing, use the MCP/API aggregate tools if available and
record that the markdown snapshot was absent.

## Steps

1. Collect snapshots for the target ISO week and group them by business process.
2. Read open feedback tickets from the same week and link them to matching
   business processes, runs, steps, screenshots, or egress hosts.
3. Rank evidence by user impact, recurrence, production risk, and reversibility.
4. For each high-priority item, choose one outcome:
   code fix, workflow update, fixture/test update, docs/runbook update,
   decision file, or no action with rationale.
5. Create or update regression coverage for actionable behavior changes.
6. Create or update a decision file when product judgment is required:
   `processes/<bp>/decisions/YYYY-MM-DD-<topic>.md`, using the canonical
   format (`pdm:decision-format` / `.claude/skills/pdm/decision-format.md`).
   Check existing `decisions/*.md` first — the answer may already be `decided`.
7. Produce a weekly summary with blocking risks, non-blocking follow-ups,
   verification commands, and links to evidence.

## Decision File Format

Decision files use one canonical format defined in `pdm:decision-format`
(`.claude/skills/pdm/decision-format.md`). Do not invent a per-skill schema.

For unresolved product calls, create
`processes/<bp>/decisions/YYYY-MM-DD-<topic>.md` with:

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>
bp_slug: <business-process-slug>
status: asked            # asked | decided | superseded
source: weekly-review
asked_by: claude-code
decided_by:
decided_at:
ticket_ids: []
telemetry_snapshots:
  - feedback/telemetry/YYYY-Www-<bp>.md
supersedes:
superseded_by:
---
```

Sections (canonical order): `## Вопрос`, `## Контекст`, `## Варианты`
(optional), `## Решение` (`—` until decided), `## Реализовано в`. See
`pdm:decision-format` for the full spec and the `asked → decided →
superseded` lifecycle. Bring any legacy `status: proposed` / `Resolution:`
files to this format when you touch them.

## Output

- Weekly review summary.
- Prioritized actions with evidence links.
- Regression commands run, with pass/fail result.
- Decision files for unresolved product calls.
- PR-readiness risks marked as blocking or non-blocking.

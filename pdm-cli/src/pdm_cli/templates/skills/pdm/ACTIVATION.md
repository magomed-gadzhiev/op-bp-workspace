---
name: pdm-activation-map
description: Activation map for the pdm-* skills — representative ru/en prompts that should select exactly one skill. Reference artifact; not a skill itself.
---

# PDM skill activation map

This file is the **activation map** for the `pdm-*` AI-agent skills. For every skill it
lists 3–5 representative user formulations (prompts) — at least one Russian and one English —
that should unambiguously select **that** skill and no other. It is two things at once:

- a **human review oracle** — read a skill's prompts top-to-bottom and confirm each one
  obviously belongs to it and not to a close neighbour;
- a **machine-readable contract** — the fenced `yaml` block below is parsed by the
  activation parity guard (`tools/pdm-cli/tests/test_activation_map.py`), which enforces
  one-to-one parity with the `pdm-*.md` skill files plus per-skill invariants (3–5 prompts,
  ≥1 `ru` and ≥1 `en`).

The guard parses **only the first fenced `yaml` block**. Keys MUST equal the skill file
stems (hyphen form, e.g. `pdm-debug-ssh`). `decision-format.md` is intentionally absent —
it is not a `pdm-*` skill and is excluded by the guard's `pdm-*.md` glob.

Three close pairs are deliberately disambiguated — their prompt sets are disjoint:

- `pdm-create-process` (a NEW BP) ↔ `pdm-edit-process` (an EXISTING BP)
- `pdm-debug-failed-run` (any failed run) ↔ `pdm-debug-ssh` (specifically an SSH step)

When you add, rename, or remove a skill, update its entry here in the same change — the
guard fails on any mismatch (see `docs/TESTING.md`).

```yaml
skills:
  pdm-create-process:
    prompts:
      - { lang: ru, text: "создай новый бизнес-процесс с нуля" }
      - { lang: en, text: "scaffold a brand-new business process" }
      - { lang: ru, text: "заведи новый BP для приёмки счетов" }
      - { lang: en, text: "create a process that does not exist yet" }
  pdm-edit-process:
    prompts:
      - { lang: ru, text: "поправь шаг в существующем процессе payroll" }
      - { lang: en, text: "update the manifest of the payroll process" }
      - { lang: en, text: "change a task in an existing BP" }
      - { lang: ru, text: "измени сущность в текущем бизнес-процессе" }
  pdm-explain-bp:
    prompts:
      - { lang: ru, text: "объясни как устроен процесс payroll" }
      - { lang: en, text: "give me an overview of the invoice-intake BP" }
      - { lang: ru, text: "расскажи что делает бизнес-процесс X" }
      - { lang: en, text: "explain how process Y works" }
  pdm-record-fixture:
    prompts:
      - { lang: ru, text: "запиши фикстуры из трафика за неделю" }
      - { lang: en, text: "capture last week's HTTP traffic into a fixture" }
      - { lang: ru, text: "зафиксируй сценарий happy-path" }
      - { lang: en, text: "save the SSH traffic for case negative-balance" }
  pdm-debug-failed-run:
    prompts:
      - { lang: ru, text: "разбери почему упал прогон БП" }
      - { lang: en, text: "debug this failed pdm test case" }
      - { lang: ru, text: "прогон в sandbox завершился со статусом failed" }
      - { lang: en, text: "triage the failed run from last-run.json" }
  pdm-debug-ssh:
    prompts:
      - { lang: ru, text: "упал SSH-шаг в прогоне, exit 127" }
      - { lang: en, text: "the ssh exec step returned no matcher" }
      - { lang: ru, text: "ssh завис на проверке host-key" }
      - { lang: en, text: "debug the failing SSH replay step" }
  pdm-promote-release:
    prompts:
      - { lang: ru, text: "продвинь релиз v1.4.0 в прод" }
      - { lang: en, text: "promote the release to production" }
      - { lang: ru, text: "протегируй и выкати новую версию" }
      - { lang: en, text: "tag and promote v2.0.0" }
  pdm-triage-feedback:
    prompts:
      - { lang: ru, text: "разбери входящие фидбек-тикеты" }
      - { lang: en, text: "triage the feedback tickets inbox" }
      - { lang: ru, text: "обработай замечания пользователей из feedback/tickets" }
      - { lang: en, text: "turn feedback tickets into scoped work" }
  pdm-weekly-review:
    prompts:
      - { lang: ru, text: "сделай еженедельный обзор продакшена" }
      - { lang: en, text: "do the weekly production review" }
      - { lang: ru, text: "недельный разбор по телеметрии" }
      - { lang: en, text: "weekly review from telemetry snapshots" }
```

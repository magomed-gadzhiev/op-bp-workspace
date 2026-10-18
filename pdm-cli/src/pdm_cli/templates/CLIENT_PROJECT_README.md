# PDM Client Project

This repo is a git mirror of business-process definitions for a PDM
installation, with two-way sync via `pdm-cli`. See the spec at
`docs/superpowers/specs/2026-05-07-pdm-client-project-design.md`.

## Layout

```
processes/<bp-slug>/
  manifest.yaml       # name, description, version, status
  entities/*.yaml     # entity schemas
  tasks/*.yaml        # BP steps
pdm.config.yaml       # endpoints (committed)
.pdm/secrets.yaml     # API keys, bypass secret (gitignored)
```

## Common operations

```bash
pdm validate                       # check repo structure
pdm pull --from sandbox            # pull current state from sandbox
pdm push --to sandbox              # push local changes to sandbox as published generation
pdm diff --against sandbox         # see what differs

# release flow
git tag v1.0.0
git push --tags
pdm promote v1.0.0
```

## IMPORTANT — read-only mode for prod

For "git is source of truth" to hold, your prod PDM must be started with:

```
PDM_READ_ONLY_BP=true
PDM_CLI_BYPASS_SECRET=<the same value as in .pdm/secrets.yaml>
```

Without these, admins can edit BPs through the UI of the prod PDM and the
git repo will drift out of sync.

## Security

`.pdm/secrets.yaml` is gitignored. Do NOT commit it. For CI, use environment
variables instead: `PDM_API_KEY_PROD`, `PDM_API_KEY_SANDBOX`,
`PDM_CLI_BYPASS_SECRET`.

## Etap 1 (MVP) coverage

This Etap 1 covers manifests, entities, and tasks. Subsequent etapes add:

- scripts (`processes/<bp>/scripts/*.py`) — Etap 4
- sandbox with mocks (Hoverfly + SSH replay) — Etap 2-3
- AI-agent skills — Etap 1.5
- F1/F2/F3 feedback channels — Etap 8

## MCP-серверы для AI-агента (Etap 6+)

При первом `pdm bootstrap` файл `.claude/mcp.json` уже сконфигурирован двумя
серверами:
- `pdm-prod` — read-only обёртка над prod-PDM (телеметрия, runs, БП-описания,
  локальные фидбэк-тикеты).
- `pdm-sandbox` — то же для sandbox + локальные `.pdm/runs/<id>/journal.json`.

Если Claude Code не видит серверы:
1. Установи extras: `pip install 'pdm-cli[mcp]'`.
2. Проверь `.pdm/secrets.yaml` — должны быть `read_api_key_prod` и
   `read_api_key_sandbox`. Если нет:
   - `pdm tokens rotate-read --env=prod`
   - `pdm tokens rotate-read --env=sandbox`
3. Требуется env-var `PDM_INTERNAL_API_TOKEN` (выдаётся при деплое PDM).

**Read-only гарантия:** read-токены принадлежат группе `pdm_readonly` на
стороне PDM и отвергают любые write-actions (`import_full`, `promote`, …).
Если агент через креативный обходной путь попытается мутировать prod — PDM
вернёт 403.

**Tool-calls:**

| Tool | Что делает |
|------|-----------|
| `list_processes` | Список БП с status/version/owner |
| `get_process_summary` | Лёгкий summary одного БП |
| `get_process` | Полный snapshot БП (тяжёлый — использовать целенаправленно) |
| `get_entity_schema` | JSON Schema entity-типа |
| `search_telemetry` | Прогоны за период с фильтрами |
| `get_run_details` | Полный run + assignments + egress |
| `get_feedback` | F1-тикеты из `feedback/tickets/*.md` |

См. также скиллы `pdm-explain-bp` и `pdm-debug-failed-run` в
`.claude/skills/pdm/`.

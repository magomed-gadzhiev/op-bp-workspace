# pdm-cli

CLI for managing PDM business processes via git. See spec at
`docs/superpowers/specs/2026-05-07-pdm-client-project-design.md` and
plan at `docs/superpowers/plans/2026-05-07-pdm-client-project-etap-1-mvp.md`.

## Development environment (Docker)

pdm-cli runs in a long-lived dev container `pdm-cli-dev` defined in
`docker-compose.full.yml`. It auto-installs the package with dev deps
on container start.

```bash
docker compose -f docker-compose.full.yml up -d pdm-cli-dev
docker compose -f docker-compose.full.yml exec pdm-cli-dev pytest -v
docker compose -f docker-compose.full.yml exec pdm-cli-dev pdm --help
```

The container mounts `./tools/pdm-cli` to `/work` — edits on host take
effect immediately inside the container (editable install).

## Local install (alternative)

```
cd tools/pdm-cli
python -m venv .venv
.venv\Scripts\activate         # Windows PowerShell
# source .venv/bin/activate    # bash
pip install -e ".[dev]"
```

## Run tests

```
pytest
```

The default run skips a number of env-gated e2e tests. For the expected baseline
(passed/skipped counts), the full skip taxonomy, the drift guard, and how to run
each gated group for real, see [`docs/TESTING.md`](../../docs/TESTING.md).

## End-to-end testing

E2E tests exercise the full CLI cycle against a real PDM backend. They're
skipped by default and run only when env vars are set.

```bash
docker compose -f docker-compose.full.yml exec \
  -e PDM_TEST_BASE_URL=http://pdm-backend:8000 \
  -e PDM_TEST_API_KEY=<superuser-token> \
  -e PDM_TEST_BYPASS_SECRET=<value-or-empty> \
  pdm-cli-dev pytest -m e2e -v
```

To get a superuser token:

```bash
docker compose -f docker-compose.full.yml exec pdm-backend \
  python manage.py drf_create_token <existing-superuser>
```

(or use the Django admin to create a token for any user with required permissions).

## Этап 4: scripts.py + pdm test

### Scripts as files

Python-скрипты бизнес-процесса теперь хранятся как настоящие `.py` файлы
вместо строк в YAML:

```
processes/<bp-slug>/
└── scripts/
    ├── send_notification.py         # actual Python code
    └── send_notification.meta.yaml  # name, display_name, status, hash
```

- `name` в `meta.yaml` — ASCII snake_case (используется как basename файла).
- Оригинальный display_name (включая non-ASCII / кириллицу) сохраняется в `meta.yaml` и при `push` возвращается на сервер без потерь.
- `pdm pull` распаковывает скрипты из `/full/`-снапшота на диск.
- `pdm push` собирает их обратно в payload для `/import_full/`.
- Round-trip сохраняет байт-в-байт равенство кода и display_name (см. `tests/test_e2e_scripts_roundtrip.py`).

### Integration tests: `processes/<bp>/tests/<case>.yaml`

Каждый кейс — отдельный YAML с входами и ожиданиями (side-effects). Подробности см.
в [design-doc](../../docs/superpowers/specs/2026-05-13-pdm-client-project-etap-4-scripts-tests-design.md);
кратко:

- **`setup`** — какую BP и entity-type seed'ить в sandbox перед запуском.
- **`start`** — параметры `start_for_entity` (которому требуется superuser-token, см. ниже).
- **`fixtures`** — какие HTTP/SSH-фикстуры подгрузить в Hoverfly / ssh-replay.
- **`expect.side_effects[]`** — список ассертов по «journals»:
  - **`kind: http`** — запись в журнале Hoverfly (`/api/v2/journal`).
  - **`kind: ssh`** — запись в `/journal` ssh-replay (`session_open` / `exec` / `subsystem`).
  - **`kind: db`** — SQL-проверка против whitelist таблиц pdm-postgres-sandbox: `process_instances`, `entity_state`, `assignments` (любая другая таблица — runtime ValueError).

### Commands

| Команда | Что делает |
|---------|------------|
| `pdm test --bp <slug> --case <name>` | Запустить один кейс против уже поднятой sandbox |
| `pdm test --ephemeral`              | Поднять sandbox, прогнать кейсы, снести |
| `pdm test --ephemeral --keep`       | Поднять, прогнать, **оставить** sandbox для отладки |
| `pdm logs <run_id>`                 | Снимок последнего запуска в один JSON (instance state, HTTP-журнал, SSH-журнал, DB rows) |

Каждый прогон оставляет артефакт `.pdm/last-run.json` — последний снапшот используется
скиллом `pdm:debug-failed-run` для триажа.

### Prereqs

- `start_for_entity` в PDM требует superuser-permission, поэтому
  `pdm.config.yaml` → `api_keys.sandbox` должен указывать на DRF-токен суперпользователя
  sandbox. См. `tools/pdm-cli/docs/etap-4-discovery.md` для seed-recipe.
- Без superuser-токена `pdm test` упадёт на этапе `start_for_entity` с 403.

## MCP servers (Этап 6 — read-only)

`pdm mcp serve --env=<prod|sandbox>` starts a stdio MCP server (FastMCP)
that exposes 7 read-only tool-calls to a Claude Code agent:

- `get_run_details(run_id)` — process-instance state + steps + egress
- `search_telemetry(bp_slug, since, status?)` — recent runs of a BP
- `get_feedback(bp_slug?, status?, since?)` — read F1 tickets
- `list_bps()` — BPs available on this environment
- `get_bp_manifest(bp_slug)` — manifest + version metadata
- `get_entity_schema(entity_type)` — JSON-schema for entity-type
- `health()` — environment + PDM API version handshake

Configured per-environment via `api_keys.prod` / `api_keys.sandbox` in
`pdm.config.yaml`. After `pdm bootstrap` the agent gets
`.claude/mcp.json` with `pdm-prod` and `pdm-sandbox-readonly` entries.
The agent's skill `pdm:debug-failed-run` Path B uses these read-only
calls for triage; the skill `pdm:explain-bp` answers BP-shape questions.

## Sandbox MCP

`pdm sandbox-mcp serve` starts a stdio MCP server for *interactive*
sandbox debugging. Unlike `pdm mcp serve --env=sandbox` (Etap 6, read-only),
this server can mutate sandbox state: run test-cases, replay steps, override
fixtures, add new fixtures.

```
pdm sandbox-mcp serve [--call-timeout=300] [--skip-version-check]
```

Hard-coded sandbox-only — no `--env` flag. Reads `environments.sandbox`
from `pdm.config.yaml`. Refuses to start without a sandbox section.

Tool-calls:
- `sandbox.run_test(bp, case)` — run `processes/<bp>/tests/<case>.yaml`.
- `sandbox.run_step(run_id, step_id, input_overrides)` — replay a single
  script in dry-run mode.
- `sandbox.inspect_state(run_id)` — context_data + assignments + status.
- `sandbox.list_egress(run_id)` — HTTP/SSH egress of a run.
- `sandbox.add_fixture(bp, kind, matcher, response)` — append to
  `_inbox-<kind>.yaml`; hot-reloads Hoverfly for `kind=http`.
- `sandbox.replay_with_override(run_id, overrides)` — new run_id with
  `entity_fields` / `http_fixtures` / `ssh_fixtures` patches applied.

Ops: `pdm sandbox-mcp cleanup-overrides` removes stale `replay-*.yaml`
from `${PDM_REPO_ROOT}/.pdm/sandbox/ssh-overrides/`.

After `pdm bootstrap`, `.claude/mcp.json` contains three MCP servers:
- `pdm-prod` — read-only against prod
- `pdm-sandbox-readonly` — read-only against sandbox (Etap 6)
- `pdm-sandbox` — interactive against sandbox (Etap 7, this server)

The agent's skill `pdm:debug-failed-run` Path C uses these tool-calls
for iterative debug loops.

## mcp-pdm-bp: сервер правок БП из чата (defmcp)

`pdm defmcp serve` поднимает MCP-сервер **pdm-bp** (спека 143, ADR-0059) —
write-контур агента «БП-инженер» в LibreChat. В стеке это сервис
`mcp-pdm-bp` (`tools/pdm-cli/Dockerfile.mcp`, `:8016`, см.
`docker-compose.full.yml`); локально — `--transport stdio`.

Агент правит пакеты БП в **workspace черновиков** `MCP_BP_DRAFTS_ROOT`
(в контейнере — `/work/.pdm/drafts`, внутри маунта `./.pdm`), а не в git:
git-цикл (`bp_commit`/`bp_drift`/`bp_push_sandbox` и маунт `./.git`)
удалён. Цикл один, без развилок:

```
bp_draft_from_server(slug) → bp_read_file/bp_edit_file → bp_compile → bp_draft_save(slug)
```

`bp_draft_save` сохраняет пакет как **тестовую версию** БП на сервере PDM
(шов draft-import, без подтверждений); публикация («Применить»/«Отклонить»)
— только человек в админке PDM. Канон инструкции агента —
[`src/pdm_cli/templates/skills/pdm/pdm-edit-process.md`](src/pdm_cli/templates/skills/pdm/pdm-edit-process.md)
(копию в Mongo LibreChat обновляет человек по рунбуку
`docs/runbooks/pdm-mcp-weak-model-agent.md`).

Вербы: `bp_list_files`/`bp_read_file`/`bp_edit_file`/`bp_new_process`
(от workspace), `bp_compile` (offline Tier 0), `bp_draft_from_server`/
`bp_draft_save`/`bp_draft_status` (нужен `PDM_API_BASE`/`PDM_API_TOKEN`),
`bp_script_check`, `bp_test` (движок `pdm test`, нужен docker.sock — таблица
маунтов в рунбуке). Без API сервер работает в offline-режиме:
read/edit/new_process/compile доступны, draft-вербы отключаются.

## Status

Etap 1 (MVP) — initial scaffolding only. Subcommands `bootstrap / pull / push / promote / validate / diff` are added in subsequent tasks.

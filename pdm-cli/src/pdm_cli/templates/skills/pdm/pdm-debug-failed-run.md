---
name: pdm-debug-failed-run
description: Use when a `pdm test` case fails or a sandbox BP run ends in failed/cancelled status — triage via .pdm/last-run.json and `pdm logs <run_id>`, classify the failure (HTTP no-match, SSH no-match, script exception, side-effect mismatch, timeout, infra) and propose a fix + a regression test case. Применять, когда упал прогон БП или тест-кейс. Triggers / триггеры — "the run failed", "debug this failed test", «прогон упал», «разбери падение теста». Anti-trigger: если падает именно SSH-шаг (exit 127 / no matcher / host-key) — pdm-debug-ssh.
---

# pdm-debug-failed-run

## Цель

Расследовать неудачный прогон БП (через `pdm test` или ручной запуск в
sandbox) и довести до **конкретной гипотезы** (файл + строка / фикстура +
матчер) и предложения фикса. **Не** автоматизировать починку, **не**
коммитить, **не** трогать prod.

## Preconditions

- Был хотя бы один прогон — есть `.pdm/last-run.json` либо в руках
  `run_id`.
- Sandbox-стенд поднят (если предстоит что-то перепрогнать):
  `docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml ps`.

## Preflight (Etap 6+)

Перед расследованием определи источник прогона и канал данных:

1. **Откуда `run_id`?**
   - Если из недавнего `pdm test` (последние 60 минут) → run живёт в sandbox.
   - Если из реального инцидента в prod → run в prod.
   - Если непонятно — спроси пользователя.

2. **Какой MCP-сервер релевантен?**
   - prod-run → `pdm-prod.get_run_details(run_id)`
   - sandbox-run → `pdm-sandbox.get_run_details(run_id)` (он сам склеит
     PDM API + локальный `.pdm/runs/<id>/journal.json`)

3. **Если MCP недоступен** (`ToolError: PDM API unreachable` или модуль не
   зарегистрирован в Claude Code) → fallback на CLI-путь, описанный ниже.

## Steps

### 1. Собрать контекст

#### Путь A — через MCP (рекомендуется, быстрее)

1. `<env>.get_run_details(run_id)` — получаешь steps + errors + egress одним вызовом.
1.5. **Replay-цепочка (если run имеет source_run_id):** вызвать `<env>.get_replay_chain(run_id)`.
   - Если цепочка > 1 уровня — показать дерево прогонов.
   - Отметить на каком уровне впервые появилась ошибка.
   - Если ошибка только в последнем replay — проблема в override_payload, не в исходном БП.
2. Если в `egress.http` есть `response_status >= 400` — запиши их как кандидаты в «виновники».
3. Если есть `egress.ssh` с `exit_code != 0` — то же.
4. Переходи к Шагу 2.

#### Путь B — через CLI (fallback, если MCP недоступен)

- Прочитать `.pdm/last-run.json`. Если упомянут конкретный кейс — взять
  оттуда `run_id` и `bp_slug`. Если в файле несколько кейсов и неясно
  какой именно интересует — спросить у пользователя.
- Если `.pdm/last-run.json` нет — попросить run_id вручную.
- Вызвать `pdm logs <run_id> --format json` и сохранить вывод. Это
  главный источник истины: оттуда тянутся `final_status`,
  `process_instance.steps`, `egress.http[]`, `egress.ssh[]`,
  `assertions[]`, `containers.*`.

### Path C: Interactive sandbox debug (Etap 7)

Use when you have a failed sandbox run and need to ITERATE on hypothesis.
Requires `pdm-sandbox` MCP server (configured by `pdm bootstrap` in
`.claude/mcp.json`).

1. **Snapshot current state.** Call `sandbox.inspect_state(run_id)` to see
   context_data, status of each assignment, and the point of failure.
2. **Suspect a specific script step?** Call
   `sandbox.run_step(run_id, step_id, input_overrides={...})` to replay
   exactly that step without advancing the process. Iterate with different
   `input_overrides` to test hypotheses. The run state is not mutated —
   each call is a dry-run.
3. **Suspect an HTTP/SSH response?** Call `sandbox.list_egress(run_id)` to
   see what actually came back. If the response looks wrong, replay with a
   corrected fixture via
   `sandbox.replay_with_override(run_id, overrides={http_fixtures: [{matcher, response}]})`.
   For SSH, use `overrides={ssh_fixtures: [...]}`. The replay creates a
   *new* run_id (with `source_run_id` pointing at the original).
4. **Missing fixture?** Call
   `sandbox.add_fixture(bp, kind, matcher, response)` — written to
   `processes/<bp>/fixtures/_inbox-<kind>.yaml`. **For HTTP**, Hoverfly is
   hot-reloaded immediately. **For SSH**, the file is saved but ssh-replay
   doesn't reload until restart — use `replay_with_override` if you need
   the fixture active for the next replay. The `_inbox-*.yaml` file is
   pending-review and is NOT auto-committed; a human moves entries into
   the main `*-fixtures.yaml` after PR review.
5. **After each hypothesis:** rerun `sandbox.replay_with_override(run_id,
   overrides)`. The status field tells you whether the bug is gone.
6. **Once you've found the cause:** fix in code / fixtures via the normal
   PDM flow (edit file → `pdm push`), then confirm with
   `sandbox.run_test(bp, case)`.

**Don't:**
- Use `sandbox.*` tool-calls against prod — `pdm-sandbox` MCP server cannot
  reach prod by construction, but if you find yourself looking for an
  equivalent prod tool, stop and use `pdm logs <run_id>` (Path A) or the
  read-only `pdm-prod` MCP (Path B) instead.
- Patch script code via `replay_with_override.overrides` — there is no such
  override. Script code must go through git + `pdm push`.

### 2. Классифицировать падение

Проходить чек-лист сверху вниз, **остановиться на первом совпавшем
классе** (часто корневая причина одна, остальное — следствие):

#### 2.1 Timeout (`status: timeout` / `final_status: timeout`)

- Найти `process_instance.steps[-1]` — на каком шаге зависло.
- Сопоставить с egress'ом: HTTP-таймаут (нет `response`, только
  `request`), SSH-таймаут (нет `exit_code`), либо скрипт в бесконечном
  цикле (нет egress'а вообще, а `containers.pdm-sandbox` показывает
  активность).
- Гипотеза: внешняя зависимость не отвечает / скрипт зациклился.

#### 2.2 HTTP no-match (Hoverfly 502)

- В `egress.http[]` есть запись со `response.status == 502` от Hoverfly
  (Hoverfly возвращает 502 на промахи в simulate-режиме).
- Найти ближайший матчер в `processes/<bp>/fixtures/http-*.yaml`.
- Сравнить method / path / headers / body. Типичные расхождения:
  лишний query-param, разный case у хедера, body-template не
  подставился. Назвать **конкретное поле**.
- Гипотеза: фикстура не покрывает запрос. Фикс — `pdm fixtures record`
  на свежем прогоне в capture-режиме либо ручная правка YAML.

#### 2.3 SSH no-match (exit 127 + matched_fixture: null)

- В `egress.ssh[]` запись с `exit_code: 127` и `matched_fixture: null`.
- Замэтчить против `processes/<bp>/fixtures/ssh-*.yaml`, поле
  `command_matches`.
- Типичные расхождения: лишние/недостающие пробелы, незаэкранированные
  `.`/`/`, кейс-зависимая regex, пропущенный named-group.
- Если матчер вообще отсутствует — отправить к `pdm-debug-ssh` шаг 4
  (capture → record).

#### 2.4 Script exception (Python traceback)

- В `containers.pdm-sandbox` (или соответствующем worker-контейнере)
  есть traceback.
- Извлечь traceback целиком, найти **верхнюю строку юзер-кода**:
  `processes/<bp>/scripts/<name>.py:<line>`.
- Прочитать функцию (`Read`-tool на конкретный диапазон строк),
  поставить диагноз: `KeyError` (отсутствующее поле во входе?), `TypeError`
  (несовместимые типы / None?), `IndexError`, кастомное исключение.

#### 2.5 Side-effect assertion mismatch

- `assertions[]` содержит запись со `status: failed`.
- Прочитать `expected` vs `actual` — для HTTP/SSH side-effect'ов
  сравнить с `egress.http[]` / `egress.ssh[]`.
- Развилка:
  - **БП не сделал ожидаемый вызов** — баг в скрипте/workflow (ветка
    пошла не туда, условие false). Идти в код.
  - **БП сделал вызов, но матчер ассерта мимо** — баг в `case.yaml`
    (неточное `expected`).

#### 2.6 Infra (final_status: null + sandbox unreachable)

- `pdm logs` молчит / нет `final_status` / контейнеры down.
- Отправить пользователя к `pdm-debug-ssh` (если падение про SSH) или
  к простой `docker compose ... ps` диагностике sandbox-compose.
- В скилле **не** разворачивать инфру самостоятельно.

### 3. Сформулировать гипотезу + фикс

Один абзац без воды. Структура:

> **Корень:** `<class>` — `<one-line summary>`.
> **Где:** `<file>:<line>` или `processes/<bp>/fixtures/<file>.yaml`.
> **Что сделать:** `<concrete action>` (например: «добавить хедер
> `X-Idempotency-Key` в матчер `http-happy-path.yaml` pair #3»; либо
> «в `calc_bonus.py:42` обработать `None` от `lookup_rate()`»).

### 4. Предложить регрессионный кейс

Если корень — script bug или missing fixture, **оформить** минимальный
`tests/<bp>/<case>.yaml`, который воспроизводит проблему. Показать
пользователю YAML, **не коммитить**, не вызывать `pdm test`. Решение о
включении в регрессии — за пользователем.

### 5. Чего скилл НЕ делает

- Не правит код / не пересоздаёт фикстуры автоматически.
- Не вызывает `pdm fixtures record`, `pdm push`, `git commit`.
- Не разворачивает sandbox.
- Не догадывается за пользователя, какой именно run_id, если их в
  `last-run.json` несколько — **спрашивает**.

## Red flags

| Trigger | Что не делать |
|---|---|
| Пользователь просит «просто почини» | Скилл — триаж, а не auto-fix. Сформулировать гипотезу и отдать. |
| `final_status: passed`, но пользователь говорит «упало» | Спросить, какой run_id; возможно смотрит на старый. |
| Сразу две assertion-failure записи | Классифицировать **корневую** (обычно первую по `process_instance.steps`), остальные — следствия. |
| Hoverfly 502 + traceback одновременно | Класс 2.2 (HTTP no-match) первичен; traceback в скрипте — это реакция БП на 502. |
| Нет ни `.pdm/last-run.json`, ни run_id | Не выдумывать. Попросить у пользователя или направить к `pdm test`. |

## Шаг N: Проверка контекста через telemetry (Etap 6+)

Если ошибка повторяющаяся (есть подозрение на системную проблему):

1. `<env>.search_telemetry(bp_slug, since="7d", status="error")` — все
   error-прогоны за неделю.
2. Если `error_summary` совпадает у нескольких runs — это системная
   проблема. Упомяни в финальном отчёте.
3. `<env>.get_feedback(bp_slug, status="new", since="30d")` — поищи
   пользовательские тикеты со схожей жалобой. Если есть — добавь
   `related_tickets: [T-...]` в итог.

## Postconditions

- Зафиксирована **одна** корневая гипотеза (класс 2.1–2.6) с конкретным
  файлом/строкой/матчером.
- Предложен фикс (текстом, без применения).
- Если уместно — показан draft регрессионного `tests/<bp>/<case>.yaml`.
- Решение об апплае фикса и записи теста — за пользователем.

## Manual validation

Для тренировки и регрессии скилла в репо есть набор заведомо падающих
кейсов: `tools/pdm-cli/sandbox/fixtures/debug-scenarios/`
(`http-no-match`, `ssh-no-match`, `script-raises`,
`side-effect-mismatch`). См. `README.md` рядом.

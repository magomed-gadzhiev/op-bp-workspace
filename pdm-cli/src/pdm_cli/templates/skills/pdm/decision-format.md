---
name: pdm:decision-format
description: Canonical format for decision files at processes/<bp>/decisions/YYYY-MM-DD-<topic>.md. Read before creating or updating a decision file from any pdm- skill.
---

# pdm:decision-format

Единый формат decision-файлов client-project. Любой скилл, который создаёт
или обновляет `processes/<bp>/decisions/*.md` (`pdm:triage-feedback`,
`pdm:weekly-review`, `pdm:edit-workflow`, `pdm:debug-ssh`, `pdm:explain-bp`),
обязан использовать именно этот формат. Другие схемы (`status: proposed`,
`Resolution:` и т.п.) считаются устаревшими — приводи к этому формату.

## Имя файла

```
processes/<bp>/decisions/YYYY-MM-DD-<topic>.md
```

- `YYYY-MM-DD` — дата постановки вопроса; совпадает с `date` во front matter.
- `<topic>` — короткий kebab-case; совпадает с `topic` во front matter.

## Front matter (канонический)

```yaml
---
date: 2026-05-19            # дата вопроса; совпадает с префиксом имени файла
topic: <kebab-topic>        # совпадает с <topic> в имени файла
bp_slug: <business-process> # к какому БП относится решение
status: asked               # asked | decided | superseded
source: feedback            # feedback | weekly-review | edit-process | debug-ssh | other
asked_by: claude-code       # кто задал вопрос
decided_by:                 # кто принял решение (заполняется при status: decided)
decided_at:                 # дата решения (заполняется при status: decided)
ticket_ids: []              # опц.: id/имена feedback-тикетов
telemetry_snapshots: []     # опц.: feedback/telemetry/YYYY-Www-<bp>.md
supersedes:                 # обязат. при status: superseded — date старого решения
superseded_by:              # проставляется в старом файле при замене
---
```

Обязательные ключи: `date`, `topic`, `bp_slug`, `status`, `source`, `asked_by`.
`decided_by` и `decided_at` обязательны, когда `status: decided`.
`supersedes` обязателен, когда `status: superseded`.

## Жизненный цикл `status`

```
asked  ──> decided ──> superseded
```

- `asked` — вопрос поставлен, варианты записаны, решения админа ещё нет.
  (Старое значение `proposed` маппится сюда.)
- `decided` — админ принял решение; заполнены `decided_by`, `decided_at`,
  раздел «Решение» и «Реализовано в» (по мере реализации).
- `superseded` — решение заменено более новым; проставлен `supersedes`
  (date старого), а в старом файле — `superseded_by` (date нового).

## Секции

Заголовки можно дублировать английским алиасом (`## Вопрос / Question`),
порядок фиксирован:

1. `## Вопрос` — формулировка открытого вопроса.
2. `## Контекст` — что подвело к вопросу: ссылки на тикеты, телеметрию,
   текущий код/workflow.
3. `## Варианты` — опционально, 2–4 конкретных варианта с tradeoff'ами.
4. `## Решение` — ответ админа. До `status: decided` — `—`.
5. `## Реализовано в` — `commit <sha>, тест <path>`. До реализации — `—`.

## Минимальный пример

```markdown
---
date: 2026-05-19
topic: bonus-rounding
bp_slug: payroll
status: asked
source: feedback
asked_by: claude-code
decided_by:
decided_at:
ticket_ids:
  - 2026-05-18-bonus-off-by-one.md
telemetry_snapshots: []
supersedes:
superseded_by:
---

## Вопрос
Округлять премию вверх или к ближайшему рублю?

## Контекст
Тикет 2026-05-18-bonus-off-by-one: пользователь видит расхождение в 1 ₽
с ручным расчётом. Код в `scripts/calc_bonus.py` использует `round()`.

## Варианты
- A: банковское округление (текущее) — стабильно, но расходится с 1С.
- B: округление вверх — совпадает с 1С, увеличивает фонд на ~0.3%.

## Решение
—

## Реализовано в
—
```

## Перед постановкой вопроса

Агент обязан проверить `processes/<bp>/decisions/*.md`: возможно, ответ
уже есть (`status: decided` без относящегося к нему `superseded_by`).
Не дублируй вопрос — обнови существующий файл или сошлись на него.

## Что НЕ делать

- Не выводить продуктовую политику из одного неоднозначного тикета.
- Не использовать устаревшие схемы (`status: proposed`, `Resolution:`,
  `owners:`) — приводи к канону при правке.
- Не коммитить в decision-файл секреты, PII, payload'ы.

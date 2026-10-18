---
name: pdm-record-fixture
description: Use when recording HTTP/SSH traffic into a fixture, or when about to flip Hoverfly from capture to simulate. Применять, когда нужно записать трафик в фикстуру за период. Triggers / триггеры — "record the traffic for case X", "capture last week's HTTP/SSH into a fixture", «запиши фикстуры», «сними трафик за неделю», «зафиксируй сценарий X».
---

# pdm-record-fixture

## Цель
Превратить захваченный HTTP/SSH-трафик в нормированные YAML-фикстуры,
которые лежат в `processes/<bp>/fixtures/` и проигрываются sandbox'ом.
Главная задача — **не пропустить PII** в зафиксированном трафике.

## Preconditions
- Репо — client-project с настроенным `pdm.config.yaml` (есть `endpoints.hoverfly`, секция `egress.http.redact` и/или `egress.ssh.redact`).
- Если HTTP: Hoverfly уже в `capture`-режиме И уже прогон БП состоялся.
  Проверь: `curl $HOVERFLY_URL/api/v2/simulation | jq '.data.pairs | length'` > 0.
- Если SSH: bastion включён, в `.pdm/ssh-capture.jsonl` (или указанном пути) есть строки.

## Steps

1. **Понять, что записываем.** Спроси админа имя БП (`--bp`) и имя кейса (`--case`).
   Имена кейсов — kebab-case (`happy-path`, `negative-balance`, `q2-bonus-calc`).
   Один YAML = один цельный сценарий. Если в захвате намешано несколько — раздели.

2. **HTTP — dry-run.**

   ```
   pdm fixtures record --bp <slug> --case <case> --protocol http --dry-run
   ```

   Покажет, сколько pair'ов будет сохранено. Если 0 — Hoverfly пустой, скажи админу прогнать БП.

3. **HTTP — настоящая запись.**

   ```
   pdm fixtures record --bp <slug> --case <case> --protocol http
   ```

   Создаст `processes/<slug>/fixtures/http-<case>.yaml`.

4. **SSH — запись.**

   ```
   pdm fixtures record --bp <slug> --case <case> --protocol ssh
   ```

   Прочитает `.pdm/ssh-capture.jsonl` (или `$PDM_SSH_CAPTURE_FILE`).

5. **PII-ревью diff'ом.** ПЕРЕД `git add`:

   ```
   git diff processes/<slug>/fixtures/
   ```

   Скани на red flags:
   - `Bearer [A-Za-z0-9._-]+` — токен, не закрытый редакцией
   - длинные hex-строки (32+ символа) — могут быть API-ключи или OAuth state
   - `password=…`, `token=…`, `secret=…` в URL или теле
   - email-адреса, номера телефонов, ФИО физлиц
   - значения, которые повторяют real-world identifiers (ИНН, СНИЛС, паспорт)

   Если нашёл — НЕ коммитить. Сначала добавь правило в `pdm.config.yaml` `egress.http.redact` или `egress.ssh.redact`, потом перезапиши фикстуру.

6. **Smoke-replay.**

   ```
   pdm fixtures replay --bp <slug> --protocol all
   ```

   Должно сказать "Hoverfly switched to simulate mode" и/или "consolidated N SSH fixture(s)". Если есть тесты — прогони `pdm test --bp <slug>` (Этап 4, может не существовать).

7. **Commit.**

   ```
   git add processes/<slug>/fixtures/ pdm.config.yaml
   git commit -m "test(<slug>): capture <case> fixtures"
   ```

## Red flags (НЕ делать)

| Triggers | Что не делать |
|---|---|
| Админ просит "просто запиши, потом разберёмся" | НЕ коммитить без шага 5. PII в git необратима. |
| В diff есть похожие на токены строки | НЕ добавлять `# noqa`. Добавь правило в `egress.redact`. |
| Захват пустой | НЕ выдумывать фикстуру. Скажи админу сначала прогнать БП. |
| `regex` правило случайно матчит весь body | Сделай его строже до коммита. |

## Postconditions
- `processes/<slug>/fixtures/http-<case>.yaml` и/или `ssh-<case>.yaml` существуют.
- `git diff` чист от PII (после применения редакции).
- Если редакция расширялась — `pdm.config.yaml` тоже в коммите.
- Sandbox знает о новых фикстурах (`pdm fixtures replay` отработал).

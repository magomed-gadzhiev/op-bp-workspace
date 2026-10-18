# debug-scenarios

Заведомо падающие кейсы для **ручной** тренировки и регрессии скилла
`pdm:debug-failed-run`. Это **скетчи**, не готовые e2e-кейсы: они
показывают форму проблемы (`case.yaml` + минимальная фикстура / скрипт),
а не полностью runnable. Чтобы реально прогнать — нужен соответствующий
BP в `processes/<bp>/` и поднятый sandbox-стенд.

## Цель

Каждый сценарий моделирует один класс падения из чек-листа скилла. После
запуска через `pdm test --bp <bp> --case <case-name>` (Этап 4) и
получения `final_status: error` / `cancelled` админ зовёт скилл и
проверяет, что тот **правильно классифицирует** проблему.

## Сценарии

| Каталог | Класс из скилла | Симптом в `pdm logs <run_id>` |
|---|---|---|
| `http-no-match/` | 2.2 HTTP no-match | `egress.http[]` содержит запись со `response.status: 502` от Hoverfly |
| `ssh-no-match/` | 2.3 SSH no-match | `egress.ssh[]`: `exit_code: 127`, `matched_fixture: null` |
| `script-raises/` | 2.4 Script exception | `containers.pdm-sandbox`: Python traceback из юзер-кода |
| `side-effect-mismatch/` | 2.5 Side-effect assertion mismatch | `final_status: completed`, но `assertions[].status: failed` (БП не сделал ожидаемый POST) |

## Как использовать

1. Скопировать сценарий в реальный `processes/<bp>/` своего
   client-project (или собрать заглушечный BP под него).
2. Положить `case.yaml` в `processes/<bp>/tests/`.
3. Положить файлы из `fixtures/` (если есть) в
   `processes/<bp>/fixtures/`.
4. Прогнать `pdm test --bp <bp> --case <name>` в sandbox.
5. Получить ожидаемое падение → позвать `pdm:debug-failed-run`.
6. Проверить, что скилл:
   - корректно классифицировал (см. таблицу выше);
   - указал конкретный файл/строку или матчер;
   - предложил фикс без авто-применения.

## Замечания

- Кейсы **не подключены** к авто-CI. Их прогон — ручной (как и в
  `pdm:debug-ssh`).
- Если форма `case.yaml` поменяется на Этапе 4 — синхронизировать.
- Регулярки и эндпоинты — иллюстративные. Реальные значения зависят от
  конкретного BP, в который сценарий встроен.

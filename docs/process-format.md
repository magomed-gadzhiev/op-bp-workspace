# Формат пакета БП в воркспейсе (словарь ключей)

Канон семантики: спека [163](README-ссылки внизу), ADR-0070; мастер
определений — БД PDM. Этот файл — словарь ключей YAML-формы, которой
оперируют `pdm ws init/check/diff/test/report`. Живой полный образец:
`examples/contract-approval/`.

Состав каталога БП (`workspace/<slug>/`):

```
<slug>/
├── process.yaml            # шапка БП
├── tasks/NN-slug.yaml      # задачи, NN — порядок (10, 20, …)
├── scripts/*.py            # скрипты песочницы (без импортов)
├── document_templates/*.yaml
├── catalogs/*.yaml
└── table_view.yaml         # опционально: табличный режим
```

## process.yaml

| Ключ | Значение |
|---|---|
| `name`, `slug`, `description` | шапка; тексты с «:» — только фолдед-скаляр `>-` |
| `document_template_refs` | имена шаблонов (`document_templates/*.yaml:name`) |
| `allowed_starter_groups` | группы, кому разрешён старт (пусто — всем) |
| `instance_visibility` | `default` \| `isolated` (инициатор видит только своё; isolated требует непустых групп запуска) |
| `access_policy` | `local` (дефолт; субъекты прав не едут в пакет) \| `portable` |
| `admin_users` | администраторы БП (usernames; при `local` не переносятся) |
| `is_template` | `true` — шаблонный процесс |
| `debug_mode` | `true` (дефолт) — подробное логирование прогонов; `false` — только ошибки |
| `initiation_config.auto_start_first_task` | `true` — первая задача стартует сама |
| `initiation_config.naming` | `{enabled: true, prefix: Договор}` — автонумерация «Договор №26-000NN»; действует после «Применить» |
| `priority_config` | `{enabled: true, default: low\|medium\|high}` — приоритет заявок |
| `scripts` | `{name, code_file, display_name, description, status: draft\|active\|inactive\|deprecated, requirements}` — реестр; код в `scripts/<code_file>` |
| `instance_script_bindings` | `[script_name]` — скрипты старта/завершения/приостановки ЭКЗЕМПЛЯРА (типы `instance_on_start`, `instance_on_complete`, …); **на тест-прогоне не действуют** (bp-уровень, до «Применить») |
| `on_complete_start` | декларативный конвейер «по завершении задачи — запустить процесс»: `{task, target, transfer: [{template, mode: link\|copy}]}` |
| `instance_commands` | кнопки экземпляра: `{slug, title, order, confirm, rollback_target_task, allowed_for: [{role: initiator\|executor\|observer, task: <имя>}], form: {document_template: <имя>}, script}`; тоже bp-уровень |

## Документы заявки — два механизма

1. **Автосоздание на старте экземпляра** (после «Применить»): секция
   «Типы сущностей» БП (= `document_template_refs` + `entity_config` задач)
   — движок сам создаёт по документу каждого типа при старте. Для
   тест-прогона кандидата эти типы ещё не в БП — поэтому:
2. **Скрипт `on_start` первой задачи** (`process.create_document`) —
   работает и на тест-прогоне (образец `examples/contract-approval`).

## tasks/NN-*.yaml

| Ключ | Значение |
|---|---|
| `name`, `order` | имя (уникально в БП, им ссылаются условия) и порядок; **порядок — только отображение на схеме**, последовательность задают условия |
| `description` | описание задачи |
| `priority` | приоритет поручения (0–4) |
| `start_condition` | когда задача стартует: `condition_tree: {condition: and\|or, rules: [...]}`; правило-событие `{assignment_task: <имя>, operator: equals, value: completed}`; правило-поле документа `{field: <Документ.Поле>, operator: equals\|'true', value: …}` |
| `auto_start_on_open` | `true` — поручение стартует при открытии |
| `assign_to_starter` | `true` — исполнитель = инициатор заявки |
| `responsible` / `responsible_groups` | ответственный/группы исполнителей |
| `watchers` / `watcher_groups` | наблюдатели-пользователи/группы |
| `reject_target_task` | имя задачи для «Отклонить с возвратом» |
| `is_final` | `true` — финальная задача |
| `script_bindings` | `[{script_name, script_type, order, is_enabled}]`; типы: `on_start`, `on_complete` (дефолт, гейт), `on_error`, `on_reopen`, `on_reject`, `on_timeout`, `custom` |
| `timeout_days` + `timeout_decision` | таймаут задачи (дней) и действие по таймауту — питает биндинг `on_timeout` |
| `webhook_url` + `webhook_payload_template` | исходящий вебхук задачи (URL + JSON-шаблон payload) |
| `card_fields_config` | `{<Документ>: [поля]}` — поля документов в карточке/списке поручений |
| `documents_display_order` | порядок документов на задаче |
| `readable_entity_types` / `editable_entity_types` / `hidden_entity_types` | режимы доступа к документам на задаче |
| `can_create_entity` / `creates_entity_type` | задача создаёт документ указанного типа |
| `entity_config` | конфиг сущности задачи (создание/перенос: `on_complete_start`, transfer-правила) |
| `approver_resolution` | орг-резолв согласующего: `{mode: org_unit_head, unit_source: {kind: document_field, ref: <Документ.Подразделение>}, overrides: [...]}`; `responsible_groups` — фолбэк |
| `kind` + `config` | FSM-узел: `script` \| `human-decision` \| `human-action` (+ обязательный `config` для kind); для обычных задач не задавать |

## document_templates/*.yaml

```yaml
name: Карточка договора          # глобально уникальное имя!
system_type: document
description: >-
  <p>Текст с двоеточиями — только так.</p>
fields:
- {name: Номер, field_type: string, order: 0, in_string_representation: true}
- {name: Сумма, field_type: decimal, order: 1}
- {name: Тип, field_type: catalog_reference, order: 2, reference_catalog: Тип договора}
```

Палитра типов поля (UI «Поля» редактора типа, 19 шт.) → `field_type`:
`string` (Строка), `text` (Текст), `number` (Число), `decimal` (Число
десятичное), `date` (Дата), `boolean` (Логическое), `file_reference` (Ссылка
на файл), `reference` (Ссылка на сущность + `reference_entity_type`),
`user` (Пользователь), `org_unit` (Подразделение), `array_reference` (Массив
сущностей), `catalog_reference` (Элемент справочника + `reference_catalog`),
`array_string`, `array_number`, `array_date`, `array_boolean`,
`array_catalog_reference` (массивы), `table_section` (Табличная часть +
`reference_table_section`), `static_text` (Текст без вопроса), `computed`
(Вычисляемое; пересчёт — «Пересчитать все»).
Модификаторы поля: `required`, `unique`, `in_string_representation`,
`display_name`, `properties` (напр. `ui.widget: radio`).

Свойства ТИПА (UI «Расширенные настройки»; в YAML — `system_type`):
`document | catalog | catalog_item | custom`, признак «Системный» (нельзя
удалить через UI), `singleton` (ровно один экземпляр типа); «Родительский
тип» — наследование полей (в пакете не выражается); иконка (bootstrap-icons)
— косметика. Табы редактора типа: Основное, Поля, Табличные секции,
Интерфейсы, JSON Schema.

Использование справочников: `catalog_reference` (один элемент) /
`array_catalog_reference` (массив-теги) → каталог из `catalogs/*.yaml`;
редактор ЭЛЕМЕНТОВ справочника — глобальный раздел «Справочники» вне
конструктора БП (живой пример использования — SEMSYS в ЛЭМ: 8 полей-массивов
по каталогам задач + «Да/Нет»).

⚠ Документы, которые создаёт стартовый скрипт, не должны иметь
`required`-полей — `create_document()` валидирует и не создаст пустой
карточки. Обязательность обеспечивает скрипт-валидатор на задаче.

## catalogs/*.yaml

```yaml
name: Тип договора
fields:
- {field_type: string, name: title}
items:
- {name: Поставка, uuid: <uuid4>, data: {title: Поставка}}
```

Поля шаблонов и каталогов (`fields[]`): `name`, `field_type`, `order`,
`display_name`, `required`, `unique`, `in_string_representation`,
`reference_entity_type`, `reference_catalog`, `reference_table_section`,
`properties` (напр. `ui.widget: radio`).

## folder_template.yaml (опционально)

Шаблон дерева папок Nextcloud для экземпляров — создаётся при старте
строки реестра. В UI не редактируется, живёт только в пакете.

## scripts/*.py — API песочницы (без импортов, только это)

| Вызов | Что делает |
|---|---|
| `process.get_document('<имя>')` | документ заявки (None, если нет) |
| `process.create_document('<имя>', data={})` | создать документ; **валидирует required** |
| `documents.find('<имя>')` | список документов по шаблону |
| `doc.get('<Поле>')` / `doc.set('<Поле>', v)` | чтение/запись поля |
| `doc.save()` / `doc.save(validate=False)` / `doc.validate()` | сохранение/валидация |
| `assign_task('<Задача>', <user>)` | назначить исполнителя задачи |
| `set_deadline('<Задача>', <дата>)` | срок задачи |
| `log('<текст>')` | строка в журнал прогона |

Ошибки скрипта (`raise ValueError('текст')`) блокируют завершение задачи и
попадают в журнал прогона — это штатный способ валидации.

## Чего НЕТ в YAML-форме (только UI / сервер)

Возможности конструктора, не выражаемые пакетом воркспейса. При правке
существующего БП они **не трогаются** импортом (candidates создаются
заново — сверься с человеком, если правка нужна):

- **Уведомления задачи** — матрица «получатель × событие × канал» (App/@;
  события: назначение/смена исполнителя, смена статуса поручения и др.)
  в UI-конструкторе задачи.
- **Режим биндинга** `sync (гейт) / async (Celery)` + число ретраев +
  `params` (JSON) — UI «Автоматизация»; YAML несёт только
  script/type/order/is_enabled.
- **Трудоёмкость задачи** — плановые часы, сложность, автокорректировка.
- **Связи процесса** («Связи» в конструкторе).
- **Скриптовая автоматизация вне задач** — расписания (schedules), вебхуки
  скриптов, секреты, сущностные события (entity_event_bindings),
  instance_actions — есть в модели ProcessScript, но **в UI редактора
  скрипта их нет** (там: имя/статус draft|active|inactive|deprecated/описание/
  код с «Сгенерировать·Проверить синтаксис·Форматировать»/ТЗ-requirements);
  настраиваются серверно.
- Подпись кнопки запуска («Имя запуска» в Настройках) и флаг авто-бора
  всех поручений в работу — уточняй у человека, в пакете не выражены.
- «Родительский тип» (наследование типов сущностей) — только UI.

И наоборот — **таймаут (`timeout_days`/`timeout_decision`) и вебхук задачи
(`webhook_url`/`webhook_payload_template`) в UI НЕ редактируются** (их нет
во фронтенде): они выражаются только пакетом воркспейса. Тип события
биндинга «При таймауте» в UI есть, а сам таймаут ставится YAML-ом.

## Ловушки (каждая стоит итерации)

1. **bp-уровень не действует на тест-прогоне**: `instance_script_bindings`,
   `instance_commands`, `naming`, `priority_config` оживают только после
   «Применить» человеком. Документы для прогона создавай скриптом с
   `script_type: on_start` на первой задаче.
2. **Правка только тела шаблона/каталога** может дать no-op при сохранении
   (тела ресурсов не входили в payload_hash у версий, созданных старой
   сборкой сервера) — смотри статус ответа `ws test`.
3. **`pdm ws diff <slug>`** перед `ws test` — видно ровно то, что уйдёт.
4. Имена шаблонов глобально уникальны; фолдед-скаляры для текстов с «:».

## Ссылки

- Полный живой пример: `examples/contract-approval/`
- Цикл и запреты: `.clinerules`
- Отчёт человеку: `templates/report-checklist.md`

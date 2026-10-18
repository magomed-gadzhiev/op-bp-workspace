# PDM API Discovery — Etap 1 Baseline

**Дата:** 2026-05-07  
**Ветка:** 029-pdm-client-project-mvp  
**Цель:** зафиксировать фактическое состояние PDM Django-backend для планирования реализации CLI-инструмента (Etap 1 MVP).

---

## 1. Модели БП и версий

### Основная модель бизнес-процесса

**Класс:** `BusinessProcess` (`pdm/backend/processes/models.py`, строка 27)

Это единственная модель «шаблона» бизнес-процесса. Отдельного класса-версии (`BusinessProcessVersion`, `ProcessVersion` и т.п.) **не существует**.

**Стабильный идентификатор:** `id` (integer, автоинкремент). Поля `slug` или `code` нет. Имя (`name`) уникальным ограничением не помечено.

**Ключевые поля:**

| Поле | Тип | Назначение |
|------|-----|------------|
| `id` | AutoField | PK |
| `name` | CharField(255) | Название |
| `description` | TextField | Описание (HTML, sanitize) |
| `is_deleted` | BooleanField | Soft-delete флаг |
| `is_template` | BooleanField | Является ли шаблоном |
| `initiation_config` | JSONField | Конфигурация автозапуска |
| `creates_entity_type` | FK(DocumentTemplate) | Тип сущности при старте |
| `entity_types` | M2M(DocumentTemplate) | Шаблоны документов процесса |
| `allowed_starter_groups` | M2M(Group) | Группы, которые могут запустить |
| `created_at` | DateTimeField | Дата создания |
| `updated_at` | DateTimeField | Дата обновления |

**Поле статуса версии:** отсутствует. Нет ни `status`, ни `state`, ни `version_number`, ни `published`. Модели версий вообще нет — `BusinessProcess` сам по себе является «живым» мутируемым объектом без истории версий в БД (только `simple_history.HistoricalRecords` есть на `ProcessInstance`, а не на `BusinessProcess`).

**Вывод для Task 1:** поле `version_status` добавлять некуда — версионной модели не существует. Нужно либо создать новую модель `BusinessProcessVersion`, либо добавить `status`/`version` непосредственно на `BusinessProcess`. Это ключевое расхождение с планом.

---

## 2. Связанные модели

### Task (шаблон задачи)

**Класс:** `Task` (`pdm/backend/processes/models.py`, строка 223)

Привязан к `BusinessProcess` через FK с `related_name='tasks'`. Доступ: `bp.tasks.all()`.

Ключевые поля:
- `business_process` — FK → BusinessProcess
- `name`, `description`, `order`, `priority`
- `responsible` — FK → User
- `responsible_groups` — M2M → Group
- `watchers`, `watcher_groups` — M2M → User/Group
- `readable_entity_types`, `editable_entity_types`, `hidden_entity_types` — M2M → DocumentTemplate
- `is_final` — BooleanField (финальная задача завершает ProcessInstance)
- `can_create_entity`, `creates_entity_type`, `entity_config`
- `start_condition` — OneToOne → TaskStartCondition

### TaskStartCondition

**Класс:** `TaskStartCondition` (`pdm/backend/processes/models.py`, строка 348)

OneToOne к Task через `related_name='start_condition'`. Хранит условие запуска задачи в виде:
- Старое плоское: `operator`, `field_path`, `value`
- Новое дерево: `condition_tree` (JSONField)

### ProcessLink

**Класс:** `ProcessLink` (строка 178) — связь «после какого процесса можно запустить какой». FK к BusinessProcess дважды: `source_process.outgoing_links`, `target_process.incoming_links`.

### ProcessInstance (экземпляр процесса)

**Класс:** `ProcessInstance` (строка 472) — запущенный экземпляр шаблона.

Привязан к `BusinessProcess` через `related_name='instances'`.

Статус — CharField с choices: `running | completed | cancelled | error | suspended`.

### EntitySource / EntityContract / EntityBinding / EntityContext

Система привязки сущностей (Entity) к задачам и процессам. Определены в `processes/models.py`, доступны через `processes/views/entity_views.py`. Не являются «entities» в смысле DocumentTemplate.

### DocumentTemplate / Entity

Модели сущностей живут в `pdm/backend/entities/models.py`:
- `DocumentTemplate` — тип/шаблон документа (`name` уникальный, `system_type`)
- `Entity` — экземпляр документа

Связь с БП: `DocumentTemplate` ↔ `BusinessProcess` через M2M `entity_types` / `related_name='business_processes'`.

---

## 3. Существующие эндпоинты для БП

**Базовый URL:** `/api/` (из `pdm/backend/pdm_backend/urls.py`)  
**Аутентификация:** TokenAuthentication первым, SessionAuthentication вторым (`pdm/backend/pdm_backend/settings.py`, строки 353–356). Токен передаётся как `Authorization: Token <key>`.

### Эндпоинты BusinessProcessViewSet

Зарегистрирован как `router.register(r'business-processes', BusinessProcessViewSet)` → базовый путь `/api/business-processes/`.

| Метод | URL | Описание | Права |
|-------|-----|----------|-------|
| GET | `/api/business-processes/` | Список всех БП (поиск, сортировка, фильтр `is_template`, `include_deleted`) | IsAuthenticated |
| POST | `/api/business-processes/` | Создать БП | IsSuperUser |
| GET | `/api/business-processes/{id}/` | Получить один БП (с tasks и entity_types) | IsAuthenticated |
| PUT/PATCH | `/api/business-processes/{id}/` | Обновить БП | IsSuperUser |
| DELETE | `/api/business-processes/{id}/` | Мягкое удаление БП | IsSuperUser |
| POST | `/api/business-processes/{id}/soft_delete/` | Мягкое удаление (явный action) | IsSuperUser |
| POST | `/api/business-processes/{id}/restore/` | Восстановить удалённый БП | IsSuperUser |
| POST | `/api/business-processes/{id}/copy_as_template/` | Скопировать как шаблон | IsSuperUser |
| POST | `/api/business-processes/{id}/create_from_template/` | Создать из шаблона | IsSuperUser |
| GET | `/api/business-processes/{id}/requirement_topics/` | Темы требований, связанные с БП | IsAuthenticated |
| GET | `/api/business-processes/{id}/scripts/` | Скрипты БП | IsAuthenticated |
| POST | `/api/business-processes/{id}/start_for_entity/` | Запустить БП для сущности | IsAuthenticated |
| GET | `/api/business-processes/{id}/entity-contracts/` | Контракты сущностей | IsAuthenticated |
| GET | `/api/business-processes/{id}/export_prepare/` | Подготовка к экспорту | IsSuperUser |
| POST | `/api/business-processes/{id}/export/` | Экспорт БП в ZIP | IsAuthenticated (viewset default) |

### Эндпоинты импорта

| Метод | URL | Описание | Права |
|-------|-----|----------|-------|
| POST | `/api/processes/import/preview/` | Анализ конфликтов при импорте ZIP (без записи в БД) | IsSuperUser |
| POST | `/api/processes/import/confirm/` | Применить импорт ZIP с решениями по конфликтам | IsSuperUser |

**Примечание:** URL-префикс для процессов — `path('api/', include('processes.urls'))`, а в `processes/urls.py` маршруты `import/preview/` и `import/confirm/` заданы как `path('processes/import/preview/', ...)`. Итоговый полный URL: `/api/processes/import/preview/` и `/api/processes/import/confirm/`.

### Остальные ViewSet-ы (неполный список)

- `/api/tasks/` — CRUD шаблонов задач
- `/api/process-instances/` — CRUD экземпляров процессов
- `/api/assignments/` — CRUD поручений
- `/api/process-links/` — CRUD связей БП

---

## 4. Существующий формат экспорта

Экспорт **уже реализован** (`bp_package.py`, `BPExporter.serialize_business_process`). Данные zip-пакета:

### process.json (из `BPExporter.serialize_business_process`)

```json
{
  "format_version": "1.0",
  "business_process": {
    "name": "Согласование договора",
    "description": "...",
    "is_template": true,
    "allowed_starter_groups": ["lawyers", "managers"],
    "document_template_refs": ["contract", "approval_sheet"],
    "tasks": [
      {
        "name": "Проверка юристом",
        "description": "...",
        "order": 0,
        "priority": 0,
        "is_final": false,
        "can_create_entity": false,
        "creates_entity_type": null,
        "entity_config": {},
        "readable_entity_types": ["contract"],
        "editable_entity_types": [],
        "hidden_entity_types": [],
        "start_condition": {
          "operator": "equals",
          "field_path": "contract.amount",
          "value": "100",
          "condition_tree": {},
          "order": 0
        },
        "script_bindings": [
          {
            "script_name": "check_contract",
            "script_type": "pre",
            "order": 0,
            "is_enabled": true
          }
        ]
      }
    ],
    "scripts": [
      {
        "name": "check_contract",
        "display_name": "Проверка договора",
        "description": "...",
        "status": "active",
        "code": "...",
        "requirements": ""
      }
    ]
  }
}
```

Все ссылки между компонентами — по `name`, не по `id`.

### manifest.json (из `BPExporter.build_zip`)

Содержит `format_version`, `exported_at`, имя БП, список включённых компонентов.

### document_templates/<name>.json (из `BPExporter.serialize_document_template`)

Включает полную структуру DocumentTemplate: `name`, `description`, `system_type`, `schema`, `json_schema`, `settings`, `fields[]`.

**Статус реализации дизайна (`2026-04-16-bp-export-import-design.md`):** РЕАЛИЗОВАН полностью. `BPExporter` + `BPImporter` + `ImportPreviewView` + `ImportConfirmView` — всё в production-коде. Конфликт-ревью и применение с решениями — присутствуют.

---

## 5. Чего не хватает для Etap 1

> **Историческая заметка (2026-08-23):** этот раздел — baseline Etap 1 от 2026-05-07.
> С тех пор реализованы `BusinessProcessVersion`, `import_full`/`export_full`, `pdm push`/`promote`.
> Актуальное поведение push: создаёт **опубликованное поколение** (`published`), не draft.
> Ниже сохранено как архив первоначального gap-анализа.

### Критическое: версионная модель не существует

План (Task 1–3) предполагает наличие или создание `BusinessProcessVersion` с полем `version_status`. **Такой модели нет**. Текущий `BusinessProcess` — живой мутируемый объект без явной версионности.

Варианты:
1. **Создать `BusinessProcessVersion`** — новая модель с FK → `BusinessProcess`, полями `number`, `body` (snapshot JSON), `status` (draft/testing/published/archived), `payload_hash`, `git_tag`. Самая чистая архитектура.
2. **Добавить поля версии на `BusinessProcess`** — `version_status`, `version_number`, `payload_hash`, `git_tag`. Проще, но плохо моделирует историю.

### Новые эндпоинты, которых нет

| Эндпоинт | Описание | Нужен для |
|----------|----------|-----------|
| `GET /api/business-processes/{id}/export_full/` | Полный экспорт в JSON (не ZIP) для CLI | `pdm bootstrap`, `pdm pull` |
| `POST /api/business-processes/import_full/` | Импорт из JSON (не ZIP); **сейчас** создаёт опубликованное поколение (`published`), не draft | `pdm push` |
| `POST /api/business-processes/{id}/promote/` | Публикация версии (draft → published) с записью git_tag; отдельный шаг после draft-import в раннем дизайне | `pdm promote` |
| `GET /api/business-processes/{id}/versions/` | История версий БП | просмотр истории |

**Примечание:** `export` и `import/preview` + `import/confirm` уже есть, но работают с ZIP. Для CLI нужен легковесный JSON-only вариант.

### Feature-флаг READ_ONLY_BP

Не существует нигде в codebase (`grep` по `READ_ONLY_BP` ничего не дал). Нужно добавить в `settings.py` и подключить к `get_permissions()` в `BusinessProcessViewSet`.

### Поле `payload_hash`

Нет ни на `BusinessProcess`, ни где-либо ещё. Нужно для идемпотентного push (не создавать новую версию если содержимое не изменилось).

### Поле `git_tag`

Нет. Нужно для привязки публикации к git-тегу.

---

## 6. Места в коде, где runtime читает «текущую» версию БП

**Версионной модели не существует**, поэтому нет и паттернов типа `versions.filter(status='published').first()`.

`BusinessProcess` читается напрямую по `id`:
- `pdm/backend/processes/api.py:142` — `BusinessProcess.objects.get(id=create_data.business_process_id)`
- `pdm/backend/processes/api.py:104` — `ProcessInstance.objects.select_related('business_process').get(id=process_id)`
- `pdm/backend/processes/views/business_process_views.py:22` — `BusinessProcess.objects.prefetch_related('tasks', 'entity_types').all()`
- `pdm/backend/processes/process_engine.py` — используется напрямую через `ProcessInstance.business_process` FK

Паттерны `is_active=True` существуют в коде, но относятся к другим моделям (`MCPUserToken`, `MappingRule`, `ScriptHelper`, `ScriptLibrary`, `WebhookSubscription`, `OpenProjectConfig`) — не к версиям БП.

**Вывод:** при введении версионности нужно будет обновить все точки, где `ProcessInstance` связывается с `BusinessProcess` — возможно добавить FK `source_version` → `BusinessProcessVersion`.

---

## 7. Миграции, которые понадобятся

Список изменений БД, следующих из анализа (при выборе варианта с новой моделью версии):

1. **Создать модель `BusinessProcessVersion`** — поля: `process` (FK → BusinessProcess), `number` (IntegerField), `body` (JSONField — snapshot экспорта), `status` (CharField с choices draft/testing/published/archived, default=draft, db_index=True), `payload_hash` (CharField(32), blank=True), `git_tag` (CharField(50), blank=True), `created_at`, `published_at` (nullable DateTimeField)
2. **Добавить `READ_ONLY_BP` setting** — не миграция, изменение `settings.py`
3. **Добавить `slug` на `BusinessProcess`** — если CLI будет адресовать БП по slug (а не по числовому id), нужен `SlugField(unique=True, blank=True)` + migration + автозаполнение через slugify(name)

Если выбрать упрощённый вариант (без отдельной версионной модели):

1. **Добавить на `BusinessProcess`**: `version_status` (CharField, choices draft/testing/published/archived, default=draft), `version_number` (IntegerField, default=0), `payload_hash` (CharField(32), blank), `git_tag` (CharField(50), blank), `published_at` (DateTimeField, null=True)
2. **Добавить `slug`** — аналогично выше

---

## Итог: расхождения с планом

| Допущение плана | Реальность | Риск |
|----------------|------------|------|
| Существует `BusinessProcessVersion` | Нет такой модели | CRITICAL — Task 1 написан под несуществующую модель |
| BP адресуется по slug | Только по `id`, slug отсутствует | HIGH — CLI-команды используют slug в путях файлов |
| `version_status` поле уже есть или легко добавить | Добавить можно, но сначала нужно решить: отдельная модель или поле на BP | MEDIUM |
| Экспорт/импорт ещё не реализован | Уже реализован (ZIP), но не JSON-only для CLI | LOW — переиспользуем логику `bp_package.py` |
| `READ_ONLY_BP` флаг нужно создать с нуля | Подтверждается — флага нет | LOW |

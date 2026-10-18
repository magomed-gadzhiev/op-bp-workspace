# Etap 4 Discovery — `start_for_entity` shape in sandbox

**Дата:** 2026-05-13
**Ветка:** 029-pdm-client-project-mvp
**Цель:** Зафиксировать фактический контракт `start_for_entity` action перед реализацией `pdm test` (Этап 4, Task 1).

---

## TL;DR — расхождения со спекой (2026-05-13-pdm-client-project-etap-4-scripts-tests-design.md)

Спецификация требует обновлений в нескольких местах **до начала Фазы 4 (runner)**. Ключевые расхождения:

| # | Спека говорит | Фактически | Где исправить |
|---|---|---|---|
| 1 | `POST /api/business-processes/<slug>/start_for_entity/` (строка 175) | `POST /api/business-processes/<id>/start_for_entity/` — DRF router использует `pk`, не `slug`. `BusinessProcessViewSet.lookup_field` не переопределён | Спека уже частично корректна (строка 175 говорит `<id>`, но строка 296 и формулировка задачи — `<slug>`). Привести к `<id>` везде; CLI должен ресолвить `slug → id` перед вызовом (есть `slug` на модели). |
| 2 | Payload: `{"entity": {"type": "...", "data": {}}, "input": {}}` (строки 131, 136) | Payload: `{"entity_id": <int>, "additional_entities": {"<role>": <int>, ...}}` (опционально). Поля `input` нет вообще — view его игнорирует. | Перепроектировать секцию `tests/<case>.yaml`: вместо `entity: {type, data}` и `input` нужны `entity_id` (или способ создать Entity перед стартом) + опц. `additional_entities`. Альтернатива — расширить view новым полем, но это выходит за рамки Этапа 4. |
| 3 | `final_status: completed \| failed \| cancelled` (строки 139, 175, 281) | Реальные значения `ProcessInstance.status`: `running \| completed \| cancelled \| error \| suspended`. Значения `failed` **нет**; неуспех — это `error`. Также возможен `suspended` (прервано). | В спеке `expect.final_status` и логике поллинга заменить `failed` → `error` и расширить терминальное множество до `{completed, cancelled, error}` (опц. `suspended` как infra-сигнал). |
| 4 | Поле называется `final_status` (строки 139, 175 и др.) | Поле называется `status` (см. `ProcessInstance.status` choices в models.py:494, и `ProcessInstanceSerializer.Meta.fields` в serializers.py:307). Отдельного `final_status` не существует. | В спеке `final_status` → `status`. |
| 5 | Response `start_for_entity` содержит `process_instance_id` (строка 175) | Response — полный `ProcessInstanceSerializer` payload; ID лежит в поле `id` (не `process_instance_id`). | В спеке поправить упоминание ключа: `run_id = response["id"]`. |

**Действие:** перед стартом Фазы 4 обновить `2026-05-13-pdm-client-project-etap-4-scripts-tests-design.md` (секции «YAML-формат», «Алгоритм runner'а», `last-run.json` примеры, классификация ошибок).

---

## 1. URL и lookup

**Endpoint:** `POST /api/business-processes/<pk>/start_for_entity/`

- Зарегистрирован в `pdm/backend/processes/urls.py:54` через `DefaultRouter` (`router.register(r'business-processes', BusinessProcessViewSet, basename='business-process')`).
- `BusinessProcessViewSet` (`pdm/backend/processes/views/business_process_views.py:42`) не переопределяет `lookup_field` — следовательно, используется дефолтный `pk` (integer ID).
- Подтверждено runtime-инспекцией URL resolver в работающем `pdm_backend` контейнере:

  ```
  api/^business-processes/(?P<pk>[^/.]+)/start_for_entity/$
  api/^business-processes/(?P<pk>[^/.]+)/start_for_entity\.(?P<format>[a-z0-9]+)/?$
  ```

**CLI должен** ресолвить slug → id (`GET /api/business-processes/?search=<slug>` или хранить кэш в `.pdm/`). Поле `slug` на модели существует (см. миграцию `0054_businessprocess_slug_...`), но в URL не используется.

---

## 2. Request payload

Из `business_process_views.py:174-227`:

```python
@action(detail=True, methods=['post'])
def start_for_entity(self, request, pk=None):
    business_process = self.get_object()

    entity_id = request.data.get('entity_id')               # ← REQUIRED, int
    if not entity_id:
        return Response({'error': 'Не указан entity_id'}, status=400)

    entity = Entity.objects.get(id=entity_id)               # ← 404 если не найдена

    additional_entities_data = request.data.get('additional_entities', {})  # ← OPTIONAL
    # формат: {"<role>": <entity_id_int>, ...}
    # каждая Entity резолвится по id; 404 если хоть одна не существует

    process_instance = ProcessEntityService.start_process_for_entity(
        business_process=business_process,
        entity=entity,
        user=request.user if request.user.is_authenticated else None,
        additional_entities=additional_entities if additional_entities else None,
    )
```

**Канонический body:**

```json
{
  "entity_id": 42,
  "additional_entities": {
    "contract": 17,
    "contractor": 89
  }
}
```

**Поля, которых нет:** `entity` (объект), `input`, `context`, `parameters`. Если их прислать — будут проигнорированы (DRF просто не передаст в `start_process_for_entity`).

**Валидация в service-слое** (`processes/services/process_entity_service.py:43-110`):
- Если `business_process.entity_types.exists()` и `entity.entity_type not in business_process.entity_types.all()` → `ValueError("Тип сущности 'X' не разрешен для процесса 'Y'")` → HTTP 400 с `{"error": "..."}`.

---

## 3. Response payload

**HTTP 201 Created** при успехе, тело — полный `ProcessInstanceSerializer` (`processes/serializers.py:291-317`):

```json
{
  "id": 123,
  "business_process": 7,
  "business_process_name": "...",
  "name": "<bp.name> - <entity.name>",
  "description": null,
  "status": "running",
  "primary_entity": { /* EntitySerializer */ },
  "related_entities": [ /* ProcessInstanceEntitySerializer[] */ ],
  "context_data": {},
  "entity_types_names": [ ... ],
  "assignments": [ ... ],          // только при retrieve, на create — пусто/отсутствует
  "parent_instance_id": null,
  "parent_instance_name": null,
  "child_instances": [],
  "is_deleted": false,
  "created_by": <user_id>,
  "created_at": "...",
  "updated_at": "...",
  "completed_at": null
}
```

**Ключ ID для последующего поллинга:** `response["id"]` (integer), **не** `process_instance_id`.

**Error responses:**
- `400` `{"error": "Не указан entity_id"}` — нет `entity_id`.
- `400` `{"error": "Тип сущности 'X' не разрешен ..."}` — несовместимый `entity_type`.
- `404` `{"error": "Сущность с ID N не найдена"}` — `entity_id` не существует.
- `404` `{"error": "Дополнительная сущность с ID N (роль: R) не найдена"}` — bad `additional_entities`.
- `500` `{"error": "Ошибка при запуске процесса: <exc>"}` — любое прочее.

---

## 4. Polling: `GET /api/process-instances/<id>/`

- Endpoint: `GET /api/process-instances/<pk>/` (зарегистрирован в `urls.py:57`, `ProcessInstanceViewSet`, default lookup = `pk`).
- Response: тот же `ProcessInstanceSerializer`.
- **Поле статуса:** `status` (НЕ `final_status`).
- **Choices** (из `models.py:494-505`):

  | значение | label |
  |---|---|
  | `running` | Выполняется |
  | `completed` | Завершён |
  | `cancelled` | Отменён |
  | `error` | Ошибка |
  | `suspended` | Прервано |

- Терминальные значения для runner'а: **`{completed, cancelled, error}`**. Возможно `suspended` (прервано вручную) — runner должен считать его infra-сигналом или ошибкой кейса (решить в спеке).
- `completed_at` заполняется в `completed` (использовать для расчёта длительности).
- `assignments` отдаётся в response только при action=`retrieve` (см. serializers.py:351-353 `get_assignments` проверяет `view.action`), что даёт runner'у видимость шагов БП.

---

## 5. Permissions

- `BusinessProcessViewSet.get_permissions()` (views/business_process_views.py:52-57): для `POST` (write methods) — `[BPReadOnlyPermission(), IsSuperUser()]`. **Только superuser** может вызвать `start_for_entity`.
- `ProcessInstanceViewSet` — default permission (`IsAuthenticated`). Non-superuser users видят только ProcessInstance, где они являются `created_by` или участником assignment'а.

**Следствие для CLI:** `pdm test` должен использовать токен superuser'а (или sandbox-токен с superuser-флагом). В прод-стенде это создаёт риск — отметить в спеке.

---

## 6. Smoke-call: статус и блокер

**Sandbox-стек не запускается:** `pdm-backend-sandbox` в crash-loop (`Restarting (1) X seconds ago` при `docker compose ps`). Причина:

```
django.db.utils.NotSupportedError: extension "vector" is not available
DETAIL:  Could not open extension control file "/usr/local/share/postgresql/extension/vector.control": No such file or directory.
  Applying entities.0023_enable_pgvector...
```

`pdm-postgres-sandbox` в `tools/pdm-cli/sandbox/docker-compose.sandbox.yml:23-24` использует `postgres:16-alpine` (без pgvector), но миграция `entities.0023_enable_pgvector` требует `CREATE EXTENSION vector`. **Это pre-existing bug сэндбокса, не введённый Этапом 4.** Прод `pdm_backend` использует `pgvector/pgvector:pg16` и работает.

**Что сделано вместо live smoke-call:**

1. Подтверждён URL pattern runtime-инспекцией в работающем `pdm_backend` (см. секция 1).
2. Прочитан и зафиксирован весь контракт по коду (views + serializers + service) — все ответы выше детерминированы кодом, sandbox-смок добавил бы только проверку, что код деплоится в sandbox. Учитывая, что прод и sandbox используют один и тот же образ `op-pdm-backend-sandbox` ← `op-pdm-backend`, шейп API идентичен.
3. Прод pdm-backend пустой (нет BP/Entity), создать минимальную пару BP+Entity через ORM возможно, но для discovery-документа это избыточно — контракт зафиксирован по коду.

**Что должно быть сделано до Фазы 4 (Task в плане Этапа 4 — runner):**

- **Починить `pdm-postgres-sandbox`** в `docker-compose.sandbox.yml`: сменить `image: postgres:16-alpine` → `image: pgvector/pgvector:pg16`. Это однострочное изменение; сделать его в отдельном коммите перед задачей «реализация runner».
- После починки — `docker compose ... up -d pdm-postgres-sandbox pdm-backend-sandbox` и убедиться, что миграции прогоняются.
- Опционально (низкий приоритет): добавить fixture-команду `pdm sandbox seed` создающую минимальный BP + Entity для smoke-тестов runner'а.

---

## 7. Источники

- `pdm/backend/processes/views/business_process_views.py:174-227` — action.
- `pdm/backend/processes/views/business_process_views.py:52-57` — permissions.
- `pdm/backend/processes/services/process_entity_service.py:30-110` — `start_process_for_entity`.
- `pdm/backend/processes/serializers.py:291-317` — `ProcessInstanceSerializer`.
- `pdm/backend/processes/models.py:486-505` — `ProcessInstance.status` choices.
- `pdm/backend/processes/urls.py:54,57` — DRF router registrations.
- `pdm/backend/processes/views/process_instance_views.py:25-80` — polling endpoint.
- Runtime URL-resolver inspection: `docker exec pdm_backend python manage.py shell -c "<walker>"` → confirmed `(?P<pk>...)`.
- `docker logs pdm_backend_sandbox` — pgvector blocker.

---

## 8. Live smoke (commit 681c521 + pgvector fix)

**Дата:** 2026-05-13. Sandbox-стек поднят и контракт `start_for_entity` подтверждён end-to-end.

### 8.1 URL-маршрутизация entity-эндпоинтов

Конфликт с интуитивной структурой: `entities/urls.py` подключён в корень `path('api/', include('entities.urls'))` (`pdm_backend/urls.py:46`). Поэтому **правильные URL**:

- `GET/POST /api/entity-types/` (НЕ `/api/entities/entity-types/` — запрос к последнему попытается интерпретировать `entity-types` как `pk` Entity и упасть с 500 `Field 'id' expected a number but got 'entity-types'`).
- `GET/POST /api/entities/`
- `GET/POST /api/business-processes/`
- `GET/PATCH /api/process-instances/<id>/`

### 8.2 Минимальный recipe для seed sandbox

Все шаги — superuser. Препод-условие: `docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml up -d pdm-postgres-sandbox pdm-redis-sandbox pdm-backend-sandbox` поднимает все три контейнера (postgres сейчас на `pgvector/pgvector:pg16` — миграции `entities.0023_enable_pgvector` проходят).

```bash
# 1. Superuser + token
docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml \
  exec -T pdm-backend-sandbox python manage.py shell <<'PY'
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
U = get_user_model()
u, _ = U.objects.get_or_create(username='admin', defaults={'email':'a@b.com','is_staff':True,'is_superuser':True})
u.is_staff=True; u.is_superuser=True; u.set_password('admin12345!'); u.save()
t, _ = Token.objects.get_or_create(user=u)
print("TOKEN", t.key)
PY

TOKEN=<вывод выше>

# 2. EntityType (DocumentTemplate)
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8001/api/entity-types/ \
  -d '{"name":"smoke_type","description":"E4 smoke","system_type":"document"}'
# → {"id":1, "name":"smoke_type", ...}

# 3. BusinessProcess
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8001/api/business-processes/ \
  -d '{"name":"smoke_bp","description":"E4 smoke BP"}'
# → {"id":1, "name":"smoke_bp", "tasks":[], ...}

# 4. Entity
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8001/api/entities/ \
  -d '{"entity_type":1,"name":"smoke_entity","data":{}}'
# → {"id":1, "uuid":"...", "entity_type":1, ...}

# 5. start_for_entity → 201
curl -s -X POST -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8001/api/business-processes/1/start_for_entity/ \
  -d '{"entity_id":1,"additional_entities":{}}'
# → 201 {"id":1, "status":"running", "business_process":1, ...}

# 6. Polling
curl -s -H "Authorization: Token $TOKEN" http://localhost:8001/api/process-instances/1/
# → {"id":1, "status":"running", "completed_at":null, ...}

# 7. Cancel (для smoke-теста терминального перехода)
curl -s -X PATCH -H "Authorization: Token $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8001/api/process-instances/1/ \
  -d '{"status":"cancelled"}'
# → 200 {"id":1, "status":"cancelled", ...}
```

### 8.3 Подтверждённые шейпы (live)

**`POST /api/entity-types/` (`EntityTypeViewSet`)**

- Permission: `IsAuthenticated` (default, нет явного `permission_classes`). Superuser НЕ требуется, но в реальной работе у обычного пользователя обычно нет CREATE-прав через UI.
- Required: `name`. Опционально: `description`, `system_type` (`document` / `catalog` / ... — choices, дефолт допустим), `fields` (читается). `display_name` отсутствует в OPTIONS — поле модели только в admin.
- 201 → `{"id": <int>, "name": ..., "fields": [], ...}`. Используется `id` для FK на Entity.

**`POST /api/entities/` (`EntityViewSet`)**

- Permission: `IsAuthenticated`.
- Required: `entity_type` (id). `name` — `required=False, allow_blank=True`. `data` — JSON object; обязательные поля проверяются по `entity_type.fields.filter(required=True)`. Для type без полей `data: {}` достаточно.
- 201 → `{"id": <int>, "uuid": "...", "entity_type": 1, "status": "active", ...}`.

**`POST /api/business-processes/` (`BusinessProcessViewSet`)**

- Permission: `IsSuperUser` для write-методов (подтверждено OPTIONS работает только под admin).
- Required: `name` (CharField, max 255).
- 201 → `{"id": <int>, "name": ..., "tasks": [], ...}`. У пустого BP `tasks: []`.

**`POST /api/business-processes/<id>/start_for_entity/`** (подтверждение Section 2)

- Permission: `IsSuperUser`.
- Live request `{"entity_id":1,"additional_entities":{}}` → **HTTP 201**, body — полный `ProcessInstanceSerializer`. Подтверждено, что ID лежит в `id` (не `process_instance_id`).
- `status` создаётся как `"running"`. `context_data` содержит `{"primary": {"_entity_id": ..., "_entity_name": ..., "_entity_type": ...}}` (новое наблюдение — не упомянуто в спеке).

**`GET /api/process-instances/<id>/`** (поллинг)

- Permission: `IsAuthenticated`. Created superuser видит все.
- Choices `status` (подтверждено через OPTIONS): `running | completed | cancelled | error | suspended` — точно как в коде. **Поля `failed` НЕТ.**
- `completed_at` — `null` при `running` и `cancelled`; заполняется только при `completed` (см. service-слой, требует verify отдельно).

### 8.4 Ключевые наблюдения для runner'а (Этап 4 Task 11)

1. **Пустой BP (нет tasks) НЕ авто-завершается** — `status` остаётся `running` бесконечно. Это означает, что smoke-кейсы для runner'а должны либо:
   - Использовать BP с реальными tasks, которые автокомплитят (требует seed-комбинации task+condition+executor — выходит за рамки smoke), ИЛИ
   - Иметь явный шаг "cancel" в YAML (PATCH `status=cancelled`) для перевода в терминал, ИЛИ
   - Поддерживать timeout с классификацией `running-after-timeout` как infra-ошибку (вариант для design-spec).

   **Рекомендация:** в дизайне runner'а добавить `expect.timeout_status` (что считать терминалом, если ничего не пришло за N сек). Это нужно зафиксировать в спеке Этапа 4.

2. **Cancel via PATCH работает** (`PATCH /api/process-instances/<id>/ {"status":"cancelled"}` → 200). НЕ требуется dedicated `cancel` action. Это полезно для runner'а как teardown-ритуал, чтобы оставлять sandbox чистым.

3. **Гибридный YAML вариант C — implementation notes:**
   - При `entity: {type, fields: {...}}` runner должен:
     - Сначала зарезолвить `type` (slug/name) в `entity_type_id` через `GET /api/entity-types/?search=<type>` (затем выбрать ровно один результат, иначе `ambiguous`).
     - Затем `POST /api/entities/ {"entity_type":<id>, "name":<auto-generated>, "data":<fields>}`.
     - Извлечь `id` из 201-response.
     - Передать как `entity_id` в `start_for_entity`.
   - Опционально — пометить созданную сущность для cleanup'а (например, имя с префиксом `pdm-test-<run-id>-`).

4. **MinIO не нужен для smoke** — `pdm_backend_sandbox` логирует ошибку `init_minio_bucket` (`localhost:9000` недоступен), но это non-fatal; API работает. Если runner будет тестировать BP, которые создают файлы, MinIO придётся поднимать. Для базового `pdm test` Этапа 4 — не блокер.

### 8.5 Дельты к спеке Этапа 4 (дополнительно к Section TL;DR)

| # | Дельта | Куда |
|---|--------|------|
| 6 | URL для создания entity — `/api/entities/`, для entity-type — `/api/entity-types/` (НЕ `/api/entities/entity-types/`). | YAML-секция "entity creation" в design-spec |
| 7 | Пустой BP → `running` без завершения. Runner должен иметь timeout + ритуал cancel (PATCH `{"status":"cancelled"}`). | Алгоритм runner'а |
| 8 | `context_data.primary` (с `_entity_id/_entity_name/_entity_type`) — потенциально полезно для assertions в YAML. | Опционально расширить `expect.context_data` |
| 9 | `IsAuthenticated` достаточно для CREATE `entity-types`/`entities`, но `business-processes` и `start_for_entity` требуют `IsSuperUser`. | Секция Permissions: уточнить, что CLI-токен должен быть superuser. |

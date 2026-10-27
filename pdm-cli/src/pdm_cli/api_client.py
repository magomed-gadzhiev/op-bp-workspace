"""HTTP client for PDM API."""

import json

import httpx

from .models import Process


class SandboxLockConflict(RuntimeError):
    def __init__(self, body: dict):
        self.body = body
        super().__init__(body.get("error") or "sandbox override lock conflict")


class PdmApiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        cli_bypass_secret: str = "",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=self._default_headers(api_key, cli_bypass_secret),
        )

    @staticmethod
    def _default_headers(api_key: str, bypass: str) -> dict[str, str]:
        h = {"Authorization": f"Token {api_key}"}
        if bypass:
            h["X-Pdm-Cli-Bypass"] = bypass
        return h

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- API methods ----

    def list_processes(self) -> list[dict]:
        """Returns the list of BPs (raw dicts as returned by the API).

        DRF ``ConfigurablePageNumberPagination`` defaults to 20/page. Without
        following ``next``, find_bp_pk / slug-collision checks miss later pages.
        ``next`` не берётся дословно: сервер строит абсолютный URL без префикса
        маунта ( srv-dkr-01/api/... вместо srv-dkr-01/pdm/api/...), страница 2
        давала 404 (дрилл 2026-10-19). Переносим только query-параметры
        (page, slug, …) на наш базовый путь.
        """
        collected: list[dict] = []
        from urllib.parse import urlparse

        url: str | None = "/api/business-processes/"
        seen: set[str] = set()
        for _ in range(100):
            if not url or url in seen:
                break
            seen.add(url)
            r = self._client.get(url)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "results" in data:
                collected.extend(data["results"])
                nxt = data.get("next")
                if not nxt:
                    url = None
                else:
                    query = urlparse(nxt).query
                    url = "/api/business-processes/" + (f"?{query}" if query else "")
            else:
                return data
        return collected

    def get_full(self, slug: str, version: int | None = None) -> Process:
        """Fetch full BP definition. Returns Process model."""
        params = {"version": version} if version is not None else None
        r = self._client.get(
            f"/api/business-processes/{slug}/full/", params=params
        )
        r.raise_for_status()
        return _process_from_full_response(r.json())

    def import_full(self, process: Process) -> Process:
        """Push a Process (as R2 payload) → server creates new draft version."""
        slug = process.manifest.slug
        # Strip version/status from manifest — server assigns them on response
        payload = process.model_dump()
        payload["manifest"].pop("version", None)
        payload["manifest"].pop("status", None)
        r = self._client.post(
            f"/api/business-processes/{slug}/import_full/", json=payload
        )
        r.raise_for_status()
        return _process_from_full_response(r.json())

    def promote(self, slug: str, version: int, tag: str) -> Process:
        """Promote draft version → published."""
        r = self._client.post(
            f"/api/business-processes/{slug}/promote/",
            json={"version": version, "tag": tag},
        )
        r.raise_for_status()
        return _process_from_full_response(r.json())

    # ---- Пакетный путь (git-declared, DB-materialized) ----
    # ZIP-пакет — единственный путь ПОЛНОЙ фидельности определений БП:
    # граф+условия+биндинги, скрипты, шаблоны документов, справочники,
    # табличные части. /full/+/import_full/ переносит только FSM-lite
    # подмножество (name/order/kind/config) — для ЛЭМ/UI150 это потеря.

    def find_bp_pk(self, slug: str) -> int:
        """pk бизнес-процесса по слагу (export-эндпоинт адресуется по pk)."""
        for item in self.list_processes():
            if item.get("slug") == slug:
                return int(item["id"])
        raise LookupError(f"BP with slug '{slug}' not found on server")

    def export_package(self, slug: str, version: int | None = None) -> bytes:
        """POST /api/business-processes/<pk>/export/ → zip-пакет (bytes).

        version — ZIP поколения конкретной версии (спека 143, W3: экспорт
        testing-версии); None — действующее определение (прежнее поведение).
        """
        pk = self.find_bp_pk(slug)
        params = {"version": version} if version is not None else None
        r = self._client.post(
            f"/api/business-processes/{pk}/export/", params=params
        )
        r.raise_for_status()
        return r.content

    def bp_versions(self, slug: str) -> dict:
        """GET /api/business-processes/<slug>/versions/ — реестр версий БП.

        Список версий + diff-сводка testing vs published (спека 143, W2).
        """
        r = self._client.get(f"/api/business-processes/{slug}/versions/")
        r.raise_for_status()
        return r.json()

    def draft_import(
        self, slug: str, zip_bytes: bytes, filename: str = "bp.zip",
    ) -> dict:
        """POST /api/business-processes/<slug>/draft-import/ — шов ИИ
        (спека 143, W2, ADR-0059): создание/замена testing-версии из ZIP.

        422 draft_validation_failed возвращается как dict с errors, а не
        исключением (как 409 у import_confirm) — список ошибок нужен агенту.
        """
        r = self._client.post(
            f"/api/business-processes/{slug}/draft-import/",
            files={"file": (filename, zip_bytes, "application/zip")},
        )
        if r.status_code == 422:
            return r.json()
        r.raise_for_status()
        return r.json()

    def import_preview(self, zip_bytes: bytes, filename: str = "bp.zip") -> dict:
        """POST /api/processes/import/preview/ — dry-run конфликт-отчёт."""
        r = self._client.post(
            "/api/processes/import/preview/",
            files={"file": (filename, zip_bytes, "application/zip")},
        )
        r.raise_for_status()
        return r.json()

    def import_confirm(
        self,
        zip_bytes: bytes,
        decisions: dict | None = None,
        *,
        confirm_prod: bool = False,
        filename: str = "bp.zip",
    ) -> dict:
        """POST /api/processes/import/confirm/ — применить пакет.

        409 (prod-гейт без confirm_prod) возвращается как dict с
        requires_prod_confirmation=True, а не исключением.
        """
        data = {"decisions": json.dumps(decisions or {})}
        if confirm_prod:
            data["confirm_prod"] = "true"
        r = self._client.post(
            "/api/processes/import/confirm/",
            files={"file": (filename, zip_bytes, "application/zip")},
            data=data,
        )
        if r.status_code == 409:
            # prod-гейт: сервер вернул конфликт-отчёт, ничего не записав
            return r.json()
        r.raise_for_status()
        return r.json()

    # ---- Read-only methods (Etap 6 C4.3) ----

    def health(self) -> dict:
        r = self._client.get("/api/health/")
        r.raise_for_status()
        return r.json()

    # ---- Замечания по инструменту (спека 166, ADR-0073) ----

    def submit_feedback(self, payload: dict) -> tuple[int, dict]:
        """POST /api/feedbacks/submit/ → (status_code, body).

        Не бросает на 4xx: CLI сам объясняет 401/409/422/429.
        """
        r = self._client.post("/api/feedbacks/submit/", json=payload)
        try:
            body = r.json()
        except ValueError:
            body = {"detail": r.text[:500]}
        return r.status_code, body

    def list_feedback(self, params: dict | None = None) -> list[dict]:
        """GET /api/feedbacks/ с пагинацией (next — только query-параметры)."""
        from urllib.parse import urlencode, urlparse

        collected: list[dict] = []
        query = urlencode(
            {k: v for k, v in (params or {}).items() if v is not None})
        url = "/api/feedbacks/" + (f"?{query}" if query else "")
        seen: set[str] = set()
        for _ in range(100):
            if not url or url in seen:
                break
            seen.add(url)
            r = self._client.get(url)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "results" in data:
                collected.extend(data["results"])
                nxt = data.get("next")
                url = ("/api/feedbacks/?" + urlparse(nxt).query
                       if nxt else None)
            else:
                return data
        return collected

    # ---- Верификационные decks (Волна 1, ADR-0012) ----

    def decks_import(self, decks: list[dict], *, confirm: bool = True) -> dict:
        """Материализация decks из git (POST /api/verification/decks/import/)."""
        r = self._client.post(
            "/api/verification/decks/import/",
            json={"decks": decks, "confirm": confirm},
        )
        r.raise_for_status()
        return r.json()

    def decks_drift(self, decks: list[dict]) -> dict:
        """Сверка git-decks с БД (POST /api/verification/decks/drift/)."""
        r = self._client.post("/api/verification/decks/drift/", json={"decks": decks})
        r.raise_for_status()
        return r.json()

    def list_runs(
        self, bp_slug: str, *,
        since: str | None = None, until: str | None = None,
        status: str | None = None, limit: int = 50, offset: int = 0,
    ) -> dict:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if status:
            params["status"] = status
        r = self._client.get(f"/api/business-processes/{bp_slug}/runs/", params=params)
        r.raise_for_status()
        return r.json()

    def run_details(
        self, run_id: int | str, *, include_script_output: bool = False,
    ) -> dict:
        """GET /api/process-instances/<id>/details/.

        Etap 7: pass ``include_script_output=True`` to request sandbox-only
        script output (server adds it to the response under the
        ``script_output`` key when allowed).
        """
        params: dict[str, str] = {}
        if include_script_output:
            params["include_script_output"] = "1"
        r = self._client.get(
            f"/api/process-instances/{run_id}/details/",
            params=params or None,
        )
        r.raise_for_status()
        return r.json()

    def create_process_instance(self, payload: dict) -> dict:
        """POST /api/process-instances/ — создать и запустить экземпляр.

        Тестовый прогон (спека 143 W5 / 163 §4.3): payload несёт
        ``business_process`` (pk БП) и ``source_version`` (PK testing-версии
        из /versions/ — шов принимает PK, не номер); сервер сам выставляет
        ``is_test_run=True`` и пиннит поколение. Возвращает сериализованный
        экземпляр (id, status, …).
        """
        r = self._client.post("/api/process-instances/", json=payload)
        r.raise_for_status()
        return r.json()

    def run_aggregates(
        self, *, bp_slug: str | None = None,
        since: str, until: str | None = None,
    ) -> dict:
        """GET /api/runs/aggregates/ for cross-run telemetry summaries."""
        params: dict[str, str] = {"since": since}
        if bp_slug:
            params["bp"] = bp_slug
        if until:
            params["until"] = until
        r = self._client.get("/api/runs/aggregates/", params=params)
        r.raise_for_status()
        return r.json()

    def run_trends(self, *, bp_slug: str | None = None, weeks: int = 8) -> dict:
        """GET /api/runs/trends/ — weekly run_count / success_rate timeseries."""
        params: dict[str, str] = {"weeks": str(weeks)}
        if bp_slug:
            params["bp"] = bp_slug
        r = self._client.get("/api/runs/trends/", params=params)
        r.raise_for_status()
        return r.json()

    def get_entity_schema(self, bp_slug: str, entity_slug: str) -> dict:
        r = self._client.get(
            f"/api/business-processes/{bp_slug}/entities/{entity_slug}/schema/",
        )
        r.raise_for_status()
        return r.json()

    def validate_script_syntax(self, code: str) -> dict:
        """POST /api/admin/processes/script/validate-syntax/ — ast-проверка.

        Тот же эндпоинт, что в редакторе скриптов админки PDM:
        ``{valid: bool, errors: [{line, column, message, text}]}``.
        """
        r = self._client.post(
            "/api/admin/processes/script/validate-syntax/",
            json={"code": code},
        )
        r.raise_for_status()
        return r.json()

    # ---- Публикации форм (спека 171, ADR-0079) ----

    def ef_publications(self) -> list[dict]:
        """GET /api/external-forms-admin/publications/ — листинг публикаций.

        Суперюзеру видны все, издателю — его (``admin_users``); PAT read
        проходит (SAFE), publish/переходы закрыты энфорсером на сервере.
        """
        r = self._client.get("/api/external-forms-admin/publications/")
        r.raise_for_status()
        data = r.json()
        return data.get("results") if isinstance(data, dict) else data or []

    def ef_schema_preview(self, pk: int) -> dict:
        """GET /api/external-forms-admin/publications/<pk>/schema-preview/."""
        r = self._client.get(
            f"/api/external-forms-admin/publications/{pk}/schema-preview/")
        r.raise_for_status()
        return r.json()

    def ef_patch_publication(self, pk: int, payload: dict) -> dict:
        """PATCH /api/external-forms-admin/publications/<pk>/ — правки
        оверлея/метаданных (PAT draft; ADR-0079 п.2)."""
        r = self._client.patch(
            f"/api/external-forms-admin/publications/{pk}/", json=payload)
        r.raise_for_status()
        return r.json()

    # ---- Etap 7 — sandbox / replay helpers ----

    def replay_step(
        self, run_id: str, step_id: str,
        input_overrides: dict | None = None,
        override_owner: str | None = None,
    ) -> dict:
        """Etap 7 — POST /api/process-instances/<id>/replay_step/.

        Triggers a sandbox replay of a single step with optional input
        overrides. Server returns the executed step result.
        """
        headers = None
        if override_owner:
            headers = {"X-PDM-Override-Owner": override_owner}
        r = self._client.post(
            f"/api/process-instances/{run_id}/replay_step/",
            json={
                "step_id": step_id,
                "input_overrides": input_overrides or {},
                "dry_run": True,
            },
            headers=headers,
            timeout=120,
        )
        if r.status_code == 409:
            raise SandboxLockConflict(r.json())
        r.raise_for_status()
        return r.json()

    def replay_chain(self, run_id: int | str) -> dict:
        """GET /api/process-instances/<id>/replay-chain/ — Etap 9 C2.

        Returns the full replay chain (root + all derived replays) with
        depth indicators for visualization.
        """
        r = self._client.get(f"/api/process-instances/{run_id}/replay-chain/")
        r.raise_for_status()
        return r.json()

    def entity_clone_with_overrides(
        self, entity_id: int, field_overrides: dict,
    ) -> dict:
        """Etap 7 — composite GET + POST: clone an entity with merged data.

        Fetches ``/api/entities/<id>/``, merges ``field_overrides`` into the
        source ``data`` payload, and POSTs a new entity of the same
        ``entity_type``. Returns the freshly created entity.
        """
        r = self._client.get(f"/api/entities/{entity_id}/", timeout=15)
        r.raise_for_status()
        src = r.json()
        merged = dict(src.get("data") or {})
        merged.update(field_overrides or {})
        r2 = self._client.post(
            "/api/entities/",
            json={"entity_type": src["entity_type"], "data": merged},
            timeout=15,
        )
        r2.raise_for_status()
        return r2.json()


def _process_from_full_response(data: dict) -> Process:
    """Convert /full/ endpoint response (snapshot_json + version metadata) to Process model.

    The endpoint returns the snapshot shape (`{"manifest", "entities", "tasks"}`
    for new snapshots OR `{"manifest", "business_process": {...}}` for legacy
    snapshots from migration 0055). We coerce to the R2 shape that Process expects.
    """
    manifest_raw = dict(data.get("manifest") or {})
    entities_raw = list(data.get("entities") or [])
    tasks_raw = list(data.get("tasks") or [])
    scripts_raw = list(data.get("scripts") or [])

    # Legacy fallback: legacy snapshots have everything inside `business_process`
    # (per migration 0055 in PDM Task 1). If we see no entities/tasks at top
    # level but a `business_process` key, leave entities/tasks empty (they won't
    # round-trip cleanly anyway — user should re-push to normalize the shape).
    return Process.model_validate({
        "manifest": manifest_raw,
        "entities": entities_raw,
        "tasks": tasks_raw,
        "scripts": scripts_raw,
    })

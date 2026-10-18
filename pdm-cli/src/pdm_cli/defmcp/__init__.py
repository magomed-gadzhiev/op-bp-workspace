"""Chat-edit MCP server для определений БП (спека 143, ADR-0059).

Цикл агента: bp_draft_from_server (или bp_new_process) → правки файлов в
workspace черновиков (MCP_BP_DRAFTS_ROOT) → bp_compile → bp_draft_save —
тестовая версия БП в БД PDM. Git не участвует (Д8); запись — только в
тестовую версию через отдельный шов draft-import (узкое переоткрытие
ADR-0017 п.4, спека 067 не тронута); публикация — человек в админке PDM.
"""

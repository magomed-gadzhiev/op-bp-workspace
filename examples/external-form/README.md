# Пример: моделирование публикации формы (спека 171, ADR-0079)

Живой пример конфигурации для цикла `pdm ws forms` — состав полей,
порядок и переименования. Это учебная копия: настоящие файлы выгружает
`pdm ws forms init <slug>` в `workspace/forms/<slug>/`.

## Файлы

- `publication.yaml` — редактируемая конфигурация публикации: заголовок,
  интро, лимит инлайна каталогов и **оверлей** (состав полей `fields`,
  порядок `order`, переименования `renames`, справка `help_overrides`,
  скрипты сабмита `submit_scripts`).
- `fields.yaml` — READ-ONLY манифест public-полей базовой формы
  (EntityType): допустимые имена для оверлея. Пересоздаётся
  `pdm ws forms init`, руками не правится.

## Цикл

```bash
pdm ws forms list                     # доступные публикации
pdm ws forms init demo-external-api  # выгрузка в workspace/forms/…
# …правка publication.yaml…
pdm ws forms check                    # имена/дубли/схема (офлайн)
pdm ws forms diff demo-external-api   # что уйдёт в push
pdm ws forms push demo-external-api   # черновой оверлей на сервер (PAT draft)
pdm ws forms preview demo-external-api  # сводка схемы, отличие от активной версии
```

Публикация версии («Опубликовать (минор)» / «Новый мажор»), переходы
версий, гранты и токены — только человек в PDM UI, раздел «Публикации
форм» (`/pdm/management/external-forms`): PAT воркспейса получит 403
`token_scope` — это серверный инвариант.

## Что важно помнить

- `overlay.fields: []` (пустой состав) — ошибка check: публикация
  станет unpublishable (схема пуста).
- Правки оверлея до publish внешнее приложение **не видит**: потребитель
  читает только опубликованные снимки версий.
- Имена полей — только из `fields.yaml`; незнакомое имя — ошибка check,
  а не молчаливое отбрасывание.

---
name: pdm-create-process
description: Use when creating a NEW business process from scratch — interview the analyst, scaffold via `pdm new-bp`, fill in, validate, commit. Применять, когда нужно завести новый бизнес-процесс с нуля. Triggers / триггеры — "create a new business process", "scaffold a new BP from scratch", «создай новый бизнес-процесс», «заведи новый BP». Anti-trigger: не для правки уже существующего процесса — для этого pdm-edit-process.
---

## Purpose

Use this skill when the user asks to **create**, **add**, **start**, or build a **new** business
process **from scratch** — i.e. one that does not exist yet under `processes/`. Invoke when the user
says "create", "new", "add a", or "from scratch" in the context of a business process.

This is distinct from `pdm-edit-process`, which modifies an **existing** BP (triggers: "edit",
"change", "update", "fix"). If the process already exists, stop and use `pdm-edit-process` instead —
do not overwrite.

## Preconditions

- Working directory is the client-project repository root (it has a `processes/` directory)
- `pdm` CLI is available (`pdm --version` works)
- `git` is available in PATH
- The intended BP slug does **not** already exist under `processes/<slug>/`

## Steps

1. **Interview the analyst** before creating any files. Gather at minimum:
   - **slug** — lowercase, hyphenated identifier matching `[a-z0-9][a-z0-9-]*[a-z0-9]` (e.g. `invoice-intake`)
   - **human-readable name** — the manifest `name` (e.g. "Invoice Intake")
   - **description** — one or two sentences on what the process does
   - **intended entities and tasks** — the data shapes and the steps the process will perform

   If the analyst cannot articulate the purpose, the entities, or the tasks, **stop and clarify**
   before generating anything.

2. **Scaffold via the CLI** — run the generator; do **not** hand-write the directory layout:

   ```
   pdm new-bp <slug> --name "<name>" --description "<description>"
   ```

   This creates `processes/<slug>/` with a populated `manifest.yaml`, a placeholder task, and empty
   `fixtures/`, `tests/`, and `decisions/` directories. `pdm new-bp` is the single source of truth
   for the skeleton layout — always defer file creation to it.

3. **Fill in the skeleton** based on the interview: replace the placeholder task with the real
   tasks, add entities, and record any initial design rationale under `decisions/`.

4. **Validate**: run `pdm validate --bp <slug>` and fix any reported errors before committing.

5. **Commit**: stage and commit with a descriptive message referencing the BP slug and intent.

## Red Flags — Stop and Ask

- **Slug already exists**: if `processes/<slug>/` is present, do NOT overwrite. Stop and confirm
  whether the user meant to edit the existing BP (use `pdm-edit-process`) or pick a different slug.

- **Vague purpose or unknown entities/tasks**: if the analyst cannot describe what the process does
  or what data and steps it involves, stop and clarify — do not generate a skeleton on guesswork.

- **Duplicates an existing process**: if the requested process overlaps an existing BP, confirm the
  intent before creating a near-duplicate.

## Post-Conditions

- A new `processes/<slug>/` directory exists, created via `pdm new-bp`
- `pdm validate` passes with no errors
- Changes are committed with a clear message
- Nothing is pushed to `origin` without explicit owner confirmation

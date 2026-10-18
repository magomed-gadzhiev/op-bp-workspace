---
name: pdm-promote-release
description: Use when promoting a release — validate, test, tag and promote, with --skip-gate explanation and a dirty-tree guard. Применять, когда нужно продвинуть релиз в prod. Triggers / триггеры — "promote the release", "tag and promote to prod", «продвинь релиз», «протегируй и выкати в прод».
---

## Purpose

Use this skill when the agent needs to promote a release tag to the PDM client environment.
It ensures the working tree is clean, all gates pass, and the git tag is valid before calling
`pdm promote`. Invoke this skill when the user says "release", "promote", or "push to prod".

## Preconditions

- `pdm` CLI is installed and configured (`pdm --version` works)
- `git` is available in PATH
- Working directory is the client-project repository root
- User has provided (or confirmed) the target version tag (e.g. `v1.4.0`)

## Steps

1. **Validate**: Run `pdm validate` — fix any reported errors before proceeding.

2. **Run full test suite**: Run `pdm test --all` — all tests must pass; do not proceed if any fail.

3. **Check working tree**: Run `git status` — the working tree MUST be clean (no staged or unstaged changes).
   - If the tree is dirty: stop, list the uncommitted files, and ask the user whether to commit or stash them before continuing.
   - If the tag already exists locally: run `git tag -l vX.Y.Z` — if the tag is listed, **stop and warn** the user. Do NOT re-tag or force-push; ask the user to confirm intent before any tag operation.

4. **Create git tag**: Run `git tag vX.Y.Z` (substitute the actual version).

5. **Promote**: Run `pdm promote <tag>` (e.g. `pdm promote v1.4.0`).

### --skip-gate flag

`pdm promote` accepts `--skip-gate` to bypass the pre-promote validation gate.

**Use only when**:
- The gate is broken due to an infrastructure issue unrelated to the release content
- A hotfix must ship immediately and the gate failure is a known false positive
- An authorised team lead has explicitly approved skipping

**Risks of --skip-gate**:
- Unvalidated manifest or schema changes may reach production
- Broken business-process definitions can corrupt live data
- Gate skips are not logged in the audit trail — document them manually in `decisions/`

## Post-Conditions

- `pdm validate` passed with no errors
- `pdm test --all` passed with no failures
- Git tag `vX.Y.Z` exists locally
- `pdm promote <tag>` exited 0
- The promoted release is visible in the PDM backend

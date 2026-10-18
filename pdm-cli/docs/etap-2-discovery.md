# Etap 2 — Discovery notes (egress proxy + fixtures)

Concrete extension points in the existing pdm-cli codebase that the Etap 2
tasks (egress proxy, replay, fixtures, PII redaction) will hook into. Line
numbers refer to the state at commit `023a09c` on branch
`029-pdm-client-project-mvp`.

Branch choice for Etap 2: continue on `029-pdm-client-project-mvp`
(Etap 1 closing commit `023a09c` not yet merged to master). New commits
stack on top; we'll merge the whole stack in one PR at the end of Etap 2.

---

## 1. Where commands are registered (`pdm_cli/cli.py`)

File: `tools/pdm-cli/src/pdm_cli/cli.py` — 31 lines total. Single Click group
`main` with one-line `main.add_command(...)` per command.

```
 9  from .commands import bootstrap as bootstrap_cmd, diff as diff_cmd, \
        promote as promote_cmd, pull as pull_cmd, push as push_cmd, \
        validate as validate_cmd
…
21  main.add_command(bootstrap_cmd)
22  main.add_command(diff_cmd)
23  main.add_command(promote_cmd)
24  main.add_command(pull_cmd)
25  main.add_command(push_cmd)
26  main.add_command(validate_cmd)
```

Note: each command module exports a Click object at module level (not
`from .commands.bootstrap import bootstrap`); the import alias style is
`bootstrap as bootstrap_cmd`. The new `fixtures` group should follow the
same convention:

1. Add a new file `tools/pdm-cli/src/pdm_cli/commands/fixtures.py` that
   defines `fixtures = click.Group(name="fixtures")` and registers
   subcommands (`fixtures record`, `fixtures replay`, `fixtures redact`,
   etc.) on that group.
2. In `cli.py` add to the import line: `fixtures as fixtures_cmd`.
3. Add `main.add_command(fixtures_cmd)` next to the others (keep
   alphabetical order: it goes between `diff_cmd` and `promote_cmd`).

The `ctx.obj` contract is `{"cwd": Path}` (set on line 18). All existing
commands read `ctx.obj["cwd"]` to locate the repo root — `fixtures`
subcommands must do the same so that `CliRunner(..., obj={"cwd": tmp_path})`
in tests keeps working.

---

## 2. Where to add `egress:` config parsing (`pdm_cli/config.py`)

File: `tools/pdm-cli/src/pdm_cli/config.py` — 83 lines. Loader is a single
function `load_config(repo_root)` at line 46. Currently parses two sections:

- `endpoints:` (line 56, required)
- `.pdm/secrets.yaml` (line 60–64, optional)

Extension point for Etap 2:

- **Schema change:** add an optional top-level `egress:` block to
  `pdm.config.yaml`. Shape (proposed):
  ```yaml
  egress:
    mode: direct | hoverfly | ssh-bastion | replay
    hoverfly_url: http://localhost:8500       # for hoverfly/replay
    simulation_file: .pdm/egress/simulation.json
    ssh_bastion:                              # only for ssh-bastion
      host: bastion.customer.example
      user: pdm-egress
      key_path: .pdm/secrets/bastion-ed25519
    redact:                                   # PII redaction rules
      - field: "$.tasks[*].assignee.email"
        replacement: "<redacted-email>"
      - regex: "[A-Z]{2}\\d{6,}"              # passport-like numbers
        replacement: "<redacted-id>"
  ```
- **Dataclass change:** extend `Config` (line 21) with a new field
  `egress: EgressConfig | None = None`. Define `EgressConfig` as a sibling
  `@dataclass` in the same file (keeps imports thin; no Pydantic needed
  here — the project already keeps `config.py` plain-dataclass).
- **Loader change:** after the existing `endpoints` block on line 56, add
  a parser for `cfg_data.get("egress")`. Validate `mode` against an enum
  and raise `ConfigError` on unknown values. Pass to `Config(..., egress=...)`
  on line 77.
- **Secrets indirection:** SSH key path and any per-bastion passphrase
  should go in `.pdm/secrets.yaml` (same indirection pattern as
  `api_key_<env>` on lines 66–70), referenced by name from `egress:`. Add
  helper `Config.egress_secret(name)` mirroring `api_key()` (line 35).

The `bootstrap.py` `CONFIG_TEMPLATE` already mentions egress in a
placeholder comment on line 30 — replace that with a real (commented-out)
example once the schema lands.

---

## 3. Reusable test scaffolding (CliRunner + tmp_path + ruamel.yaml)

Pattern used everywhere: `CliRunner().invoke(main, [...], obj={"cwd": tmp_path})`.
No conftest helpers yet — each test file inlines its own copy of `_prep` /
`_stage_repo`. **Don't refactor these in Etap 2 unless adding a fixtures-
specific helper module is cleaner** — the duplication is intentional and
isolated. Examples to copy from:

- `tests/test_command_validate.py` lines 9–18: `_stage_repo(tmp_path)`
  copies `tests/fixtures/sample-repo` into `tmp_path` with
  `shutil.copytree(..., dirs_exist_ok=True)` and writes a minimal
  `pdm.config.yaml`. Best template for "I need a valid repo on disk".
- `tests/test_command_push.py` lines 14–23: `_prep(tmp_path)` extends
  that with a `.pdm/secrets.yaml` containing
  `api_key_prod`, `api_key_sandbox`, `cli_bypass_secret`. Best template
  for tests that need authenticated calls.
- `tests/test_command_bootstrap.py` lines 11–34: uses `@respx.mock` to
  stub HTTP and asserts on files written. Best template for tests of
  commands that talk to the PDM API. Fixture tests for Etap 2 will mock
  Hoverfly's Admin API the same way.
- `tests/test_config.py`: direct tests of `load_config()` — extend in
  Task ≥3 with `egress:` parsing cases.

All YAML reads use `ruamel.yaml.YAML(typ="safe")` (see `config.py:52`).
Tests usually write YAML with plain `Path.write_text(...)` rather than
ruamel — that's fine and faster; reserve ruamel for round-trip preservation.

---

## 4. Existing fixtures (`tests/fixtures/sample-repo/`)

Current layout (one BP, minimal):

```
tests/fixtures/sample-repo/
└── processes/
    └── payroll/
        ├── manifest.yaml
        ├── entities/
        │   └── employee.yaml
        └── tasks/
            └── calc-bonus.yaml
```

This is sufficient for `validate`, `push`, `diff`, `promote` smoke tests as
they exist today. For Etap 2 we need extra fixtures specifically for
egress/redaction tests; **add them alongside, do not mutate the existing
shape** (it would break ~30 assertions). Proposed additions when Task ≥4
lands:

- `tests/fixtures/with-pii/` — a BP whose entities/tasks contain emails,
  phone numbers, and passport-like IDs, used to verify redaction rules.
- `tests/fixtures/hoverfly-simulations/payroll-full.json` — a recorded
  Hoverfly simulation of a clean `bootstrap` → `validate` → `push` cycle,
  used to drive replay-mode CI tests without a live PDM container.

---

## 5. Existing CLI commands (one-liners)

From `tools/pdm-cli/src/pdm_cli/commands/`:

- **`bootstrap.py`** — initializes a fresh client-project repo: writes
  `pdm.config.yaml`, `.pdm/secrets.yaml`, `.gitignore`, packaged
  `README.md`, then pulls all published BPs from prod into
  `processes/<slug>/`. Refuses if repo already initialized.
- **`validate.py`** — runs the local schema/lint pipeline over
  `processes/**/*.yaml` (manifest slug pattern, status enum, cross-refs).
  Pure-local, no network. Used by CI and pre-commit.
- **`pull.py`** — fetches the current state of one or more BPs from a
  given endpoint (`--from prod|sandbox`) and overwrites local files.
  Inverse of push for keeping in sync after manual edits in PDM UI.
- **`push.py`** — uploads local BPs to **sandbox only** (refuses `--to prod`,
  see `test_push_refuses_to_prod`). Sends `X-Pdm-Cli-Bypass` header
  carrying `cli_bypass_secret` so PDM accepts the import.
- **`promote.py`** — copies a BP from sandbox to prod via the PDM
  promote endpoint. The only sanctioned route to production data.
- **`diff.py`** — shows the diff between local files and a remote
  endpoint without writing anything. Read-only counterpart of push.

Etap 2 doesn't replace any of these; it adds a new `fixtures` group that
sits *underneath* them (proxying their HTTP calls through Hoverfly or an
SSH tunnel based on `egress.mode`).

---

## Lessons learned / Surprises during Etap 2 implementation

Concrete things that diverged from the plan or surfaced unexpectedly:

1. **Hoverfly round-trip converter needed glob-wildcard strip (Task 4).** Hoverfly simulation JSON stores URL patterns with trailing `*` glob wildcards in capture mode. When converting simulation → HttpFixture → simulation for replay, those wildcards caused Hoverfly to return 502 instead of the recorded response. The converter now explicitly strips trailing wildcards before writing to HttpFixture YAML.

2. **Bastion env vars moved to function-time loading for testability (Task 12).** Initially environment variables were read at module-import time, making tests order-dependent. Moved all `os.environ` reads inside the handler function. Also added `BASTION_FORWARD_PASSWORD` env var for scenarios where bastion tunnels upstream authentication. Tests can now use `monkeypatch.setenv` without module reloads.

3. **paramiko ≥3.4 with cryptography 48 installed cleanly via prebuilt wheels (Task 11).** Anticipated possible native-build pain. In practice `pip install paramiko>=3.4 cryptography>=48` inside Ubuntu 22.04 resolved entirely through prebuilt manylinux2 wheels — zero compilation, no extra build deps in the Dockerfile.

4. **Compose build context paths use `../ssh-replay` / `../ssh-bastion` relative to the sandbox compose file (Task 15).** Docker Compose resolves `build.context` relative to the compose file, not the shell's `cwd`. Because `docker-compose.sandbox.yml` lives in `sandbox/` and is invoked via `-f tools/pdm-cli/sandbox/docker-compose.sandbox.yml` from the repo root, paths like `../ssh-replay` correctly reach `tools/pdm-cli/ssh-replay/`. Confirmed by `config --quiet` exit-code test.

5. **Skill packaging needed `[tool.hatch.build.targets.wheel.force-include]` to ship the .md file (Task 17).** Hatch's default wheel builder excludes non-Python files. The `pdm:record-fixture` skill is a plain Markdown file inside `src/pdm_cli/templates/skills/`. Required an explicit `force-include` mapping in `pyproject.toml` to bundle it in the wheel so `pdm bootstrap` can unpack it to `.claude/skills/pdm/`.

---

## Sandbox stand — endpoint URLs

After `docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml up -d`:

- Hoverfly Admin API: `http://hoverfly:8888` (inside default network), `http://localhost:8888` (from host)
- Hoverfly Proxy: `http://hoverfly:8500`
- Sandbox PDM backend: `http://pdm-backend-sandbox:8000` (inside), `http://localhost:8001` (from host)
- Sandbox postgres: `pdm-postgres-sandbox:5432`
- Sandbox redis: `pdm-redis-sandbox:6379`

# Sandbox stack — pinned versions (Etap 2)

This file pins exact versions of the tooling that the Etap 2 egress / fixtures
sandbox stack will be built against. Lock these in `docker-compose.full.yml`,
`pyproject.toml` and any helper scripts; update intentionally, not drift.

## Hoverfly — `spectolabs/hoverfly:v1.10.4`

- **What:** HTTP(S) record/replay proxy used as the front edge of the egress
  sandbox. CLI requests to PDM in `sandbox`/`replay` mode go through Hoverfly
  so that we can capture interactions, redact PII, and later replay them
  deterministically in CI without a live PDM.
- **Why this version:**
  - `v1.10.x` is the current stable line (released through 2025–2026); the
    Admin/Hoverctl API has been stable since 1.5+, so simulation files
    captured today remain replayable on minor upgrades.
  - The official image tag is `spectolabs/hoverfly:v1.10.4` — pin the tag, not
    `:latest`, so reruns of `docker compose pull` give identical bytes.
  - Supports the `middleware` hook we need for PII-redaction (Python script
    invoked per request/response).
- **Pin location (when Task ≥2 lands):** `docker-compose.full.yml` service
  `pdm-egress-hoverfly`, plus a copy in this file.

## paramiko — `paramiko>=3.4,<4.0`

- **What:** Python SSH client used by the `pdm-egress-ssh-bastion` egress
  replacement (Step «pdm-egress-ssh-bastion / replay» in the design). The CLI
  tunnels API calls through an SSH bastion to a customer-side jump host when
  Hoverfly mode isn't enough (e.g. for live cutover from an isolated
  network).
- **Why this range:**
  - `paramiko 3.x` is the first line with full Python 3.11/3.12 wheels
    (`cryptography>=41`, `pynacl>=1.5`) — matches our `pyproject.toml`
    `requires-python = ">=3.11"`.
  - Cap at `<4.0` because a future major may drop deprecated transport
    primitives; we'll re-evaluate before bumping.
  - `>=3.4` includes the OpenSSH `ed25519-sk` and `ssh-ed25519` fixes we want
    available even if we never enable hardware keys directly.
- **Pin location (when Task ≥10 lands):** `tools/pdm-cli/pyproject.toml`
  `dependencies` array. CI lockfile (if introduced) should resolve to a
  single concrete patch version per release.

## Update policy

- Bump deliberately, in its own commit, with a short note here explaining
  why and what was tested.
- Never silently float (`:latest`, unbounded `>=`).
- Hoverfly simulation files (`.json`) captured under an older minor are
  fine to replay against a newer minor, but re-record once per Etap to
  catch subtle protocol drift.

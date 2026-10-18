# Prod egress capture — templates

This directory contains templates the customer admin copies to their PDM host
when they're ready to capture real traffic for fixture generation.

## What you set up once

1. Generate a self-signed CA on your machine (`../ca/generate-ca.sh`), copy `ca.crt`+`ca.key` to `./hoverfly-certs/`.
2. Bundle `ca.crt` into your PDM container trust stores. We don't automate this — it's a one-time ops task.
3. Set `HTTP_PROXY=http://pdm-hoverfly-capture:8500` and `HTTPS_PROXY=http://pdm-hoverfly-capture:8500` on PDM services.
4. (Optional) For SSH: deploy a key to bastion (`./ssh-bastion-keys/forward_id_rsa`), point SSH clients at bastion.
5. Start: `docker compose -f docker-compose.yml -f docker-compose.prod-capture.yml [--profile bastion] up -d`.

## Day-to-day

1. Run a BP that calls the external service.
2. On your dev machine: `pdm fixtures record --bp <slug> --case <name> --protocol http` —
   reads from `http://prod-host:8888/api/v2/simulation` (configure `endpoints.hoverfly` in pdm.config.yaml to point there).
3. Commit, PR, merge — replay copies are loaded into sandbox by `pdm fixtures replay`.

## Security notes

- Hoverfly admin (:8888) and proxy (:8500) are bound to 127.0.0.1 only in this template — never expose them.
- The CA private key never leaves the prod host.
- Captured request/response bodies are stored in `./hoverfly-data` and may contain PII even after redaction at fixture-extract time. Treat that directory as sensitive.

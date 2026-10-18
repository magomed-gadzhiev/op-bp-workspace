"""Helpers for managing the docker-compose sandbox stack from pdm test."""

import json
import os
import subprocess
import time

COMPOSE_FILES = [
    "docker-compose.full.yml",
    "tools/pdm-cli/sandbox/docker-compose.sandbox.yml",
]
REQUIRED_SERVICES = [
    "pdm-backend-sandbox",
    "pdm-postgres-sandbox",
    "hoverfly",
    "pdm-egress-ssh-replay",
]


class SandboxNotRunningError(RuntimeError):
    pass


def _compose_cmd(*args: str) -> list[str]:
    """Команда compose с опциональными ручками контурного запуска (спека 142).

    На хосте (CLI `pdm test`) ручки не заданы — поведение прежнее: файлы
    относительно cwd, проект/переменные — по умолчанию compose. Контейнер
    mcp-pdm-bp (верба bp_test) управляет ТЕМ же стеком стенда через сокет
    docker и обязан резолвить относительные bind-пути (./processes,
    ./tools/pdm-cli/…) по каталогу репо НА ХОСТЕ, а не по своему /work:

    - PDM_COMPOSE_PROJECT_DIR  → --project-directory (host-путь репо);
    - PDM_COMPOSE_ENV_FILE     → --env-file (контейнерная копия .env);
    - COMPOSE_PROJECT_NAME     → читается compose natively (общий проект).
    """
    cmd = ["docker", "compose"]
    project_dir = os.environ.get("PDM_COMPOSE_PROJECT_DIR")
    if project_dir:
        cmd.extend(["--project-directory", project_dir])
    env_file = os.environ.get("PDM_COMPOSE_ENV_FILE")
    if env_file:
        cmd.extend(["--env-file", env_file])
    # Абсолютные пути: относительный -f резолвится по --project-directory
    # (host-путь, которого нет в контейнере), а не по cwd процесса.
    for f in COMPOSE_FILES:
        cmd.extend(["-f", os.path.abspath(f)])
    cmd.extend(args)
    return cmd


def _parse_compose_ps_output(stdout: str) -> list[dict]:
    """Parse `docker compose ps --format json` output.

    Compose v2 may emit either a JSON array (older) or newline-delimited
    JSON objects (newer streaming). Handle both transparently.
    """
    text = stdout.strip()
    if not text:
        return []
    # Try JSON array first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    # Fallback: newline-delimited JSON
    objs: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        objs.append(json.loads(line))
    return objs


def healthcheck(services: list[str] = REQUIRED_SERVICES) -> bool:
    try:
        r = subprocess.run(
            _compose_cmd("ps", "--format", "json", *services),
            capture_output=True, text=True,
        )
    except OSError:
        # Нет docker CLI / недоступен сокет (контур без docker, спека 142):
        # это «песочница не поднята», а не англ. трейс FileNotFoundError.
        return False
    if r.returncode != 0:
        return False
    objs = _parse_compose_ps_output(r.stdout)
    if not objs:
        return False
    for obj in objs:
        state = (obj.get("State") or "").lower()
        health = (obj.get("Health") or "").lower()
        if state != "running":
            return False
        if health and health != "healthy":
            return False
    return True


def ensure_sandbox_up() -> None:
    if not healthcheck():
        raise SandboxNotRunningError(
            "Sandbox is not running. Bring it up with:\n"
            "  docker compose -f docker-compose.full.yml "
            "-f tools/pdm-cli/sandbox/docker-compose.sandbox.yml up -d\n"
            "Or pass --ephemeral to pdm test."
        )


def bring_up_sandbox(wait_sec: int = 120) -> None:
    subprocess.run(
        _compose_cmd("up", "-d", *REQUIRED_SERVICES),
        check=True,
    )
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if healthcheck():
            return
        time.sleep(2)
    raise RuntimeError(f"Sandbox did not become healthy within {wait_sec}s")


def bring_down_sandbox() -> None:
    subprocess.run(_compose_cmd("down"), check=False)

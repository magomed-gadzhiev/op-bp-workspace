from pdm_cli.sandbox_lifecycle import (
    ensure_sandbox_up, bring_up_sandbox, bring_down_sandbox,
    SandboxNotRunningError, healthcheck,
)


def test_healthcheck_returns_true_when_all_healthy(monkeypatch):
    def fake_run(cmd, **kw):
        class R:
            returncode = 0
            stdout = '[{"State":"running","Health":"healthy"}]'
        return R()
    monkeypatch.setattr("subprocess.run", fake_run)
    assert healthcheck(["service-a"]) is True


def test_ensure_sandbox_up_raises_when_down(monkeypatch):
    monkeypatch.setattr(
        "pdm_cli.sandbox_lifecycle.healthcheck",
        lambda *a, **kw: False,
    )
    import pytest
    with pytest.raises(SandboxNotRunningError):
        ensure_sandbox_up()


def test_healthcheck_false_when_docker_cli_missing(monkeypatch):
    """Нет docker CLI/сокета в контуре (спека 142, bp_test в mcp-pdm-bp):
    OSError — это «песочница не поднята», а не FileNotFoundError-трейс."""
    def fake_run(cmd, **kw):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'docker'")
    monkeypatch.setattr("subprocess.run", fake_run)
    assert healthcheck(["service-a"]) is False
    import pytest as _pytest
    with _pytest.raises(SandboxNotRunningError):
        ensure_sandbox_up()


def test_compose_cmd_container_knobs(monkeypatch):
    """PDM_COMPOSE_PROJECT_DIR/ENV_FILE добавляют флаги (контейнер mcp-pdm-bp
    резолвит bind-пути по host-репо); -f всегда абсолютные (относительный
    -f резолвится по --project-directory, которого нет в контейнере)."""
    import os

    from pdm_cli.sandbox_lifecycle import COMPOSE_FILES, _compose_cmd
    monkeypatch.delenv("PDM_COMPOSE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("PDM_COMPOSE_ENV_FILE", raising=False)
    files = [os.path.abspath(f) for f in COMPOSE_FILES]
    assert _compose_cmd("ps") == ["docker", "compose"] + [
        part for f in files for part in ("-f", f)] + ["ps"]
    monkeypatch.setenv("PDM_COMPOSE_PROJECT_DIR", "/home/x/op")
    monkeypatch.setenv("PDM_COMPOSE_ENV_FILE", "/work/.env")
    assert _compose_cmd("ps") == [
        "docker", "compose",
        "--project-directory", "/home/x/op",
        "--env-file", "/work/.env",
    ] + [part for f in files for part in ("-f", f)] + ["ps"]

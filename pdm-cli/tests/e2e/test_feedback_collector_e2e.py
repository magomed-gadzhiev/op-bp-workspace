"""E2E: Feedback row -> collector task -> git ticket export.

Requires PDM_E2E=1 and a running sandbox compose stack.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e
ENABLED = os.environ.get("PDM_E2E") == "1"
MAIN_COMPOSE = os.environ.get("MAIN_COMPOSE", "docker-compose.full.yml")
SANDBOX_COMPOSE = os.environ.get(
    "SANDBOX_COMPOSE",
    "tools/pdm-cli/sandbox/docker-compose.sandbox.yml",
)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.full.yml").exists():
            return parent
    return Path(os.environ.get("PDM_REPO_ROOT", Path.cwd())).resolve()


ROOT = _repo_root()


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", MAIN_COMPOSE, "-f", SANDBOX_COMPOSE, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not ENABLED, reason="set PDM_E2E=1")
def test_feedback_collector_full_cycle_in_sandbox():
    ps = _compose("ps", "-q", "pdm-backend-sandbox")
    if ps.returncode != 0 or not ps.stdout.strip():
        pytest.skip("pdm-backend-sandbox is not running")

    script = textwrap.dedent(
        r"""
        import json
        import subprocess
        import tempfile
        from pathlib import Path

        from django.conf import settings
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from feedback.models import Feedback
        from feedback.tasks import feedback_collector_tick


        def run(cmd, cwd=None):
            subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


        tmp = Path(tempfile.mkdtemp(prefix="pdm-feedback-e2e-"))
        remote = tmp / "remote.git"
        seed = tmp / "seed"
        local = tmp / "local"

        run(["git", "init", "--bare", str(remote)])
        seed.mkdir()
        run(["git", "init"], cwd=seed)
        run(["git", "checkout", "-b", "master"], cwd=seed)
        run(["git", "config", "user.email", "seed@example.local"], cwd=seed)
        run(["git", "config", "user.name", "Seed"], cwd=seed)
        (seed / "README.md").write_text("feedback e2e seed\n")
        run(["git", "add", "."], cwd=seed)
        run(["git", "commit", "-m", "init"], cwd=seed)
        run(["git", "remote", "add", "origin", str(remote)], cwd=seed)
        run(["git", "push", "origin", "master"], cwd=seed)
        run(["git", "clone", str(remote), str(local)])

        settings.PDM_FEEDBACK_EXPORT_ENABLED = True
        settings.PDM_FEEDBACK_REPO_URL = str(remote)
        settings.PDM_FEEDBACK_REPO_LOCAL_PATH = str(local)
        settings.PDM_FEEDBACK_GIT_DEFAULT_BRANCH = "master"
        settings.PDM_FEEDBACK_GIT_AUTHOR_NAME = "PDM E2E Bot"
        settings.PDM_FEEDBACK_GIT_AUTHOR_EMAIL = "pdm-e2e@example.local"
        settings.PDM_FEEDBACK_BATCH_SIZE = 10

        User = get_user_model()
        user, _ = User.objects.get_or_create(username="pdm-feedback-e2e")
        fb = Feedback.objects.create(
            type="error",
            status="new",
            title="E2E feedback collector",
            description="auto-test feedback export",
            created_by=user,
        )

        feedback_collector_tick()
        fb.refresh_from_db()

        ticket = local / "feedback" / "tickets" / f"{fb.created_at.strftime('%Y-%m-%d')}-{fb.id}.md"
        assert fb.exported_at is not None, "collector did not mark feedback exported"
        assert ticket.exists(), f"ticket markdown was not written: {ticket}"
        content = ticket.read_text()
        assert f"id: {fb.id}" in content
        assert "# E2E feedback collector" in content
        assert "auto-test feedback export" in content

        branch = f"feedback/auto-{timezone.now().strftime('%Y-%m-%d')}"
        run(["git", "--git-dir", str(remote), "rev-parse", "--verify", branch])
        print(json.dumps({"feedback_id": fb.id, "ticket": str(ticket), "branch": branch}))
        """
    )

    result = _compose(
        "exec",
        "-T",
        "pdm-backend-sandbox",
        "python",
        "manage.py",
        "shell",
        "-c",
        script,
    )
    assert result.returncode == 0, result.stdout + result.stderr

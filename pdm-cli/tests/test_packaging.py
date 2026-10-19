"""Упаковка: колесо собирается без дубликатов путей.

Инцидент 2026-10-19: мёртвый force-include дублировал templates/skills
(каталог уже входит в packages = ["src/pdm_cli"]) — hatchling падал
``ValueError: A second file is being added to the wheel archive`` при
``uv tool install`` на проде (Windows). Юнит-тесты сборку не видят,
поэтому здесь — настоящая сборка колеса.
"""

import collections
import subprocess
import sys
import zipfile
from importlib.util import find_spec
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    find_spec("hatchling") is None,
    reason="hatchling не установлен (dev-зависимость pdm-cli)",
)


def test_wheel_builds_without_duplicate_paths(tmp_path: Path):
    out = tmp_path / "dist"
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps",
         "--no-build-isolation", "-w", str(out), "."],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    wheels = list(out.glob("*.whl"))
    assert wheels, "pip не собрал колесо"

    names = zipfile.ZipFile(wheels[0]).namelist()
    dup = [n for n, c in collections.Counter(names).items() if c > 1]
    assert not dup, f"дубликаты путей в колесе: {dup}"

    # Канон-скиллы обвязки доезжают до установки (тот самый force-include).
    assert any(
        n.endswith("templates/skills/pdm/pdm-edit-process.md") for n in names
    ), "скиллы templates/skills не попали в колесо"

"""Skill file installation helpers shared by bootstrap and scaffold."""
import importlib.resources
from pathlib import Path
from typing import Literal

InstallAction = Literal["installed", "skipped", "overwritten"]


def install_skills(
    target_dir: Path,
    force: bool = False,
) -> dict[str, InstallAction]:
    """Install packaged skill templates into target_dir/.claude/skills/pdm/.

    Returns a mapping of filename -> action, where action is one of
    "installed", "skipped" (existed, force=False), or "overwritten"
    (existed, force=True).
    """
    skills_root = target_dir / ".claude" / "skills" / "pdm"
    skills_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, InstallAction] = {}
    try:
        package = "pdm_cli.templates.skills.pdm"
        for entry in importlib.resources.files(package).iterdir():
            if not entry.name.endswith(".md"):
                continue
            dest = skills_root / entry.name
            if dest.exists() and not force:
                results[entry.name] = "skipped"
                continue
            action: InstallAction = "overwritten" if dest.exists() else "installed"
            dest.write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
            results[entry.name] = action
    except (FileNotFoundError, ModuleNotFoundError):
        pass  # package resource unavailable — non-fatal
    return results

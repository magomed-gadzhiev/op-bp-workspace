"""R2 directory ↔ Process model serialization.

Round-trip is byte-stable: read → write produces identical bytes for unchanged input.
"""

from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from .models import Manifest, Entity, Task, Script, Process


def _yaml() -> YAML:
    y = YAML(typ="safe")
    y.default_flow_style = False
    y.indent(mapping=2, sequence=2, offset=0)
    y.allow_unicode = True
    return y


def _sort_keys(value):
    """Recursively sort dict keys for stable output."""
    if isinstance(value, dict):
        return {k: _sort_keys(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        return [_sort_keys(v) for v in value]
    return value


# PEP 263 coding header prepended to scripts containing non-ASCII characters.
# Stripped on read so round-trip read(write(p)) == p is preserved.
_CODING_HEADER = "# -*- coding: utf-8 -*-\n"


def _dump_yaml(data: dict) -> str:
    y = _yaml()
    sorted_data = _sort_keys(data)
    buf = StringIO()
    y.dump(sorted_data, buf)
    return buf.getvalue()


def _load_yaml(path: Path) -> dict:
    y = _yaml()
    with path.open("r", encoding="utf-8") as f:
        data = y.load(f)
    return data or {}


def _bp_dir(repo_root: Path, slug: str) -> Path:
    return Path(repo_root) / "processes" / slug


def list_process_slugs(repo_root: Path) -> list[str]:
    """List BP slugs present in repo_root/processes/ (sorted)."""
    proc_root = Path(repo_root) / "processes"
    if not proc_root.is_dir():
        return []
    return sorted(
        d.name for d in proc_root.iterdir()
        if d.is_dir() and (d / "manifest.yaml").is_file()
    )


def read_process(repo_root: Path, slug: str) -> Process:
    """Read a single BP from disk into a Process model."""
    bp_dir = _bp_dir(repo_root, slug)
    manifest_path = bp_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    manifest = Manifest(**_load_yaml(manifest_path))

    entities: list[Entity] = []
    ent_dir = bp_dir / "entities"
    if ent_dir.is_dir():
        for f in sorted(ent_dir.glob("*.yaml")):
            entities.append(Entity(**_load_yaml(f)))

    tasks: list[Task] = []
    task_dir = bp_dir / "tasks"
    if task_dir.is_dir():
        for f in sorted(task_dir.glob("*.yaml")):
            tasks.append(Task(**_load_yaml(f)))

    scripts: list[Script] = []
    scripts_dir = bp_dir / "scripts"
    if scripts_dir.is_dir():
        for py_file in sorted(scripts_dir.glob("*.py")):
            name = py_file.stem
            code = py_file.read_text(encoding="utf-8")
            # Strip the coding header inserted on write so read(write(p)) == p.
            # Handle both leading-header and shebang-then-header cases.
            if code.startswith(_CODING_HEADER):
                code = code[len(_CODING_HEADER):]
            elif code.startswith("#!"):
                nl = code.index("\n") + 1
                if code[nl:].startswith(_CODING_HEADER):
                    code = code[:nl] + code[nl + len(_CODING_HEADER):]
            meta_path = scripts_dir / f"{name}.meta.yaml"
            if meta_path.is_file():
                meta = _load_yaml(meta_path)
            else:
                meta = {"name": name}  # fallback to defaults
            scripts.append(Script(
                name=meta.get("name", name),
                display_name=meta.get("display_name", ""),
                description=meta.get("description", ""),
                status=meta.get("status", "draft"),
                code=code,
                requirements=meta.get("requirements", ""),
            ))

    return Process(manifest=manifest, entities=entities, tasks=tasks, scripts=scripts)


def write_process(repo_root: Path, process: Process) -> None:
    """Write a Process to disk, replacing entities/ and tasks/ directory contents.

    The manifest.yaml is overwritten in place. The entities/ and tasks/ directories
    are reset to contain exactly the files corresponding to the new model state —
    any pre-existing .yaml files there that no longer correspond are removed.
    """
    repo_root = Path(repo_root)
    bp_dir = _bp_dir(repo_root, process.manifest.slug)
    bp_dir.mkdir(parents=True, exist_ok=True)

    (bp_dir / "manifest.yaml").write_text(
        _dump_yaml(process.manifest.model_dump()),
        encoding="utf-8",
    )

    _replace_dir(
        bp_dir / "entities",
        {f"{e.slug}.yaml": _dump_yaml(e.model_dump()) for e in process.entities},
    )
    _replace_dir(
        bp_dir / "tasks",
        {f"{t.slug}.yaml": _dump_yaml(t.model_dump()) for t in process.tasks},
    )
    _replace_scripts_dir(bp_dir / "scripts", process.scripts)


def _replace_dir(directory: Path, files: dict[str, str]) -> None:
    """Make `directory` contain exactly `files`. Removes any pre-existing .yaml not in the new set."""
    directory.mkdir(parents=True, exist_ok=True)
    keep = set(files.keys())
    for existing in directory.glob("*.yaml"):
        if existing.name not in keep:
            existing.unlink()
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")


def _script_meta_dict(s: Script) -> dict:
    return {
        "name": s.name,
        "display_name": s.display_name,
        "description": s.description,
        "status": s.status,
        "requirements": s.requirements,
    }


def _replace_scripts_dir(directory: Path, scripts: list[Script]) -> None:
    """Reset scripts/ to contain exactly <name>.py + <name>.meta.yaml for each Script."""
    directory.mkdir(parents=True, exist_ok=True)
    keep = set()
    for s in scripts:
        py_name = f"{s.name}.py"
        meta_name = f"{s.name}.meta.yaml"
        keep.add(py_name)
        keep.add(meta_name)
        code = s.code
        if not code.isascii() and not code.startswith(_CODING_HEADER):
            if code.startswith("#!"):
                # Per PEP 263, the coding header must be on line 1 or 2;
                # if the file starts with a shebang it must remain on line 1.
                nl = code.index("\n") + 1
                code = code[:nl] + _CODING_HEADER + code[nl:]
            else:
                code = _CODING_HEADER + code
        (directory / py_name).write_text(code, encoding="utf-8", newline="\n")
        (directory / meta_name).write_text(
            _dump_yaml(_script_meta_dict(s)), encoding="utf-8",
        )
    for existing in directory.iterdir():
        if existing.is_file() and existing.name not in keep:
            existing.unlink()

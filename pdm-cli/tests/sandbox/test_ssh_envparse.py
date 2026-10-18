"""Parser for PDM_RUN_ID=<id> PDM_SOURCE=<src> command-prefix."""

import importlib.util
from pathlib import Path


def _load(modname: str, path: Path):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REPO = Path(__file__).resolve().parents[2]
parser_mod = _load(
    "ssh_envparse",
    REPO / "sandbox" / "ssh-bastion" / "envparse.py",
)


def test_strips_run_id_and_source():
    run_id, source, cmd = parser_mod.parse_pdm_envprefix(
        "PDM_RUN_ID=42 PDM_SOURCE=pdm-script deploy.sh --v 1"
    )
    assert run_id == "42"
    assert source == "pdm-script"
    assert cmd == "deploy.sh --v 1"


def test_no_prefix_returns_none():
    run_id, source, cmd = parser_mod.parse_pdm_envprefix("deploy.sh")
    assert run_id is None
    assert source is None
    assert cmd == "deploy.sh"


def test_only_run_id_no_source():
    run_id, source, cmd = parser_mod.parse_pdm_envprefix("PDM_RUN_ID=99 ls /")
    assert run_id == "99"
    assert source is None
    assert cmd == "ls /"


def test_quoted_command_preserved():
    run_id, _, cmd = parser_mod.parse_pdm_envprefix(
        'PDM_RUN_ID=7 sh -c "echo hello world"'
    )
    assert run_id == "7"
    assert cmd == 'sh -c "echo hello world"'

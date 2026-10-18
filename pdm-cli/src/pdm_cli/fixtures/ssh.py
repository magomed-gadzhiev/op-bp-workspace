"""SSH fixture models + YAML I/O + matcher.

Matches non-interactive exec only (Tier 1 per design):
  ssh <user>@<host> "<command>"
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from ruamel.yaml import YAML


class SshRequest(BaseModel):
    host: str
    user: str
    command_matches: str  # regex, optional named groups for substitution into response


class SshResponse(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0


class SshMatcher(BaseModel):
    request: SshRequest
    response: SshResponse


class SshFixture(BaseModel):
    name: str
    version: int = Field(default=1, ge=1)  # E16: ≥1; legacy files default to 1 (FR-003)
    recorded_at: str | None = None  # E16: ISO-8601 UTC, None = unknown (FR-003)
    matchers: list[SshMatcher]


def load_ssh_fixture(path: Path) -> SshFixture:
    y = YAML(typ="safe")
    with Path(path).open("r", encoding="utf-8") as f:
        return SshFixture.model_validate(y.load(f) or {})


def dump_ssh_fixture(fix: SshFixture, path: Path) -> None:
    y = YAML()
    y.default_flow_style = False
    y.indent(mapping=2, sequence=4, offset=2)
    with Path(path).open("w", encoding="utf-8") as f:
        y.dump(fix.model_dump(mode="python"), f)


def _substitute(template: str, groups: dict[str, str]) -> str:
    """Replace {{name}} with groups[name]."""
    for name, value in groups.items():
        template = template.replace("{{" + name + "}}", value)
    return template


import json as _json
import re as _re


def from_capture_jsonl(jsonl_path: Path, case_name: str) -> "SshFixture":
    """Build an SshFixture from a bastion capture JSONL.

    Each captured record becomes one matcher with an exact-command regex.
    """
    matchers: list[SshMatcher] = []
    for raw in Path(jsonl_path).read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        rec = _json.loads(raw)
        matchers.append(SshMatcher(
            request=SshRequest(
                host=rec.get("host", ""),
                user=rec.get("user", ""),
                command_matches=_re.escape(rec.get("command", "")),
            ),
            response=SshResponse(
                stdout=rec.get("stdout", ""),
                stderr=rec.get("stderr", ""),
                exit_code=int(rec.get("exit_code", 0)),
                duration_ms=int(rec.get("duration_ms", 0)),
            ),
        ))
    return SshFixture(name=case_name, matchers=matchers)


def from_capture_jsonl_dir(captures_root: Path, bp_slug: str, case_name: str) -> "SshFixture":
    """Aggregate every *.jsonl file under <captures_root>/<bp_slug>/ into one SshFixture."""
    bp_dir = Path(captures_root) / bp_slug
    if not bp_dir.is_dir():
        raise FileNotFoundError(f"No capture directory for BP '{bp_slug}': {bp_dir}")
    jsonl_files = sorted(bp_dir.glob("*.jsonl"))
    if not jsonl_files:
        raise FileNotFoundError(f"No *.jsonl files under {bp_dir}")
    matchers: list[SshMatcher] = []
    for jf in jsonl_files:
        partial = from_capture_jsonl(jf, case_name=case_name)
        matchers.extend(partial.matchers)
    return SshFixture(name=case_name, matchers=matchers)


def redact_ssh_fixture(fix: "SshFixture", rules) -> "SshFixture":
    """Apply SSH redact rules (only regex kind for now) to command/stdout/stderr."""
    out = fix.model_copy(deep=True)
    for m in out.matchers:
        for rule in rules:
            if not getattr(rule, "regex", ""):
                continue
            m.request.command_matches = _re.sub(rule.regex, rule.replacement, m.request.command_matches)
            m.response.stdout = _re.sub(rule.regex, rule.replacement, m.response.stdout)
            m.response.stderr = _re.sub(rule.regex, rule.replacement, m.response.stderr)
    return out


def match_ssh_request(
    fix: SshFixture, host: str, user: str, command: str
) -> Optional[SshResponse]:
    for m in fix.matchers:
        if m.request.host != host or m.request.user != user:
            continue
        m_match = re.search(m.request.command_matches, command)
        if not m_match:
            continue
        groups = m_match.groupdict()
        resp = m.response.model_copy(deep=True)
        resp.stdout = _substitute(resp.stdout, groups)
        resp.stderr = _substitute(resp.stderr, groups)
        return resp
    return None

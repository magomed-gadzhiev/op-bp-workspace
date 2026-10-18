"""PII redaction for fixtures.

Applies user-defined rules from pdm.config.yaml `egress:` section.
Three rule kinds:
  - header: <name>            replaces the value of a request/response header
  - regex: <pattern>          replaces matches in URL, body, and header values
  - jsonpath: <expr>          (HTTP only) replaces JSON values in request/response body if body is valid JSON

Order matters: rules are applied in declaration order. Once value redacted, it stays redacted.
"""
from __future__ import annotations
import json
import re
from typing import Iterable

from ..config import RedactRule
from .http import HttpFixture


def _apply_regex(text: str, rule: RedactRule) -> str:
    if not rule.regex:
        return text
    return re.sub(rule.regex, rule.replacement, text)


def _apply_jsonpath(body: str, rule: RedactRule) -> str:
    if not rule.jsonpath or not body.strip():
        return body
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body
    # Minimal jsonpath: only $.<key>[.<key>]... — no wildcards, no [], no functions.
    if not rule.jsonpath.startswith("$."):
        return body
    parts = rule.jsonpath[2:].split(".")

    def _walk(node, path):
        if not path:
            return rule.replacement
        head, *tail = path
        if isinstance(node, dict) and head in node:
            node[head] = _walk(node[head], tail)
        return node

    data = _walk(data, parts)
    return json.dumps(data, ensure_ascii=False)


def redact_http_fixture(fix: HttpFixture, rules: Iterable[RedactRule]) -> HttpFixture:
    out = fix.model_copy(deep=True)
    for m in out.matchers:
        for rule in rules:
            if rule.header:
                for d in (m.request.headers, m.response.headers):
                    if rule.header in d:
                        d[rule.header] = rule.replacement
            if rule.regex:
                m.request.url_matches = _apply_regex(m.request.url_matches, rule)
                m.response.body = _apply_regex(m.response.body, rule)
                for d in (m.request.headers, m.response.headers):
                    for k in list(d.keys()):
                        d[k] = _apply_regex(d[k], rule)
            if rule.jsonpath:
                m.response.body = _apply_jsonpath(m.response.body, rule)
    return out

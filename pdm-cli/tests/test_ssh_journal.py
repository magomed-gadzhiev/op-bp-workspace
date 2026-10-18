"""Tests for pdm_cli.test_runner.ssh_journal (SSH side-effect queries)."""
import httpx
import respx

from pdm_cli.test_case import SshSideEffect
from pdm_cli.test_runner.ssh_journal import (
    clear_ssh_journal,
    get_ssh_journal,
    match_ssh_side_effect,
)


@respx.mock
def test_clear_ssh_journal_deletes():
    route = respx.delete("http://ssh-replay:8889/journal").mock(
        return_value=httpx.Response(200, json={})
    )
    clear_ssh_journal("http://ssh-replay:8889")
    assert route.called


@respx.mock
def test_clear_ssh_journal_strips_trailing_slash():
    route = respx.delete("http://ssh-replay:8889/journal").mock(
        return_value=httpx.Response(200, json={})
    )
    clear_ssh_journal("http://ssh-replay:8889/")
    assert route.called


@respx.mock
def test_get_ssh_journal_returns_entries():
    respx.get("http://ssh-replay:8889/journal").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"host": "h1", "user": "u", "command": "uptime",
                 "matched_fixture": "uptime", "exit_code": 0, "ts": "t1"},
                {"host": "h2", "user": "u", "command": "ls",
                 "matched_fixture": None, "exit_code": 127, "ts": "t2"},
            ],
        )
    )
    entries = get_ssh_journal("http://ssh-replay:8889")
    assert len(entries) == 2
    assert entries[0]["host"] == "h1"


@respx.mock
def test_get_ssh_journal_handles_empty():
    respx.get("http://ssh-replay:8889/journal").mock(
        return_value=httpx.Response(200, json=[])
    )
    assert get_ssh_journal("http://ssh-replay:8889") == []


@respx.mock
def test_match_ssh_filters_by_host_and_command():
    respx.get("http://ssh-replay:8889/journal").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"host": "deploy.local", "user": "u",
                 "command": "deploy_release.sh v1",
                 "matched_fixture": "deploy", "exit_code": 0, "ts": "t1"},
                {"host": "other.local", "user": "u",
                 "command": "deploy_release.sh v2",
                 "matched_fixture": None, "exit_code": 127, "ts": "t2"},
            ],
        )
    )
    eff = SshSideEffect(
        kind="ssh", host="deploy.local", command_matches="deploy_release"
    )
    matches = match_ssh_side_effect("http://ssh-replay:8889", eff)
    assert len(matches) == 1
    assert matches[0]["host"] == "deploy.local"


@respx.mock
def test_match_ssh_no_host_matches_any_host():
    respx.get("http://ssh-replay:8889/journal").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"host": "a.local", "user": "u", "command": "run-job foo",
                 "matched_fixture": "j", "exit_code": 0, "ts": "t1"},
                {"host": "b.local", "user": "u", "command": "run-job bar",
                 "matched_fixture": "j", "exit_code": 0, "ts": "t2"},
            ],
        )
    )
    eff = SshSideEffect(kind="ssh", command_matches="run-job")
    matches = match_ssh_side_effect("http://ssh-replay:8889", eff)
    assert len(matches) == 2


@respx.mock
def test_match_ssh_regex_no_match():
    respx.get("http://ssh-replay:8889/journal").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"host": "h1", "user": "u", "command": "uptime",
                 "matched_fixture": "u", "exit_code": 0, "ts": "t1"},
            ],
        )
    )
    eff = SshSideEffect(kind="ssh", command_matches=r"^deploy_")
    assert match_ssh_side_effect("http://ssh-replay:8889", eff) == []


@respx.mock
def test_match_ssh_handles_null_command():
    respx.get("http://ssh-replay:8889/journal").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"host": "h1", "user": "u", "command": None,
                 "matched_fixture": None, "exit_code": 127, "ts": "t1"},
                {"host": "h1", "user": "u", "command": "real cmd",
                 "matched_fixture": "f", "exit_code": 0, "ts": "t2"},
            ],
        )
    )
    eff = SshSideEffect(kind="ssh", host="h1", command_matches="real")
    matches = match_ssh_side_effect("http://ssh-replay:8889", eff)
    assert len(matches) == 1
    assert matches[0]["command"] == "real cmd"

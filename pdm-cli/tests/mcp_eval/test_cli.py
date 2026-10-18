"""CLI `pdm mcp-eval`: env-гейт PDM_MCP_EVAL_LLM (без него — вежливый
skip, код 0), сборка раннера, отчёты."""

import json

from click.testing import CliRunner

from pdm_cli.mcp_eval import cli as mcp_eval_cli
from pdm_cli.mcp_eval.cli import mcp_eval


def test_env_gate_polite_skip(monkeypatch):
    monkeypatch.delenv("PDM_MCP_EVAL_LLM", raising=False)
    runner = CliRunner()
    result = runner.invoke(mcp_eval, ["--base", "http://x/mcp"])
    assert result.exit_code == 0
    assert "skip" in result.output.lower()
    assert "PDM_MCP_EVAL_LLM" in result.output


def test_env_gate_skips_even_with_llm_option(monkeypatch):
    """Гейт — именно переменная окружения: без неё не гоняем (CI без GPU)."""
    monkeypatch.delenv("PDM_MCP_EVAL_LLM", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        mcp_eval, ["--base", "http://x/mcp", "--llm", "http://y/v1",
                   "--model", "m"])
    assert result.exit_code == 0
    assert "skip" in result.output.lower()


def test_missing_model_is_russian_error(monkeypatch, tmp_path):
    monkeypatch.setenv("PDM_MCP_EVAL_LLM", "http://y/v1")
    monkeypatch.delenv("PDM_MCP_EVAL_MODEL", raising=False)
    runner = CliRunner()
    result = runner.invoke(mcp_eval, ["--base", "http://x/mcp"])
    assert result.exit_code != 0
    assert "--model" in result.output


def test_runner_crash_isolated_per_case(monkeypatch, tmp_path):
    """Даже неожиданный крах раннера в одном кейсе не роняет батарею:
    кейс помечается fail с трейсом причины, остальные идут, отчёт пишется."""
    monkeypatch.setenv("PDM_MCP_EVAL_LLM", "http://llm/v1")

    from tests.mcp_eval.test_runner import FakeEndpoint, FakeLlm, _final

    class CrashyRunner:
        def __init__(self, endpoints, llm, system_prompt=None):
            self._inner = None

        def run_case(self, case):
            if case.id == "list-processes":
                raise ValueError("unexpected runner bug")
            return _make_pass_result(case)

    def _make_pass_result(case):
        from pdm_cli.mcp_eval.runner import CaseResult
        return CaseResult(case=case, status="pass", final_answer="ok")

    from pdm_cli.mcp_eval import cli as mcp_eval_cli
    monkeypatch.setattr(mcp_eval_cli, "McpEndpoint",
                        lambda name, url: FakeEndpoint(name, []))
    monkeypatch.setattr(mcp_eval_cli, "LlmClient",
                        lambda base_url, model, timeout=300.0, temperature=0.1: FakeLlm([]))
    monkeypatch.setattr(mcp_eval_cli, "AgentRunner", CrashyRunner)

    out_json = tmp_path / "report.json"
    runner = CliRunner()
    result = runner.invoke(mcp_eval, [
        "--base", "http://read/mcp", "--model", "m",
        "--case", "list-processes", "--case", "publish-handoff",
        "--out", str(out_json),
    ])
    assert result.exit_code == 1, result.output  # один кейс упал → гейт красный
    report = json.loads(out_json.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in report["cases"]}
    assert by_id["list-processes"]["status"] == "fail"
    assert "unexpected runner bug" in " ".join(
        by_id["list-processes"]["fail_reasons"])
    assert by_id["publish-handoff"]["status"] == "pass"
    assert report["summary"]["passed"] == 1


def test_run_battery_wiring_and_reports(monkeypatch, tmp_path):
    """Полный путь: кейсы из cases/, фейковые фабрики, отчёты на диск."""
    monkeypatch.setenv("PDM_MCP_EVAL_LLM", "http://llm/v1")
    seen = {}

    class FakeEndpointFactory:
        def __call__(self, name, url):
            seen[f"{name}_url"] = url
            from tests.mcp_eval.test_runner import FakeEndpoint
            if name == "read":
                ep = FakeEndpoint("read", ["list_business_processes"])
                ep.results["list_business_processes"] = {
                    "obj": {"items": [{"id": 12, "name": "ЛЕМ"}]}}
                return ep
            return FakeEndpoint("write", [])

    class FakeLlmFactory:
        def __call__(self, base_url, model, timeout=300.0, temperature=0.1):
            seen["llm"] = (base_url, model, timeout)
            from tests.mcp_eval.test_runner import FakeLlm, _assistant, _final, _tc
            return FakeLlm([
                _assistant(_tc("list_business_processes", {})),
                _final("Один процесс: ЛЕМ (id 12)"),
            ])

    monkeypatch.setattr(mcp_eval_cli, "McpEndpoint", FakeEndpointFactory())
    monkeypatch.setattr(mcp_eval_cli, "LlmClient", FakeLlmFactory())

    only = ("list-processes",)  # из поставки cases/*.yaml
    out_json = tmp_path / "report.json"
    out_md = tmp_path / "summary.md"
    runner = CliRunner()
    result = runner.invoke(mcp_eval, [
        "--base", "http://read/mcp?toolset=bp-admin",
        "--bp-base", "http://write/mcp",
        "--model", "test-model",
        "--case", only[0],
        "--out", str(out_json),
        "--md-out", str(out_md),
    ])
    assert result.exit_code == 0, result.output
    assert seen["read_url"] == "http://read/mcp?toolset=bp-admin"
    assert seen["write_url"] == "http://write/mcp"
    assert seen["llm"] == ("http://llm/v1", "test-model", 300.0)

    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["summary"]["passed"] == 1
    assert report["cases"][0]["id"] == "list-processes"
    assert out_md.read_text(encoding="utf-8").startswith("#")

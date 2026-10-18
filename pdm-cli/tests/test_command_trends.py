"""Tests for `pdm trends` (E15 Trends UI, spec 038)."""
from pathlib import Path

import respx
from click.testing import CliRunner

from pdm_cli.cli import main
from pdm_cli.commands.trends import sparkline

PROD = "https://prod.local"


def _write_config(tmp_path: Path) -> None:
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  prod: https://prod.local\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir(exist_ok=True)
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: test-key\n", encoding="utf-8"
    )


def _trend(weeks):
    buckets = []
    for i in range(weeks):
        run = (i + 1) * 2
        succ = i + 1
        buckets.append({
            "period": f"2026-W{10 + i:02d}", "run_count": run,
            "success_count": succ, "error_count": run - succ,
            "success_rate": round(succ / run, 4),
        })
    tot_run = sum(b["run_count"] for b in buckets)
    tot_succ = sum(b["success_count"] for b in buckets)
    return {
        "granularity": "week",
        "window": {"since": "x", "until": "y"},
        "filter": {"bp_slug": "order"},
        "weeks": weeks,
        "buckets": buckets,
        "totals": {
            "run_count": tot_run, "success_count": tot_succ,
            "error_count": tot_run - tot_succ,
            "success_rate": round(tot_succ / tot_run, 4),
        },
    }


# --- sparkline unit ---

def test_sparkline_empty():
    assert sparkline([]) == ""


def test_sparkline_flat_is_uniform():
    out = sparkline([3, 3, 3])
    assert len(out) == 3
    assert len(set(out)) == 1


def test_sparkline_monotonic_increasing():
    out = sparkline([0, 1, 2, 3])
    assert out[0] != out[-1]
    assert len(out) == 4


# --- CLI integration ---

@respx.mock
def test_trends_prints_week_rows_and_sparkline(tmp_path: Path):
    _write_config(tmp_path)
    respx.get(f"{PROD}/api/runs/trends/").respond(json=_trend(6))
    result = CliRunner().invoke(
        main, ["trends", "order", "--weeks", "6"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    # one row per week
    for i in range(6):
        assert f"2026-W{10 + i:02d}" in result.output
    assert "run_count:" in result.output
    assert "success_rate:" in result.output
    assert "Итого" in result.output


@respx.mock
def test_trends_default_weeks(tmp_path: Path):
    _write_config(tmp_path)
    route = respx.get(f"{PROD}/api/runs/trends/").respond(json=_trend(8))
    result = CliRunner().invoke(main, ["trends", "order"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert route.calls.last.request.url.params["weeks"] == "8"


@respx.mock
def test_trends_empty_series_message(tmp_path: Path):
    _write_config(tmp_path)
    empty = {
        "granularity": "week", "window": {"since": "x", "until": "y"},
        "filter": {"bp_slug": "order"}, "weeks": 8,
        "buckets": [
            {"period": "2026-W20", "run_count": 0, "success_count": 0,
             "error_count": 0, "success_rate": 0.0}
        ],
        "totals": {"run_count": 0, "success_count": 0, "error_count": 0,
                   "success_rate": 0.0},
    }
    respx.get(f"{PROD}/api/runs/trends/").respond(json=empty)
    result = CliRunner().invoke(main, ["trends", "order"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "Нет данных" in result.output


def test_trends_help():
    result = CliRunner().invoke(main, ["trends", "--help"])
    assert result.exit_code == 0
    assert "--weeks" in result.output
    assert "--env" in result.output

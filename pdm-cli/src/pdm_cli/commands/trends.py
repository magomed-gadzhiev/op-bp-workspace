"""pdm trends — weekly run_count / success_rate timeseries for a BP (E15, spec 038).

Reads the backend trends endpoint (GET /api/runs/trends/) and prints a per-week
table plus a compact unicode sparkline so the trend reads at a glance. Mirrors the
config/auth conventions of `pdm telemetry`.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..api_client import PdmApiClient
from ..config import load_config

_SPARK_TICKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float]) -> str:
    """Render a list of numbers as a unicode sparkline (empty for no/flat data)."""
    nums = [float(v) for v in values]
    if not nums:
        return ""
    lo, hi = min(nums), max(nums)
    if hi == lo:
        # flat line — mid tick for every point
        return _SPARK_TICKS[len(_SPARK_TICKS) // 2] * len(nums)
    span = hi - lo
    out = []
    for n in nums:
        idx = int((n - lo) / span * (len(_SPARK_TICKS) - 1))
        out.append(_SPARK_TICKS[idx])
    return "".join(out)


@click.command("trends")
@click.argument("bp", required=False)
@click.option("--weeks", default=8, show_default=True, type=int,
              help="Number of trailing ISO weeks to chart.")
@click.option("--env", default="prod", show_default=True,
              help="PDM environment name from pdm.config.yaml endpoints.")
@click.pass_context
def trends_cmd(ctx, bp, weeks, env):
    """Show weekly run_count and success_rate for BP (or all BPs if omitted)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    cfg = load_config(cwd)
    api_key = cfg.api_key(env)
    base_url = cfg.endpoint(env)

    with PdmApiClient(base_url=base_url, api_key=api_key) as client:
        data = client.run_trends(bp_slug=bp, weeks=weeks)

    buckets = data.get("buckets", [])
    totals = data.get("totals", {})
    scope = bp or "all BPs"

    if not buckets or totals.get("run_count", 0) == 0:
        click.echo(f"Нет данных о запусках за последние {weeks} нед. ({scope}).")
        return

    table = Table(title=f"Тренды запусков — {scope} (последние {weeks} нед.)")
    table.add_column("Неделя", style="cyan")
    table.add_column("Запусков", justify="right")
    table.add_column("Успешно", justify="right")
    table.add_column("Ошибок", justify="right")
    table.add_column("Success rate", justify="right")
    for b in buckets:
        rate = b.get("success_rate", 0.0)
        table.add_row(
            str(b.get("period", "")),
            str(b.get("run_count", 0)),
            str(b.get("success_count", 0)),
            str(b.get("error_count", 0)),
            f"{rate * 100:.0f}%",
        )

    console = Console()
    console.print(table)
    runs_spark = sparkline([b.get("run_count", 0) for b in buckets])
    rate_spark = sparkline([b.get("success_rate", 0.0) for b in buckets])
    console.print(f"run_count:    {runs_spark}")
    console.print(f"success_rate: {rate_spark}")
    console.print(
        f"Итого: {totals.get('run_count', 0)} запусков, "
        f"success rate {totals.get('success_rate', 0.0) * 100:.0f}%"
    )

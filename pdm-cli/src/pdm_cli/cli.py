"""pdm-cli entry point."""

import os
from pathlib import Path

import click

from . import __version__
from .commands import bootstrap as bootstrap_cmd, diff as diff_cmd, promote as promote_cmd, pull as pull_cmd, push as push_cmd, validate as validate_cmd
from .commands.compile import compile_cmd
from .commands.drift import drift
from .commands.new_bp import new_bp as new_bp_cmd
from .commands.fixtures import fixtures as fixtures_cmd
from .commands.logs import logs as logs_cmd
from .commands.test_cmd import test as test_cmd
from .commands.feedback import feedback as _feedback_group
from .commands.telemetry import telemetry as _telemetry_group
from .commands.trends import trends_cmd as _trends_cmd
from .commands.tokens import tokens_group as _tokens_group
from .commands.scaffold import scaffold_group as _scaffold_group
from .commands.sign import gen_key as _gen_key_cmd, register_key as _register_key_cmd, sign as _sign_cmd
from .commands.decks import decks_group as _decks_group
from .commands.ws import ws as _ws_group
from .mcp.cli import mcp_group as _mcp_group
from .sandbox_mcp.cli import sandbox_mcp_group as _sandbox_mcp_group
from .defmcp.cli import defmcp_group as _defmcp_group
from .mcp_eval.cli import mcp_eval as _mcp_eval_cmd


@click.group()
@click.version_option(__version__, prog_name="pdm-cli")
@click.pass_context
def main(ctx):
    """CLI for managing PDM business processes (ZIP transport)."""
    if ctx.obj is None:
        ctx.obj = {"cwd": Path(os.getcwd())}


main.add_command(bootstrap_cmd)
main.add_command(new_bp_cmd)
main.add_command(diff_cmd)
main.add_command(compile_cmd)
main.add_command(drift)
main.add_command(promote_cmd)
main.add_command(pull_cmd)
main.add_command(push_cmd)
main.add_command(validate_cmd)
main.add_command(fixtures_cmd)
main.add_command(test_cmd)
main.add_command(logs_cmd)
main.add_command(_feedback_group)
main.add_command(_telemetry_group)
main.add_command(_trends_cmd)
main.add_command(_mcp_group)
main.add_command(_sandbox_mcp_group)
main.add_command(_defmcp_group)
main.add_command(_mcp_eval_cmd)
main.add_command(_tokens_group)
main.add_command(_scaffold_group)
main.add_command(_decks_group)
main.add_command(_ws_group)
main.add_command(_gen_key_cmd)
main.add_command(_register_key_cmd)
main.add_command(_sign_cmd)


if __name__ == "__main__":
    main()

from click.testing import CliRunner

from pdm_cli.cli import main


def test_cli_help_runs():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "managing PDM" in result.output


def test_cli_version():
    # Версия — из метаданных пакета (pyproject), совпадает с pdm --version
    # установленной сборки; исходниковый чекаут — 0.0.0+source.
    from pdm_cli import __version__

    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output

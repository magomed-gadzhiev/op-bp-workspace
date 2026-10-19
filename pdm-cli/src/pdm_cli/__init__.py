"""pdm-cli: обвязка PDM (компилятор пакетов БП, воркспейс `pdm ws`, sandbox).

Версия берётся из метаданных установленного пакета (pyproject), а не
дублируется константой: `pdm --version` — единственный способ увидеть,
какая сборка зеркала стоит у менеджера, и застать дрейф зеркала.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("pdm-cli")
except PackageNotFoundError:  # запуск из исходников без установки
    __version__ = "0.0.0+source"

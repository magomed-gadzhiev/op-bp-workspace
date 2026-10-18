#!/usr/bin/env bash
# uv-bootstrap (спека 163 §5.1): установка uv при отсутствии и pdm-cli
# из этого зеркала. Запуск из корня клона зеркала:
#   bash scripts/uv-bootstrap.sh            # первая установка
#   bash scripts/uv-bootstrap.sh --reinstall  # обновление после git pull
# Windows: uv ставится PowerShell-командой из README §5, затем этот скрипт
# можно запустить в Git Bash; без Git Bash — выполните команду uv tool install
# из README §5 вручную.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

EXTRA_ARGS=()
if [ "${1:-}" = "--reinstall" ]; then
  EXTRA_ARGS=(--reinstall)
elif [ -n "${1:-}" ]; then
  echo "uv-bootstrap: неизвестный аргумент '$1' (ожидается пусто или --reinstall)" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv-bootstrap: uv не найден — ставлю официальным установщиком…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || {
  echo "uv-bootstrap: установка uv не удалась — поставьте по https://docs.astral.sh/uv/ и повторите." >&2
  exit 1
}
echo "uv-bootstrap: uv $(uv --version | awk '{print $2}')"

# URL зеркала — из origin этого клона; git-ссылки приводим к pip-виду git+.
remote="$(git remote get-url origin)"
case "$remote" in
  git+*) url="$remote" ;;
  git@*:*) url="ssh://${remote%%:*}/${remote#*:}" ;;          # git@host:path → ssh://git@host/path
  http://*|https://*|ssh://*) url="$remote" ;;
  *) echo "uv-bootstrap: не понял remote origin: $remote — задайте URL вручную (README §5)." >&2; exit 1 ;;
esac
case "$url" in
  *.git) ;;
  *) url="${url}.git" ;;
esac
url="git+${url}"

echo "uv-bootstrap: ставлю pdm-cli из ${url}#subdirectory=pdm-cli …"
uv tool install "pdm-cli @ ${url}#subdirectory=pdm-cli" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}

command -v pdm >/dev/null 2>&1 || export PATH="$HOME/.local/bin:$PATH"
echo "uv-bootstrap: проверка — $(pdm --version)"
pdm ws --help >/dev/null && echo "uv-bootstrap: готово, команды 'pdm ws' доступны."

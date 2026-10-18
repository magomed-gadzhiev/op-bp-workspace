#!/bin/sh
set -e
if [ -f /work/pyproject.toml ]; then
    echo "[pdm-cli-dev] installing package + dev deps..."
    pip install -e ".[dev,mcp]" --no-warn-script-location || true
    echo "[pdm-cli-dev] ready. pytest, pdm --help, etc. available."
else
    echo "[pdm-cli-dev] WARNING: /work/pyproject.toml not found — volume mount missing?"
fi
exec sleep infinity

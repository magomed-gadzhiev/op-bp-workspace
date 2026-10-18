#!/usr/bin/env bash
set -euo pipefail
DIR=$(dirname "$0")
cd "$DIR"

mkdir -p out
cd out

if [[ -f ca.crt && -f ca.key ]]; then
  echo "CA already exists in $(pwd)/. Delete out/ to regenerate."
  exit 0
fi

# Root CA — 10 years
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -subj "/CN=PDM Sandbox Root CA" \
  -out ca.crt

echo "Generated CA at $(pwd):"
ls -la
echo
echo "Mount ca.crt into PDM-backend at /usr/local/share/ca-certificates/pdm-sandbox-ca.crt and run update-ca-certificates."

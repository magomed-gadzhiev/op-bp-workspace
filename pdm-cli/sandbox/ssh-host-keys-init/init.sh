#!/bin/sh
set -eu
KEY_DIR="${KEY_DIR:-/shared/host_keys}"
KEY_PATH="$KEY_DIR/host_rsa_key"
mkdir -p "$KEY_DIR"
if [ -f "$KEY_PATH" ] && [ -f "$KEY_PATH.pub" ]; then
  echo "[init] host key already present at $KEY_PATH"
else
  echo "[init] generating new RSA host key at $KEY_PATH"
  ssh-keygen -t rsa -b 2048 -f "$KEY_PATH" -N "" -q
fi
chmod 600 "$KEY_PATH"
chmod 644 "$KEY_PATH.pub"
echo "[init] host key fingerprint: $(ssh-keygen -lf "$KEY_PATH.pub")"

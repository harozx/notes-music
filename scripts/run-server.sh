#!/usr/bin/env bash
# Chạy server nhạc (systemd gọi file này). Ưu tiên .venv-linux, không có thì python3 hệ thống.
cd "$(dirname "$0")/.."
PY=.venv-linux/bin/python
[ -x "$PY" ] || PY=$(command -v python3)
export PYTHONUNBUFFERED=1
exec "$PY" -m notes

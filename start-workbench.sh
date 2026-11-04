#!/bin/sh
cd "$(dirname "$0")" || exit 1
PORT="${1:-8799}"
echo "workbench → http://127.0.0.1:$PORT"
exec python3 workbench/server.py "$PORT"

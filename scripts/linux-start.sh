#!/usr/bin/env bash
# Chạy server + Cloudflare Tunnel ở nền trên Linux (không tắt khi đóng terminal). Dừng: scripts/linux-stop.sh
cd "$(dirname "$0")/.."
pkill -f "python3? app.py"; pkill -f "cloudflared.*tunnel.*run"; sleep 1

# python: ưu tiên .venv-linux, không có thì dùng python3 của hệ thống
PY=.venv-linux/bin/python; [ -x "$PY" ] || PY=python3
nohup "$PY" app.py >> server.log 2>&1 &

# cloudflared: ưu tiên bản cài trên máy, không có thì dùng bin/cloudflared trong dự án
CF=$(command -v cloudflared || echo bin/cloudflared)
# token: lấy TUNNEL_TOKEN trong .env, không có thì hỏi cloudflared (cần ~/.cloudflared/cert.pem)
TOKEN=$(grep -E '^TUNNEL_TOKEN=' .env 2>/dev/null | cut -d= -f2- | tr -d '\r')
[ -n "$TOKEN" ] || TOKEN=$("$CF" tunnel token notes)
TUNNEL_TOKEN="$TOKEN" nohup "$CF" tunnel --no-autoupdate run --url http://127.0.0.1:8000 >> tunnel.log 2>&1 &
echo "started: https://notes.youv.dev  (log: server.log, tunnel.log)"

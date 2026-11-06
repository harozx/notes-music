#!/usr/bin/env bash
# Chạy Cloudflare Tunnel (systemd gọi file này).
# token: TUNNEL_TOKEN trong .env, không có thì hỏi cloudflared (cần ~/.cloudflared/cert.pem)
cd "$(dirname "$0")/.."
CF=$(command -v cloudflared || echo "$PWD/bin/cloudflared")
TOKEN=$(grep -E '^TUNNEL_TOKEN=' .env 2>/dev/null | cut -d= -f2- | tr -d '\r')
[ -n "$TOKEN" ] || TOKEN=$("$CF" tunnel token notes)
# chờ server lên rồi mới mở tunnel (tránh 502 lúc vừa khởi động máy)
for _ in $(seq 1 30); do
  curl -fsS -o /dev/null http://127.0.0.1:8000/auth/config 2>/dev/null && break
  sleep 1
done
export TUNNEL_TOKEN="$TOKEN"
exec "$CF" tunnel --no-autoupdate run --url http://127.0.0.1:8000

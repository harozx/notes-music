#!/usr/bin/env bash
# Cài tự khởi động: server nhạc + Cloudflare Tunnel chạy bằng systemd (user service).
#  - Tự chạy khi bật máy / khởi động lại, KHÔNG cần đăng nhập (nhờ "linger")
#  - Tự bật lại sau 5 giây nếu bị crash
# Chạy 1 lần:  bash scripts/install-autostart.sh
# Gỡ:          bash scripts/install-autostart.sh --uninstall
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

if [ "$1" = "--uninstall" ]; then
  systemctl --user disable --now notes-tunnel.service notes-music.service 2>/dev/null || true
  rm -f "$UNIT_DIR/notes-music.service" "$UNIT_DIR/notes-tunnel.service"
  systemctl --user daemon-reload
  echo "Đã gỡ tự khởi động."
  exit 0
fi

chmod +x "$DIR/scripts/run-server.sh" "$DIR/scripts/run-tunnel.sh"
[ -x "$DIR/bin/cloudflared" ] && chmod +x "$DIR/bin/cloudflared"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/notes-music.service" <<EOF
[Unit]
Description=Notes - server nghe nhac YouTube
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/scripts/run-server.sh
Restart=always
RestartSec=5
StandardOutput=append:$DIR/server.log
StandardError=append:$DIR/server.log

[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/notes-tunnel.service" <<EOF
[Unit]
Description=Notes - Cloudflare Tunnel (notes.youv.dev)
After=notes-music.service network-online.target
Wants=notes-music.service network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/scripts/run-tunnel.sh
Restart=always
RestartSec=5
StandardOutput=append:$DIR/tunnel.log
StandardError=append:$DIR/tunnel.log

[Install]
WantedBy=default.target
EOF

# tắt các bản đang chạy kiểu cũ (nohup / chạy tay) để khỏi tranh cổng 8000
pkill -f "python3? (app.py|-m notes)" 2>/dev/null || true
pkill -f "cloudflared.*tunnel.*run" 2>/dev/null || true
sleep 1

systemctl --user daemon-reload
systemctl --user enable --now notes-music.service notes-tunnel.service

# linger: cho user service chạy ngay khi bật máy, không cần đăng nhập
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  loginctl enable-linger "$USER" 2>/dev/null || sudo loginctl enable-linger "$USER"
fi

sleep 3
systemctl --user --no-pager --lines=0 status notes-music.service notes-tunnel.service || true
echo
echo "Xong! Tự chạy khi bật máy. Xem log: tail -f $DIR/server.log $DIR/tunnel.log"
echo "Lệnh hay dùng: systemctl --user restart notes-music   |   systemctl --user status notes-tunnel"

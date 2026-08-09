#!/usr/bin/env bash
# Setup IDX Screener di Oracle Cloud (Ubuntu 22.04 / ARM free tier)
# Jalankan sebagai user biasa (bukan root) setelah SSH ke VM:
#   bash setup_oracle.sh
#
# Prasyarat: port 80 sudah dibuka di Oracle Cloud Security List + iptables

set -euo pipefail

REPO_URL="https://github.com/bakhtiarrifai/idx-screener.git"
INSTALL_DIR="$HOME/idx-screener"

echo "=============================="
echo " IDX Screener — Oracle Cloud Setup"
echo "=============================="

# 1. Update system dan install dependencies
echo ""
echo "[1/7] Update system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git nginx curl jq

# 2. Clone atau update repo
echo ""
echo "[2/7] Clone/update repo..."
if [ -d "$INSTALL_DIR" ]; then
    git -C "$INSTALL_DIR" pull
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# 3. Setup virtual environment
echo ""
echo "[3/7] Setup virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# 4. Setup .env
echo ""
echo "[4/7] Setup file .env..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "⚠️  File .env dibuat dari template."
    echo "    Edit dengan kredensial Telegram kamu:"
    echo "    nano $INSTALL_DIR/.env"
    echo ""
    echo "    Isi:"
    echo "    TELEGRAM_BOT_TOKEN=<token_bot_kamu>"
    echo "    TELEGRAM_CHAT_ID=<chat_id_kamu>"
    echo ""
    read -rp "Lanjut setelah mengisi .env? [Enter]" _
else
    echo "    File .env sudah ada, skip."
fi

# 5. Buka port di iptables (Oracle Cloud default block semua inbound)
echo ""
echo "[5/7] Buka port 80 di iptables..."
if ! sudo iptables -C INPUT -m state --state NEW -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
fi
if ! dpkg -l | grep -q netfilter-persistent; then
    sudo apt-get install -y -qq iptables-persistent
fi
sudo netfilter-persistent save -q 2>/dev/null || true

# 6. Setup nginx sebagai reverse proxy di port 80
echo ""
echo "[6/7] Konfigurasi nginx..."
sudo tee /etc/nginx/sites-available/idx-screener > /dev/null <<'NGINXCONF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
NGINXCONF

sudo ln -sf /etc/nginx/sites-available/idx-screener /etc/nginx/sites-enabled/idx-screener
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
sudo systemctl enable nginx

# 7. Setup systemd user services (screener timer + dashboard)
echo ""
echo "[7/7] Setup systemd services..."
mkdir -p "$HOME/.config/systemd/user"

cat > "$HOME/.config/systemd/user/idx-screener.service" <<EOF
[Unit]
Description=IDX Daily Stock Screener
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/run_screener.sh
StandardOutput=append:$INSTALL_DIR/screener.log
StandardError=append:$INSTALL_DIR/screener.log

[Install]
WantedBy=default.target
EOF

cat > "$HOME/.config/systemd/user/idx-screener.timer" <<EOF
[Unit]
Description=Run IDX Daily Stock Screener on weekdays at 08:30 WIB

[Timer]
OnCalendar=Mon..Fri 08:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat > "$HOME/.config/systemd/user/idx-screener-dashboard.service" <<EOF
[Unit]
Description=IDX Screener Dashboard (Flask)
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/dashboard.py
Restart=on-failure
RestartSec=5
StandardOutput=append:$INSTALL_DIR/screener_dashboard.log
StandardError=append:$INSTALL_DIR/screener_dashboard.log

[Install]
WantedBy=default.target
EOF

# Pastikan systemd user session lingering aktif (agar services jalan tanpa login)
loginctl enable-linger "$USER" 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable --now idx-screener.timer
systemctl --user enable --now idx-screener-dashboard.service

# Tampilkan status
echo ""
echo "=============================="
PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || echo "<IP_PUBLIC>")
echo "✅ Setup selesai!"
echo ""
echo "  Dashboard : http://$PUBLIC_IP"
echo "  Timer     : setiap hari kerja 08:30 WIB"
echo ""
echo "Perintah berguna:"
echo "  systemctl --user status idx-screener.timer"
echo "  systemctl --user status idx-screener-dashboard"
echo "  tail -f $INSTALL_DIR/screener.log"
echo "  tail -f $INSTALL_DIR/screener_dashboard.log"
echo ""
echo "⚠️  Pastikan port 80 sudah dibuka di Oracle Cloud Console:"
echo "   Networking > VCN > Security Lists > Add Ingress Rule"
echo "   Source: 0.0.0.0/0 | Protocol: TCP | Port: 80"
echo "=============================="

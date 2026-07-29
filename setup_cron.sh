#!/usr/bin/env bash
# Script untuk menginstal cron job atau systemd timer screener harian.
# Jalankan sekali saja: bash setup_cron.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer virtualenv python if available
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

echo "Mendeteksi init system..."

if command -v systemctl &>/dev/null && systemctl --user status &>/dev/null; then
    echo "✅ Menggunakan systemd timer..."

    mkdir -p "$HOME/.config/systemd/user"

    cat > "$HOME/.config/systemd/user/idx-screener.service" <<EOF
[Unit]
Description=IDX Daily Stock Screener
After=network.target

[Service]
Type=oneshot
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/run_screener.sh
StandardOutput=append:$SCRIPT_DIR/screener.log
StandardError=append:$SCRIPT_DIR/screener.log

[Install]
WantedBy=default.target
EOF

    cat > "$HOME/.config/systemd/user/idx-screener.timer" <<EOF
[Unit]
Description=Run IDX Daily Stock Screener on weekdays at 08:30 WIB

[Timer]
OnCalendar=Mon..Fri 01:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

    systemctl --user daemon-reload
    systemctl --user enable --now idx-screener.timer
    systemctl --user status idx-screener.timer --no-pager

    echo ""
    echo "✅ Systemd timer terpasang."
    echo "   Status: systemctl --user status idx-screener.timer"
else
    echo "✅ Menggunakan cron job..."

    CRON_LINE="30 1 * * 1-5 $SCRIPT_DIR/run_screener.sh >> $SCRIPT_DIR/screener.log 2>&1"

    (crontab -l 2>/dev/null | grep -v "run_screener.sh" || true; echo "$CRON_LINE") | crontab -

    echo "Cron job terpasang:"
    echo "$CRON_LINE"
    echo ""
    echo "Daftar cron job sekarang:"
    crontab -l
fi

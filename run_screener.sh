#!/usr/bin/env bash
# Wrapper harian IDX Stock Screener.
# Jalankan dari cron setiap hari kerja pagi.
# Contoh crontab (08:30 WIB = 01:30 UTC):
# 30 1 * * 1-5 /home/bakhtiarrifai/projects/idx-screener/run_screener.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PRESET="${SCREENER_PRESET:-default}"

# Jalankan screener dan tangkap output JSON (skip baris log)
JSON_RESULT=$("$PYTHON_BIN" idx_screener.py --preset "$PRESET" --output json 2>/dev/null)

# Validasi JSON sederhana
if ! echo "$JSON_RESULT" | jq -e . >/dev/null 2>&1; then
    echo "Gagal menghasilkan output JSON dari screener." >&2
    exit 1
fi

# Kirim ke Telegram jika .env tersedia dan Telegram diatur
if [ -f ".env" ] && [ -s ".env" ]; then
    "$PYTHON_BIN" telegram_sender.py "$JSON_RESULT"
fi

# Output ke stdout juga untuk log cron
echo "$JSON_RESULT"

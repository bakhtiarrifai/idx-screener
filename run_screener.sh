#!/usr/bin/env bash
# Wrapper harian IDX Stock Screener.
# Dijalankan oleh systemd timer setiap hari kerja pagi.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PRESET="${SCREENER_PRESET:-default}"

# Optional: ping Healthchecks.io start
if [ -n "${HEALTHCHECKS_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 "${HEALTHCHECKS_URL}/start" >/dev/null 2>&1 || true
fi

# Jalankan screener dan tangkap output JSON (skip baris log)
JSON_RESULT=$("$PYTHON_BIN" idx_screener.py --preset "$PRESET" --output json 2>/dev/null)

# Validasi JSON sederhana
if ! echo "$JSON_RESULT" | jq -e . >/dev/null 2>&1; then
    echo "Gagal menghasilkan output JSON dari screener." >&2
    # Ping failure ke Healthchecks.io
    if [ -n "${HEALTHCHECKS_URL:-}" ]; then
        curl -fsS -m 10 --retry 3 "${HEALTHCHECKS_URL}/fail" >/dev/null 2>&1 || true
    fi
    exit 1
fi

# Kirim ke Telegram jika .env tersedia dan Telegram diatur
if [ -f ".env" ] && [ -s ".env" ]; then
    "$PYTHON_BIN" telegram_sender.py "$JSON_RESULT"
fi

# Ping success ke Healthchecks.io
if [ -n "${HEALTHCHECKS_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 "$HEALTHCHECKS_URL" >/dev/null 2>&1 || true
fi

# Output ke stdout juga untuk log systemd
echo "$JSON_RESULT"

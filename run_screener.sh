#!/usr/bin/env bash
# Wrapper harian IDX Stock Screener.
# Dijalankan oleh systemd timer setiap hari kerja pagi.
# Contoh crontab (08:30 WIB = 01:30 UTC):
# 30 1 * * 1-5 /home/bakhtiarrifai/projects/idx-screener/run_screener.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer virtualenv python if available
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON=".venv/Scripts/python.exe"
else
    PYTHON="python3"
fi

PRESET="${SCREENER_PRESET:-default}"

# Optional: ping Healthchecks.io start
if [ -n "${HEALTHCHECKS_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 "${HEALTHCHECKS_URL}/start" >/dev/null 2>&1 || true
fi

# Jalankan screener dan tangkap output JSON (skip baris log)
JSON_RESULT=$("$PYTHON" run.py 2>/dev/null)

# Validasi JSON sederhana
if ! echo "$JSON_RESULT" | jq -e . >/dev/null 2>&1; then
    echo "Gagal menghasilkan output JSON dari screener." >&2
    # Ping failure ke Healthchecks.io
    if [ -n "${HEALTHCHECKS_URL:-}" ]; then
        curl -fsS -m 10 --retry 3 "${HEALTHCHECKS_URL}/fail" >/dev/null 2>&1 || true
    fi
    exit 1
fi

# Ping success ke Healthchecks.io
if [ -n "${HEALTHCHECKS_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 "$HEALTHCHECKS_URL" >/dev/null 2>&1 || true
fi

# Output ke stdout juga untuk log systemd
echo "$JSON_RESULT"

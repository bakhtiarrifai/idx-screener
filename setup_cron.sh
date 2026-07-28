#!/usr/bin/env bash
# Script untuk menginstal cron job screener harian.
# Jalankan sekali saja: bash setup_cron.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_LINE="30 1 * * 1-5 ${SCRIPT_DIR}/run_screener.sh >> ${SCRIPT_DIR}/screener.log 2>&1"

# Hapus entry lama jika ada, lalu tambahkan yang baru
(crontab -l 2>/dev/null | grep -v "run_screener.sh" || true; echo "$CRON_LINE") | crontab -

echo "Cron job terpasang:"
echo "$CRON_LINE"
echo ""
echo "Daftar cron job sekarang:"
crontab -l

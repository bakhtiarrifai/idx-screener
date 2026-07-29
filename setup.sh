#!/usr/bin/env bash
# Setup script untuk Linux/macOS
# Jalankan: bash setup.sh

set -euo pipefail

echo "🚀 Setting up IDX Screener..."

# Detect Python executable
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo "❌ Python tidak ditemukan. Silakan install Python 3.10+ terlebih dahulu."
    exit 1
fi

echo "📌 Menggunakan Python: $PYTHON"

# Create virtual environment if not exists
if [ ! -d ".venv" ]; then
    echo "📦 Membuat virtual environment..."
    $PYTHON -m venv .venv
fi

# Activate virtual environment
if [[ "$OSTYPE" == "darwin"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
    source .venv/bin/activate
else
    echo "⚠️  OS tidak dikenali: $OSTYPE"
    exit 1
fi

echo "⬆️  Install dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Copy .env.example if .env not exists
if [ ! -f ".env" ]; then
    echo "🔧 Membuat file .env dari contoh..."
    cp .env.example .env
    echo "⚠️  Jangan lupa edit file .env dengan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID kamu."
fi

echo ""
echo "✅ Setup selesai!"
echo ""
echo "Langkah selanjutnya:"
echo "  1. Edit .env dengan konfigurasi Telegram (opsional)"
echo "  2. Test screener: python3 idx_screener.py --preset loose"
echo "  3. Jalankan dashboard: python3 dashboard.py"

@echo off
REM Setup script untuk Windows
REM Jalankan: setup.bat

echo 🚀 Setting up IDX Screener...

REM Detect Python executable
python --version >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON=python
) else (
    python3 --version >nul 2>&1
    if %errorlevel% == 0 (
        set PYTHON=python3
    ) else (
        echo ❌ Python tidak ditemukan. Silakan install Python 3.10+ terlebih dahulu.
        exit /b 1
    )
)

echo 📌 Menggunakan Python: %PYTHON%

REM Create virtual environment if not exists
if not exist ".venv" (
    echo 📦 Membuat virtual environment...
    %PYTHON% -m venv .venv
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

echo ⬆️  Install dependencies...
pip install --upgrade pip
pip install -r requirements.txt

REM Copy .env.example if .env not exists
if not exist ".env" (
    echo 🔧 Membuat file .env dari contoh...
    copy .env.example .env
    echo ⚠️  Jangan lupa edit file .env dengan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID kamu.
)

echo.
echo ✅ Setup selesai!
echo.
echo Langkah selanjutnya:
echo   1. Edit .env dengan konfigurasi Telegram (opsional)
echo   2. Test screener: python idx_screener.py --preset loose
echo   3. Jalankan dashboard: python dashboard.py

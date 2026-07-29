# IDX Daily Stock Screener

Prototype screener saham harian Bursa Efek Indonesia (BEI/IDX) untuk pendekatan **swing trading**.

Setiap pagi sebelum bursa buka, alat ini mengambil data harga & volume saham IDX dari Yahoo Finance, menghitung filter objektif, dan mengembalikan daftar kandidat swing trade beserta rekomendasi Entry, SL, dan TP.

> **Catatan data**: data yang digunakan adalah **closing H-1**, dirilis hari H jam 08:30 WIB sebelum bursa buka.

## Fitur

- Data harian IDX dari **Yahoo Finance** tanpa API key
- Filter objektif: likuiditas, volume spike, momentum di atas MA20
- Indikator pendukung: **RSI(14)**, **MACD**, **ATR(14)**
- Rekomendasi trading: **Entry Zone**, **Stop Loss (SL)**, **Target Profit (TP)** dengan R:R 1:2
- Penyimpanan historis ke **SQLite**
- Notifikasi **Telegram** dengan fallback log/email
- Jalankan otomatis via **systemd timer** atau **cron**
- Health check harian + integrasi **Healthchecks.io**
- Dashboard web di http://localhost:5000

## Sumber Data

- **Yahoo Finance** via [`yfinance`](https://github.com/ranaroussi/yfinance)
- Ticker format: `<KODE>.JK` (contoh: `BBCA.JK`, `BBRI.JK`)

## Kriteria Filter

- **Likuiditas**: nilai transaksi harian ≥ Rp10 miliar
- **Volume spike**: volume hari ini ≥ 1.5x rata-rata 20 hari sebelumnya
- **Momentum**: harga close di atas MA20
- **Risiko**: harga close ≥ Rp100, data lengkap

## Instalasi Cross-Platform

### Linux / macOS

```bash
git clone https://github.com/bakhtiarrifai/idx-screener.git
cd idx-screener
bash setup.sh
```

### Windows

```bat
git clone https://github.com/bakhtiarrifai/idx-screener.git
cd idx-screener
setup.bat
```

Atau jika menggunakan PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

### Manual (semua OS)

Pastikan Python 3.10+ terinstall:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# atau: .venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env
```

## Setup Telegram (Opsional)

1. Buat bot baru melalui **@BotFather**, salin token API ke `TELEGRAM_BOT_TOKEN`.
2. Dapatkan `TELEGRAM_CHAT_ID` kamu:
   - Cara cepat: kirim pesan ke **@userinfobot**, copy angka di `Id`.
   - Atau tambahkan bot ke grup, kirim pesan, lalu buka `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. Copy file contoh dan isi datanya:

```bash
cp .env.example .env
# Edit .env dengan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID kamu
```

4. Test pengiriman:

```bash
python3 test_telegram.py
```

## Penggunaan Manual

```bash
# Aktifkan virtual environment
cd idx-screener
source .venv/bin/activate  # Linux/macOS
# atau: .venv\Scripts\activate  # Windows

# Output text default
python idx_screener.py

# Output JSON
python idx_screener.py --output json

# Gunakan preset: default, strict, loose
python idx_screener.py --preset loose

# Gunakan file konfigurasi JSON kustom
python idx_screener.py --config config.json

# Parameter kustom langsung
python idx_screener.py --min-value 5000000000 --volume-spike 1.2 --top-n 15 --period 90d
```

### Runner Cross-Platform

```bash
# Linux/macOS
python run.py

# Windows
python run.py
```

## Jalankan Otomatis

### Linux (Systemd Timer)

```bash
bash setup_cron.sh
systemctl --user status idx-screener.timer
```

Timer akan berjalan hari kerja pukul 08:30 WIB.

### macOS

Systemd tidak tersedia di macOS. Gunakan **cron** atau **launchd**:

```bash
bash setup_cron.sh
```

Jika systemd tidak terdeteksi, setup_cron.sh otomatis menggunakan cron.

### Windows (Task Scheduler)

Untuk Windows Task Scheduler, jalankan manual setiap pagi atau gunakan Task Scheduler:

```powershell
# Membuat task baru dengan Task Scheduler
schtasks /create /tn "IDX Screener" /tr "C:\path\to\idx-screener\.venv\Scripts\python.exe C:\path\to\idx-screener\run.py" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:30
```

## Health Check & Monitoring

### Health Check Lokal

```bash
python health_check.py
```

### Healthchecks.io (Opsional)

1. Buat akun di https://healthchecks.io
2. Buat check baru, salin URL ping ke `.env`:

```bash
HEALTHCHECKS_URL=https://hc-ping.com/your-uuid-here
```

3. Screener akan otomatis mengirim ping saat mulai dan selesai.

## Output JSON

```json
{
  "date": "2026-07-28",
  "candidates": [...],
  "total_candidates": 0,
  "filters": {...}
}
```

## Preset Filter

| Preset | Min Value Traded | Volume Spike | Top N |
|--------|------------------|--------------|-------|
| strict | Rp 20 miliar     | 2.0x         | 10    |
| default| Rp 10 miliar     | 1.5x         | 10    |
| loose  | Rp 5 miliar      | 1.2x         | 15    |

## Rekomendasi Trading

Setiap kandidat yang lolos filter akan mendapatkan rekomendasi:

| Kolom | Keterangan |
|-------|-----------|
| **Entry Zone** | Zona harga beli yang disarankan |
| **SL** | Stop Loss, dihitung dari ATR(14) × 1.5 |
| **TP** | Target Profit, R:R minimum 1:2 |
| **R:R** | Risk-reward ratio |

## Fallback Notifikasi

Jika pengiriman Telegram gagal, pesan akan disimpan ke `fallback_notifications.log` dan/atau dikirim via email jika variabel SMTP diatur di `.env`.

## Dashboard Web

Dashboard tersedia di http://localhost:5000

### Jalankan Manual

```bash
python dashboard.py
```

### Jalankan via Systemd (Linux)

```bash
systemctl --user enable --now idx-screener-dashboard.service
systemctl --user status idx-screener-dashboard.service
```

### Endpoint API

```bash
curl http://localhost:5000/api/screenings?days=30
```

Fitur dashboard:
- Statistik total hari terekam, total kandidat, rata-rata/hari
- Filter periode (7/30/60/90 hari)
- Filter berdasarkan ticker
- Tabel histori dengan Entry Zone, SL, TP, dan R:R
- Chart kandidat per hari dan volume spike per ticker

## Catatan Penting

- Ini adalah **alat bantu analisis**, bukan sinyal beli otomatis. Keputusan trading tetap manual.
- Filter default cukup ketat. Di pasar tenang bisa jadi tidak ada kandidat yang lolos — itu wajar dan justru bagus untuk mencegah over-trading.
- Data yang digunakan adalah closing H-1 karena bursa baru buka pukul 09:00 WIB dan data harian diupdate setelah market close.

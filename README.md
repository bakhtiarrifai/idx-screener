# IDX Daily Stock Screener

Prototype screener saham harian Bursa Efek Indonesia (BEI/IDX) untuk pendekatan **swing trading**.

## Tujuan

Setiap pagi sebelum bursa buka, alat ini mengambil data harga & volume saham IDX dari Yahoo Finance, menghitung filter objektif, dan mengembalikan daftar kandidat swing trade.

## Fitur

- Data harian IDX dari **Yahoo Finance** tanpa API key
- Filter objektif: likuiditas, volume spike, momentum di atas MA20
- Indikator pendukung: **RSI(14)** dan **MACD**
- Penyimpanan historis ke **SQLite**
- Notifikasi **Telegram** dengan fallback log/email
- Jalankan otomatis via **cron**

## Sumber Data

- **Yahoo Finance** via [`yfinance`](https://github.com/ranaroussi/yfinance)
- Ticker format: `<KODE>.JK` (contoh: `BBCA.JK`, `BBRI.JK`)

## Kriteria Filter

- **Likuiditas**: nilai transaksi harian ≥ Rp10 miliar
- **Volume spike**: volume hari ini ≥ 1.5x rata-rata 20 hari sebelumnya
- **Momentum**: harga close di atas MA20
- **Risiko**: harga close ≥ Rp100, data lengkap

## Instalasi untuk Clone

```bash
git clone https://github.com/bakhtiarrifai/idx-screener.git
cd idx-screener
python3 -m pip install -r requirements.txt
```

> **Catatan penting:** File `.env` tidak ikut di repository (masuk `.gitignore`). Setelah clone, buat file `.env` sendiri dari contoh: `cp .env.example .env`, lalu isi `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID`.

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
# Output text default
python3 idx_screener.py

# Output JSON
python3 idx_screener.py --output json

# Gunakan preset: default, strict, loose
python3 idx_screener.py --preset loose

# Gunakan file konfigurasi JSON kustom
python3 idx_screener.py --config config.json

# Parameter kustom langsung
python3 idx_screener.py --min-value 5000000000 --volume-spike 1.2 --top-n 15 --period 90d
```

## Jalankan Otomatis via Cron

```bash
bash setup_cron.sh
```

Ini akan memasang cron job Senin–Jumat pukul 08:30 WIB yang menjalankan screener dan mengirim hasil ke Telegram.

Gunakan preset tertentu via environment variable:

```bash
SCREENER_PRESET=loose bash setup_cron.sh
```

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

## Fallback Notifikasi

Jika pengiriman Telegram gagal, pesan akan disimpan ke `fallback_notifications.log` dan/atau dikirim via email jika variabel SMTP diatur di `.env`.

## Catatan Penting

- Ini adalah **alat bantu analisis**, bukan sinyal beli otomatis. Keputusan trading tetap manual.
- Filter default cukup ketat. Di pasar tenang bisa jadi tidak ada kandidat yang lolos — itu wajar dan justru bagus untuk mencegah over-trading.

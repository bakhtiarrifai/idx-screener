# Proyek: IDX Daily Stock Screener (n8n)

## Konteks
Masbah membangun screener saham harian Bursa Efek Indonesia (BEI/IDX) menggunakan n8n sebagai orchestrator lokal (bagian dari ekosistem AI swarm yang sudah berjalan: Podman/Docker + n8n + Ollama di Fedora/Ubuntu, Fujitsu Lifebook U9310).

Latar belakang keputusan: pivot dari day-trading target harian (tidak realistis) ke **swing trading disiplin** — target 3-8% per posisi dalam hitungan hari-minggu, di saham likuid, dengan stop loss dan trading journal. Screener ini menggantikan "rekomendasi feeling" dengan kriteria objektif.

## Tujuan Screener
Setiap pagi sebelum bursa buka (±08:30 WIB), n8n menjalankan workflow yang:
1. Mengambil data harga & volume saham IDX (fokus awal: LQ45 / saham likuid)
2. Menyaring berdasarkan kriteria objektif, misalnya:
   - Likuiditas: nilai transaksi harian minimum (mis. > Rp10 miliar)
   - Volume spike: volume kemarin > 1.5-2x rata-rata 20 hari
   - Momentum: harga di atas MA20, atau breakout resistance
   - Filter risiko: exclude saham dengan notasi khusus / suspensi
3. Mengirim hasil (5-10 kandidat) ke Telegram/notifikasi, dengan data pendukung — BUKAN sinyal beli otomatis; keputusan tetap manual (prinsip 20% human approval gate)

## Keputusan Teknis yang Perlu Dieksplorasi Bersama Claude Code
- Sumber data: API/endpoint data IDX yang gratis & legal (mis. data harian dari sumber publik), rate limit, format
- Penyimpanan histori: SQLite/PostgreSQL lokal untuk hitung rata-rata & indikator
- Perhitungan indikator: Python script node di n8n vs service terpisah
- Jadwal: cron trigger n8n, hari bursa saja (skip weekend/libur bursa)
- Output: format pesan Telegram yang ringkas + link chart

## Konstrain
- Auth Claude Code via Claude Pro (JANGAN set ANTHROPIC_API_KEY di environment)
- Semua berjalan lokal/self-hosted, biaya operasional ~nol
- Bahasa komunikasi: Bahasa Indonesia
- Ini alat bantu analisis, bukan robot trading — tidak ada eksekusi order otomatis

## Langkah Pertama yang Disarankan
1. Riset & pilih sumber data harga IDX yang reliable
2. Prototype: script Python sederhana yang tarik data 1 hari + hitung filter volume/MA20
3. Baru setelah itu bungkus ke n8n workflow + notifikasi Telegram

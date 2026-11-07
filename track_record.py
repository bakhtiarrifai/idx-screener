#!/usr/bin/env python3
"""
Rekam jejak sinyal screener — LENGKAP, bukan hanya yang menang.

Untuk setiap sinyal di tabel `screenings` (kecuali NO_CANDIDATE), hitung hasilnya dari data harga
harian Yahoo Finance setelah sinyal dikirim, lalu simpan ke tabel `signal_outcomes` dan ekspor
JSON + potongan HTML yang bisa ditempel di landing page.

Aturan (dicetak juga di ekspor supaya publik bisa memeriksa):
  - Sinyal tanggal D memakai data penutupan D dan dikirim pagi hari bursa berikutnya (created_at).
  - Entry: hari bursa pertama setelah D yang rentang hariannya menyentuh zona entry, maksimal
    ENTRY_WINDOW hari. Harga entry = Open bila di dalam zona; bila gap di atas zona = batas atas;
    bila gap di bawah zona = batas bawah. Tidak tersentuh → "tidak_entry".
  - Setelah entry: Low <= SL → "sl"; High >= TP → "tp". Bila keduanya di hari yang sama → "sl"
    (asumsi konservatif). Termasuk hari entry itu sendiri.
  - Belum kena TP/SL setelah MAX_HOLD hari bursa → "kedaluwarsa" dengan harga Close hari itu.
  - Masih dalam jendela → "berjalan".
  - Sinyal ganda (tanggal + ticker sama) dihitung sekali.

Pemakaian:
  python3 track_record.py update   [--db screener_history.db]
  python3 track_record.py export   [--db ...] [--out public] [--strategy-since YYYY-MM-DD]
  python3 track_record.py summary  [--db ...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sqlite3
import sys
from pathlib import Path

ENTRY_WINDOW = 3   # hari bursa untuk menunggu harga masuk zona entry
MAX_HOLD = 20      # hari bursa maksimal memegang posisi
RULES_VERSION = "1"

STATUS_LABEL = {
    "tp": "Kena TP", "sl": "Kena SL", "kedaluwarsa": "Kedaluwarsa",
    "tidak_entry": "Tidak entry", "berjalan": "Berjalan",
}


def connect(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_outcomes (
            signal_date   TEXT NOT NULL,
            ticker        TEXT NOT NULL,
            screening_id  INTEGER NOT NULL,
            sent_at       TEXT,
            entry_low     REAL, entry_high REAL, stop_loss REAL, target_profit REAL,
            status        TEXT NOT NULL,
            entry_date    TEXT, entry_price REAL,
            exit_date     TEXT, exit_price REAL,
            return_pct    REAL,
            days_held     INTEGER,
            last_price_date TEXT,
            rules_version TEXT NOT NULL,
            checked_at    TEXT NOT NULL,
            PRIMARY KEY (signal_date, ticker)
        )
        """
    )
    return conn


def load_signals(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.* FROM screenings s
        JOIN (SELECT date, ticker, MIN(id) AS id FROM screenings
              WHERE ticker != 'NO_CANDIDATE' GROUP BY date, ticker) first ON first.id = s.id
        WHERE s.stop_loss IS NOT NULL AND s.target_profit IS NOT NULL
          AND s.entry_zone_low IS NOT NULL AND s.entry_zone_high IS NOT NULL
        ORDER BY s.date, s.ticker
        """
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_history(tickers: list[str], start: dt.date):
    import pandas as pd
    import yfinance as yf

    data = yf.download(tickers, start=start.isoformat(), group_by="ticker", progress=False,
                       auto_adjust=False, threads=True)
    out = {}
    for t in tickers:
        try:
            df = data[t] if len(tickers) > 1 else data
        except KeyError:
            continue
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        df.index = pd.to_datetime(df.index).date
        out[t] = df
    return out


def evaluate(sig: dict, df) -> dict:
    d = dt.date.fromisoformat(sig["date"])
    lo, hi = sig["entry_zone_low"], sig["entry_zone_high"]
    sl, tp = sig["stop_loss"], sig["target_profit"]
    days = [x for x in df.index if x > d]
    res = {"status": "berjalan", "entry_date": None, "entry_price": None, "exit_date": None,
           "exit_price": None, "return_pct": None, "days_held": None,
           "last_price_date": days[-1].isoformat() if days else None}

    entry_i = None
    for i, day in enumerate(days[:ENTRY_WINDOW]):
        r = df.loc[day]
        if r["Low"] <= hi and r["High"] >= lo:
            o = float(r["Open"])
            price = o if lo <= o <= hi else (hi if o > hi else lo)
            entry_i, res["entry_date"], res["entry_price"] = i, day.isoformat(), round(price, 2)
            break
    if entry_i is None:
        if len(days) >= ENTRY_WINDOW:
            res["status"] = "tidak_entry"
        return res

    entry = res["entry_price"]
    held = days[entry_i:entry_i + MAX_HOLD]
    for n, day in enumerate(held, start=1):
        r = df.loc[day]
        hit_sl, hit_tp = r["Low"] <= sl, r["High"] >= tp
        if hit_sl or hit_tp:
            status, price = ("sl", sl) if hit_sl else ("tp", tp)   # keduanya sehari → SL (konservatif)
            res.update(status=status, exit_date=day.isoformat(), exit_price=round(price, 2), days_held=n)
            break
    else:
        if len(held) >= MAX_HOLD:
            last = held[-1]
            res.update(status="kedaluwarsa", exit_date=last.isoformat(),
                       exit_price=round(float(df.loc[last]["Close"]), 2), days_held=MAX_HOLD)
        else:
            res["days_held"] = len(held)
            res["return_pct"] = round((float(df.loc[held[-1]]["Close"]) / entry - 1) * 100, 2) if held else None
            return res   # berjalan: return_pct = posisi terakhir (belum final)
    res["return_pct"] = round((res["exit_price"] / entry - 1) * 100, 2)
    return res


def cmd_update(conn) -> int:
    sigs = load_signals(conn)
    final = {(r["signal_date"], r["ticker"]) for r in conn.execute(
        "SELECT signal_date, ticker FROM signal_outcomes WHERE status IN ('tp','sl','kedaluwarsa','tidak_entry') "
        "AND rules_version = ?", (RULES_VERSION,))}
    todo = [s for s in sigs if (s["date"], s["ticker"]) not in final]
    if not todo:
        print("Tidak ada sinyal yang perlu diperbarui.")
        return 0
    start = min(dt.date.fromisoformat(s["date"]) for s in todo) - dt.timedelta(days=3)
    hist = fetch_history(sorted({s["ticker"] for s in todo}), start)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    n = 0
    for s in todo:
        df = hist.get(s["ticker"])
        if df is None or df.empty:
            continue
        r = evaluate(s, df)
        conn.execute(
            """INSERT OR REPLACE INTO signal_outcomes VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (s["date"], s["ticker"], s["id"], s.get("created_at"), s["entry_zone_low"], s["entry_zone_high"],
             s["stop_loss"], s["target_profit"], r["status"], r["entry_date"], r["entry_price"],
             r["exit_date"], r["exit_price"], r["return_pct"], r["days_held"], r["last_price_date"],
             RULES_VERSION, now))
        n += 1
    conn.commit()
    print(f"Diperbarui: {n} sinyal ({len(sigs)} total sinyal unik).")
    return 0


def summarize(rows: list[dict]) -> dict:
    count = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS_LABEL}
    closed = [r for r in rows if r["status"] in ("tp", "sl", "kedaluwarsa")]
    rets = [r["return_pct"] for r in closed if r["return_pct"] is not None]
    return {
        "total_sinyal": len(rows), **count,
        "selesai": len(closed),
        "rata2_return_selesai_pct": round(sum(rets) / len(rets), 2) if rets else None,
        "persen_tp_dari_selesai": round(count["tp"] / len(closed) * 100, 1) if closed else None,
    }


def rows_for_export(conn, since: str | None, tag: str | None = None) -> list[dict]:
    has_tag = "strategy" in [r[1] for r in conn.execute("PRAGMA table_info(screenings)")]
    tag_col = "COALESCE(s.strategy, 'legacy')" if has_tag else "'legacy'"
    q = (f"SELECT o.*, {tag_col} AS strategy FROM signal_outcomes o JOIN screenings s ON s.id = o.screening_id "
         "WHERE o.rules_version = ?")
    args = [RULES_VERSION]
    if since:
        q += " AND o.signal_date >= ?"
        args.append(since)
    if tag:
        q += f" AND {tag_col} = ?"
        args.append(tag)
    return [dict(r) for r in conn.execute(q + " ORDER BY o.signal_date DESC, o.ticker", args)]


def cmd_export(conn, out: Path, since: str | None, strategy: str, tag: str | None = None) -> int:
    rows = rows_for_export(conn, since, tag)
    summ = summarize(rows)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "strategy": strategy, "since": since, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "rules": {"version": RULES_VERSION, "entry_window_days": ENTRY_WINDOW, "max_hold_days": MAX_HOLD,
                  "same_day_tp_sl": "dihitung SL", "duplikat": "dihitung sekali"},
        "summary": summ, "signals": rows,
    }
    (out / "track_record.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    (out / "track_record.html").write_text(render_html(payload))
    print(json.dumps(summ, ensure_ascii=False))
    return 0


def _fmt(v, nd=0):
    return "–" if v is None else f"{v:,.{nd}f}".replace(",", ".")


def render_html(p: dict) -> str:
    s = p["summary"]
    color = {"tp": "#15803d", "sl": "#dc2626", "kedaluwarsa": "#b45309", "tidak_entry": "#6b7280", "berjalan": "#5b3df5"}
    trs = []
    for r in p["signals"]:
        ret = "–" if r["return_pct"] is None else f"{r['return_pct']:+.2f}%".replace(".", ",")
        sent = (r.get("sent_at") or "")[:16].replace("T", " ")
        trs.append(
            f"<tr><td>{html.escape(r['signal_date'])}</td><td>{html.escape(sent)} UTC</td>"
            f"<td><b>{html.escape(r['ticker'].replace('.JK', ''))}</b></td>"
            f"<td>{_fmt(r['entry_low'])}–{_fmt(r['entry_high'])}</td><td>{_fmt(r['stop_loss'])}</td><td>{_fmt(r['target_profit'])}</td>"
            f"<td style=\"color:{color[r['status']]};font-weight:700\">{STATUS_LABEL[r['status']]}</td>"
            f"<td>{ret}</td><td>{r['days_held'] or '–'}</td></tr>")
    pct = "–" if s["persen_tp_dari_selesai"] is None else f"{s['persen_tp_dari_selesai']}%".replace(".", ",")
    return f"""<section id="rekam-jejak" style="font-family:inherit">
<h2>Rekam jejak sinyal — semua, termasuk yang rugi</h2>
<p style="opacity:.75;font-size:14px">Diperbarui otomatis tiap hari bursa. Setiap baris tercatat dengan waktu kirim
sebelum hasilnya diketahui. Sinyal yang kena SL, kedaluwarsa, dan tidak entry ikut ditampilkan.</p>
<p><b>{s['total_sinyal']}</b> sinyal · <b style="color:#15803d">{s['tp']} TP</b> · <b style="color:#dc2626">{s['sl']} SL</b> ·
{s['kedaluwarsa']} kedaluwarsa · {s['tidak_entry']} tidak entry · {s['berjalan']} berjalan ·
TP dari yang selesai: <b>{pct}</b></p>
<div style="overflow-x:auto"><table style="border-collapse:collapse;font-size:13px;min-width:720px">
<thead><tr><th>Data</th><th>Dikirim</th><th>Saham</th><th>Entry</th><th>SL</th><th>TP</th><th>Hasil</th><th>Return</th><th>Hari</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table></div>
<p style="opacity:.7;font-size:12px">Aturan v{p['rules']['version']}: entry bila harga menyentuh zona dalam {p['rules']['entry_window_days']} hari bursa;
maksimal {p['rules']['max_hold_days']} hari bursa; bila TP dan SL tersentuh di hari yang sama dihitung SL. Return belum termasuk biaya
transaksi. Rekam jejak masa lalu bukan jaminan hasil di masa depan dan bukan rekomendasi investasi.</p>
</section>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["update", "export", "summary"])
    ap.add_argument("--db", default=str(Path(__file__).with_name("screener_history.db")))
    ap.add_argument("--out", default=str(Path(__file__).with_name("public")))
    ap.add_argument("--since", default=None, help="Hanya sinyal sejak tanggal ini (mis. mulai strategi Scanry)")
    ap.add_argument("--tag", default=None, help="Hanya sinyal dengan tag strategi ini (legacy, legacy-fixed, t1)")
    ap.add_argument("--strategy", default=None, help="Label strategi di ekspor (default: dari --tag)")
    a = ap.parse_args()
    conn = connect(a.db)
    if a.cmd == "update":
        return cmd_update(conn)
    if a.cmd == "export":
        label = a.strategy or {None: "semua strategi", "legacy": "MA20 + volume spike (legacy, ada bug)",
                               "legacy-fixed": "MA20 + volume spike (diperbaiki)",
                               "t1": "T1 breakout tren + IHSG uptrend"}.get(a.tag, a.tag)
        return cmd_export(conn, Path(a.out), a.since, label, a.tag)
    print(json.dumps(summarize(rows_for_export(conn, a.since, a.tag)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

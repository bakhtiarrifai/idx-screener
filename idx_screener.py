#!/usr/bin/env python3
"""
IDX Daily Stock Screener (prototype)

Mengambil data harga saham IDX dari Yahoo Finance via yfinance,
lalu menyaring kandidat swing trade berdasarkan:
- Likuiditas: nilai transaksi harian minimum (default > Rp10 miliar)
- Volume spike: volume kemarin > 1.5x rata-rata 20 hari
- Momentum: harga close di atas MA20
- Filter risiko: exclude saham dengan data tidak lengkap atau harga terlalu rendah
- Indikator pendukung: RSI, MACD
- Rekomendasi: entry zone, TP (target profit), SL (stop loss)

Output: daftar kandidat dengan metrik pendukung (text atau JSON).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import logging
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

LQ45_TICKERS = [
    "ACES.JK", "ADRO.JK", "AMRT.JK", "ANTM.JK", "ARTO.JK", "ASII.JK",
    "BBCA.JK", "BBNI.JK", "BBRI.JK", "BMRI.JK", "BRIS.JK", "BRPT.JK",
    "CPIN.JK", "EMTK.JK", "ESSA.JK", "EXCL.JK", "GGRM.JK", "GOTO.JK",
    "HMSP.JK", "HRUM.JK", "ICBP.JK", "INCO.JK", "INDF.JK", "ITMG.JK",
    "KLBF.JK", "LPPF.JK", "MBMA.JK", "MEDC.JK", "MIKA.JK", "MNCN.JK",
    "PGAS.JK", "PTBA.JK", "SMGR.JK", "TBIG.JK", "TINS.JK", "TLKM.JK",
    "TOWR.JK", "UNTR.JK", "UNVR.JK", "WIIM.JK",
]

PRESETS = {
    "default": {"min_value_traded": 10_000_000_000.0, "volume_spike_ratio": 1.5, "min_close_price": 100.0, "top_n": 10},
    "strict": {"min_value_traded": 20_000_000_000.0, "volume_spike_ratio": 2.0, "min_close_price": 100.0, "top_n": 10},
    "loose": {"min_value_traded": 5_000_000_000.0, "volume_spike_ratio": 1.2, "min_close_price": 50.0, "top_n": 15},
}

# Konstanta rekomendasi risiko
SWING_RISK_PERCENT = 0.07       # jarak SL 7% dari harga close
MIN_REWARD_RISK = 2.0           # minimum R:R 1:2
DEFAULT_TP_PERCENT = 0.05       # TP +5% (kalau ATR tidak tersedia)
DEFAULT_ENTRY_BUFFER = 0.015    # zona entry ±1.5%


@dataclass
class ScreenerConfig:
    min_value_traded: float = 10_000_000_000.0
    volume_spike_ratio: float = 1.5
    ma_window: int = 20
    min_close_price: float = 100.0
    top_n: int = 10

    @classmethod
    def from_preset(cls, name: str) -> "ScreenerConfig":
        preset = PRESETS.get(name, PRESETS["default"])
        return cls(**preset)

    @classmethod
    def from_file(cls, path: str | Path) -> "ScreenerConfig":
        with open(path) as f:
            data = json.load(f)
        return cls(**data)


@dataclass
class TradeRecommendation:
    ticker: str
    close: float
    entry_zone_low: float
    entry_zone_high: float
    stop_loss: float
    target_profit: float
    risk_reward: float
    rationale: str


@dataclass
class StockMetrics:
    ticker: str
    close: float
    volume: int
    value_traded: float
    avg_volume_20d: float
    volume_spike: float
    ma20: float
    above_ma20: bool
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    atr14: float | None
    latest_date: str
    recommendation: TradeRecommendation | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "StockMetrics":
        """Bangun StockMetrics dari dict (mis. hasil asdict/JSON), termasuk nested recommendation."""
        data = dict(data)
        rec = data.get("recommendation")
        if isinstance(rec, dict):
            data["recommendation"] = TradeRecommendation(**rec)
        return cls(**data)


def _compute_rsi(prices: pd.Series, window: int = 14) -> float | None:
    if len(prices) < window + 1:
        return None
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0)).astype(float)
    avg_gain = gain.rolling(window=window).mean().iloc[-1]
    avg_loss = loss.rolling(window=window).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def _compute_macd(prices: pd.Series) -> tuple[float | None, float | None]:
    if len(prices) < 35:
        return None, None
    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return float(macd.iloc[-1]), float(signal.iloc[-1])


def _compute_atr(df: pd.DataFrame, window: int = 14) -> float | None:
    """Average True Range untuk sizing SL dinamis."""
    if len(df) < window + 1:
        return None
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=window).mean().iloc[-1]
    return float(atr) if pd.notna(atr) else None


def generate_recommendation(
    ticker: str,
    close: float,
    ma20: float,
    atr14: float | None,
    rsi14: float | None,
) -> TradeRecommendation:
    """
    Buat rekomendasi entry, SL, dan TP untuk swing trading.
    - Entry zone: sekitar close dengan buffer kecil (atau pullback ke MA20 jika RSI tinggi)
    - SL: di bawah support terdekat (ATR-based atau 7%)
    - TP: berdasarkan risk-reward minimum 1:1.5
    """
    # Tentukan entry zone
    if rsi14 is not None and rsi14 > 70:
        # Jangan chase, tunggu pullback ke dekat MA20
        entry_zone_high = close
        entry_zone_low = max(close * 0.96, ma20)
    else:
        entry_zone_low = close * (1 - DEFAULT_ENTRY_BUFFER)
        entry_zone_high = close * (1 + DEFAULT_ENTRY_BUFFER)

    # Stop loss: ATR-based kalau tersedia, fallback 7%
    if atr14 is not None and atr14 > 0:
        sl_distance = max(atr14 * 1.5, close * 0.04)
    else:
        sl_distance = close * SWING_RISK_PERCENT

    stop_loss = close - sl_distance

    # TP harus memenuhi R:R minimum
    tp_distance = sl_distance * MIN_REWARD_RISK
    target_profit = close + tp_distance

    risk_reward = (target_profit - close) / (close - stop_loss)

    if rsi14 is not None and rsi14 > 70:
        rationale = f"RSI tinggi ({rsi14:.1f}); tunggu pullback ke zona entry. SL ATR-based, TP {MIN_REWARD_RISK:.0f}:1."
    else:
        rationale = f"Breakout volume dengan SL ATR-based. Target TP {MIN_REWARD_RISK:.0f}:1 risk-reward."

    return TradeRecommendation(
        ticker=ticker,
        close=close,
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        stop_loss=stop_loss,
        target_profit=target_profit,
        risk_reward=risk_reward,
        rationale=rationale,
    )


def fetch_prices(tickers: list[str], period: str = "90d", progress: bool = False) -> pd.DataFrame:
    """Download OHLCV untuk sekumpulan ticker Yahoo Finance."""
    logger.info("Mengunduh data untuk %d ticker (period=%s)...", len(tickers), period)
    data = yf.download(tickers, period=period, group_by="ticker", progress=progress, threads=True)

    if data is None or data.empty:
        raise ValueError("Tidak ada data yang berhasil diunduh.")

    if len(tickers) == 1 and "Close" in data.columns:
        df = data.copy()
        df["Ticker"] = tickers[0]
    else:
        frames = []
        for ticker in tickers:
            if ticker not in data.columns.levels[0]:
                logger.warning("Ticker %s tidak ditemukan di hasil download.", ticker)
                continue
            tdf = data[ticker].copy()
            tdf["Ticker"] = ticker
            frames.append(tdf)
        if not frames:
            raise ValueError("Tidak ada ticker yang berhasil diunduh.")
        df = pd.concat(frames)

    df = df.reset_index()
    df = df[["Date", "Ticker", "Open", "High", "Low", "Close", "Volume"]]
    df = df.dropna(subset=["Close", "Volume"])
    return df


def calculate_metrics(df: pd.DataFrame, config: ScreenerConfig) -> list[StockMetrics]:
    """Hitung metrik per ticker berdasarkan DataFrame OHLCV."""
    metrics: list[StockMetrics] = []

    for ticker, group in df.groupby("Ticker"):
        group = group.sort_values("Date").reset_index(drop=True)
        if len(group) < config.ma_window + 1:
            continue

        latest = group.iloc[-1]
        close = float(latest["Close"])
        volume = int(latest["Volume"])
        value_traded = close * volume

        # [upgrade-2026-11] fix: rata-rata volume = 20 hari SEBELUM hari sinyal; MA20 = 20 close terakhir.
        prev = group.iloc[:-1]
        if len(prev) < config.ma_window:
            continue

        avg_volume_20d = float(prev["Volume"].tail(config.ma_window).mean())
        ma20 = float(group["Close"].tail(config.ma_window).mean())
        volume_spike = volume / avg_volume_20d if avg_volume_20d > 0 else 0.0

        close_series = group["Close"]
        rsi14 = _compute_rsi(close_series, window=14)
        macd, macd_signal = _compute_macd(close_series)
        atr14 = _compute_atr(group)

        recommendation = generate_recommendation(
            ticker=ticker,
            close=close,
            ma20=ma20,
            atr14=atr14,
            rsi14=rsi14,
        )

        metrics.append(
            StockMetrics(
                ticker=ticker,
                close=close,
                volume=volume,
                value_traded=value_traded,
                avg_volume_20d=avg_volume_20d,
                volume_spike=volume_spike,
                ma20=ma20,
                above_ma20=close > ma20,
                rsi14=rsi14,
                macd=macd,
                macd_signal=macd_signal,
                atr14=atr14,
                latest_date=pd.to_datetime(latest["Date"]).date().isoformat(),
                recommendation=recommendation,
            )
        )

    return metrics


def filter_candidates(metrics: list[StockMetrics], config: ScreenerConfig) -> list[StockMetrics]:
    """Terapkan filter screener."""
    candidates = [
        m for m in metrics
        if m.value_traded >= config.min_value_traded
        and m.volume_spike >= config.volume_spike_ratio
        and m.above_ma20
        and m.close >= config.min_close_price
    ]
    candidates.sort(key=lambda x: (x.volume_spike, x.value_traded), reverse=True)
    return candidates[: config.top_n]


def format_currency(value: float) -> str:
    """Format angka ke Rupiah ringkas."""
    if value >= 1_000_000_000_000:
        return f"Rp {value/1_000_000_000_000:.2f} T"
    if value >= 1_000_000_000:
        return f"Rp {value/1_000_000_000:.2f} M"
    if value >= 1_000_000:
        return f"Rp {value/1_000_000:.2f} jt"
    return f"Rp {value:,.0f}"


def print_results(candidates: list[StockMetrics], date_str: str | None = None) -> None:
    if not candidates:
        print(f"\nTidak ada kandidat yang lolos filter pada tanggal {date_str or 'terakhir'}.\n")
        return

    print(f"\n📊 IDX Swing Trade Screener — {date_str}\n")
    for m in candidates:
        print(f"{'='*70}")
        print(f"*{m.ticker}*  Close: {m.close:,.0f}")
        print(f"  Volume Spike: {m.volume_spike:.2f}x | MA20: {m.ma20:,.0f} | RSI14: {m.rsi14:.1f} | MACD: {m.macd:.2f}")
        if m.recommendation:
            rec = m.recommendation
            print(f"\n  💡 Entry Zone: {rec.entry_zone_low:,.0f} - {rec.entry_zone_high:,.0f}")
            print(f"  🛑 Stop Loss:  {rec.stop_loss:,.0f}")
            print(f"  🎯 Target:     {rec.target_profit:,.0f}")
            print(f"  ⚖️  R:R:        1:{rec.risk_reward:.2f}")
            print(f"  📝 {rec.rationale}")
    print(f"\nTotal kandidat: {len(candidates)}\n")


class HistoryStore:
    """SQLite store untuk menyimpan hasil screener harian."""

    def __init__(self, db_path: str | Path = "screener_history.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS screenings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    value_traded REAL NOT NULL,
                    volume_spike REAL NOT NULL,
                    ma20 REAL NOT NULL,
                    rsi14 REAL,
                    macd REAL,
                    macd_signal REAL,
                    atr14 REAL,
                    entry_zone_low REAL,
                    entry_zone_high REAL,
                    stop_loss REAL,
                    target_profit REAL,
                    risk_reward REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def save(self, date: str, candidates: list[dict]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            if candidates:
                for c in candidates:
                    rec = c.get("recommendation")
                    conn.execute(
                        """
                        INSERT INTO screenings
                        (date, ticker, close, volume, value_traded, volume_spike, ma20, rsi14, macd, macd_signal,
                         atr14, entry_zone_low, entry_zone_high, stop_loss, target_profit, risk_reward)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            date,
                            c["ticker"],
                            c["close"],
                            c["volume"],
                            c["value_traded"],
                            c["volume_spike"],
                            c["ma20"],
                            c.get("rsi14"),
                            c.get("macd"),
                            c.get("macd_signal"),
                            c.get("atr14"),
                            rec.get("entry_zone_low") if rec else None,
                            rec.get("entry_zone_high") if rec else None,
                            rec.get("stop_loss") if rec else None,
                            rec.get("target_profit") if rec else None,
                            rec.get("risk_reward") if rec else None,
                        ),
                    )
            else:
                # Insert a "no candidate" placeholder row so the date is recorded
                conn.execute(
                    """
                    INSERT INTO screenings
                    (date, ticker, close, volume, value_traded, volume_spike, ma20, rsi14, macd, macd_signal,
                     atr14, entry_zone_low, entry_zone_high, stop_loss, target_profit, risk_reward)
                    VALUES (?, 'NO_CANDIDATE', 0, 0, 0, 0, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                    """,
                    (date,),
                )
            conn.commit()

    def get_recent(self, limit: int = 30) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM screenings ORDER BY date DESC, volume_spike DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]


# Migration: add recommendation columns if table exists without them

def _migrate_db(db_path: str | Path) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("PRAGMA table_info(screenings)")
        columns = [row[1] for row in cursor.fetchall()]
        new_columns = {
            "atr14": "REAL",
            "entry_zone_low": "REAL",
            "entry_zone_high": "REAL",
            "stop_loss": "REAL",
            "target_profit": "REAL",
            "risk_reward": "REAL",
            "strategy": "TEXT",  # [upgrade-2026-11]
        }
        for col, col_type in new_columns.items():
            if col not in columns:
                conn.execute(f"ALTER TABLE screenings ADD COLUMN {col} {col_type}")
        conn.commit()


# [upgrade-2026-11] Tag strategi & penjaga data basi (hari libur).
def _date_already_saved(db_path, date: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT 1 FROM screenings WHERE date = ? LIMIT 1", (date,)).fetchone() is not None


def _tag_strategy(db_path, date: str, strategy: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE screenings SET strategy = ? WHERE date = ? AND strategy IS NULL", (strategy, date))
        conn.commit()


# [upgrade-2026-11] Strategi T1 — dipilih lewat backtest 2019–2023 & diuji 2024–2026 (lihat supervisor bulanan).
T1_SL_ATR = float(os.environ.get("T1_SL_ATR", "2.0"))   # ubah via env setelah disetujui dari laporan supervisor
T1_TP_ATR = float(os.environ.get("T1_TP_ATR", "4.0"))
T1_MAX_DAYS, T1_TOP_N = 20, 5
INDEX_TICKER = "^JKSE"


def _wilder_atr(g: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat([g["High"] - g["Low"], (g["High"] - g["Close"].shift()).abs(),
                    (g["Low"] - g["Close"].shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def _index_uptrend() -> bool:
    idx = yf.download(INDEX_TICKER, period="2y", progress=False, auto_adjust=True)
    c = idx["Close"].squeeze().dropna()
    ma50, ma200 = c.rolling(50).mean(), c.rolling(200).mean()
    return bool(c.iloc[-1] > ma50.iloc[-1] > ma200.iloc[-1])


def t1_candidates(df: pd.DataFrame, config: "ScreenerConfig") -> list["StockMetrics"]:
    """Breakout close di atas high 20 hari + volume ≥1,5× rata-rata 20 hari + MA50>MA200, saat IHSG uptrend."""
    if not _index_uptrend():
        logger.info("T1: IHSG tidak dalam tren naik (close>MA50>MA200) — tidak ada sinyal.")
        return []
    out = []
    for ticker, g in df.groupby("Ticker"):
        g = g.sort_values("Date").reset_index(drop=True)
        if len(g) < 210:
            continue
        c, v = g["Close"], g["Volume"]
        close, volume = float(c.iloc[-1]), int(v.iloc[-1])
        vavg20 = float(v.iloc[-21:-1].mean())
        ma20, ma50, ma200 = (float(c.tail(n).mean()) for n in (20, 50, 200))
        hh20 = float(c.iloc[-21:-1].max())
        atr = float(_wilder_atr(g).iloc[-1])
        spike = volume / vavg20 if vavg20 > 0 else 0.0
        if not (close * volume >= config.min_value_traded and close >= config.min_close_price
                and close > hh20 and spike >= config.volume_spike_ratio and close > ma50 > ma200 and atr > 0):
            continue
        sl, tp = close - T1_SL_ATR * atr, close + T1_TP_ATR * atr
        rec = TradeRecommendation(
            ticker=ticker, close=close, entry_zone_low=close * 0.985, entry_zone_high=close * 1.015,
            stop_loss=sl, target_profit=tp, risk_reward=(tp - close) / (close - sl),
            rationale=(f"Breakout high 20 hari, volume {spike:.1f}x, tren naik (MA50>MA200), IHSG uptrend. "
                       f"SL {T1_SL_ATR:.0f}xATR, TP {T1_TP_ATR:.0f}xATR, keluar bila {T1_MAX_DAYS} hari bursa belum kena."))
        macd, macd_signal = _compute_macd(c)
        out.append(StockMetrics(ticker=ticker, close=close, volume=volume, value_traded=close * volume,
                                avg_volume_20d=vavg20, volume_spike=spike, ma20=ma20, above_ma20=close > ma20,
                                rsi14=_compute_rsi(c), macd=macd, macd_signal=macd_signal, atr14=atr,
                                latest_date=pd.to_datetime(g["Date"].iloc[-1]).date().isoformat(), recommendation=rec))
    out.sort(key=lambda m: m.volume_spike, reverse=True)
    return out[:T1_TOP_N]


def run_screener(
    tickers: list[str],
    config: ScreenerConfig,
    period: str = "90d",
    store: HistoryStore | None = None,
    strategy: str = "t1",  # [upgrade-2026-11]
) -> dict:
    """Jalankan pipeline screener dan kembalikan hasil dalam dictionary."""
    # [upgrade-2026-11] t1 butuh ±2 tahun data untuk MA200
    df = fetch_prices(tickers, period="2y" if strategy == "t1" else period)
    if strategy == "t1":
        candidates = t1_candidates(df, config)
    else:
        metrics = calculate_metrics(df, config)
        candidates = filter_candidates(metrics, config)
    latest_date = pd.to_datetime(df["Date"]).max().date().isoformat() if not df.empty else None

    candidate_dicts = [asdict(m) for m in candidates]

    stale = bool(store and latest_date and _date_already_saved(store.db_path, latest_date))  # [upgrade-2026-11]
    if stale:
        logger.warning("Data %s sudah tersimpan (bursa libur / data belum diperbarui) — tidak disimpan ulang.", latest_date)
        candidate_dicts = []
    elif store and latest_date:
        store.save(latest_date, candidate_dicts)
        _tag_strategy(store.db_path, latest_date, strategy)
        logger.info("Menyimpan %d kandidat ke SQLite.", len(candidate_dicts))

    return {
        "date": latest_date,
        "strategy": strategy,
        "stale": stale,
        "candidates": candidate_dicts,
        "total_candidates": len(candidate_dicts),
        "filters": {
            "min_value_traded": config.min_value_traded,
            "volume_spike_ratio": config.volume_spike_ratio,
            "ma_window": config.ma_window,
            "min_close_price": config.min_close_price,
            "top_n": config.top_n,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="IDX Daily Stock Screener")
    parser.add_argument("--tickers", nargs="+", default=None, help="Daftar ticker Yahoo Finance")
    parser.add_argument("--min-value", type=float, default=None, help="Nilai transaksi minimum")
    parser.add_argument("--volume-spike", type=float, default=None, help="Rasio volume spike minimum")
    parser.add_argument("--top-n", type=int, default=None, help="Jumlah kandidat top")
    parser.add_argument("--period", type=str, default="90d", help="Periode data Yahoo Finance")
    parser.add_argument("--preset", type=str, choices=list(PRESETS.keys()), default="default", help="Preset filter")
    parser.add_argument("--config", type=str, default=None, help="Path ke file konfigurasi JSON")
    parser.add_argument("--output", type=str, choices=["text", "json"], default="text", help="Format output")
    parser.add_argument("--save-history", action="store_true", default=True, help="Simpan hasil ke SQLite")
    parser.add_argument("--strategy", choices=["t1", "legacy-fixed"] if "idx" == "idx" else ["legacy-fixed"],
                        default=os.environ.get("SCREENER_STRATEGY", "t1"))  # [upgrade-2026-11]
    parser.add_argument("--no-save-history", action="store_true", help="Jangan simpan hasil ke SQLite")
    args = parser.parse_args()

    if args.config:
        config = ScreenerConfig.from_file(args.config)
    else:
        config = ScreenerConfig.from_preset(args.preset)

    if args.min_value is not None:
        config.min_value_traded = args.min_value
    if args.volume_spike is not None:
        config.volume_spike_ratio = args.volume_spike
    if args.top_n is not None:
        config.top_n = args.top_n

    tickers = args.tickers or LQ45_TICKERS
    store = HistoryStore() if args.save_history and not args.no_save_history else None

    # Migrate old DB
    if store:
        _migrate_db(store.db_path)

    result = run_screener(tickers, config, period=args.period, store=store, strategy=args.strategy)

    if args.output == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        candidates = [StockMetrics.from_dict(c) for c in result["candidates"]]
        print_results(candidates, result["date"])

    return 0


if __name__ == "__main__":
    sys.exit(main())

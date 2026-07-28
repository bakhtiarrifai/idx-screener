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

Output: daftar kandidat dengan metrik pendukung (text atau JSON).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
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

# Daftar ticker LQ45-ish (Yahoo Finance format: <KODE>.JK)
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
    latest_date: str


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

        past = group.iloc[:-config.ma_window]
        if len(past) < config.ma_window:
            continue

        avg_volume_20d = float(past["Volume"].tail(config.ma_window).mean())
        ma20 = float(past["Close"].tail(config.ma_window).mean())
        volume_spike = volume / avg_volume_20d if avg_volume_20d > 0 else 0.0

        close_series = group["Close"]
        rsi14 = _compute_rsi(close_series, window=14)
        macd, macd_signal = _compute_macd(close_series)

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
                latest_date=pd.to_datetime(latest["Date"]).date().isoformat(),
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
    print(f"{'Ticker':<8} {'Close':>10} {'Volume':>12} {'Value':>12} {'Vol Spike':>10} {'MA20':>10} {'RSI14':>8} {'MACD':>10} {'>MA20':>6}")
    print("-" * 100)
    for m in candidates:
        rsi = f"{m.rsi14:.1f}" if m.rsi14 is not None else "-"
        macd = f"{m.macd:.2f}" if m.macd is not None else "-"
        print(
            f"{m.ticker:<8} {m.close:>10,.0f} {m.volume:>12,} {format_currency(m.value_traded):>12} "
            f"{m.volume_spike:>9.2f}x {m.ma20:>10,.0f} {rsi:>8} {macd:>10} {'✓' if m.above_ma20 else '✗':>6}"
        )
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def save(self, date: str, candidates: list[dict]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            for c in candidates:
                conn.execute(
                    """
                    INSERT INTO screenings
                    (date, ticker, close, volume, value_traded, volume_spike, ma20, rsi14, macd, macd_signal)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
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


def run_screener(
    tickers: list[str],
    config: ScreenerConfig,
    period: str = "90d",
    store: HistoryStore | None = None,
) -> dict:
    """Jalankan pipeline screener dan kembalikan hasil dalam dictionary."""
    df = fetch_prices(tickers, period=period)
    metrics = calculate_metrics(df, config)
    candidates = filter_candidates(metrics, config)
    latest_date = pd.to_datetime(df["Date"]).max().date().isoformat() if not df.empty else None

    candidate_dicts = [asdict(m) for m in candidates]

    if store and latest_date:
        store.save(latest_date, candidate_dicts)
        logger.info("Menyimpan %d kandidat ke SQLite.", len(candidate_dicts))

    return {
        "date": latest_date,
        "candidates": candidate_dicts,
        "total_candidates": len(candidates),
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

    result = run_screener(tickers, config, period=args.period, store=store)

    if args.output == "json":
        print(json.dumps(result, indent=2, default=str))
    else:
        candidates = [StockMetrics(**c) for c in result["candidates"]]
        print_results(candidates, result["date"])

    return 0


if __name__ == "__main__":
    sys.exit(main())

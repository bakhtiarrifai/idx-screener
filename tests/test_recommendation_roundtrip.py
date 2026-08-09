"""
Test: roundtrip StockMetrics → asdict → from_dict → print_results
tanpa koneksi jaringan / Yahoo Finance.
"""
from dataclasses import asdict
from io import StringIO
from unittest.mock import patch

import pytest

from idx_screener import StockMetrics, TradeRecommendation, print_results


def make_trade_rec(ticker: str = "BBCA.JK") -> TradeRecommendation:
    return TradeRecommendation(
        ticker=ticker,
        close=9_000.0,
        entry_zone_low=8_820.0,
        entry_zone_high=9_180.0,
        stop_loss=8_370.0,
        target_profit=9_675.0,
        risk_reward=1.5,
        rationale="Breakout volume; SL ATR-based.",
    )


def make_stock_metrics(rec: TradeRecommendation | None = None) -> StockMetrics:
    return StockMetrics(
        ticker="BBCA.JK",
        close=9_000.0,
        volume=50_000_000,
        value_traded=450_000_000_000.0,
        avg_volume_20d=25_000_000.0,
        volume_spike=2.0,
        ma20=8_700.0,
        above_ma20=True,
        rsi14=58.5,
        macd=120.0,
        macd_signal=80.0,
        atr14=200.0,
        latest_date="2026-08-09",
        recommendation=rec,
    )


class TestRecommendationRoundtrip:
    def test_from_dict_preserves_recommendation_as_object(self):
        """Setelah asdict → from_dict, recommendation harus objek TradeRecommendation."""
        original = make_stock_metrics(rec=make_trade_rec())
        as_dict = asdict(original)

        # Pastikan asdict mengubah nested recommendation menjadi dict
        assert isinstance(as_dict["recommendation"], dict)

        rebuilt = StockMetrics.from_dict(as_dict)
        assert isinstance(rebuilt.recommendation, TradeRecommendation)

    def test_from_dict_values_intact(self):
        """Nilai-nilai recommendation tidak berubah setelah roundtrip."""
        rec = make_trade_rec()
        original = make_stock_metrics(rec=rec)
        rebuilt = StockMetrics.from_dict(asdict(original))

        r = rebuilt.recommendation
        assert r.entry_zone_low == rec.entry_zone_low
        assert r.entry_zone_high == rec.entry_zone_high
        assert r.stop_loss == rec.stop_loss
        assert r.target_profit == rec.target_profit
        assert r.risk_reward == rec.risk_reward
        assert r.rationale == rec.rationale

    def test_from_dict_without_recommendation(self):
        """StockMetrics tanpa recommendation tidak crash saat from_dict."""
        original = make_stock_metrics(rec=None)
        rebuilt = StockMetrics.from_dict(asdict(original))
        assert rebuilt.recommendation is None

    def test_print_results_no_attribute_error(self):
        """print_results tidak boleh raise AttributeError setelah roundtrip."""
        original = make_stock_metrics(rec=make_trade_rec())
        candidates = [StockMetrics.from_dict(asdict(original))]

        buf = StringIO()
        with patch("sys.stdout", buf):
            print_results(candidates, date_str="2026-08-09")

        output = buf.getvalue()
        assert "BBCA.JK" in output
        assert "Entry Zone" in output
        assert "Stop Loss" in output
        assert "Target" in output

    def test_print_results_without_recommendation(self):
        """Kandidat tanpa recommendation tetap ditampilkan tanpa error."""
        original = make_stock_metrics(rec=None)
        candidates = [StockMetrics.from_dict(asdict(original))]

        buf = StringIO()
        with patch("sys.stdout", buf):
            print_results(candidates, date_str="2026-08-09")

        output = buf.getvalue()
        assert "BBCA.JK" in output
        assert "Entry Zone" not in output  # tidak ada rekomendasi → tidak muncul

    def test_print_results_empty_list(self):
        """List kosong menampilkan pesan tidak ada kandidat, tidak crash."""
        buf = StringIO()
        with patch("sys.stdout", buf):
            print_results([], date_str="2026-08-09")

        assert "Tidak ada kandidat" in buf.getvalue()

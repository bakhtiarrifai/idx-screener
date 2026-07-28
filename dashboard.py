#!/usr/bin/env python3
"""
Dashboard web sederhana untuk melihat histori kandidat IDX Screener.
Jalankan: python3 dashboard.py
Buka: http://localhost:5000
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, render_template_string, request

app = Flask(__name__)

PROJECT_DIR = Path(__file__).parent
DB_PATH = PROJECT_DIR / "screener_history.db"


@dataclass
class ScreeningStats:
    total_days: int
    total_candidates: int
    latest_date: str | None
    avg_candidates_per_day: float


def get_recent_screenings(days: int = 30, ticker: str | None = None) -> list[dict]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    sql = "SELECT * FROM screenings WHERE date >= ?"
    params: list = [cutoff]

    if ticker:
        sql += " AND ticker = ?"
        params.append(ticker)

    sql += " ORDER BY date DESC, volume_spike DESC"

    cursor = conn.execute(sql, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_daily_counts(days: int = 30) -> list[dict]:
    """Aggregate candidate counts per date for charting."""
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    cursor = conn.execute(
        "SELECT date, COUNT(*) as count FROM screenings WHERE date >= ? GROUP BY date ORDER BY date",
        (cutoff,),
    )
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_ticker_volume_spike(days: int = 30) -> list[dict]:
    """Aggregate average volume spike per ticker."""
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    cursor = conn.execute(
        """
        SELECT ticker, AVG(volume_spike) as avg_spike, COUNT(*) as count
        FROM screenings
        WHERE date >= ?
        GROUP BY ticker
        ORDER BY avg_spike DESC
        """,
        (cutoff,),
    )
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_stats() -> ScreeningStats:
    if not DB_PATH.exists():
        return ScreeningStats(0, 0, None, 0.0)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT COUNT(DISTINCT date) as days, COUNT(*) as total, MAX(date) as latest FROM screenings")
    row = cursor.fetchone()
    conn.close()

    if not row:
        return ScreeningStats(0, 0, None, 0.0)

    days = row[0]
    total = row[1]
    latest = row[2]
    avg = total / days if days else 0.0

    return ScreeningStats(days, total, latest, avg)


def get_unique_tickers() -> list[str]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT DISTINCT ticker FROM screenings ORDER BY ticker")
    tickers = [row[0] for row in cursor.fetchall()]
    conn.close()
    return tickers


DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IDX Screener Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg: #0f172a;
            --card: #1e293b;
            --text: #f8fafc;
            --muted: #94a3b8;
            --accent: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        h1 { margin-bottom: 0.5rem; }
        .subtitle { color: var(--muted); margin-bottom: 2rem; }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .stat-card {
            background: var(--card);
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .stat-card h3 { margin: 0; color: var(--muted); font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; }
        .stat-card .value { font-size: 2rem; font-weight: 700; margin-top: 0.5rem; }
        .controls {
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
            align-items: center;
        }
        .controls label { color: var(--muted); }
        .controls select, .controls input {
            background: var(--card);
            color: var(--text);
            border: 1px solid #334155;
            padding: 0.5rem 0.75rem;
            border-radius: 6px;
        }
        .controls button {
            background: var(--accent);
            color: #000;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
        }
        .charts {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .chart-card {
            background: var(--card);
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .chart-card h3 { margin: 0 0 1rem 0; color: var(--muted); font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; }
        table {
            width: 100%;
            border-collapse: collapse;
            background: var(--card);
            border-radius: 12px;
            overflow: hidden;
        }
        th, td { padding: 1rem; text-align: left; }
        th { background: #334155; color: var(--muted); font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; }
        tr:not(:last-child) td { border-bottom: 1px solid #334155; }
        tr:hover { background: rgba(255,255,255,0.03); }
        .up { color: var(--accent); }
        .down { color: var(--danger); }
        .muted { color: var(--muted); }
        @media (max-width: 768px) {
            .container { padding: 1rem; }
            .charts { grid-template-columns: 1fr; }
            table { font-size: 0.875rem; }
            th, td { padding: 0.75rem 0.5rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 IDX Screener Dashboard</h1>
        <p class="subtitle">Histori kandidat swing trade harian dari Bursa Efek Indonesia</p>

        <div class="stats">
            <div class="stat-card">
                <h3>Hari Terekam</h3>
                <div class="value">{{ stats.total_days }}</div>
            </div>
            <div class="stat-card">
                <h3>Total Kandidat</h3>
                <div class="value">{{ stats.total_candidates }}</div>
            </div>
            <div class="stat-card">
                <h3>Rata-rata / Hari</h3>
                <div class="value">{{ "%.1f" % stats.avg_candidates_per_day }}</div>
            </div>
            <div class="stat-card">
                <h3>Tanggal Terakhir</h3>
                <div class="value">{{ stats.latest_date or "-" }}</div>
            </div>
        </div>

        <form method="GET" class="controls">
            <label for="days">Periode:</label>
            <select name="days" id="days">
                <option value="7" {{ "selected" if days == 7 else "" }}>7 hari</option>
                <option value="30" {{ "selected" if days == 30 else "" }}>30 hari</option>
                <option value="60" {{ "selected" if days == 60 else "" }}>60 hari</option>
                <option value="90" {{ "selected" if days == 90 else "" }}>90 hari</option>
            </select>

            <label for="ticker">Filter Ticker:</label>
            <select name="ticker" id="ticker">
                <option value="">Semua</option>
                {% for t in tickers %}
                <option value="{{ t }}" {{ "selected" if ticker == t else "" }}>{{ t }}</option>
                {% endfor %}
            </select>

            <button type="submit">Terapkan</button>
        </form>

        <div class="charts">
            <div class="chart-card">
                <h3>Kandidat per Hari</h3>
                <canvas id="dailyChart"></canvas>
            </div>
            <div class="chart-card">
                <h3>Volume Spike per Ticker</h3>
                <canvas id="spikeChart"></canvas>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Tanggal</th>
                    <th>Ticker</th>
                    <th>Close</th>
                    <th>Volume</th>
                    <th>Value</th>
                    <th>Vol Spike</th>
                    <th>MA20</th>
                    <th>RSI14</th>
                    <th>MACD</th>
                </tr>
            </thead>
            <tbody>
                {% for row in screenings %}
                <tr>
                    <td>{{ row.date }}</td>
                    <td><strong>{{ row.ticker }}</strong></td>
                    <td>{{ "{:,.0f}".format(row.close) }}</td>
                    <td>{{ "{:,}".format(row.volume) }}</td>
                    <td>{{ "{:,.0f}".format(row.value_traded) }}</td>
                    <td class="{{ 'up' if row.volume_spike >= 1.5 else 'muted' }}">{{ "{:.2f}x".format(row.volume_spike) }}</td>
                    <td>{{ "{:,.0f}".format(row.ma20) }}</td>
                    <td>{{ "{:.1f}".format(row.rsi14) if row.rsi14 else "-" }}</td>
                    <td class="{{ 'up' if row.macd and row.macd > 0 else 'down' }}">{{ "{:.2f}".format(row.macd) if row.macd else "-" }}</td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="9" style="text-align:center; color: var(--muted);">Belum ada data. Jalankan screener terlebih dahulu.</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <script>
        const dailyLabels = {{ daily_labels | tojson }};
        const dailyCounts = {{ daily_counts | tojson }};
        const spikeLabels = {{ spike_labels | tojson }};
        const spikeValues = {{ spike_values | tojson }};

        new Chart(document.getElementById('dailyChart'), {
            type: 'bar',
            data: {
                labels: dailyLabels,
                datasets: [{
                    label: 'Jumlah Kandidat',
                    data: dailyCounts,
                    backgroundColor: 'rgba(16, 185, 129, 0.7)',
                    borderColor: '#10b981',
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                    x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } }
                }
            }
        });

        new Chart(document.getElementById('spikeChart'), {
            type: 'bar',
            data: {
                labels: spikeLabels,
                datasets: [{
                    label: 'Avg Volume Spike',
                    data: spikeValues,
                    backgroundColor: 'rgba(245, 158, 11, 0.7)',
                    borderColor: '#f59e0b',
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
                    x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } }
                }
            }
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30

    ticker = request.args.get("ticker", "").strip().upper() or None
    screenings = get_recent_screenings(days=days, ticker=ticker)
    stats = get_stats()
    tickers = get_unique_tickers()

    daily = get_daily_counts(days=days)
    daily_labels = [d["date"][-5:] for d in daily]  # MM-DD
    daily_counts = [d["count"] for d in daily]

    spike_data = get_ticker_volume_spike(days=days)
    spike_labels = [d["ticker"] for d in spike_data]
    spike_values = [round(d["avg_spike"], 2) for d in spike_data]

    return render_template_string(
        DASHBOARD_TEMPLATE,
        stats=stats,
        screenings=screenings,
        tickers=tickers,
        days=days,
        ticker=ticker or "",
        daily_labels=daily_labels,
        daily_counts=daily_counts,
        spike_labels=spike_labels,
        spike_values=spike_values,
    )


@app.route("/api/screenings")
def api_screenings():
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30

    ticker = request.args.get("ticker", "").strip().upper() or None
    screenings = get_recent_screenings(days=days, ticker=ticker)
    return {"screenings": screenings, "count": len(screenings)}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

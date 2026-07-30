#!/usr/bin/env python3
"""
Cross-platform runner untuk IDX Screener.
Menjalankan screener dan (opsional) mengirim hasil ke Telegram.
Dapat dipanggil dari cron, systemd, Task Scheduler, atau terminal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

PROJECT_DIR = Path(__file__).parent
PYTHON = sys.executable


def run_screener_json(preset: str = "default") -> dict:
    """Jalankan screener dan kembalikan hasil JSON."""
    result = subprocess.run(
        [PYTHON, str(PROJECT_DIR / "idx_screener.py"), "--preset", preset, "--output", "json"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Screener failed:\n{result.stderr}")

    # Parse multi-line JSON output
    stdout = result.stdout.strip()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    # Fallback: try parsing entire stdout
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Tidak ada output JSON valid dari screener: {e}\nOutput: {stdout[:200]}")


def send_telegram(payload: dict) -> None:
    """Kirim hasil ke Telegram jika env tersedia."""
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        return

    result = subprocess.run(
        [PYTHON, str(PROJECT_DIR / "telegram_sender.py"), json.dumps(payload)],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        print(f"Telegram failed: {result.stderr}", file=sys.stderr)
    else:
        print(result.stdout.strip())


def main() -> int:
    preset = os.environ.get("SCREENER_PRESET", "default")

    try:
        payload = run_screener_json(preset=preset)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    send_telegram(payload)

    # Output JSON ke stdout juga (single line, mudah diparse bash)
    print(json.dumps(payload, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

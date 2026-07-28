#!/usr/bin/env python3
"""
Test pengiriman Telegram dengan pesan dummy.
Gunakan untuk memastikan TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID sudah benar.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from telegram_sender import build_message, send_result

load_dotenv(Path(__file__).parent / ".env")


def main() -> int:
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        print("TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID belum di-set.", file=sys.stderr)
        return 1

    dummy = {
        "date": "2026-07-28",
        "candidates": [
            {
                "ticker": "ANTM.JK",
                "close": 2950.0,
                "volume": 65347100,
                "value_traded": 192773945000.0,
                "volume_spike": 1.42,
                "ma20": 2915.0,
            }
        ],
    }

    try:
        send_result({**dummy, "total_candidates": 1})
        print("Test message sent to Telegram.")
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

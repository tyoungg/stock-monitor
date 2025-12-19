"""
Stock monitor script with market-hours logic and structured alerts.

Reads rules from CSV
Fetches prices via yfinance
Writes alerts.json when triggers occur
"""

import csv
import os
import sys
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, time
from zoneinfo import ZoneInfo

# ---- dependency checks ----
_missing = []
try:
    import requests
except Exception:
    _missing.append("requests")

try:
    import yfinance as yf
except Exception:
    _missing.append("yfinance")

if _missing:
    print("Missing packages:", ", ".join(_missing))
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

RULES_FILE = os.environ.get("RULES_FILE", "rules.csv")
ALERTS_FILE = "alerts.json"


# ---------------- helpers ----------------

def safe_float(s: str) -> Optional[float]:
    try:
        return float(s) if s not in ("", None) else None
    except Exception:
        return None


def is_market_open() -> bool:
    now = datetime.now(ZoneInfo("US/Eastern"))

    # Mon–Fri only
    if now.weekday() >= 5:
        return False

    return time(9, 30) <= now.time() <= time(16, 0)


def fetch_price(symbol: str) -> Optional[Dict[str, float]]:
    try:
        t = yf.Ticker(symbol)

        try:
            fi = t.fast_info
            price = fi.get("lastPrice") or fi.get("last")
            prev = fi.get("previousClose")
        except Exception:
            price = prev = None

        hist = t.history(period="3d")
        if hist is not None and len(hist) >= 2:
            price = price or float(hist["Close"].iloc[-1])
            prev = prev or float(hist["Close"].iloc[-2])

        if price is None or prev is None:
            return None

        return {"price": float(price), "prev": float(prev)}
    except Exception:
        logging.exception("Price fetch failed for %s", symbol)
        return None


def evaluate(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    symbol = row.get("symbol")
    if not symbol:
        return None

    low = safe_float(row.get("low"))
    high = safe_float(row.get("high"))
    pct_up = safe_float(row.get("pct_up"))
    pct_down = safe_float(row.get("pct_down"))

    data = fetch_price(symbol)
    if not data:
        return None

    price = data["price"]
    prev = data["prev"]
    change = (price - prev) / prev * 100

    triggers = []
    if low is not None and price <= low:
        triggers.append(f"Price ≤ {low}")
    if high is not None and price >= high:
        triggers.append(f"Price ≥ {high}")
    if pct_up is not None and change >= pct_up:
        triggers.append(f"Up ≥ {pct_up}%")
    if pct_down is not None and change <= -abs(pct_down):
        triggers.append(f"Down ≥ {pct_down}%")

    if not triggers:
        return None

    severity = "info"
    if any("Down" in t for t in triggers):
        severity = "down"
    elif any("Up" in t for t in triggers):
        severity = "up"

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "change": round(change, 2),
        "triggers": triggers,
        "severity": severity,
        "text": (
            f"{symbol}\n"
            f"{', '.join(triggers)}\n"
            f"Price: {price:.2f} | Δ: {change:.2f}%"
        )
    }


# ---------------- main ----------------

def main() -> int:
    # Skip outside market hours unless manually triggered
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        if not is_market_open():
            logging.info("Market closed — skipping run.")
            return 0

    if not os.path.exists(RULES_FILE):
        logging.error("Rules file not found")
        return 0

    alerts: List[Dict[str, Any]] = []

    with open(RULES_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                alert = evaluate(row)
                if alert:
                    alerts.append(alert)
            except Exception:
                logging.exception("Row evaluation failed")

    if alerts:
        with open(ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(alerts, f, indent=2)
        for a in alerts:
            print(a["text"])

    return 0


if __name__ == "__main__":
    sys.exit(main())

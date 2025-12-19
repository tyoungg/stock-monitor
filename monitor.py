"""
Stock monitor script (GitHub Actions + Discord).

Features:
- Reads rules from rules.csv
- Robust per-symbol price fetching via yfinance
- Index normalization (SPX, VIX, COMP.IDX, DJIND)
- Per-day alert deduping (safe for hourly schedules)
- Emits alerts.json for Discord embed workflow
"""

import csv
import os
import sys
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import date

# ---- Dependency checks ------------------------------------------------------

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
    print("Missing required Python packages: " + ", ".join(_missing))
    print("Install them with:\n")
    print("  python -m pip install -r requirements.txt")
    sys.exit(1)

# ---- Logging ----------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ---- Constants --------------------------------------------------------------

RULES_FILE = os.environ.get("RULES_FILE", "rules.csv")
DEFAULT_WEBHOOK = os.environ.get("DEFAULT_WEBHOOK")
STOCK_LIST_ENV = os.environ.get("STOCK_LIST", "")
DEFAULT_PCT_UP = os.environ.get("DEFAULT_PCT_UP")
DEFAULT_PCT_DOWN = os.environ.get("DEFAULT_PCT_DOWN")

ALERTS_FILE = "alerts.json"
STATE_FILE = "alert_state.json"
TODAY = str(date.today())

# Logical symbol → Yahoo symbol
INDEX_MAP = {
    "SPX": "^GSPC",
    "VIX": "^VIX",
    "COMP.IDX": "^IXIC",
    "DJIND": "^DJI",
}

# ---- Helpers ----------------------------------------------------------------

def safe_float(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def normalize_symbol(sym: str) -> str:
    return INDEX_MAP.get(sym, sym)


def load_state() -> Dict[str, str]:
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, str]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ---- Market data ------------------------------------------------------------

def fetch_price_and_prev_close(symbol: str) -> Optional[Dict[str, float]]:
    try:
        t = yf.Ticker(symbol)
        price = None
        prev_close = None

        # fast_info (best case)
        try:
            fi = t.fast_info
            price = fi.get("lastPrice") or fi.get("last")
            prev_close = fi.get("previousClose")
        except Exception:
            pass

        # history fallback
        hist = t.history(period="3d", interval="1d")
        if hist is not None and len(hist) >= 1:
            price = price or float(hist["Close"].iloc[-1])
            if len(hist) >= 2:
                prev_close = prev_close or float(hist["Close"].iloc[-2])

        # info fallback
        if price is None or prev_close is None:
            info = t.info
            price = price or info.get("regularMarketPrice")
            prev_close = prev_close or info.get("previousClose")

        if price is None or prev_close is None:
            logging.warning("Could not determine price or previous close for %s", symbol)
            return None

        return {"price": float(price), "prev_close": float(prev_close)}

    except Exception as e:
        logging.exception("Error fetching data for %s: %s", symbol, e)
        return None


# ---- Rule evaluation --------------------------------------------------------

def evaluate_row(
    row: Dict[str, str],
    state: Dict[str, str],
) -> Optional[Dict[str, Any]]:

    raw_symbol = row.get("symbol")
    if not raw_symbol:
        return None

    yf_symbol = normalize_symbol(raw_symbol)

    low = safe_float(row.get("low"))
    high = safe_float(row.get("high"))
    pct_up = safe_float(row.get("pct_up"))
    pct_down = safe_float(row.get("pct_down"))

    data = fetch_price_and_prev_close(yf_symbol)
    if data is None:
        return None

    price = data["price"]
    prev_close = data["prev_close"]
    change = (price - prev_close) / prev_close * 100.0

    triggers: List[str] = []

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

    fingerprint = f"{raw_symbol}|{'|'.join(triggers)}"

    # ---- Dedup: once per day per trigger
    if state.get(fingerprint) == TODAY:
        return None

    state[fingerprint] = TODAY

    severity = "info"
    if any("Down" in t for t in triggers):
        severity = "down"
    elif any("Up" in t or "≥" in t for t in triggers):
        severity = "up"

    text = (
        f"**{raw_symbol}**\n"
        f"{', '.join(triggers)}\n"
        f"Price: `{price:.2f}` | Δ: `{change:.2f}%`"
    )

    return {
        "symbol": raw_symbol,
        "yf_symbol": yf_symbol,
        "triggers": triggers,
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "change": round(change, 2),
        "severity": severity,
        "text": text,
        "fingerprint": fingerprint,
    }


# ---- Main -------------------------------------------------------------------

def main() -> int:
    if not os.path.exists(RULES_FILE):
        logging.error("Rules file not found: %s", RULES_FILE)
        return 1

    # Load rules
    with open(RULES_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Load state for deduping
    state = load_state()

    alerts: List[Dict[str, Any]] = []

    for row in rows:
        try:
            alert = evaluate_row(row, state)
            if alert:
                alerts.append(alert)
        except Exception:
            logging.exception("Error evaluating row: %s", row)

    # Write outputs
    if alerts:
        with open(ALERTS_FILE, "w", encoding="utf-8") as af:
            json.dump(alerts, af, ensure_ascii=False, indent=2)

        save_state(state)

        for a in alerts:
            print(a["text"])

        # non-zero exit → GitHub marks run clearly
        return 1

    # Clean up stale alert file
    if os.path.exists(ALERTS_FILE):
        try:
            os.remove(ALERTS_FILE)
        except Exception:
            pass

    logging.info("No alerts triggered")
    return 0


if __name__ == "__main__":
    sys.exit(main())

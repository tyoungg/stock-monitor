"""
Simple stock monitor script.

Reads rules from `rules.csv` (headers: symbol,low,high,pct_up,pct_down,webhook)
Fetches current price and previous close via yfinance
Sends POST to webhook URL when any rule triggers (or prints alerts when no webhook configured)

Usage: python monitor.py
Environment:
  DEFAULT_WEBHOOK - fallback webhook URL used if rule row has no webhook
"""

import csv
import os
import sys
import json
import logging
from typing import Optional, Dict, Any, List

# Friendly import-check: print guidance and exit if required third-party packages are missing.
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
    print("Install them with:\n\n  python -m pip install --upgrade pip\n  python -m pip install -r requirements.txt\n\nOr install specific packages: python -m pip install yfinance pandas requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

RULES_FILE = os.environ.get("RULES_FILE", "rules.csv")
DEFAULT_WEBHOOK = os.environ.get("DEFAULT_WEBHOOK")
STOCK_LIST_ENV = os.environ.get("STOCK_LIST", "")  # comma-separated list
DEFAULT_PCT_UP = os.environ.get("DEFAULT_PCT_UP")
DEFAULT_PCT_DOWN = os.environ.get("DEFAULT_PCT_DOWN")
ALERTS_FILE = "alerts.json"


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


def fetch_price_and_prev_close(symbol: str) -> Optional[Dict[str, float]]:
    try:
        t = yf.Ticker(symbol)
        # try fast_info if available
        price = None
        prev_close = None
        try:
            fi = t.fast_info
            price = fi.get("lastPrice") or fi.get("last")
            prev_close = fi.get("previousClose")
        except Exception:
            pass

        # fallback to history
        hist = t.history(period="3d", interval="1d")
        if hist is not None and len(hist) >= 1:
            last_close = hist["Close"].iloc[-1]
            price = price or float(last_close)
            if len(hist) >= 2:
                prev_close = prev_close or float(hist["Close"].iloc[-2])

        if price is None or prev_close is None:
            # try info dict
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


def send_webhook(webhook: str, message: str) -> bool:
    try:
        payload = {"text": message}
        resp = requests.post(webhook, json=payload, timeout=10)
        if resp.status_code >= 200 and resp.status_code < 300:
            logging.info("Sent webhook (status %s)", resp.status_code)
            return True
        else:
            logging.warning("Webhook responded %s: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logging.exception("Error sending webhook: %s", e)
        return False


def evaluate_row(row: Dict[str, str]) -> Optional[str]:
    symbol = row.get("symbol")
    if not symbol:
        return None

    low = safe_float(row.get("low"))
    high = safe_float(row.get("high"))
    pct_up = safe_float(row.get("pct_up"))
    pct_down = safe_float(row.get("pct_down"))
    webhook = row.get("webhook") or None

    data = fetch_price_and_prev_close(symbol)
    if data is None:
        return None

    price = data["price"]
    prev_close = data["prev_close"]
    change = (price - prev_close) / prev_close * 100.0

    triggers: List[str] = []
    if low is not None and price <= low:
        triggers.append(f"price <= low ({price:.2f} <= {low})")
    if high is not None and price >= high:
        triggers.append(f"price >= high ({price:.2f} >= {high})")
    if pct_up is not None and change >= pct_up:
        triggers.append(f"up >= {pct_up}% ({change:.2f}%)")
    if pct_down is not None and change <= -abs(pct_down):
        triggers.append(f"down >= {pct_down}% ({change:.2f}%)")

    if triggers:
        text = (
            f"ALERT for {symbol}: {', '.join(triggers)}\n"
            f"Price: {price:.2f} | Prev close: {prev_close:.2f} | Change: {change:.2f}%"
        )
        # Return a structured alert dict so the workflow can format Discord embeds.
        severity = "info"
        if any("down" in t for t in triggers):
            severity = "down"
        elif any("up" in t for t in triggers):
            severity = "up"

        return {
            "symbol": symbol,
            "triggers": triggers,
            "price": round(price, 2),
            "prev_close": round(prev_close, 2),
            "change": round(change, 2),
            "text": text,
            "severity": severity,
        }

    return None


def main() -> int:
    if not os.path.exists(RULES_FILE):
        logging.error("Rules file not found: %s", RULES_FILE)
        return 1

    # Load rules from CSV
    rows: List[Dict[str, str]] = []
    with open(RULES_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Build lookup and optionally add symbols from STOCK_LIST env or `stocks.txt`
    existing = {row.get("symbol", "").upper(): row for row in rows if row.get("symbol")}

    stocks_from_env = [s.strip().upper() for s in STOCK_LIST_ENV.split(",") if s.strip()] if STOCK_LIST_ENV else []
    stocks_from_file = []
    if os.path.exists("stocks.txt"):
        with open("stocks.txt", "r", encoding="utf-8") as sf:
            for line in sf:
                s = line.strip().upper()
                if s:
                    stocks_from_file.append(s)

    combined_stocks = []
    for s in stocks_from_env + stocks_from_file:
        if s and s not in existing:
            combined_stocks.append(s)

    # If defaults provided, use them for any new stock entries
    for s in combined_stocks:
        rows.append({
            "symbol": s,
            "low": "",
            "high": "",
            "pct_up": (DEFAULT_PCT_UP or "") if DEFAULT_PCT_UP else "",
            "pct_down": (DEFAULT_PCT_DOWN or "") if DEFAULT_PCT_DOWN else "",
            "webhook": "",
        })

    alerts: List[Dict[str, Any]] = []
    for row in rows:
        try:
            alert = evaluate_row(row)
            if alert:
                alerts.append(alert)
        except Exception:
            logging.exception("Error evaluating row: %s", row)

    # Write structured alerts.json for the workflow to consume
    if alerts:
        with open(ALERTS_FILE, "w", encoding="utf-8") as af:
            json.dump(alerts, af, ensure_ascii=False, indent=2)
        # Also print textual summaries for logs
        for a in alerts:
            print(a.get("text") if isinstance(a, dict) else str(a))
        return 0
    else:
        if os.path.exists(ALERTS_FILE):
            try:
                os.remove(ALERTS_FILE)
            except Exception:
                pass
        logging.info("No alerts triggered")
        return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Stock monitor with daily deduplication and market-close recap.

Features:
- Read rules from `rules.csv`
- Hourly alerts with deduplication per day
- Market-close recap message to Discord
"""

import csv, os, sys, json, logging
from typing import Optional, Dict, Any, List
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from market_calendar import is_market_open, get_market_close_time

# Third-party imports
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
    print("Missing required packages:", ", ".join(_missing))
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# --- Config ---
RULES_FILE = os.environ.get("RULES_FILE", "rules.csv")
DEFAULT_WEBHOOK = os.environ.get("DEFAULT_WEBHOOK")
STOCK_LIST_ENV = os.environ.get("STOCK_LIST", "")
DEFAULT_PCT_UP = os.environ.get("DEFAULT_PCT_UP")
DEFAULT_PCT_DOWN = os.environ.get("DEFAULT_PCT_DOWN")
ALERTS_FILE = "alerts.json"
STATE_FILE = "alert_state.json"
RECAP_FILE = "daily_recap.json"
TODAY = datetime.utcnow().strftime("%Y-%m-%d")

# --- Helpers ---
def safe_float(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except:
        return None

def fetch_price_and_prev_close(symbol: str) -> Optional[Dict[str, float]]:
    try:
        t = yf.Ticker(symbol)
        price = prev_close = None
        try:
            fi = t.fast_info
            price = fi.get("lastPrice") or fi.get("last")
            prev_close = fi.get("previousClose")
        except: pass
        hist = t.history(period="3d", interval="1d")
        if hist is not None and len(hist) >= 1:
            last_close = hist["Close"].iloc[-1]
            price = price or float(last_close)
            if len(hist) >= 2:
                prev_close = prev_close or float(hist["Close"].iloc[-2])
        if price is None or prev_close is None:
            info = t.info
            price = price or info.get("regularMarketPrice")
            prev_close = prev_close or info.get("previousClose")
        if price is None or prev_close is None:
            logging.warning("Could not determine price for %s", symbol)
            return None
        return {"price": float(price), "prev_close": float(prev_close)}
    except Exception as e:
        logging.exception("Error fetching %s: %s", symbol, e)
        return None

def send_webhook(webhook: str, message: str) -> bool:
    try:
        resp = requests.post(webhook, json={"text": message}, timeout=10)
        return resp.status_code >= 200 and resp.status_code < 300
    except:
        logging.exception("Webhook error")
        return False

# --- State helpers ---
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def load_recap() -> dict:
    if os.path.exists(RECAP_FILE):
        try:
            with open(RECAP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_recap(data: dict) -> None:
    with open(RECAP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_market_close_window() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    market_close_time = get_market_close_time(now.date())
    market_close_dt = datetime.combine(now.date(), market_close_time, tzinfo=now.tzinfo)

    # Run recap if within 30 minutes *after* market close.
    return market_close_dt <= now <= market_close_dt + timedelta(minutes=30)

# --- Evaluate one row ---
def evaluate_row(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    symbol = row.get("symbol")
    if not symbol: return None
    low = safe_float(row.get("low"))
    high = safe_float(row.get("high"))
    pct_up = safe_float(row.get("pct_up"))
    pct_down = safe_float(row.get("pct_down"))
    webhook = row.get("webhook") or None

    data = fetch_price_and_prev_close(symbol)
    if data is None: return None
    price = data["price"]
    prev_close = data["prev_close"]
    change = (price - prev_close) / prev_close * 100.0

    # --- Update daily recap for ALL symbols ---
    recap = load_recap()
    recap[symbol] = {"price": round(price,2), "change": round(change,2)}
    save_recap(recap)

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
        # --- Deduplicate daily alerts ---
        state = load_state()
        new_triggers = []
        for t in triggers:
            if "price <=" in t: key = f"{symbol}|price<=low|{TODAY}"
            elif "price >=" in t: key = f"{symbol}|price>=high|{TODAY}"
            elif "up >=" in t: key = f"{symbol}|pct_up|{TODAY}"
            elif "down >=" in t: key = f"{symbol}|pct_down|{TODAY}"
            else: key = f"{symbol}|other|{TODAY}"
            if key not in state:
                state[key] = True
                new_triggers.append(t)
        if not new_triggers: return None
        save_state(state)

        # --- Build alert text ---
        text = (
            f"ALERT for {symbol}: {', '.join(new_triggers)}\n"
            f"Price: {price:.2f} | Prev close: {prev_close:.2f} | Change: {change:.2f}%"
        )
        severity = "info"
        if any("down" in t for t in new_triggers): severity = "down"
        elif any("up" in t for t in new_triggers): severity = "up"

        return {"symbol": symbol, "triggers": new_triggers, "price": round(price,2),
                "prev_close": round(prev_close,2), "change": round(change,2),
                "text": text, "severity": severity}
    return None

# --- Main ---
def main() -> int:
    if not is_market_open():
        logging.info("Market is closed. Skipping run.")
        return 0

    if not os.path.exists(RULES_FILE):
        logging.error("Rules file not found: %s", RULES_FILE)
        return 0

    rows: List[Dict[str,str]] = []
    with open(RULES_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Add symbols from STOCK_LIST or stocks.txt if not already present
    existing = {row.get("symbol","").upper(): row for row in rows if row.get("symbol")}
    stocks_from_env = [s.strip().upper() for s in STOCK_LIST_ENV.split(",") if s.strip()] if STOCK_LIST_ENV else []
    stocks_from_file = []
    if os.path.exists("stocks.txt"):
        with open("stocks.txt","r",encoding="utf-8") as sf:
            stocks_from_file = [line.strip().upper() for line in sf if line.strip()]
    combined_stocks = []
    for s in stocks_from_env + stocks_from_file:
        if s not in existing: combined_stocks.append(s)
    for s in combined_stocks:
        rows.append({
            "symbol": s, "low": "", "high": "",
            "pct_up": DEFAULT_PCT_UP or "",
            "pct_down": DEFAULT_PCT_DOWN or "",
            "webhook": "",
        })

    # Evaluate all rows
    alerts: List[Dict[str,Any]] = []
    for row in rows:
        try:
            alert = evaluate_row(row)
            if alert: alerts.append(alert)
        except: logging.exception("Error evaluating row: %s", row)

    # Write alerts.json
    if alerts:
        with open(ALERTS_FILE,"w",encoding="utf-8") as af:
            json.dump(alerts, af, ensure_ascii=False, indent=2)
        for a in alerts: print(a.get("text") if isinstance(a, dict) else str(a))
    else:
        if os.path.exists(ALERTS_FILE): os.remove(ALERTS_FILE)
        logging.info("No alerts triggered")

    # --- Market-close recap ---
    if is_market_close_window():
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                print("is_market_close=true", file=f)
        recap = load_recap()
        if recap:
            recap_alerts = []
            for symbol, data in recap.items():
                sign = "▲" if data["change"] >= 0 else "▼"
                recap_alerts.append(f"**{symbol}** {sign} {data['change']}% — ${data['price']}")
            recap_payload = {
                "type": "recap",
                "title": f"📊 Market Close Recap ({TODAY})",
                "lines": recap_alerts
            }
            with open("recap.json","w",encoding="utf-8") as f:
                json.dump(recap_payload,f,indent=2)
            os.remove(RECAP_FILE)

    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.exception("Fatal error")
        sys.exit(0)   # <-- NEVER fail the workflow

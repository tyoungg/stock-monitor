"""
Stock monitor with daily deduplication and market-close recap.

Features:
- Read rules from `rules.csv`
- Hourly alerts with deduplication per day
- Market-close recap message to Discord
"""

import csv, os, sys, json, logging, math
from typing import Optional, Dict, Any, List
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from market_calendar import is_extended_trading_hours, get_market_close_time

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
TODAY = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")

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

        # 1. Try fast_info
        try:
            fi = t.fast_info
            price = fi.get("lastPrice") or fi.get("last_price") or fi.get("last")
            prev_close = fi.get("previousClose") or fi.get("previous_close")
        except Exception as e:
            logging.debug("fast_info failed for %s: %s", symbol, e)

        # 2. Try history
        try:
            hist = t.history(period="3d", interval="1d")
            if hist is not None and not hist.empty:
                last_close = hist["Close"].iloc[-1]
                price = price or float(last_close)
                if len(hist) >= 2:
                    prev_close = prev_close or float(hist["Close"].iloc[-2])
        except Exception as e:
            logging.debug("history failed for %s: %s", symbol, e)

        # 3. Try info (often slowest/least reliable)
        if price is None or prev_close is None:
            try:
                info = t.info
                if info:
                    price = price or info.get("regularMarketPrice") or info.get("currentPrice")
                    prev_close = prev_close or info.get("previousClose") or info.get("regularMarketPreviousClose")
            except Exception as e:
                logging.debug("info failed for %s: %s", symbol, e)

        # Validate results
        def is_valid(val):
            return val is not None and not (isinstance(val, float) and math.isnan(val))

        if not is_valid(price) or not is_valid(prev_close):
            # One last try: basic_info (available in some yfinance versions)
            try:
                bi = getattr(t, "basic_info", None)
                if bi:
                    price = price or bi.get("lastPrice") or bi.get("last_price")
                    prev_close = prev_close or bi.get("previousClose") or bi.get("previous_close")
            except: pass

        if not is_valid(price) or not is_valid(prev_close):
            logging.warning("Could not determine valid price/prev_close for %s (price=%s, prev=%s)", symbol, price, prev_close)
            return None

        return {"price": float(price), "prev_close": float(prev_close)}
    except Exception as e:
        logging.exception("Fatal error fetching %s: %s", symbol, e)
        return None

def send_webhook(webhook: str, message: str) -> bool:
    try:
        resp = requests.post(webhook, json={"text": message}, timeout=10)
        return resp.status_code >= 200 and resp.status_code < 300
    except:
        logging.exception("Webhook error")
        return False

# --- State helpers ---
def load_state(current_date: str) -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("date") == current_date:
                    return data.get("state", {})
        except: pass
    return {}

def save_state(state: dict, current_date: str) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": current_date, "state": state}, f, indent=2)
    except Exception as e:
        logging.error("Failed to save state: %s", e)

def load_recap() -> dict:
    if os.path.exists(RECAP_FILE):
        try:
            with open(RECAP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_recap(data: dict) -> None:
    try:
        with open(RECAP_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logging.error("Failed to save recap: %s", e)


def is_market_close_window() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    market_close_time = get_market_close_time(now.date())
    market_close_dt = datetime.combine(now.date(), market_close_time, tzinfo=now.tzinfo)

    # Run recap if within 55 minutes *after* market close.
    return market_close_dt <= now <= market_close_dt + timedelta(minutes=55)

def generate_html_recap(recap_data: Dict[str, Dict[str, float]]) -> str:
    """Generates an HTML table from the recap data."""
    rows = []
    for symbol, data in sorted(recap_data.items()):
        price = data.get("price", 0)
        change = data.get("change", 0)
        color = "#1f9d55" if change >= 0 else "#e3342f"
        rows.append(f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #eee;"><strong>{symbol}</strong></td>
            <td style="padding:10px;border-bottom:1px solid #eee;">${price:.2f}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;color:{color};">{change:+.2f}%</td>
        </tr>
        """)

    return f"""
    <html>
        <body style="font-family:Arial,sans-serif;background:#f7f7f7;padding:20px;">
            <table width="100%" style="background:#ffffff;border-collapse:collapse;border:1px solid #ddd;">
                <thead>
                    <tr>
                        <th style="padding:10px;border-bottom:2px solid #ddd;text-align:left;">Symbol</th>
                        <th style="padding:10px;border-bottom:2px solid #ddd;text-align:left;">Price</th>
                        <th style="padding:10px;border-bottom:2px solid #ddd;text-align:left;">Change (%)</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </body>
    </html>
    """

# --- Evaluate one row ---
def evaluate_row(row: Dict[str, str], recap: Dict, state: Dict) -> Optional[Dict[str, Any]]:
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

    # --- Update daily recap for ALL symbols (in-memory) ---
    recap[symbol] = {"price": round(price,2), "change": round(change,2)}

    triggers: List[str] = []
    if low is not None and price <= low:
        triggers.append(f"low: price <= low ({price:.2f} <= {low})")
    if high is not None and price >= high:
        triggers.append(f"high: price >= high ({price:.2f} >= {high})")
    if pct_up is not None and change >= pct_up:
        triggers.append(f"up >= {pct_up}% ({change:.2f}%)")
    if pct_down is not None and change <= -abs(pct_down):
        triggers.append(f"down >= {pct_down}% ({change:.2f}%)")

    if triggers:
        # --- Deduplicate alerts based on the specific trigger type ---
        alert_key = f"{symbol}"

        # Filter out triggers that have already been sent
        new_triggers = []
        for t in triggers:
            # Normalize the trigger string to get a stable alert type
            alert_type = t.split(' ')[0] # e.g., 'low:', 'high:', 'up', 'down'
            if alert_type not in state.get(alert_key, []):
                new_triggers.append(t)
            else:
                logging.info("Deduplicating %s alert for %s", alert_type, symbol)

        if not new_triggers:
            logging.info("All triggers for %s already sent today", symbol)
            return None # All triggered alerts for this symbol have been silenced

        # Update state with the new alerts that will be sent
        if alert_key not in state:
            state[alert_key] = []
        for t in new_triggers:
            alert_type = t.split(' ')[0]
            if alert_type not in state[alert_key]:
                state[alert_key].append(alert_type)

        # --- Build alert text ---
        text = (
            f"ALERT for {symbol}: {', '.join(new_triggers)}\n"
            f"Price: {price:.2f} | Prev close: {prev_close:.2f} | Change: {change:.2f}%"
        )
        severity = "info"
        if any(keyword in t.lower() for t in triggers for keyword in ["down", "low"]):
            severity = "down"
        elif any(keyword in t.lower() for t in triggers for keyword in ["up", "high"]):
            severity = "up"

        return {"symbol": symbol, "triggers": triggers, "price": round(price,2),
                "prev_close": round(prev_close,2), "change": round(change,2),
                "text": text, "severity": severity}
    return None

# --- Main ---
def main() -> int:
    if not is_extended_trading_hours() and os.environ.get("IGNORE_MARKET_HOURS") != "true":
        logging.info("Market is closed (including extended hours). Skipping run.")
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
    recap = load_recap()
    state = load_state(TODAY)
    for row in rows:
        try:
            alert = evaluate_row(row, recap, state)
            if alert: alerts.append(alert)
        except: logging.exception("Error evaluating row: %s", row)

    save_recap(recap)
    save_state(state, TODAY)

    # Write alerts.json
    if alerts:
        with open(ALERTS_FILE,"w",encoding="utf-8") as af:
            json.dump(alerts, af, ensure_ascii=False, indent=2)
        for a in alerts: print(a.get("text") if isinstance(a, dict) else str(a))
    else:
        try:
            if os.path.exists(ALERTS_FILE): os.remove(ALERTS_FILE)
        except Exception as e:
            logging.debug("Could not remove alerts file: %s", e)
        logging.info("No alerts triggered")

    # --- Market-close recap ---
    if is_market_close_window():
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                print("is_market_close=true", file=f)
        recap = load_recap()
        if recap:
            # Generate HTML recap
            html_recap = generate_html_recap(recap)
            with open("recap.html", "w", encoding="utf-8") as f:
                f.write(html_recap)

            # Generate JSON recap for plaintext fallback
            recap_alerts = []
            for symbol, data in recap.items():
                sign = "▲" if data["change"] >= 0 else "▼"
                recap_alerts.append(f"**{symbol}** {sign} {abs(data['change'])}% — ${data['price']}")
            recap_payload = {
                "type": "recap",
                "title": f"📊 Market Close Recap ({TODAY})",
                "lines": recap_alerts
            }
            with open("recap.json","w",encoding="utf-8") as f:
                json.dump(recap_payload,f,indent=2)

            # Clean up old daily recap file
            os.remove(RECAP_FILE)

    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.exception("Fatal error in main")
        sys.exit(1)

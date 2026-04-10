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
FINANCIALS_CACHE_FILE = "financials_cache.json"
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

def fetch_stock_data(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        t = yf.Ticker(symbol)
        price = prev_close = None

        # Fetch 1 year of history for indicators
        hist = t.history(period="1y")
        if hist is None or hist.empty:
            logging.warning("No history found for %s", symbol)
            return None

        # 1. Try fast_info for most recent price
        try:
            fi = t.fast_info
            price = fi.get("lastPrice") or fi.get("last_price") or fi.get("last")
            prev_close = fi.get("previousClose") or fi.get("previous_close")
        except Exception as e:
            logging.debug("fast_info failed for %s: %s", symbol, e)

        # Use history as fallback for price/prev_close
        if price is None:
            price = float(hist["Close"].iloc[-1])
        if prev_close is None:
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) > 1 else price

        # Validate results
        def is_valid(val):
            return val is not None and not (isinstance(val, float) and math.isnan(val))

        if not is_valid(price) or not is_valid(prev_close):
            logging.warning("Could not determine valid price/prev_close for %s (price=%s, prev=%s)", symbol, price, prev_close)
            return None

        return {
            "price": float(price),
            "prev_close": float(prev_close),
            "history": hist,
            "low_today": float(hist["Low"].iloc[-1])
        }
    except Exception as e:
        logging.exception("Fatal error fetching %s: %s", symbol, e)
        return None

def calculate_indicators(hist, current_price: float, current_low: float) -> Dict[str, Any]:
    try:
        # SMA
        sma50 = float(hist["Close"].rolling(window=50).mean().iloc[-1])
        sma200 = float(hist["Close"].rolling(window=200).mean().iloc[-1])

        # RSI (Simple Rolling Mean version for robustness)
        delta = hist["Close"].diff()
        gain = (delta.where(delta > 0, 0))
        loss = (-delta.where(delta < 0, 0))
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss
        rsi = float(100 - (100 / (1 + rs)).iloc[-1])

        # 52-week high/low
        high52 = float(hist["High"].max())
        low52 = float(hist["Low"].min())

        # U&R (Undercut & Rally)
        # Prior low: lowest low of last 60 trading days (excluding today)
        if len(hist) > 1:
            prior_lows = hist["Low"].iloc[-61:-1]
            prior_60d_low = float(prior_lows.min())
            ur_signal = current_low < prior_60d_low and current_price > prior_60d_low
        else:
            prior_60d_low = 0.0
            ur_signal = False

        return {
            "sma50": sma50,
            "sma200": sma200,
            "rsi": rsi,
            "high52": high52,
            "low52": low52,
            "ur_signal": ur_signal,
            "prior_60d_low": prior_60d_low
        }
    except Exception as e:
        logging.error("Error calculating indicators: %s", e)
        return {
            "sma50": 0.0, "sma200": 0.0, "rsi": 50.0,
            "high52": 0.0, "low52": 0.0, "ur_signal": False, "prior_60d_low": 0.0
        }

def calculate_rank(indicators: Dict[str, Any], current_price: float) -> int:
    score = 0
    if current_price > indicators["sma50"]: score += 20
    if current_price > indicators["sma200"]: score += 20
    if indicators["sma50"] > indicators["sma200"]: score += 10
    if 40 <= indicators["rsi"] <= 65: score += 20
    elif indicators["rsi"] > 65 and indicators["rsi"] <= 75: score += 10

    if indicators["high52"] > 0:
        dist_from_high = (indicators["high52"] - current_price) / indicators["high52"]
        if dist_from_high < 0.15: score += 30

    return score

def get_burry_take(symbol: str) -> Optional[Dict[str, Any]]:
    """Calculates Burry's Owner's Earnings (Burry-take) and its components with 4Y history."""
    if symbol.startswith("^"):
        return None
    try:
        t = yf.Ticker(symbol)

        # Market Cap from fast_info
        try:
            mcap = t.fast_info.get("market_cap") or t.fast_info.get("marketCap")
        except:
            mcap = None

        def get_series(df, keys):
            for k in keys:
                if k in df.index:
                    return df.loc[k].fillna(0).tolist()
            return []

        # Financials (4Y)
        ni_series = get_series(t.financials, ['Net Income'])
        rev_series = get_series(t.financials, ['Total Revenue'])
        shares_series = get_series(t.financials, ['Basic Average Shares', 'Diluted Average Shares'])

        if not ni_series:
            return None

        # Cashflow (4Y)
        sbc_series = get_series(t.cashflow, ['Stock Based Compensation'])
        buyback_series = [abs(x) for x in get_series(t.cashflow, ['Repurchase Of Capital Stock'])]
        fcf_series = get_series(t.cashflow, ['Free Cash Flow'])

        # RSU Tax Withholding (often under 'Common Stock Payments' or similar)
        rsu_tax_series = [abs(x) for x in get_series(t.cashflow, [
            'Payments for tax related to settlement of equity awards',
            'Cash Paid for Tax Related to Settlement of Equity Awards',
            'Taxes Paid Related to Settlement of Equity Awards'
        ])]

        # If no RSU tax found, try 'Common Stock Payments' but ONLY if it's not the same as buybacks
        if not any(rsu_tax_series):
            csp = [abs(x) for x in get_series(t.cashflow, ['Common Stock Payments'])]
            if csp and csp != buyback_series:
                rsu_tax_series = csp
            else:
                rsu_tax_series = [0.0] * len(buyback_series)

        # Ensure all series are same length (pad with 0)
        max_len = max(len(ni_series), len(rev_series), len(shares_series), len(sbc_series), len(buyback_series), len(fcf_series))
        def pad(s): return (s + [0.0] * max_len)[:max_len]

        ni_series = pad(ni_series)
        rev_series = pad(rev_series)
        shares_series = pad(shares_series)
        sbc_series = pad(sbc_series)
        buyback_series = pad(buyback_series)
        fcf_series = pad(fcf_series)
        rsu_tax_series = pad(rsu_tax_series)

        ni = ni_series[0]
        sbc = sbc_series[0]
        bb = buyback_series[0]
        rsu = rsu_tax_series[0]

        # Current Owner's Earnings
        oe = ni + sbc - bb - rsu

        return {
            "net_income": float(ni),
            "sbc": float(sbc),
            "buybacks": float(bb),
            "rsu_tax": float(rsu),
            "owner_earnings": float(oe),
            "market_cap": float(mcap) if mcap else None,
            "history": {
                "ni": ni_series,
                "rev": rev_series,
                "shares": shares_series,
                "sbc": sbc_series,
                "buybacks": buyback_series,
                "fcf": fcf_series
            }
        }

    except Exception as e:
        logging.debug("Error calculating Burry-take for %s: %s", symbol, e)
        return None

def calculate_burry_analytics(data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculates derived metrics and quality scores based on Burry's methodology."""
    if not data or not data.get("history"):
        return {}

    mcap = data.get("market_cap")
    ni = data.get("net_income")
    oe = data.get("owner_earnings")
    sbc = data.get("sbc")
    bb = data.get("buybacks")
    h = data["history"]

    # 1. Yields
    gaap_yield = (ni / mcap) * 100 if mcap and ni is not None else 0
    burry_yield = (oe / mcap) * 100 if mcap and oe is not None else 0

    # 2. Growth (1Y)
    rev_growth = 0.0
    if len(h.get("rev", [])) > 1 and h["rev"][1] and h["rev"][1] > 0:
        rev_growth = (h["rev"][0] / h["rev"][1]) - 1

    share_growth = 0.0
    if len(h.get("shares", [])) > 1 and h["shares"][1] and h["shares"][1] > 0:
        share_growth = (h["shares"][0] / h["shares"][1]) - 1

    net_growth = (rev_growth - share_growth) * 100

    # 3. Real Shareholder Yield
    real_yield = (max(0, bb - sbc) / mcap) * 100 if mcap and bb is not None else 0

    # 4. Buyback Burden
    fcf = h.get("fcf", [0])[0]
    burden = (min(sbc, bb) / fcf) * 100 if fcf and fcf > 0 else 0

    # 5. Quality & Flags
    flags = []
    if bb is not None and sbc is not None and bb < 1.1 * sbc and bb > 0:
        flags.append("Defensive Buybacks: mostly offsetting dilution")
    if share_growth > 0.02:
        flags.append(f"High Dilution: shares up {share_growth*100:.1f}%")
    if ni and ni > 0 and mcap and burry_yield < 0.5 * gaap_yield:
        flags.append("Optical Illusion: GAAP earnings heavily inflated by SBC")

    score = "🟡"
    sbc_ratio = sbc / ni if ni and ni > 0 else 1.0
    if sbc_ratio < 0.1 and bb > sbc:
        score = "🟢"
    elif sbc_ratio > 0.25 or (oe is not None and oe < 0):
        score = "🔴"

    # 6. Trends (3Y)
    sbc_ratios = []
    share_growths = []
    bb_coverages = []

    for i in range(min(3, len(h.get("ni", [])))):
        if h["ni"][i] and h["ni"][i] > 0:
            sbc_ratios.append(h["sbc"][i] / h["ni"][i])

    for i in range(min(3, len(h.get("shares", [])) - 1)):
        if h["shares"][i+1] > 0:
            share_growths.append((h["shares"][i] / h["shares"][i+1]) - 1)

    for i in range(min(3, len(h.get("sbc", [])))):
        if h["sbc"][i] and h["sbc"][i] > 0:
            bb_coverages.append(h["buybacks"][i] / h["sbc"][i])

    avg_sbc_ratio = (sum(sbc_ratios) / len(sbc_ratios)) * 100 if sbc_ratios else 0
    avg_share_growth = (sum(share_growths) / len(share_growths)) * 100 if share_growths else 0
    avg_bb_coverage = (sum(bb_coverages) / len(bb_coverages)) if bb_coverages else 0

    return {
        "gaap_yield": round(gaap_yield, 2),
        "burry_yield": round(burry_yield, 2),
        "net_growth": round(net_growth, 2),
        "real_yield": round(real_yield, 2),
        "burden": round(burden, 1),
        "quality_score": score,
        "flags": flags,
        "avg_sbc_ratio": round(avg_sbc_ratio, 1),
        "avg_share_growth": round(avg_share_growth, 2),
        "avg_bb_coverage": round(avg_bb_coverage, 2),
        "share_growth_pct": round(share_growth * 100, 2)
    }

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

def load_recap(current_date: str) -> dict:
    if os.path.exists(RECAP_FILE):
        try:
            with open(RECAP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("date") == current_date:
                    return data.get("recap", {})
        except: pass
    return {}

def save_recap(recap: dict, current_date: str) -> None:
    try:
        with open(RECAP_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": current_date, "recap": recap}, f, indent=2)
    except Exception as e:
        logging.error("Failed to save recap: %s", e)

def load_financials_cache() -> dict:
    if os.path.exists(FINANCIALS_CACHE_FILE):
        try:
            with open(FINANCIALS_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {}

def save_financials_cache(cache: dict) -> None:
    try:
        with open(FINANCIALS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logging.error("Failed to save financials cache: %s", e)


def is_market_close_window() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    market_close_time = get_market_close_time(now.date())
    market_close_dt = datetime.combine(now.date(), market_close_time, tzinfo=now.tzinfo)

    # Run recap if within 55 minutes *after* market close.
    return market_close_dt <= now <= market_close_dt + timedelta(minutes=55)

def is_noon_window() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    # Noon ET: 12:00 PM to 12:55 PM
    return 12 == now.hour and 0 <= now.minute <= 55

def generate_html_recap(recap_data: Dict[str, Dict[str, Any]]) -> str:
    """Generates an HTML table from the recap data."""
    rows = []
    # Sort by rank (descending), then symbol
    sorted_items = sorted(recap_data.items(), key=lambda x: (-x[1].get("rank", 0), x[0]))

    for symbol, data in sorted_items:
        price = data.get("price", 0)
        change = data.get("change", 0)
        rank = data.get("rank", 0)
        ur = "🚀 U&R" if data.get("ur") else ""
        color = "#1f9d55" if change >= 0 else "#e3342f"
        rows.append(f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #eee;"><strong>{symbol}</strong></td>
            <td style="padding:10px;border-bottom:1px solid #eee;">${price:.2f}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;color:{color};">{change:+.2f}%</td>
            <td style="padding:10px;border-bottom:1px solid #eee;">{rank}/100</td>
            <td style="padding:10px;border-bottom:1px solid #eee;font-weight:bold;color:#1f9d55;">{ur}</td>
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
                        <th style="padding:10px;border-bottom:2px solid #ddd;text-align:left;">Tech Rank</th>
                        <th style="padding:10px;border-bottom:2px solid #ddd;text-align:left;">Signal</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </body>
    </html>
    """

def format_large_number(n: float) -> str:
    """Formats a large number into a human-readable string (e.g., $27.5B)."""
    abs_n = abs(n)
    sign = "-" if n < 0 else ""
    if abs_n >= 1e12:
        return f"{sign}${abs_n/1e12:.1f}T"
    elif abs_n >= 1e9:
        return f"{sign}${abs_n/1e9:.1f}B"
    elif abs_n >= 1e6:
        return f"{sign}${abs_n/1e6:.1f}M"
    else:
        return f"{sign}${abs_n:,.0f}"

def generate_dashboard(recap_data: Dict[str, Dict[str, Any]]) -> None:
    """Generates a comprehensive HTML dashboard in the docs/ directory."""
    os.makedirs("docs", exist_ok=True)

    rows = []
    # Sort by rank (descending), then symbol
    sorted_items = sorted(recap_data.items(), key=lambda x: (-x[1].get("rank", 0), x[0]))

    for symbol, data in sorted_items:
        price = data.get("price", 0)
        change = data.get("change", 0)
        rank = data.get("rank", 0)
        ur = "🚀 U&R" if data.get("ur") else ""
        low = data.get("low")
        high = data.get("high")

        # Calculate visual position between low and high
        progress_bar = ""
        pos_sort = -1
        if low is not None and high is not None and high > low:
            pos = (price - low) / (high - low) * 100
            pos = max(0, min(100, pos))
            pos_sort = pos
            color = "#3490dc" # blue
            if pos < 10: color = "#e3342f" # red
            elif pos > 90: color = "#38c172" # green

            progress_bar = f"""
            <div style="width:100px; background:#eee; height:12px; border-radius:6px; position:relative; overflow:hidden;">
                <div style="width:{pos}%; background:{color}; height:100%;"></div>
            </div>
            <div style="font-size:10px; color:#777; margin-top:2px;">
                ${low} - ${high}
            </div>
            """
        elif low is not None:
            progress_bar = f"<div style='font-size:10px; color:#777;'>Low Rule: ${low}</div>"
        elif high is not None:
            progress_bar = f"<div style='font-size:10px; color:#777;'>High Rule: ${high}</div>"

        # Calculate 52-week range position
        low52 = data.get("low52")
        high52 = data.get("high52")
        progress_bar_52w = ""
        pos52_sort = -1
        if low52 and high52 and high52 > low52:
            pos52 = (price - low52) / (high52 - low52) * 100
            pos52 = max(0, min(100, pos52))
            pos52_sort = pos52
            progress_bar_52w = f"""
            <div style="width:100px; background:#eee; height:12px; border-radius:6px; position:relative; overflow:hidden;">
                <div style="width:{pos52}%; background:#6c757d; height:100%;"></div>
            </div>
            <div style="font-size:10px; color:#777; margin-top:2px;">
                ${low52} - ${high52}
            </div>
            """

        change_color = "#1f9d55" if change >= 0 else "#e3342f"
        ur_sort = 1 if data.get("ur") else 0
        rsi_sort = data.get("rsi", 0)

        burry_take_data = data.get("burry_take")
        a = data.get("burry_analytics", {})

        gaap_ni_str = "N/A"
        gaap_ni_sort = -1e15
        burry_take_str = "N/A"
        burry_sort = -1e15
        details = ""

        if isinstance(burry_take_data, dict):
            oe = burry_take_data.get("owner_earnings")
            ni = burry_take_data.get("net_income")
            sbc = burry_take_data.get("sbc")
            bb = burry_take_data.get("buybacks")
            rsu = burry_take_data.get("rsu_tax", 0.0)

            burry_take_str = format_large_number(oe) if oe is not None else "N/A"
            burry_sort = oe if oe is not None else -1e15

            if ni is not None:
                gaap_ni_str = format_large_number(ni)
                gaap_ni_sort = ni

            details = f"""
            <div style="font-size:0.8em; color:#777; line-height:1.2;">
                NI: {format_large_number(ni) if ni is not None else '-'}<br/>
                SBC: +{format_large_number(sbc) if sbc is not None else '-'}<br/>
                BB: -{format_large_number(bb) if bb is not None else '-'}<br/>
                RSU Tax: -{format_large_number(rsu) if rsu is not None else '-'}
            </div>
            """

        # Analytics columns
        yields_html = f"""
        <div style="font-weight:bold;">B: {a.get('burry_yield', 'N/A')}%</div>
        <div style="font-size:0.85em; color:#777;">G: {a.get('gaap_yield', 'N/A')}%</div>
        """

        net_growth = a.get("net_growth", 0)
        growth_color = "#1f9d55" if net_growth > 0 else "#e3342f"
        growth_html = f"""
        <div style="font-weight:bold; color:{growth_color};">{net_growth:+.1f}%</div>
        <div style="font-size:0.8em; color:#777;">(1Y Rev-Shares)</div>
        """

        flags_html = ""
        for flag in a.get("flags", []):
            flags_html += f"<div title='{flag}' style='cursor:help; display:inline-block; margin-right:4px;'>⚠️</div>"

        quality_score = a.get("quality_score", "⚪")
        quality_html = f"""
        <div style="font-size:1.2em; display:flex; align-items:center;">
            {quality_score} <span style="font-size:0.6em; margin-left:4px;">{flags_html}</span>
        </div>
        """

        history_json = json.dumps(data.get("history_prices", []))

        rows.append(f"""
        <tr>
            <td style="padding:12px; border-bottom:1px solid #eee;"><strong>{symbol}</strong></td>
            <td class="price-cell" style="padding:12px; border-bottom:1px solid #eee; cursor: help;" data-sort="{price}" data-history='{history_json}'>
                ${price:.2f} <span style="color:{change_color}; font-size:0.9em;">({change:+.2f}%)</span>
            </td>
            <td style="padding:12px; border-bottom:1px solid #eee;" data-sort="{pos_sort}">{progress_bar}</td>
            <td style="padding:12px; border-bottom:1px solid #eee;" data-sort="{pos52_sort}">{progress_bar_52w}</td>
            <td style="padding:12px; border-bottom:1px solid #eee;" data-sort="{rank}"><span style="display:inline-block; padding:2px 8px; background:#f0f0f0; border-radius:12px; font-size:0.9em;">{rank}/100</span></td>
            <td style="padding:12px; border-bottom:1px solid #eee;" data-sort="{a.get('burry_yield', -100)}">{yields_html}</td>
            <td style="padding:12px; border-bottom:1px solid #eee;" data-sort="{net_growth}">{growth_html}</td>
            <td style="padding:12px; border-bottom:1px solid #eee;" data-sort="{a.get('real_yield', 0)}">{a.get('real_yield', 0)}%</td>
            <td style="padding:12px; border-bottom:1px solid #eee;" data-sort="{a.get('burden', 0)}">{a.get('burden', 0)}%</td>
            <td style="padding:12px; border-bottom:1px solid #eee;" data-sort="{quality_score}">{quality_html}</td>
            <td style="padding:12px; border-bottom:1px solid #eee; color:#555;" data-sort="{burry_sort}">
                <div style="font-weight:bold; margin-bottom:4px;">{burry_take_str}</div>
                {details}
            </td>
            <td style="padding:12px; border-bottom:1px solid #eee; font-size:0.85em; color:#666;" data-sort="{rsi_sort}">
                SBC/NI: {a.get('avg_sbc_ratio', 0)}% (3Y)<br/>
                Shr: {a.get('avg_share_growth', 0):+.1f}% (3Y)<br/>
                BB/SBC: {a.get('avg_bb_coverage', 0)}x
            </td>
        </tr>
        """)

    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M %p ET")

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Stock Monitor Dashboard</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #f4f7f6; color: #333; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
            h1 {{ margin-top: 0; color: #2c3e50; }}
            .updated {{ font-size: 0.9em; color: #7f8c8d; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
            th {{ text-align: left; padding: 12px; border-bottom: 2px solid #eee; color: #7f8c8d; font-weight: 600; text-transform: uppercase; font-size: 0.8em; cursor: pointer; user-select: none; }}
            th:hover {{ color: #2c3e50; background: #f9f9f9; }}
            th.sort-asc::after {{ content: " ↑"; }}
            th.sort-desc::after {{ content: " ↓"; }}
            tr:hover {{ background-color: #f9f9f9; }}
            .price-cell {{ border-bottom: 1px dotted #ccc; }}
            .price-cell:hover {{ background-color: #f0f7ff; }}
        </style>
    </head>
    <body>
        <div id="sparklineTooltip" style="position: absolute; display: none; background: rgba(255,255,255,0.95); border: 1px solid #ccc; padding: 10px; border-radius: 4px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); pointer-events: none; z-index: 1000;">
            <canvas id="sparklineCanvas" width="200" height="60"></canvas>
        </div>
        <div class="container">
            <h1>📈 Stock Monitor Dashboard</h1>
            <div class="updated">Last updated: {timestamp}</div>
            <table id="stockTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0)">Symbol</th>
                        <th onclick="sortTable(1)">Price</th>
                        <th onclick="sortTable(2)">Rules</th>
                        <th onclick="sortTable(3)">52W Range</th>
                        <th onclick="sortTable(4)">Rank</th>
                        <th onclick="sortTable(5)">Yields (B/G)</th>
                        <th onclick="sortTable(6)">Net Growth</th>
                        <th onclick="sortTable(7)">Real Yield</th>
                        <th onclick="sortTable(8)">SBC Burden</th>
                        <th onclick="sortTable(9)">Quality</th>
                        <th onclick="sortTable(10)">Owner Earnings</th>
                        <th onclick="sortTable(11)">3Y Trends</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
            <div style="margin-top:25px; padding-top:15px; border-top:1px solid #eee; font-size:0.85em; color:#777;">
                <strong>Burry-Take Formula:</strong> Owner's Earnings ≈ Net Income + SBC - Buybacks - RSU Tax.<br/>
                <span style="font-size:0.9em; margin-top:5px; display:block;">
                    * <strong>Burry Yield:</strong> Owner's Earnings / Market Cap. <strong>Real Yield:</strong> (Buybacks - SBC) / Market Cap.<br/>
                    * <strong>Net Growth:</strong> 1Y Revenue Growth - 1Y Share Growth. <strong>SBC Burden:</strong> min(SBC, Buybacks) / FCF.
                </span>
            </div>
        </div>
        <script>
        function sortTable(n) {{
            var table, rows, switching, i, x, y, shouldSwitch, dir, switchcount = 0;
            table = document.getElementById("stockTable");
            switching = true;
            dir = "asc";

            // Clear all sort classes
            var headers = table.getElementsByTagName("TH");
            for (i = 0; i < headers.length; i++) {{
                headers[i].classList.remove("sort-asc", "sort-desc");
            }}

            while (switching) {{
                switching = false;
                rows = table.rows;
                for (i = 1; i < (rows.length - 1); i++) {{
                    shouldSwitch = false;
                    x = rows[i].getElementsByTagName("TD")[n];
                    y = rows[i + 1].getElementsByTagName("TD")[n];

                    var xVal = x.getAttribute("data-sort") || x.innerText.toLowerCase();
                    var yVal = y.getAttribute("data-sort") || y.innerText.toLowerCase();

                    if (!isNaN(parseFloat(xVal)) && !isNaN(parseFloat(yVal))) {{
                        xVal = parseFloat(xVal);
                        yVal = parseFloat(yVal);
                    }}

                    if (dir == "asc") {{
                        if (xVal > yVal) {{
                            shouldSwitch = true;
                            break;
                        }}
                    }} else if (dir == "desc") {{
                        if (xVal < yVal) {{
                            shouldSwitch = true;
                            break;
                        }}
                    }}
                }}
                if (shouldSwitch) {{
                    rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                    switching = true;
                    switchcount ++;
                }} else {{
                    if (switchcount == 0 && dir == "asc") {{
                        dir = "desc";
                        switching = true;
                    }}
                }}
            }}

            if (dir == "asc") {{
                headers[n].classList.add("sort-asc");
            }} else {{
                headers[n].classList.add("sort-desc");
            }}
        }}

        const tooltip = document.getElementById('sparklineTooltip');
        const canvas = document.getElementById('sparklineCanvas');
        const ctx = canvas.getContext('2d');

        document.querySelectorAll('.price-cell').forEach(cell => {{
            cell.addEventListener('mouseenter', (e) => {{
                const history = JSON.parse(cell.getAttribute('data-history'));
                if (!history || history.length === 0) return;

                const min = Math.min(...history);
                const max = Math.max(...history);
                const range = max === min ? 1 : max - min;

                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.beginPath();
                ctx.strokeStyle = '#3490dc';
                ctx.lineWidth = 2;

                history.forEach((price, i) => {{
                    const x = (i / (history.length - 1)) * canvas.width;
                    const y = canvas.height - ((price - min) / range) * canvas.height * 0.8 - (canvas.height * 0.1);
                    if (i === 0) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                }});
                ctx.stroke();

                // High point (Green)
                const maxIdx = history.indexOf(max);
                const maxX = (maxIdx / (history.length - 1)) * canvas.width;
                const maxY = canvas.height - ((max - min) / range) * canvas.height * 0.8 - (canvas.height * 0.1);
                ctx.fillStyle = 'green';
                ctx.beginPath();
                ctx.arc(maxX, maxY, 4, 0, Math.PI * 2);
                ctx.fill();

                // Low point (Red)
                const minIdx = history.indexOf(min);
                const minX = (minIdx / (history.length - 1)) * canvas.width;
                const minY = canvas.height - ((min - min) / range) * canvas.height * 0.8 - (canvas.height * 0.1);
                ctx.fillStyle = 'red';
                ctx.beginPath();
                ctx.arc(minX, minY, 4, 0, Math.PI * 2);
                ctx.fill();

                tooltip.style.display = 'block';
            }});

            cell.addEventListener('mousemove', (e) => {{
                tooltip.style.left = (e.pageX + 15) + 'px';
                tooltip.style.top = (e.pageY + 15) + 'px';
            }});

            cell.addEventListener('mouseleave', () => {{
                tooltip.style.display = 'none';
            }});
        }});
        </script>
    </body>
    </html>
    """

    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    logging.info("Dashboard generated at docs/index.html")

# --- Evaluate one row ---
def evaluate_row(row: Dict[str, str], recap: Dict, state: Dict, financials_cache: Dict) -> Optional[Dict[str, Any]]:
    symbol = row.get("symbol")
    if not symbol: return None
    low = safe_float(row.get("low"))
    high = safe_float(row.get("high"))
    pct_up = safe_float(row.get("pct_up"))
    pct_down = safe_float(row.get("pct_down"))
    webhook = row.get("webhook") or None

    data = fetch_stock_data(symbol)
    if data is None: return None
    price = data["price"]
    prev_close = data["prev_close"]
    history = data["history"]
    low_today = data["low_today"]
    change = (price - prev_close) / prev_close * 100.0

    # Calculate indicators
    indicators = calculate_indicators(history, price, low_today)
    rank = calculate_rank(indicators, price)

    # --- Fetch Burry-take from caches or yfinance ---
    # 1. Check in-memory daily recap (recap.json)
    burry_take = recap.get(symbol, {}).get("burry_take")

    # 2. Check persistent financials cache (financials_cache.json)
    if burry_take is None:
        cached_data = financials_cache.get(symbol)
        if cached_data and isinstance(cached_data, dict):
            # Cache for 30 days since annual financials don't change often
            cache_date = datetime.strptime(cached_data["date"], "%Y-%m-%d").date()
            if (datetime.now().date() - cache_date).days < 30:
                # Compatibility check for old schema
                if not isinstance(cached_data["value"], dict) or "history" not in cached_data["value"]:
                    burry_take = None
                else:
                    burry_take = cached_data["value"]

    # 3. Fetch from yfinance as last resort
    if burry_take is None:
        logging.info("Fetching financials for %s...", symbol)
        burry_take = get_burry_take(symbol)
        # Cache even if None (to avoid re-fetching indices/unsupported symbols)
        financials_cache[symbol] = {
            "value": burry_take,
            "date": TODAY
        }

    # --- Calculate Analytics ---
    burry_analytics = calculate_burry_analytics(burry_take) if burry_take else {}

    # --- Update daily recap for ALL symbols (in-memory) ---
    recap[symbol] = {
        "price": round(price, 2),
        "change": round(change, 2),
        "rank": rank,
        "ur": indicators["ur_signal"],
        "low": low,
        "high": high,
        "pct_up": pct_up,
        "pct_down": pct_down,
        "sma50": round(indicators["sma50"], 2),
        "sma200": round(indicators["sma200"], 2),
        "rsi": round(indicators["rsi"], 2),
        "high52": round(indicators["high52"], 2),
        "low52": round(indicators["low52"], 2),
        "history_prices": [round(float(p), 2) for p in history["Close"].tolist()],
        "burry_take": burry_take,
        "burry_analytics": burry_analytics
    }

    triggers: List[str] = []
    if indicators["ur_signal"]:
        triggers.append(f"U&R: Undercut & Rally entry (Price ${price:.2f} > Low ${indicators['prior_60d_low']:.2f})")
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
            f"Price: {price:.2f} | Change: {change:.2f}% | Rank: {rank}/100"
        )
        severity = "info"
        if any(keyword in t.lower() for t in triggers for keyword in ["u&r", "up", "high"]):
            severity = "up"
        elif any(keyword in t.lower() for t in triggers for keyword in ["down", "low"]):
            severity = "down"

        return {"symbol": symbol, "triggers": triggers, "price": round(price,2),
                "prev_close": round(prev_close,2), "change": round(change,2),
                "rank": rank, "ur": indicators["ur_signal"],
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
    existing_symbols = {row.get("symbol","").strip().upper() for row in rows if row.get("symbol")}
    stocks_from_env = [s.strip().upper() for s in STOCK_LIST_ENV.split(",") if s.strip()] if STOCK_LIST_ENV else []
    stocks_from_file = []
    if os.path.exists("stocks.txt"):
        with open("stocks.txt","r",encoding="utf-8") as sf:
            stocks_from_file = [line.strip().upper() for line in sf if line.strip()]

    seen = set(existing_symbols)
    for s in stocks_from_env + stocks_from_file:
        if s and s not in seen:
            seen.add(s)
            rows.append({
                "symbol": s, "low": "", "high": "",
                "pct_up": DEFAULT_PCT_UP or "",
                "pct_down": DEFAULT_PCT_DOWN or "",
                "webhook": "",
            })

    # Evaluate all rows
    alerts: List[Dict[str,Any]] = []
    recap = load_recap(TODAY)
    state = load_state(TODAY)
    financials_cache = load_financials_cache()
    for row in rows:
        try:
            alert = evaluate_row(row, recap, state, financials_cache)
            if alert: alerts.append(alert)
        except: logging.exception("Error evaluating row: %s", row)

    save_recap(recap, TODAY)
    save_state(state, TODAY)
    save_financials_cache(financials_cache)

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

    # --- Dashboard generation (Always on run) ---
    if recap:
        generate_dashboard(recap)

    # --- Market-close recap ---
    if is_market_close_window():
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                print("is_market_close=true", file=f)
        if recap:
            # Generate HTML recap
            html_recap = generate_html_recap(recap)
            with open("recap.html", "w", encoding="utf-8") as f:
                f.write(html_recap)

            # Generate JSON recap for plaintext fallback
            recap_alerts = []
            # Sort by rank (descending), then symbol
            sorted_recap = sorted(recap.items(), key=lambda x: (-x[1].get("rank", 0), x[0]))
            for symbol, data in sorted_recap:
                sign = "▲" if data["change"] >= 0 else "▼"
                ur_str = " (U&R!)" if data.get("ur") else ""
                recap_alerts.append(f"**{symbol}** {sign} {abs(data['change'])}% — ${data['price']} | Rank: {data.get('rank')}/100{ur_str}")
            recap_payload = {
                "type": "recap",
                "title": f"📊 Market Close Recap ({TODAY})",
                "lines": recap_alerts
            }
            with open("recap.json","w",encoding="utf-8") as f:
                json.dump(recap_payload,f,indent=2)

    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.exception("Fatal error in main")
        sys.exit(1)

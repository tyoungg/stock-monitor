"""
Simple stock monitor script.

Reads rules from `rules.csv` (headers: symbol,low,high,pct_up,pct_down,webhook)
Fetches current price and previous close via yfinance
Sends POST to webhook URL when any rule triggers (or prints alerts when no webhook configured)

Usage: python monitor.py
Environment:
  DEFAULT_WEBHOOK - fallback webhook URL used if rule row has no webhook
"""

import pandas as pd
import yfinance as yf
import json
import os
from datetime import date

RULES_FILE = "rules.csv"
STATE_FILE = "alert_state.json"

INDEX_MAP = {
    "SPX": "^GSPC",
    "VIX": "^VIX",
    "COMP.IDX": "^IXIC",
    "DJIND": "^DJI"
}

def normalize_symbol(sym):
    return INDEX_MAP.get(sym, sym)

def load_rules():
    return pd.read_csv(RULES_FILE)

def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE))
    return {}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w"))

def fetch_prices(symbols):
    data = yf.download(
        symbols,
        period="2d",
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        progress=False
    )
    return data

def get_metrics(data, sym):
    df = data[sym]
    last = df["Close"].iloc[-1]
    prev = df["Close"].iloc[-2]
    pct = (last - prev) / prev * 100
    return round(last, 2), round(pct, 2)

def main():
    rules = load_rules()
    state = load_state()
    today = str(date.today())

    rules["yf_symbol"] = rules["ticker"].apply(normalize_symbol)
    symbols = rules["yf_symbol"].unique().tolist()

    prices = fetch_prices(symbols)

    alerts = []

    for _, r in rules.iterrows():
        price, pct = get_metrics(prices, r.yf_symbol)
        triggered = False
        severity = None

        if r.rule_type == "Low Target" and price <= r.threshold:
            triggered, severity = True, "down"
        elif r.rule_type == "High Target" and price >= r.threshold:
            triggered, severity = True, "up"
        elif r.rule_type == "Daily % Up" and pct >= r.threshold:
            triggered, severity = True, "up"
        elif r.rule_type == "Daily % Down" and pct <= -r.threshold:
            triggered, severity = True, "down"

        if not triggered:
            continue

        fingerprint = f"{r.ticker}|{r.rule_type}|{r.threshold}"

        # Dedup: only alert once per day per fingerprint
        if state.get(fingerprint) == today:
            continue

        text = (
            f"**{r.ticker}** — {r.rule_type}\n"
            f"Threshold: `{r.threshold}`\n"
            f"Price: `{price}` | %Δ: `{pct}`"
        )

        alerts.append({
            "symbol": r.ticker,
            "rule": r.rule_type,
            "threshold": r.threshold,
            "price": price,
            "pct_change": pct,
            "severity": severity,
            "text": text,
            "fingerprint": fingerprint
        })

        state[fingerprint] = today

    if alerts:
        json.dump(alerts, open("alerts.json", "w"), indent=2)
        save_state(state)
        print(f"🚨 {len(alerts)} alert(s) triggered")
        raise SystemExit(1)

    print("✅ No alerts")

if __name__ == "__main__":
    main()

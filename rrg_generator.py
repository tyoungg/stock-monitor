import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from datetime import datetime
from zoneinfo import ZoneInfo

plt.style.use("dark_background")

# ---------------------------
# CONFIG
# ---------------------------
TICKERS = [
    "XLK",  # Tech
    "XLF",  # Financials
    "XLV",  # Healthcare
    "XLE",  # Energy
    "XLI",  # Industrials
    "XLP",  # Staples
    "XLY",  # Discretionary
    "XLRE"  # Real Estate
]

BENCHMARK = "^GSPC"
PERIOD = "2y"
WINDOW = 14   # smoothing window

# ---------------------------
# DOWNLOAD DATA
# ---------------------------
data = yf.download(TICKERS + [BENCHMARK], period=PERIOD)

# Handle different yfinance versions and their return formats
if isinstance(data.columns, pd.MultiIndex):
    if "Adj Close" in data.columns.levels[0]:
        data = data["Adj Close"]
    else:
        data = data["Close"]
else:
    if "Adj Close" in data.columns:
        data = data["Adj Close"]
    else:
        data = data["Close"]

# Convert to weekly (important for RRG)
data = data.resample("W-FRI").last()

benchmark = data[BENCHMARK]
prices = data.drop(columns=[BENCHMARK])

# ---------------------------
# RRG CALCULATION
# ---------------------------
def compute_rrg(price, benchmark):
    rs = price / benchmark

    # RS-Ratio (normalized + smoothed)
    rs_mean = rs.rolling(WINDOW).mean()
    rs_std = rs.rolling(WINDOW).std()
    rs_ratio = 100 + (rs - rs_mean) / rs_std * 10

    # RS-Momentum (rate of change of RS-Ratio)
    momentum = rs_ratio.diff()
    mom_mean = momentum.rolling(WINDOW).mean()
    mom_std = momentum.rolling(WINDOW).std()
    rs_momentum = 100 + (momentum - mom_mean) / mom_std * 10

    return rs_ratio, rs_momentum

rrg = {}
for ticker in prices.columns:
    rs_ratio, rs_mom = compute_rrg(prices[ticker], benchmark)

    df = pd.DataFrame({
        "RS_Ratio": rs_ratio,
        "RS_Momentum": rs_mom
    }).dropna()

    rrg[ticker] = df.tail(12)  # last 12 weeks for trails

# ---------------------------
# COLORS (match your style)
# ---------------------------
colors = {
    "XLK": "yellow",
    "XLF": "lime",
    "XLV": "magenta",
    "XLE": "red",
    "XLI": "orange",
    "XLP": "cyan",
    "XLY": "white",
    "XLRE": "pink"
}

# ---------------------------
# PLOT
# ---------------------------
plt.figure(figsize=(10, 8))

# Quadrants
plt.axvline(100, color='gray', linestyle='--', alpha=0.5)
plt.axhline(100, color='gray', linestyle='--', alpha=0.5)

# Labels
plt.text(102, 104, "Leading", color="white")
plt.text(102, 96, "Weakening", color="white")
plt.text(96, 96, "Lagging", color="white")
plt.text(96, 104, "Improving", color="white")

# Trails
for ticker, df in rrg.items():
    color = colors.get(ticker, "white")

    # trail line
    plt.plot(df["RS_Ratio"], df["RS_Momentum"],
             marker='o', markersize=3,
             color=color, label=ticker)

    # arrows (direction)
    for i in range(1, len(df)):
        plt.arrow(
            df["RS_Ratio"].iloc[i-1],
            df["RS_Momentum"].iloc[i-1],
            df["RS_Ratio"].iloc[i] - df["RS_Ratio"].iloc[i-1],
            df["RS_Momentum"].iloc[i] - df["RS_Momentum"].iloc[i-1],
            head_width=0.3,
            length_includes_head=True,
            color=color,
            alpha=0.7
        )

    # last point highlight
    plt.scatter(df["RS_Ratio"].iloc[-1],
                df["RS_Momentum"].iloc[-1],
                s=80, color=color)

    # label last point
    plt.text(df["RS_Ratio"].iloc[-1] + 0.3,
             df["RS_Momentum"].iloc[-1] + 0.3,
             ticker, color=color)

# ---------------------------
# FINAL TOUCHES
# ---------------------------
plt.title("Relative Rotation Graph (RRG) - Sector ETFs")
plt.xlabel("JdK RS-Ratio")
plt.ylabel("JdK RS-Momentum")
plt.grid(alpha=0.2)
plt.xlim(90, 110)
plt.ylim(90, 110)

plt.legend(loc="upper left", fontsize=8)

# Ensure docs directory exists
os.makedirs("docs", exist_ok=True)

# Save the plot
plt.savefig("docs/rrg.png", dpi=150, bbox_inches='tight')
plt.close()

# Generate RRG.html
timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M %p ET")
html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sector RRG</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #121212; color: #eee; margin: 0; padding: 20px; text-align: center; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: #1e1e1e; padding: 30px; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }}
        h1 {{ margin-top: 0; color: #fff; }}
        .updated {{ font-size: 0.9em; color: #aaa; margin-bottom: 20px; }}
        img {{ max-width: 100%; height: auto; border-radius: 4px; border: 1px solid #333; }}
        .nav {{ margin-bottom: 20px; }}
        .nav a {{ color: #3490dc; text-decoration: none; font-weight: bold; }}
        .nav a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="index.html">← Back to Dashboard</a>
        </div>
        <h1>Sector Relative Rotation Graph (RRG)</h1>
        <div class="updated">Last updated: {timestamp}</div>
        <img src="rrg.png" alt="RRG Graph">
        <div style="margin-top:20px; text-align: left; font-size: 0.9em; color: #ccc;">
            <p><strong>Relative Rotation Graphs (RRG)</strong> help visualize the relative strength and momentum of different sectors against a benchmark (S&P 500).</p>
            <ul>
                <li><strong>Leading (Top-Right):</strong> Strong relative strength and strong momentum.</li>
                <li><strong>Weakening (Bottom-Right):</strong> Strong relative strength but losing momentum.</li>
                <li><strong>Lagging (Bottom-Left):</strong> Weak relative strength and weak momentum.</li>
                <li><strong>Improving (Top-Left):</strong> Weak relative strength but gaining momentum.</li>
            </ul>
        </div>
    </div>
</body>
</html>
"""

with open("docs/RRG.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print("RRG image and HTML page generated successfully.")

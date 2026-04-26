import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# ---------------------------
# CONFIG
# ---------------------------
TICKERS = ["XLK","XLF","XLV","XLE","XLI","XLP","XLY","XLRE","PSP"]
BENCHMARK = "^GSPC"

TICKER_NAMES = {
    "PSP": "PE Proxy (PSP)"
}
PERIOD = "2y"
WINDOW = 14
TAIL_LENGTH = 8  # how many trailing points

# ---------------------------
# DOWNLOAD DATA
# ---------------------------
data = yf.download(TICKERS + [BENCHMARK], period=PERIOD, auto_adjust=False)

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

data = data.resample("W-FRI").last()

benchmark = data[BENCHMARK]
prices = data.drop(columns=[BENCHMARK])

# ---------------------------
# RRG CALCULATION
# ---------------------------
def compute_rrg(price, benchmark):
    rs = price / benchmark

    rs_mean = rs.rolling(WINDOW).mean()
    rs_std = rs.rolling(WINDOW).std()
    rs_ratio = 100 + (rs - rs_mean) / rs_std * 10

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
    rrg[ticker] = df

# ---------------------------
# ---------------------------
# LABELS (names + tickers)
# ---------------------------
sector_names = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLP": "Staples",
    "XLY": "Discretionary",
    "XLRE": "Real Estate",
    "PSP": "Private Equity"
}

def get_quadrant(x, y):
    if x >= 100 and y >= 100:
        return "Leading"
    elif x >= 100 and y < 100:
        return "Weakening"
    elif x < 100 and y < 100:
        return "Lagging"
    else:
        return "Improving"

# Quadrant colors
quad_colors = {
    "Leading": "#00FF7F",      # green
    "Weakening": "#FFD700",    # yellow
    "Lagging": "#FF4C4C",      # red
    "Improving": "#00BFFF"     # blue
}

# ---------------------------
# BUILD FRAMES
# ---------------------------
frames = []
# Use benchmark index as the master timeline
dates = benchmark[benchmark.index >= min(df.index.min() for df in rrg.values() if not df.empty)].index

latest_leaders = []

for i in range(TAIL_LENGTH, len(dates)):
    frame_data = []
    leaders = []
    current_date = dates[i]

    for ticker in TICKERS:
        if ticker not in rrg:
            continue

        # Get data up to current_date
        df = rrg[ticker][rrg[ticker].index <= current_date]
        if len(df) == 0:
            continue

        tail = df.tail(TAIL_LENGTH)
        if len(tail) == 0:
            continue

        x = tail["RS_Ratio"].values
        y = tail["RS_Momentum"].values

        # Fade effect
        opacity = np.linspace(0.2, 1, len(tail))

        # Determine quadrant for last point
        quad = get_quadrant(x[-1], y[-1])
        color = quad_colors[quad]

        disp_name = sector_names.get(ticker, ticker)
        if quad == "Leading":
            leaders.append(disp_name)

        # Highlight leaders
        size = 12 if quad == "Leading" else 7
        marker_opacity = 1 if quad == "Leading" else 0.6

        name = f"{disp_name} ({ticker})"

        frame_data.append(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers+text",
                name=name,
                legendgroup=name,
                showlegend=(i == TAIL_LENGTH),  # only show once
                line=dict(color=color, width=2),
                marker=dict(
                    size=[4]* (len(x)-1) + [size],  # bigger last point
                    opacity=list(opacity[:-1]) + [marker_opacity],
                    color=color
                ),
                text=[""] * (len(x)-1) + [ticker],
                textposition="top center",
                hovertext=[
                    f"{name}<br>{tail.index[j].date()}<br>"
                    f"RS-Ratio: {x[j]:.2f}<br>RS-Mom: {y[j]:.2f}<br>{get_quadrant(x[j], y[j])}"
                    for j in range(len(tail))
                ],
                hoverinfo="text"
            )
        )

    # Quadrant annotations
    quadrant_annos = [
        dict(x=0.98, y=0.98, xref="paper", yref="paper", xanchor="right", yanchor="top", text="<b>Leading</b>", showarrow=False, font=dict(color="rgba(0, 150, 0, 0.3)", size=16)),
        dict(x=0.98, y=0.02, xref="paper", yref="paper", xanchor="right", yanchor="bottom", text="<b>Weakening</b>", showarrow=False, font=dict(color="rgba(150, 150, 0, 0.3)", size=16)),
        dict(x=0.02, y=0.02, xref="paper", yref="paper", xanchor="left", yanchor="bottom", text="<b>Lagging</b>", showarrow=False, font=dict(color="rgba(150, 0, 0, 0.3)", size=16)),
        dict(x=0.02, y=0.98, xref="paper", yref="paper", xanchor="left", yanchor="top", text="<b>Improving</b>", showarrow=False, font=dict(color="rgba(0, 0, 150, 0.3)", size=16)),
    ]

    # Persistent shapes for each frame
    frame_shapes = [
        dict(type="rect", xref="paper", yref="paper", x0=0.5, y0=0.5, x1=1, y1=1, fillcolor="rgba(0, 255, 127, 0.03)", line_width=0, layer="below"),
        dict(type="rect", xref="paper", yref="paper", x0=0.5, y0=0, x1=1, y1=0.5, fillcolor="rgba(255, 215, 0, 0.03)", line_width=0, layer="below"),
        dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=0.5, y1=0.5, fillcolor="rgba(255, 76, 76, 0.03)", line_width=0, layer="below"),
        dict(type="rect", xref="paper", yref="paper", x0=0, y0=0.5, x1=0.5, y1=1, fillcolor="rgba(0, 191, 255, 0.03)", line_width=0, layer="below"),
    ]

    frames.append(go.Frame(
        data=frame_data,
        name=str(dates[i].date()),
        layout=go.Layout(annotations=quadrant_annos, shapes=frame_shapes)
    ))
    # Track the leaders of the very last frame
    if i == len(dates) - 1:
        latest_leaders = leaders

# ---------------------------
# INITIAL FRAME (Start at the latest date)
# ---------------------------
# Ensure all traces in the initial frame show in the legend
init_data = []
for trace in frames[-1].data:
    trace.showlegend = True
    init_data.append(trace)

init_layout = frames[-1].layout

# ---------------------------
# FIGURE
# ---------------------------
fig = go.Figure(
    data=init_data,
    frames=frames,
    layout=init_layout
)

# ---------------------------
# QUADRANT LINES
# ---------------------------
fig.add_vline(x=100, line_dash="dash", line_color="gray")
fig.add_hline(y=100, line_dash="dash", line_color="gray")

# ---------------------------
# LAYOUT (INTERACTION)
# ---------------------------
fig.update_layout(
    title="Relative Rotation Graph (RRG) – Sector Rotation",
    xaxis=dict(title="RS-Ratio", range=[90, 110], gridcolor="#eee", zerolinecolor="#ccc"),
    yaxis=dict(title="RS-Momentum", range=[90, 110], gridcolor="#eee", zerolinecolor="#ccc"),
    plot_bgcolor="white",
    hovermode="closest",
    margin=dict(l=50, r=50, t=80, b=150),

    # 🔥 THIS enables click-to-focus via legend
    legend=dict(
        itemclick="toggleothers",   # click = isolate
        itemdoubleclick="toggle",    # double-click = toggle back
        orientation="h",
        y=-0.3,
        x=0.5,
        xanchor="center",
        font=dict(size=10)
    ),

    updatemenus=[{
        "type": "buttons",
        "showactive": False,
        "x": 0.05,
        "y": 0,
        "xanchor": "right",
        "yanchor": "top",
        "direction": "left",
        "pad": {"r": 10, "t": 65},
        "buttons": [
            {
                "label": "▶ Play",
                "method": "animate",
                "args": [None, {
                    "frame": {"duration": 300, "redraw": True},
                    "fromcurrent": True
                }]
            },
            {
                "label": "⏸ Pause",
                "method": "animate",
                "args": [[None], {
                    "frame": {"duration": 0},
                    "mode": "immediate"
                }]
            }
        ]
    }],
    sliders=[{
        "active": len(frames) - 1,
        "yanchor": "top",
        "xanchor": "left",
        "currentvalue": {
            "font": {"size": 16},
            "prefix": "Date: ",
            "visible": True,
            "xanchor": "right"
        },
        "transition": {"duration": 0},
        "pad": {"b": 10, "t": 50},
        "len": 0.9,
        "x": 0.1,
        "y": 0,
        "steps": [{
            "args": [[f.name], {"frame": {"duration": 0, "redraw": True}, "mode": "immediate"}],
            "label": f.name,
            "method": "animate"
        } for f in frames]
    }]
)

# Ensure docs directory exists
os.makedirs("docs", exist_ok=True)

# Wrap Plotly in our dashboard template
timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M %p ET")
plotly_html = fig.to_html(full_html=False, include_plotlyjs='cdn')

leaders_html = ""
if latest_leaders:
    leaders_html = f"""
    <div style="margin: 20px auto; max-width: 800px; background: #e6fffa; border: 2px solid #38b2ac; border-radius: 8px; padding: 20px;">
        <h3 style="margin-top: 0; color: #2c7a7b;">Current Market Leaders 🚀</h3>
        <div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 10px;">
            {' '.join([f'<span style="background: #38b2ac; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold;">{l}</span>' for l in latest_leaders])}
        </div>
    </div>
    """

html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sector RRG</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #f4f7f6; color: #333; margin: 0; padding: 20px; text-align: center; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        h1 {{ margin-top: 0; color: #2c3e50; }}
        .updated {{ font-size: 0.9em; color: #7f8c8d; margin-bottom: 20px; }}
        .nav {{ margin-bottom: 20px; text-align: left; }}
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

        <div style="width: 100%; height: 750px;">
            {plotly_html}
        </div>

        {leaders_html}

        <div style="margin-top:40px; text-align: left; font-size: 0.9em; color: #555; border-top: 1px solid #eee; padding-top: 20px;">
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

print("Animated RRG HTML page generated successfully.")

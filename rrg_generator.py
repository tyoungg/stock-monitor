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

# 🔥 Map ticker to consistent identity (fix legend persistence)
ticker_uid_map = {ticker: f"{sector_names.get(ticker, ticker)} ({ticker})" for ticker in TICKERS}

frames = []
dates = list(rrg.values())[0].index  # safer than relying on first ticker

for i in range(TAIL_LENGTH, len(dates)):
    frame_data = []
    leaders = []

    for ticker in TICKERS:
        df = rrg[ticker].iloc[:i+1] # Include the current point
        tail = df.tail(TAIL_LENGTH)

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
                mode="lines+markers",
                name=name,
                legendgroup=name,
#                showlegend=(i == TAIL_LENGTH),  # only show once
                showlegend=False,  # legend handled by static traces

                # 🔥 CRITICAL FIX: binds traces across frames
                uid=name,

                line=dict(color=color, width=2),
                marker=dict(
                    size=[4]* (len(x)-1) + [size],  # bigger last point
                    opacity=list(opacity[:-1]) + [marker_opacity],
                    color=color
                ),
                text=[
                    f"{name}<br>{tail.index[j].date()}<br>"
                    f"RS-Ratio: {x[j]:.2f}<br>RS-Mom: {y[j]:.2f}<br>{get_quadrant(x[j], y[j])}"
                    for j in range(len(tail))
                ],
#                hoverinfo="text"
                hovertemplate="%{text}<extra></extra>"    
            )
        )

    # Current Leaders box text
    leaders_text = "<b>Current Leaders:</b><br>" + "<br>".join([f"• {l}" for l in leaders]) if leaders else "<b>Current Leaders:</b><br><i>None</i>"

    # Quadrant annotations (must be included in every frame to persist)
    quadrant_annos = [
        dict(x=104, y=104, text="Leading", showarrow=False, font=dict(color="gray")),
        dict(x=104, y=96, text="Weakening", showarrow=False, font=dict(color="gray")),
        dict(x=96, y=96, text="Lagging", showarrow=False, font=dict(color="gray")),
        dict(x=96, y=104, text="Improving", showarrow=False, font=dict(color="gray")),
        # The Leaders Box
        dict(
            x=0.99, y=0.99,
            xref="paper", yref="paper",
            xanchor="right", yanchor="top",
            text=leaders_text,
            showarrow=False,
            align="left",
            bgcolor="rgba(255, 255, 255, 0.95)",
            bordercolor="#1b4332",
            borderwidth=2,
            borderpad=10,
            font=dict(size=14, color="#1b4332")
        )
    ]

    frames.append(go.Frame(
        data=frame_data,
        name=str(dates[i].date()),
        layout=go.Layout(annotations=quadrant_annos)
    ))

# ---------------------------
# INITIAL FRAME (Start at the latest date)
# ---------------------------
init_data = frames[-1].data
init_layout = go.Layout(annotations=frames[-1].layout.annotations)

# ---------------------------
# STATIC LEGEND TRACES (fix legend persistence)
# ---------------------------
legend_traces = []

for ticker in TICKERS:
    disp_name = sector_names.get(ticker, ticker)
    name = f"{disp_name} ({ticker})"

    legend_traces.append(
        go.Scatter(
            x=[None],
            y=[None],
            mode="markers",
            name=name,
            legendgroup=name,
            showlegend=True,

            # 🔥 MUST MATCH frame traces
            uid=name,

            marker=dict(size=10)
        )
    )

# ---------------------------
# FIGURE
# ---------------------------
fig = go.Figure(
    data=legend_traces,
    frames=frames,
    layout=init_layout
)

# Add actual traces AFTER legend scaffolding
fig.add_traces(init_data)

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
    xaxis=dict(title="RS-Ratio", range=[90, 110]),
    yaxis=dict(title="RS-Momentum", range=[90, 110]),
    hovermode="closest",

    # 🔥 THIS enables click-to-focus via legend
    legend=dict(
        itemclick="toggleothers",
        itemdoubleclick="toggle",
        groupclick="toggleitem"
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

html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sector RRG</title>
</head>
<body>
    <h1>Sector Relative Rotation Graph (RRG)</h1>
    <div>Last updated: {timestamp}</div>
    {plotly_html}
</body>
</html>
"""

with open("docs/RRG.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print("Animated RRG HTML page generated successfully.")

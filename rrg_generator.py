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
leaders_history = {} # date -> list of tickers

for i in range(TAIL_LENGTH, len(dates)):
    frame_data = []
    frame_annos = [
        dict(x=0.98, y=0.98, xref="paper", yref="paper", xanchor="right", yanchor="top", text="<b>Leading</b>", showarrow=False, font=dict(color="rgba(0, 150, 0, 0.3)", size=16)),
        dict(x=0.98, y=0.02, xref="paper", yref="paper", xanchor="right", yanchor="bottom", text="<b>Weakening</b>", showarrow=False, font=dict(color="rgba(150, 150, 0, 0.3)", size=16)),
        dict(x=0.02, y=0.02, xref="paper", yref="paper", xanchor="left", yanchor="bottom", text="<b>Lagging</b>", showarrow=False, font=dict(color="rgba(150, 0, 0, 0.3)", size=16)),
        dict(x=0.02, y=0.98, xref="paper", yref="paper", xanchor="left", yanchor="top", text="<b>Improving</b>", showarrow=False, font=dict(color="rgba(0, 0, 150, 0.3)", size=16)),
    ]
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
            leaders.append(ticker)

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
                text=[""] * (len(x)-1) + [f"<b>{ticker}</b>"],
                textposition="top center",
                textfont=dict(color=color, size=11),
                hovertext=[
                    f"{name}<br>{tail.index[j].date()}<br>"
                    f"RS-Ratio: {x[j]:.2f}<br>RS-Mom: {y[j]:.2f}<br>{get_quadrant(x[j], y[j])}"
                    for j in range(len(tail))
                ],
                hoverinfo="text"
            )
        )

    # Persistent shapes for each frame
    frame_shapes = [
        dict(type="rect", xref="paper", yref="paper", x0=0.5, y0=0.5, x1=1, y1=1, fillcolor="rgba(0, 255, 127, 0.03)", line_width=0, layer="below"),
        dict(type="rect", xref="paper", yref="paper", x0=0.5, y0=0, x1=1, y1=0.5, fillcolor="rgba(255, 215, 0, 0.03)", line_width=0, layer="below"),
        dict(type="rect", xref="paper", yref="paper", x0=0, y0=0, x1=0.5, y1=0.5, fillcolor="rgba(255, 76, 76, 0.03)", line_width=0, layer="below"),
        dict(type="rect", xref="paper", yref="paper", x0=0, y0=0.5, x1=0.5, y1=1, fillcolor="rgba(0, 191, 255, 0.03)", line_width=0, layer="below"),
    ]

    date_str = str(dates[i].date())
    frames.append(go.Frame(
        data=frame_data,
        name=date_str,
        layout=go.Layout(annotations=frame_annos, shapes=frame_shapes)
    ))
    leaders_history[date_str] = leaders
    # Track the leaders of the very last frame
    if i == len(dates) - 1:
        latest_leaders = [sector_names.get(t, t) for t in leaders]

# ---------------------------
# INITIAL FRAME (Start at the latest date)
# ---------------------------
# Copy the last frame's data and layout to initialize the figure correctly
init_data = [go.Scatter(**t.to_plotly_json()) for t in frames[-1].data]
# Ensure they are visible in our custom legend state
for t in init_data:
    t.showlegend = True

init_layout = go.Layout(
    annotations=frames[-1].layout.annotations,
    shapes=frames[-1].layout.shapes
)

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
    margin=dict(l=50, r=50, t=80, b=50),
    showlegend=False,

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
# Use a specific div_id for our toggle script
plotly_html = fig.to_html(full_html=False, include_plotlyjs='cdn', div_id="rrg-chart")

# Generate custom legend items
legend_items = []
for ticker in TICKERS:
    if ticker not in rrg: continue
    df = rrg[ticker]
    if df.empty: continue
    last_point = df.iloc[-1]
    quad = get_quadrant(last_point["RS_Ratio"], last_point["RS_Momentum"])
    color = quad_colors[quad]
    disp_name = sector_names.get(ticker, ticker)
    name = f"{disp_name} ({ticker})"
    legend_items.append({
        "ticker": ticker,
        "name": name,
        "color": color
    })

import json
leaders_json = json.dumps(leaders_history)
ticker_to_name = json.dumps({t: sector_names.get(t, t) for t in TICKERS})

legend_html = f"""
<div id="custom-legend" style="margin: 20px auto; max-width: 1000px; display: flex; flex-wrap: wrap; justify-content: center; gap: 10px;">
    {' '.join([f'''
<<<<<<< Updated upstream
    <div class="legend-item"
         onclick="toggleTrace('{item["name"]}', this)"
         onmouseover="highlightTrace('{item["name"]}', true)"
         onmouseout="highlightTrace('{item["name"]}', false)"
         style="cursor: pointer; padding: 5px 12px; border-radius: 15px; border: 2px solid {item["color"]}; background: {item["color"]}22; display: flex; align-items: center; gap: 6px; font-weight: bold; transition: all 0.2s;"
=======
    <div class="legend-item"
         onclick="toggleTrace('{item["name"]}', this)"
         onmouseover="highlightTrace('{item["name"]}', true)"
         onmouseout="highlightTrace('{item["name"]}', false)"
         style="cursor: pointer; padding: 5px 12px; border-radius: 15px; border: 2px solid {item["color"]}; background: {item["color"]}22; display: flex; align-items: center; gap: 6px; font-weight: bold; transition: all 0.2s;"
>>>>>>> Stashed changes
         data-name="{item["name"]}">
        <span style="width: 10px; height: 10px; border-radius: 50%; background: {item["color"]};"></span>
        {item["ticker"]}
    </div>
    ''' for item in legend_items])}
</div>
<div style="margin-bottom: 20px;">
    <button onclick="setAllTraces(true)" style="padding: 5px 15px; border-radius: 4px; border: 1px solid #ccc; background: white; cursor: pointer; font-size: 0.8em; margin-right: 5px;">Show All</button>
    <button onclick="setAllTraces(false)" style="padding: 5px 15px; border-radius: 4px; border: 1px solid #ccc; background: white; cursor: pointer; font-size: 0.8em;">Hide All</button>
</div>
"""

leaders_html = f"""
<div id="leaders-container" style="margin: 20px auto; max-width: 800px; background: #e6fffa; border: 2px solid #38b2ac; border-radius: 8px; padding: 20px;">
    <h3 style="margin-top: 0; color: #2c7a7b;">Market Leaders for <span id="current-date-display">{dates[-1].date()}</span> 🚀</h3>
    <div id="leaders-list" style="display: flex; flex-wrap: wrap; justify-content: center; gap: 10px;">
        {' '.join([f'<span style="background: #38b2ac; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold;">{l}</span>' for l in latest_leaders]) or '<span style="color: #666;">No clear leaders</span>'}
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
        .legend-item.hidden {{
            background: #eee !important;
            border-color: #ccc !important;
            color: #999 !important;
            opacity: 0.6;
        }}
        .legend-item.hidden span {{
            background: #ccc !important;
        }}
        .legend-item:hover {{
            transform: translateY(-2px);
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="nav">
            <a href="index.html">← Back to Dashboard</a>
        </div>
        <h1>Sector Relative Rotation Graph (RRG)</h1>
        <div class="updated">Last updated: {timestamp}</div>

<<<<<<< Updated upstream
        <div style="width: 100%; height: 750px;">
            {plotly_html}
        </div>

        {legend_html}

=======
        {legend_html}

        <div style="width: 100%; height: 750px; margin-top: 20px;">
            {plotly_html}
        </div>

>>>>>>> Stashed changes
        {leaders_html}

        <script>
        const LEADERS_HISTORY = {leaders_json};
        const TICKER_TO_NAME = {ticker_to_name};

        function toggleTrace(name, el) {{
            const gd = document.getElementById('rrg-chart');
            const index = gd.data.findIndex(t => t.name === name);
            if (index === -1) return;

            const currentVisible = gd.data[index].visible;
            const nextVisible = (currentVisible === true || currentVisible === undefined) ? 'legendonly' : true;

            Plotly.restyle('rrg-chart', {{visible: nextVisible}}, [index]);
<<<<<<< Updated upstream

=======

>>>>>>> Stashed changes
            if (nextVisible === true) {{
                el.classList.remove('hidden');
            }} else {{
                el.classList.add('hidden');
            }}
        }}

        function setAllTraces(visible) {{
            const gd = document.getElementById('rrg-chart');
            const state = visible ? true : 'legendonly';
            const indices = gd.data.map((_, i) => i);
<<<<<<< Updated upstream

            Plotly.restyle('rrg-chart', {{visible: state}}, indices);

=======

            Plotly.restyle('rrg-chart', {{visible: state}}, indices);

>>>>>>> Stashed changes
            document.querySelectorAll('.legend-item').forEach(el => {{
                if (visible) el.classList.remove('hidden');
                else el.classList.add('hidden');
            }});
        }}

        function highlightTrace(name, highlight) {{
            const gd = document.getElementById('rrg-chart');
            const index = gd.data.findIndex(t => t.name === name);
            if (index === -1) return;

            const width = highlight ? 5 : 2;
            const opacity = highlight ? 1.0 : 0.6;
            // Only update if not hidden
            if (gd.data[index].visible !== 'legendonly') {{
                Plotly.restyle('rrg-chart', {{'line.width': width}}, [index]);
            }}
<<<<<<< Updated upstream

=======

>>>>>>> Stashed changes
            // Subtle highlight on the legend item itself
            const el = document.querySelector(`.legend-item[data-name="${{name}}"]`);
            if (el && !el.classList.contains('hidden')) {{
                el.style.transform = highlight ? 'translateY(-3px)' : '';
                el.style.boxShadow = highlight ? '0 4px 8px rgba(0,0,0,0.15)' : '';
            }}
        }}

        // Listen for frame changes to update the Leaders list
        document.getElementById('rrg-chart').on('plotly_animatingframe', function(event) {{
            const date = event.name;
            updateLeaders(date);
        }});

        // Also listen for slider changes
        document.getElementById('rrg-chart').on('plotly_sliderchange', function(event) {{
            const date = event.step.label;
            updateLeaders(date);
        }});

        function updateLeaders(date) {{
            const leaders = LEADERS_HISTORY[date] || [];
            const container = document.getElementById('leaders-list');
            const dateDisplay = document.getElementById('current-date-display');
<<<<<<< Updated upstream

            dateDisplay.innerText = date;

            if (leaders.length === 0) {{
                container.innerHTML = '<span style="color: #666;">No clear leaders</span>';
            }} else {{
                container.innerHTML = leaders.map(t =>
=======

            dateDisplay.innerText = date;

            if (leaders.length === 0) {{
                container.innerHTML = '<span style="color: #666;">No clear leaders</span>';
            }} else {{
                container.innerHTML = leaders.map(t =>
>>>>>>> Stashed changes
                    `<span style="background: #38b2ac; color: white; padding: 5px 15px; border-radius: 20px; font-weight: bold;">${{TICKER_TO_NAME[t] || t}}</span>`
                ).join(' ');
            }}
        }}
        </script>

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

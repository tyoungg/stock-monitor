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
# BUILD ANIMATION FRAMES
# ---------------------------
dates = rrg[TICKERS[0]].index
frames = []
           
                                                         
                                                         

        
                                            
                                             
                                          
                                             

for i in range(TAIL_LENGTH, len(dates)):
    frame_data = []
                                       

    for ticker in TICKERS:
        df = rrg[ticker].iloc[:i+1] # Include the i-th point
        tail = df.tail(TAIL_LENGTH)
        display_name = TICKER_NAMES.get(ticker, ticker)

        frame_data.append(
            go.Scatter(
                  
                x=tail["RS_Ratio"],
                y=tail["RS_Momentum"],
                mode="lines+markers",
                name=display_name,
                text=[f"{display_name}<br>{d.date()}" for d in tail.index],
                hoverinfo="text+x+y",
                marker=dict(size=[4]*(len(tail)-1) + [10]) # Highlight last point
            )
        )

    frames.append(go.Frame(
        data=frame_data,
        name=str(dates[i].date())
    ))

# ---------------------------
# INITIAL FRAME
# ---------------------------
init_data = []
for ticker in TICKERS:
    df = rrg[ticker].iloc[:TAIL_LENGTH]
    display_name = TICKER_NAMES.get(ticker, ticker)
    init_data.append(
        go.Scatter(
            x=df["RS_Ratio"],
            y=df["RS_Momentum"],
            mode="lines+markers",
            name=display_name,
            text=[f"{display_name}<br>{d.date()}" for d in df.index],
            hoverinfo="text+x+y",
            marker=dict(size=[4]*(len(df)-1) + [10])
        )
    )

# ---------------------------
# FIGURE
# ---------------------------
fig = go.Figure(
    data=init_data,
    frames=frames
                   
)
                 

# Quadrant lines
fig.add_vline(x=100, line_dash="dash", line_color="gray", line_width=1)
fig.add_hline(y=100, line_dash="dash", line_color="gray", line_width=1)

# Labels
fig.add_annotation(x=105, y=105, text="<b>LEADING</b>", showarrow=False, font=dict(color="green"))
fig.add_annotation(x=105, y=95, text="<b>WEAKENING</b>", showarrow=False, font=dict(color="orange"))
fig.add_annotation(x=95, y=95, text="<b>LAGGING</b>", showarrow=False, font=dict(color="red"))
fig.add_annotation(x=95, y=105, text="<b>IMPROVING</b>", showarrow=False, font=dict(color="blue"))

# Layout
fig.update_layout(
    title="Sector Relative Rotation Graph (RRG) - Animation",
    xaxis=dict(title="RS-Ratio", range=[90, 110], gridcolor='lightgray'),
    yaxis=dict(title="RS-Momentum", range=[90, 110], gridcolor='lightgray'),
    hovermode="closest",
    plot_bgcolor='white',
    paper_bgcolor='white',
    font=dict(color='black'),
    updatemenus=[{
        "type": "buttons",
        "showactive": False,
        "x": 0.1,
        "y": 0,
        "xanchor": "right",
        "yanchor": "top",
        "direction": "left",
        "pad": {"r": 10, "t": 87},
        "buttons": [
            {
                "label": "▶ Play",
                "method": "animate",
                "args": [None, {"frame": {"duration": 200, "redraw": True},
                                "fromcurrent": True, "transition": {"duration": 0}}]
            },
            {
                "label": "⏸ Pause",
                "method": "animate",
                "args": [[None], {"frame": {"duration": 0}, "mode": "immediate"}]
            }
        ]
    }],
    sliders=[{
        "active": 0,
        "yanchor": "top",
        "xanchor": "left",
        "currentvalue": {
            "font": {"size": 20},
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

        <div style="width: 100%; height: 700px;">
            {plotly_html}
        </div>

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

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

BASE_DIR = Path(__file__).resolve().parent

files = [
    BASE_DIR / "prices_round_2_day_-1.csv",
    BASE_DIR / "prices_round_2_day_0.csv",
    BASE_DIR / "prices_round_2_day_1.csv",
]

df = pd.concat([pd.read_csv(f, sep=";") for f in files])

df['global_time'] = df['day'] * 1_000_000 + df['timestamp']
df = df.sort_values('global_time')

products = df['product'].unique()

fig = make_subplots(rows=len(products), cols=1, shared_xaxes=True,
                   subplot_titles=products)

for i, product in enumerate(products, start=1):
    temp = df[df['product'] == product]
    
    fig.add_trace(
        go.Scatter(x=temp['global_time'], y=temp['mid_price'],
                   mode='lines', name=product),
        row=i, col=1
    )

# Add day separators
for d in df['day'].unique():
    fig.add_vline(x=d * 1_000_000, line_dash="dash", opacity=0.4)

fig.update_layout(height=700, title="Mid Prices Across Days")

out_file = BASE_DIR / "plot_mid_prices_round2.html"
fig.write_html(out_file)
print(f"Saved interactive plot: {out_file}")
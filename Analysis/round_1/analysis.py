from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import stats


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "analysis_outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

EARLY_FRACTION = 0.20
OBI_TOP_N = 3


@dataclass
class RegressionResult:
	product: str
	model_name: str
	intercept: float
	slope: float
	r2: float
	stderr: float
	equation: str


def load_price_data() -> pd.DataFrame:
	price_files = sorted(BASE_DIR.glob("prices_round_1_day_*.csv"))
	if not price_files:
		raise FileNotFoundError("No price files found in Analysis/round_1")

	frames: List[pd.DataFrame] = []
	for file in price_files:
		df = pd.read_csv(file, sep=";", engine="python")
		df["source_file"] = file.name
		frames.append(df)

	prices = pd.concat(frames, ignore_index=True)

	numeric_cols = [
		"day",
		"timestamp",
		"bid_price_1",
		"bid_volume_1",
		"bid_price_2",
		"bid_volume_2",
		"bid_price_3",
		"bid_volume_3",
		"ask_price_1",
		"ask_volume_1",
		"ask_price_2",
		"ask_volume_2",
		"ask_price_3",
		"ask_volume_3",
		"mid_price",
		"profit_and_loss",
	]
	for col in numeric_cols:
		if col in prices.columns:
			prices[col] = pd.to_numeric(prices[col], errors="coerce")

	prices = prices.sort_values(["product", "day", "timestamp"]).reset_index(drop=True)
	return prices


def load_trade_data() -> pd.DataFrame:
	trade_files = sorted(BASE_DIR.glob("trades_round_1_day_*.csv"))
	if not trade_files:
		raise FileNotFoundError("No trade files found in Analysis/round_1")

	frames: List[pd.DataFrame] = []
	for file in trade_files:
		df = pd.read_csv(file, sep=";", engine="python")
		df["source_file"] = file.name
		frames.append(df)

	trades = pd.concat(frames, ignore_index=True)
	for col in ["timestamp", "price", "quantity"]:
		if col in trades.columns:
			trades[col] = pd.to_numeric(trades[col], errors="coerce")

	if "symbol" in trades.columns:
		trades["product"] = trades["symbol"]

	trades = trades.sort_values(["product", "timestamp"]).reset_index(drop=True)
	return trades


def _level_sum(df: pd.DataFrame, prefix: str, kind: str, top_n: int) -> pd.Series:
	cols = [f"{prefix}_{kind}_{i}" for i in range(1, top_n + 1) if f"{prefix}_{kind}_{i}" in df.columns]
	if not cols:
		return pd.Series(0.0, index=df.index)
	return df[cols].fillna(0).sum(axis=1)


def add_microstructure_features(prices: pd.DataFrame) -> pd.DataFrame:
	df = prices.copy()

	bid_top = _level_sum(df, "bid", "volume", OBI_TOP_N)
	ask_top = _level_sum(df, "ask", "volume", OBI_TOP_N)
	top_total = bid_top + ask_top

	df["obi_top"] = np.where(top_total > 0, (bid_top - ask_top) / top_total, 0.0)
	df["depth_top"] = top_total

	df["spread_1"] = df["ask_price_1"] - df["bid_price_1"]
	df["microprice"] = np.where(
		(df["bid_volume_1"] + df["ask_volume_1"]) > 0,
		(df["ask_price_1"] * df["bid_volume_1"] + df["bid_price_1"] * df["ask_volume_1"])
		/ (df["bid_volume_1"] + df["ask_volume_1"]),
		df["mid_price"],
	)

	df["mid_return"] = df.groupby("product")["mid_price"].pct_change()
	df["next_mid_return"] = df.groupby("product")["mid_return"].shift(-1)
	df["rolling_vol_20"] = (
		df.groupby("product")["mid_return"]
		.rolling(20, min_periods=5)
		.std()
		.reset_index(level=0, drop=True)
	)

	def tag_period(group: pd.DataFrame) -> pd.Series:
		n = len(group)
		early_cut = max(1, int(n * EARLY_FRACTION))
		late_cut = int(n * 0.80)
		labels = np.array(["mid"] * n, dtype=object)
		labels[:early_cut] = "early"
		labels[late_cut:] = "late"
		return pd.Series(labels, index=group.index)

	df["session_period"] = df.groupby("product", group_keys=False).apply(tag_period)
	return df


def enrich_with_trade_flow(prices: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
	if trades.empty:
		out = prices.copy()
		out["trade_count"] = 0
		out["trade_qty"] = 0.0
		out["signed_trade_qty"] = 0.0
		return out

	# align trade price to nearest mid-price timestamp per product
	merge_prices = prices[["product", "timestamp", "mid_price"]].dropna().copy()
	merge_trades = trades[["product", "timestamp", "price", "quantity"]].dropna().copy()

	aligned_parts: List[pd.DataFrame] = []
	common_products = sorted(set(merge_trades["product"].dropna()) & set(merge_prices["product"].dropna()))

	for product in common_products:
		tr = merge_trades[merge_trades["product"] == product].sort_values("timestamp")
		pr = merge_prices[merge_prices["product"] == product].sort_values("timestamp")
		if tr.empty or pr.empty:
			continue
		aligned_p = pd.merge_asof(
			tr,
			pr[["timestamp", "mid_price"]],
			on="timestamp",
			direction="nearest",
			tolerance=100,
		)
		aligned_p["product"] = product
		aligned_parts.append(aligned_p)

	if aligned_parts:
		aligned = pd.concat(aligned_parts, ignore_index=True)
	else:
		aligned = pd.DataFrame(columns=["product", "timestamp", "price", "quantity", "mid_price"])
	aligned = aligned.dropna(subset=["mid_price"])
	aligned["direction"] = np.sign(aligned["price"] - aligned["mid_price"])
	aligned["signed_qty"] = aligned["direction"] * aligned["quantity"]

	agg = (
		aligned.groupby(["product", "timestamp"], as_index=False)
		.agg(
			trade_count=("quantity", "size"),
			trade_qty=("quantity", "sum"),
			signed_trade_qty=("signed_qty", "sum"),
			vwap=("price", lambda x: np.average(x, weights=aligned.loc[x.index, "quantity"])),
		)
	)

	out = prices.merge(agg, on=["product", "timestamp"], how="left")
	out["trade_count"] = out["trade_count"].fillna(0).astype(int)
	out["trade_qty"] = out["trade_qty"].fillna(0.0)
	out["signed_trade_qty"] = out["signed_trade_qty"].fillna(0.0)
	out["vwap"] = out["vwap"].fillna(out["mid_price"])
	return out


def fit_linear_and_robust_trend(df: pd.DataFrame, product: str) -> List[RegressionResult]:
	subset = df[df["product"] == product].dropna(subset=["timestamp", "mid_price"]).copy()
	if len(subset) < 10:
		return []

	x = subset["timestamp"].to_numpy(dtype=float)
	y = subset["mid_price"].to_numpy(dtype=float)

	# OLS via scipy linregress
	lr = stats.linregress(x, y)
	y_hat = lr.intercept + lr.slope * x
	ss_res = float(np.sum((y - y_hat) ** 2))
	ss_tot = float(np.sum((y - np.mean(y)) ** 2))
	r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

	# Robust Theil-Sen (median slope)
	ts_slope, ts_intercept, _, _ = stats.theilslopes(y, x, 0.95)
	y_hat_ts = ts_intercept + ts_slope * x
	ss_res_ts = float(np.sum((y - y_hat_ts) ** 2))
	r2_ts = 1 - ss_res_ts / ss_tot if ss_tot > 0 else 0.0

	return [
		RegressionResult(
			product=product,
			model_name="OLS",
			intercept=float(lr.intercept),
			slope=float(lr.slope),
			r2=float(r2),
			stderr=float(lr.stderr if lr.stderr is not None else 0.0),
			equation=f"mid_price(t) = {lr.intercept:.6f} + ({lr.slope:.8f}) * t + noise",
		),
		RegressionResult(
			product=product,
			model_name="Theil-Sen",
			intercept=float(ts_intercept),
			slope=float(ts_slope),
			r2=float(r2_ts),
			stderr=float(np.std(y - y_hat_ts)),
			equation=f"mid_price(t) = {ts_intercept:.6f} + ({ts_slope:.8f}) * t + robust_noise",
		),
	]


def fit_microstructure_return_model(df: pd.DataFrame, product: str) -> Dict[str, float]:
	subset = df[df["product"] == product].copy()
	cols = ["next_mid_return", "obi_top", "spread_1", "depth_top", "signed_trade_qty"]
	subset = subset[cols].dropna()
	if len(subset) < 20:
		return {"product": product, "samples": int(len(subset)), "r2": np.nan}

	y = subset["next_mid_return"].to_numpy(dtype=float)
	X = subset[["obi_top", "spread_1", "depth_top", "signed_trade_qty"]].to_numpy(dtype=float)
	X = np.column_stack([np.ones(len(X)), X])

	beta, *_ = np.linalg.lstsq(X, y, rcond=None)
	y_hat = X @ beta

	ss_res = float(np.sum((y - y_hat) ** 2))
	ss_tot = float(np.sum((y - np.mean(y)) ** 2))
	r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

	return {
		"product": product,
		"samples": int(len(subset)),
		"r2": float(r2),
		"beta_intercept": float(beta[0]),
		"beta_obi_top": float(beta[1]),
		"beta_spread_1": float(beta[2]),
		"beta_depth_top": float(beta[3]),
		"beta_signed_trade_qty": float(beta[4]),
	}


def build_interactive_plots(df: pd.DataFrame, regressions: List[RegressionResult]) -> None:
	products = sorted(df["product"].dropna().unique().tolist())
	fig = make_subplots(
		rows=len(products),
		cols=3,
		subplot_titles=[
			title
			for p in products
			for title in [f"{p}: Mid + Trend", f"{p}: OBI & Early Regime", f"{p}: OBI vs Next Return"]
		],
		vertical_spacing=0.06,
		horizontal_spacing=0.05,
	)

	for idx, product in enumerate(products, start=1):
		sub = df[df["product"] == product].copy()

		# 1) mid price + regression lines
		fig.add_trace(
			go.Scatter(x=sub["timestamp"], y=sub["mid_price"], mode="lines", name=f"{product} mid", showlegend=False),
			row=idx,
			col=1,
		)

		x = sub["timestamp"].to_numpy(dtype=float)
		for reg in [r for r in regressions if r.product == product]:
			y = reg.intercept + reg.slope * x
			fig.add_trace(
				go.Scatter(
					x=sub["timestamp"],
					y=y,
					mode="lines",
					name=f"{product} {reg.model_name}",
					line=dict(dash="dash" if reg.model_name == "OLS" else "dot"),
					showlegend=False,
				),
				row=idx,
				col=1,
			)

		# 2) OBI time series with early shading
		fig.add_trace(
			go.Scatter(x=sub["timestamp"], y=sub["obi_top"], mode="lines", name=f"{product} OBI", showlegend=False),
			row=idx,
			col=2,
		)

		early_cut_idx = max(1, int(len(sub) * EARLY_FRACTION))
		early_cut_ts = sub["timestamp"].iloc[min(early_cut_idx - 1, len(sub) - 1)]
		fig.add_vrect(
			x0=sub["timestamp"].min(),
			x1=early_cut_ts,
			fillcolor="LightSalmon",
			opacity=0.2,
			line_width=0,
			row=idx,
			col=2,
		)

		fig.add_hline(y=0.15, line_dash="dash", line_color="gray", row=idx, col=2)
		fig.add_hline(y=-0.15, line_dash="dash", line_color="gray", row=idx, col=2)

		# 3) OBI vs next return scatter
		scat = sub.dropna(subset=["obi_top", "next_mid_return"]).copy()
		fig.add_trace(
			go.Scatter(
				x=scat["obi_top"],
				y=scat["next_mid_return"],
				mode="markers",
				marker=dict(size=5, opacity=0.5),
				name=f"{product} scatter",
				showlegend=False,
			),
			row=idx,
			col=3,
		)

	fig.update_layout(
		height=max(500, 330 * len(products)),
		width=1700,
		title="Advanced Microstructure Analysis: Trend, OBI Regime, and Predictive Relationship",
		template="plotly_white",
	)

	fig.write_html(str(OUTPUT_DIR / "advanced_microstructure_dashboard.html"), include_plotlyjs="cdn")


def save_summary_tables(
	df: pd.DataFrame,
	trend_results: List[RegressionResult],
	micro_results: List[Dict[str, float]],
) -> None:
	# period summary
	period_summary = (
		df.groupby(["product", "session_period"], as_index=False)
		.agg(
			rows=("mid_price", "size"),
			mean_mid=("mid_price", "mean"),
			mid_volatility=("mid_return", "std"),
			mean_spread=("spread_1", "mean"),
			mean_depth=("depth_top", "mean"),
			mean_obi=("obi_top", "mean"),
			trade_qty=("trade_qty", "sum"),
			trade_count=("trade_count", "sum"),
		)
		.sort_values(["product", "session_period"])
	)
	period_summary.to_csv(OUTPUT_DIR / "period_summary.csv", index=False)

	trend_df = pd.DataFrame([r.__dict__ for r in trend_results])
	trend_df.to_csv(OUTPUT_DIR / "trend_regressions.csv", index=False)

	micro_df = pd.DataFrame(micro_results)
	micro_df.to_csv(OUTPUT_DIR / "microstructure_regressions.csv", index=False)

	# Human-readable markdown report
	lines = [
		"# Advanced Round 1 Analysis Report",
		"",
		"## Expected Function (Trend) by Product",
		"",
	]
	for _, row in trend_df.sort_values(["product", "model_name"]).iterrows():
		lines.append(f"- **{row['product']} [{row['model_name']}]**: `{row['equation']}`  ")
		lines.append(f"  - R² = {row['r2']:.6f}, slope stderr = {row['stderr']:.6f}")

	lines.extend([
		"",
		"## Microstructure Regression (next return ~ OBI + spread + depth + signed flow)",
		"",
	])
	for _, row in micro_df.sort_values("product").iterrows():
		lines.append(
			f"- **{row['product']}** samples={int(row['samples'])}, R²={row['r2']:.6f}, "
			f"β_obi={row.get('beta_obi_top', np.nan):.6f}, β_spread={row.get('beta_spread_1', np.nan):.6f}, "
			f"β_depth={row.get('beta_depth_top', np.nan):.6f}, β_signed_flow={row.get('beta_signed_trade_qty', np.nan):.6f}"
		)

	(OUTPUT_DIR / "analysis_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
	prices = load_price_data()
	trades = load_trade_data()

	features = add_microstructure_features(prices)
	enriched = enrich_with_trade_flow(features, trades)

	products = sorted(enriched["product"].dropna().unique().tolist())

	trend_results: List[RegressionResult] = []
	micro_results: List[Dict[str, float]] = []
	for product in products:
		trend_results.extend(fit_linear_and_robust_trend(enriched, product))
		micro_results.append(fit_microstructure_return_model(enriched, product))

	build_interactive_plots(enriched, trend_results)
	save_summary_tables(enriched, trend_results, micro_results)

	enriched.to_csv(OUTPUT_DIR / "enriched_prices_with_flow.csv", index=False)

	print("Done. Outputs generated in:", OUTPUT_DIR)
	print("- advanced_microstructure_dashboard.html")
	print("- analysis_report.md")
	print("- period_summary.csv")
	print("- trend_regressions.csv")
	print("- microstructure_regressions.csv")
	print("- enriched_prices_with_flow.csv")


if __name__ == "__main__":
	main()

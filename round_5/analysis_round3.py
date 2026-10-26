from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "ROUND_4"
OUT_DIR = BASE_DIR / "analysis_outputs"
OUT_DIR.mkdir(exist_ok=True)

PRICE_GLOB = "prices_round_4_day_*.csv"
UNDERLYINGS = ["HYDROGEL_PACK", "VELVETFRUIT_EXTRACT"]


def load_prices() -> pd.DataFrame:
    files = sorted(DATA_DIR.glob(PRICE_GLOB))
    if not files:
        raise FileNotFoundError(f"No files matching {PRICE_GLOB} under {DATA_DIR}")

    frames = []
    for fp in files:
        df = pd.read_csv(fp, sep=";", engine="python")
        df["source_file"] = fp.name
        frames.append(df)

    prices = pd.concat(frames, ignore_index=True)

    for c in [
        "day",
        "timestamp",
        "mid_price",
        "bid_price_1",
        "ask_price_1",
        "bid_volume_1",
        "ask_volume_1",
    ]:
        if c in prices.columns:
            prices[c] = pd.to_numeric(prices[c], errors="coerce")

    prices = prices.dropna(subset=["day", "timestamp", "product", "mid_price"]).copy()
    prices["day"] = prices["day"].astype(int)
    prices = prices.sort_values(["day", "timestamp", "product"]).reset_index(drop=True)

    max_ts = float(prices["timestamp"].max())
    day_offset = max_ts + 100.0
    prices["continuous_t"] = prices["day"] * day_offset + prices["timestamp"]

    prices["spread_1"] = prices["ask_price_1"] - prices["bid_price_1"]

    return prices


def day_axis_info(prices: pd.DataFrame) -> tuple[list[int], list[float], list[float], list[str]]:
    days = sorted(prices["day"].unique().tolist())
    min_ts = prices.groupby("day")["continuous_t"].min().to_dict()
    max_ts = prices.groupby("day")["continuous_t"].max().to_dict()

    centers = [(min_ts[d] + max_ts[d]) / 2.0 for d in days]
    separators = []
    for i in range(len(days) - 1):
        separators.append((max_ts[days[i]] + min_ts[days[i + 1]]) / 2.0)
    labels = [f"Day {d}" for d in days]
    return days, centers, separators, labels


def plot_underlyings(prices: pd.DataFrame) -> Path:
    sub = prices[prices["product"].isin(UNDERLYINGS)].copy()
    if sub.empty:
        raise ValueError("No underlying rows found for HYDROGEL_PACK/VELVETFRUIT_EXTRACT")

    days, centers, separators, labels = day_axis_info(sub)

    fig, axes = plt.subplots(2, 1, figsize=(15, 8), sharex=True)
    for i, prod in enumerate(UNDERLYINGS):
        p = sub[sub["product"] == prod]
        axes[i].plot(p["continuous_t"], p["mid_price"], lw=1.0)
        axes[i].set_title(f"{prod} mid_price (continuous 3-day timeline)")
        axes[i].set_ylabel("mid_price")
        axes[i].grid(alpha=0.25)

        for x in separators:
            axes[i].axvline(x, linestyle="--", color="gray", alpha=0.45)

    axes[-1].set_xticks(centers)
    axes[-1].set_xticklabels(labels)
    axes[-1].set_xlabel("Continuous time across 3 days")

    out = OUT_DIR / "continuous_underlyings.png"
    fig.tight_layout()
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def plot_vev(prices: pd.DataFrame) -> Path:
    vev = prices[prices["product"].str.startswith("VEV_", na=False)].copy()
    if vev.empty:
        raise ValueError("No VEV rows found")

    vev["strike"] = vev["product"].str.replace("VEV_", "", regex=False).astype(float)
    vev = vev.sort_values(["strike", "continuous_t"])

    days, centers, separators, labels = day_axis_info(vev)

    fig, ax = plt.subplots(figsize=(16, 7))
    for prod, g in vev.groupby("product"):
        ax.plot(g["continuous_t"], g["mid_price"], lw=0.9, alpha=0.9, label=prod)

    for x in separators:
        ax.axvline(x, linestyle="--", color="gray", alpha=0.4)

    ax.set_title("VEV voucher mid prices (continuous 3-day timeline)")
    ax.set_ylabel("voucher mid_price")
    ax.set_xticks(centers)
    ax.set_xticklabels(labels)
    ax.set_xlabel("Continuous time across 3 days")
    ax.grid(alpha=0.2)
    ax.legend(ncol=3, fontsize=8)

    out = OUT_DIR / "continuous_vev_all.png"
    fig.tight_layout()
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return out


def build_vev_valuation(prices: pd.DataFrame) -> tuple[Path, Path]:
    ve = prices[prices["product"] == "VELVETFRUIT_EXTRACT"][["day", "timestamp", "continuous_t", "mid_price"]].copy()
    ve = ve.rename(columns={"mid_price": "ve_mid"})

    vev = prices[prices["product"].str.startswith("VEV_", na=False)].copy()
    vev["strike"] = vev["product"].str.replace("VEV_", "", regex=False).astype(float)

    merged = vev.merge(
        ve,
        on=["day", "timestamp", "continuous_t"],
        how="left",
    )
    merged["intrinsic"] = np.maximum(merged["ve_mid"] - merged["strike"], 0.0)
    merged["time_value"] = merged["mid_price"] - merged["intrinsic"]

    stats = (
        merged.groupby(["product", "strike"], as_index=False)
        .agg(
            mean_mid=("mid_price", "mean"),
            mean_intrinsic=("intrinsic", "mean"),
            mean_time_value=("time_value", "mean"),
            min_time_value=("time_value", "min"),
            max_time_value=("time_value", "max"),
            mean_spread=("spread_1", "mean"),
        )
        .sort_values("strike")
        .reset_index(drop=True)
    )

    out_stats = OUT_DIR / "vev_valuation_stats.csv"
    stats.to_csv(out_stats, index=False)

    sample_out = OUT_DIR / "vev_valuation_sample.csv"
    merged.head(1000).to_csv(sample_out, index=False)

    return out_stats, sample_out


def main() -> None:
    prices = load_prices()

    out_u = plot_underlyings(prices)
    out_v = plot_vev(prices)
    out_stats, out_sample = build_vev_valuation(prices)

    print(f"Saved: {out_u}")
    print(f"Saved: {out_v}")
    print(f"Saved: {out_stats}")
    print(f"Saved: {out_sample}")


if __name__ == "__main__":
    main()

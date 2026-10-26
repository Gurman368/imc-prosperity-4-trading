from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm

########################################
# CONFIG
########################################

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "ROUND_3"

PRICE_GLOB = "prices_round_3_day_*.csv"
TRADE_GLOB = "trades_round_3_day_*.csv"

UNDERLYING = "VELVETFRUIT_EXTRACT"

OPTION_SYMBOLS = [
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500"
]

STEP = 20 # 🔥 SPEED CONTROL (increase to 50 if still slow)

########################################
# LOAD PRICES
########################################

def load_prices():
    files = sorted(DATA_DIR.glob(PRICE_GLOB))
    frames = [pd.read_csv(fp, sep=";") for fp in files]

    prices = pd.concat(frames, ignore_index=True)

    for c in ["day","timestamp","mid_price","bid_price_1","ask_price_1"]:
        if c in prices.columns:
            prices[c] = pd.to_numeric(prices[c], errors="coerce")

    prices = prices.dropna(subset=["day","timestamp","product","mid_price"])
    prices["day"] = prices["day"].astype(int)

    max_ts = prices["timestamp"].max()
    prices["continuous_t"] = prices["day"]*(max_ts+100) + prices["timestamp"]

    return prices.sort_values("continuous_t")

########################################
# LOAD TRADES
########################################

def load_trades():
    files = sorted(DATA_DIR.glob(TRADE_GLOB))
    if not files:
        return pd.DataFrame()

    frames = []

    for fp in files:
        df = pd.read_csv(fp, sep=";")

        try:
            day_val = int(fp.stem.split("_")[-1])
        except:
            day_val = 0

        df["day"] = day_val
        frames.append(df)

    trades = pd.concat(frames, ignore_index=True)
    trades.columns = [c.lower() for c in trades.columns]

    if "symbol" in trades.columns:
        trades = trades.rename(columns={"symbol": "product"})

    for c in ["timestamp","price","quantity"]:
        if c in trades.columns:
            trades[c] = pd.to_numeric(trades[c], errors="coerce")

    trades = trades.dropna(subset=["timestamp","product","price"])

    max_ts = trades["timestamp"].max()
    trades["continuous_t"] = trades["day"]*(max_ts+100) + trades["timestamp"]

    return trades.sort_values("continuous_t")

########################################
# BLACK-SCHOLES
########################################

def bs_call(S, K, T, sigma):
    if sigma <= 0:
        return max(S-K,0)

    d1 = (np.log(S/K)+0.5*sigma**2*T)/(sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)

    return S*norm.cdf(d1) - K*norm.cdf(d2)

def implied_vol(price, S, K, T):
    sigma = 0.2
    for _ in range(8):  # 🔥 reduced iterations
        d1 = (np.log(S/K)+0.5*sigma**2*T)/(sigma*np.sqrt(T))
        vega = S * norm.pdf(d1) * np.sqrt(T)
        if vega < 1e-6:
            break
        sigma -= (bs_call(S,K,T,sigma)-price)/vega
        sigma = max(sigma,1e-4)
    return sigma

########################################
# MAIN ANALYSIS
########################################

def run_analysis():

    prices = load_prices()
    trades = load_trades()

    grouped = {p:df.reset_index(drop=True) for p,df in prices.groupby("product")}

    underlying = grouped[UNDERLYING]
    S_series = underlying["mid_price"].values

    T = 2/365

    all_iv_dev = {sym:[] for sym in OPTION_SYMBOLS}
    all_price_dev = {sym:[] for sym in OPTION_SYMBOLS}
    all_market = {sym:[] for sym in OPTION_SYMBOLS}
    all_theo = {sym:[] for sym in OPTION_SYMBOLS}

    ########################################
    # FAST LOOP
    ########################################

    for i in range(0, len(underlying), STEP):

        S = S_series[i]

        ivs = []
        moneyness = []
        valid = []

        for sym in OPTION_SYMBOLS:

            if sym not in grouped:
                continue

            df = grouped[sym]
            if i >= len(df):
                continue

            price = df.loc[i,"mid_price"]

            # 🔥 skip useless options
            if price < 1:
                continue

            K = int(sym.split("_")[1])

            iv = implied_vol(price,S,K,T)

            ivs.append(iv)
            moneyness.append(np.log(K/S)/np.sqrt(T))
            valid.append(sym)

        if len(ivs) < 3:
            continue

        ivs = np.array(ivs)
        moneyness = np.array(moneyness)

        coeffs = np.polyfit(moneyness, ivs, 2)
        iv_hat = np.polyval(coeffs, moneyness)

        for j,sym in enumerate(valid):

            df = grouped[sym]
            price = df.loc[i,"mid_price"]
            K = int(sym.split("_")[1])

            theo = bs_call(S,K,T,iv_hat[j])

            all_iv_dev[sym].append(ivs[j]-iv_hat[j])
            all_price_dev[sym].append(price-theo)
            all_market[sym].append(price)
            all_theo[sym].append(theo)

    ########################################
    # PLOTS
    ########################################

    plt.figure()
    for sym in OPTION_SYMBOLS:
        if all_iv_dev[sym]:
            plt.plot(all_iv_dev[sym], label=sym)
    plt.title("IV Deviations")
    plt.legend()
    plt.show()

    plt.figure()
    for sym in OPTION_SYMBOLS:
        if all_price_dev[sym]:
            plt.plot(all_price_dev[sym], label=sym)
    plt.title("Price Deviations")
    plt.legend()
    plt.show()

    key = "VEV_5000"
    if all_market[key]:
        plt.figure()
        plt.plot(all_market[key], label="Market")
        plt.plot(all_theo[key], label="BS", linestyle="--")
        plt.legend()
        plt.title(key)
        plt.show()

        norm = np.array(all_market[key])/(np.array(all_theo[key])+1e-8)
        plt.figure()
        plt.plot(norm)
        plt.axhline(1, linestyle="--")
        plt.title("Normalized Price")
        plt.show()

    ########################################
    # AUTOCORR
    ########################################

    returns = np.diff(S_series)

    def autocorr(x):
        if len(x) < 2:
            return 0
        return np.corrcoef(x[:-1],x[1:])[0,1]

    ac = [autocorr(returns[i-100:i]) if i>100 else 0 for i in range(len(returns))]

    plt.figure()
    plt.plot(ac)
    plt.title("Underlying Autocorrelation")
    plt.show()

    ########################################
    # TRADE ANALYSIS
    ########################################

    if not trades.empty:

        merged = pd.merge_asof(
            trades.sort_values("continuous_t"),
            prices.sort_values("continuous_t"),
            left_on="continuous_t",
            right_on="continuous_t",
            by="product",
            direction="backward"
        )

        merged = merged.dropna(subset=["mid_price"])

        merged["impact"] = merged["mid_price"].shift(-1) - merged["mid_price"]
        merged["sign"] = np.sign(merged["price"] - merged["mid_price"])

        # 🔥 ALIGN PROPERLY
        df_corr = merged[["sign", "impact"]].dropna()

        if len(df_corr) > 10:
            corr = np.corrcoef(df_corr["sign"], df_corr["impact"])[0,1]
            print("🔥 Trade impact correlation:", corr)
        else:
            print("⚠️ Not enough data for correlation")

            print("🔥 Trade impact correlation:", corr)

########################################
# RUN
########################################

if __name__ == "__main__":
    run_analysis()
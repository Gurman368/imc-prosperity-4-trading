# run this in jupyter or standalone — needs your backtest data CSVs
import pandas as pd
import numpy as np
import math
from statistics import NormalDist
import matplotlib.pyplot as plt

_N = NormalDist()

def bs_call(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _N.cdf(d1) - K * _N.cdf(d2)

def bs_vega(S, K, T, sigma):
    if T <= 0 or sigma <= 0:
        return 1e-8
    d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    return S * _N.pdf(d1) * math.sqrt(T)

def implied_vol(S, K, T, price):
    intrinsic = max(0.0, S - K)
    if price <= intrinsic + 1e-6:
        return None
    sigma = 0.25
    for _ in range(50):
        p  = bs_call(S, K, T, sigma)
        v  = bs_vega(S, K, T, sigma)
        if abs(p - price) < 1e-4:
            return sigma
        if v < 1e-8:
            break
        sigma -= (p - price) / v
        sigma  = max(0.005, min(sigma, 10.0))
    return None

# -----------------------------------------------
# LOAD YOUR DATA — adjust paths as needed
# -----------------------------------------------
# Expected columns: timestamp, product, bid_price_1, ask_price_1
# You'll need the underlying and each option strike
DATA_PATH = "c:/Users/rajy7/OneDrive/Documents/GitHub/Imc_prosperity4_ISI_BSDS/backtest/data/"

# Load prices — adapt to your actual file structure
# This assumes prosperity4bt data format
prices = {}
for day in [0, 1, 2]:
    df = pd.read_csv(f"{DATA_PATH}prices_round_3_day_{day}.csv", sep=";")
    prices[day] = df

T      = 0.1
STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]

# -----------------------------------------------
# TEST 1: Vol smile shape — does a parabola fit IV vs moneyness?
# -----------------------------------------------
all_ms  = []
all_ivs = []
all_devs = []   # IV - smile(m) for each strike/tick

for day, df in prices.items():
    underlying = df[df["product"] == "VELVETFRUIT_EXTRACT"].copy()
    underlying["mid"] = (underlying["bid_price_1"] + underlying["ask_price_1"]) / 2

    for _, row in underlying.iterrows():
        ts = row["timestamp"]
        S  = row["mid"]
        if pd.isna(S):
            continue

        tick_ivs = []
        for K in STRIKES:
            sym = f"VEV_{K}"
            opt_rows = df[(df["product"] == sym) & (df["timestamp"] == ts)]
            if opt_rows.empty:
                continue
            opt_row = opt_rows.iloc[0]
            bid = opt_row.get("bid_price_1", np.nan)
            ask = opt_row.get("ask_price_1", np.nan)
            if pd.isna(bid) or pd.isna(ask):
                continue
            mid   = (bid + ask) / 2
            if mid < 5:
                continue
            if (ask - bid) > 20:
                continue
            iv = implied_vol(S, K, T, mid)
            if iv is None or iv < 0.01 or iv > 5:
                continue
            m = math.log(S / K)
            tick_ivs.append((m, iv, K))

        if len(tick_ivs) < 3:
            continue

        ms_t  = np.array([x[0] for x in tick_ivs])
        ivs_t = np.array([x[1] for x in tick_ivs])

        try:
            coeffs = np.polyfit(ms_t, ivs_t, 2)
        except:
            continue

        for m, iv, K in tick_ivs:
            smile_iv = coeffs[0]*m**2 + coeffs[1]*m + coeffs[2]
            all_ms.append(m)
            all_ivs.append(iv)
            all_devs.append(iv - smile_iv)

print("=== TEST 1: Vol Smile ===")
print(f"Points collected: {len(all_ms)}")
if all_ms:
    print(f"IV range: {np.min(all_ivs):.4f} to {np.max(all_ivs):.4f}")
    print(f"IV deviation (iv - smile) mean: {np.mean(all_devs):.4f}")
    print(f"IV deviation std: {np.std(all_devs):.4f}")
    print(f"Abs deviation > 0.02: {np.mean(np.abs(all_devs) > 0.02)*100:.1f}% of ticks")

# -----------------------------------------------
# TEST 2: Price deviation autocorrelation
# Does price_dev mean revert? (1-lag negative autocorrelation)
# This is exactly what the writeup validates
# -----------------------------------------------
print("\n=== TEST 2: Price Deviation Autocorrelation by Strike ===")

for K in [5000, 5100, 5200, 5300, 5400]:
    devs_by_strike = []
    for day, df in prices.items():
        underlying = df[df["product"] == "VELVETFRUIT_EXTRACT"].copy()
        underlying["mid"] = (underlying["bid_price_1"] + underlying["ask_price_1"]) / 2
        und_dict = dict(zip(underlying["timestamp"], underlying["mid"]))

        sym     = f"VEV_{K}"
        opt_df  = df[df["product"] == sym].copy()
        opt_df["mid"] = (opt_df["bid_price_1"] + opt_df["ask_price_1"]) / 2

        for _, row in opt_df.iterrows():
            ts  = row["timestamp"]
            S   = und_dict.get(ts)
            mid = row["mid"]
            if S is None or pd.isna(mid) or mid < 5:
                continue
            if (row["ask_price_1"] - row["bid_price_1"]) > 20:
                continue

            # Quick flat-vol theo price for deviation calc
            iv = implied_vol(S, K, T, mid)
            if iv is None:
                continue
            theo = bs_call(S, K, T, 0.25)   # flat vol baseline
            devs_by_strike.append(mid - theo)

    if len(devs_by_strike) < 50:
        print(f"VEV_{K}: insufficient data ({len(devs_by_strike)} pts)")
        continue

    series = np.array(devs_by_strike)
    lag1_ac = np.corrcoef(series[:-1], series[1:])[0, 1]
    print(f"VEV_{K}: n={len(series)}, lag-1 autocorr={lag1_ac:.4f} "
          f"{'<-- MEAN REVERTS' if lag1_ac < -0.05 else ''}")

# -----------------------------------------------
# TEST 3: EMA mean reversion on underlying
# Find optimal EMA alpha and threshold
# -----------------------------------------------
print("\n=== TEST 3: EMA Mean Reversion Calibration ===")

best_pnl   = -np.inf
best_alpha = None
best_thr   = None

for alpha in [0.05, 0.08, 0.1, 0.15, 0.2]:
    for thr in [5, 8, 10, 15, 20]:
        total_pnl = 0
        for day, df in prices.items():
            und = df[df["product"] == "VELVETFRUIT_EXTRACT"].copy()
            und["mid"] = (und["bid_price_1"] + und["ask_price_1"]) / 2
            und = und.dropna(subset=["mid"]).reset_index(drop=True)

            if len(und) < 10:
                continue

            ema = float(und["mid"].iloc[0])
            pos = 0
            pnl = 0

            for i in range(1, len(und)):
                S   = float(und["mid"].iloc[i])
                ema = alpha * S + (1 - alpha) * ema
                dev = S - ema

                prev_pos = pos
                if dev > thr and pos > -20:
                    pos = max(pos - 2, -20)
                elif dev < -thr and pos < 20:
                    pos = min(pos + 2, 20)

                # PnL from position change (simplified: next tick exit)
                if i < len(und) - 1:
                    next_S = float(und["mid"].iloc[i + 1])
                    pnl   += (pos - prev_pos) * (next_S - S)

            # Unwind final position at last price
            last_S = float(und["mid"].iloc[-1])
            pnl   += -pos * last_S   # simplified closeout
            total_pnl += pnl

        if total_pnl > best_pnl:
            best_pnl   = total_pnl
            best_alpha = alpha
            best_thr   = thr

print(f"Best alpha={best_alpha}, threshold={best_thr}, PnL={best_pnl:.0f}")
print(f"Suggested params: o_mr_ema_alpha={best_alpha}, o_mr_threshold={best_thr}")

# -----------------------------------------------
# TEST 4: Smile edge threshold calibration
# What price deviation threshold maximises signal quality?
# -----------------------------------------------
print("\n=== TEST 4: Smile Edge Threshold vs Signal Quality ===")

for edge_thr in [2, 3, 4, 5, 6, 8]:
    fires   = 0
    correct = 0  # deviation reverted next tick
    for day, df in prices.items():
        underlying = df[df["product"] == "VELVETFRUIT_EXTRACT"].copy()
        underlying["mid"] = (underlying["bid_price_1"] + underlying["ask_price_1"]) / 2
        und_dict = dict(zip(underlying["timestamp"], underlying["mid"]))
        timestamps = sorted(und_dict.keys())

        for K in [5100, 5200, 5300]:
            sym    = f"VEV_{K}"
            opt_df = df[df["product"] == sym].copy()
            opt_df["mid"] = (opt_df["bid_price_1"] + opt_df["ask_price_1"]) / 2
            opt_ts = dict(zip(opt_df["timestamp"], opt_df["mid"]))

            for idx, ts in enumerate(timestamps[:-1]):
                S   = und_dict.get(ts)
                mid = opt_ts.get(ts)
                if S is None or mid is None or mid < 5:
                    continue

                # Smile vol (simplified: use flat 0.25 as proxy for test)
                theo = bs_call(S, K, T, 0.25)
                dev  = mid - theo

                if abs(dev) > edge_thr:
                    fires += 1
                    next_ts  = timestamps[idx + 1]
                    next_mid = opt_ts.get(next_ts)
                    next_S   = und_dict.get(next_ts)
                    if next_mid is None or next_S is None:
                        continue
                    next_theo = bs_call(next_S, K, T, 0.25)
                    next_dev  = next_mid - next_theo
                    # Correct if deviation moved toward zero
                    if abs(next_dev) < abs(dev):
                        correct += 1

    hit_rate = correct / fires if fires > 0 else 0
    print(f"Edge={edge_thr:2d}: fires={fires:5d}, "
          f"next-tick reversion rate={hit_rate:.3f}")
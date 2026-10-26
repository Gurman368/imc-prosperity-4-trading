import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from statsmodels.tsa.stattools import adfuller, coint

# =========================
# 1. LOAD DATA
# =========================

def load_price_data():
    files = [
        "C:\\Users\\rajy7\\OneDrive\\Documents\\GitHub\\Imc_prosperity4_ISI_BSDS\\round_3\\ROUND_3\\prices_round_3_day_0.csv",
        "C:\\Users\\rajy7\\OneDrive\\Documents\\GitHub\\Imc_prosperity4_ISI_BSDS\\round_3\\ROUND_3\\prices_round_3_day_1.csv",
        "C:\\Users\\rajy7\\OneDrive\\Documents\\GitHub\\Imc_prosperity4_ISI_BSDS\\round_3\\ROUND_3\\prices_round_3_day_2.csv"
    ]
    
    dfs = []
    offset = 0
    
    for file in files:
        df = pd.read_csv(file, sep=';')
        df['global_time'] = df['timestamp'] + offset
        offset += df['timestamp'].max() + 1
        dfs.append(df)
    
    return pd.concat(dfs).reset_index(drop=True)


def compute_mid_price(df):
    df['mid_price'] = (df['bid_price_1'] + df['ask_price_1']) / 2
    return df


def get_series(df, product):
    temp = df[df['product'] == product].copy()
    temp = temp.sort_values('global_time')
    return temp[['global_time', 'mid_price']].set_index('global_time')


# =========================
# 2. PAIR ANALYSIS
# =========================

def analyze_pair(h, f):
    df = h.join(f, how='inner', lsuffix='_H', rsuffix='_F')
    
    corr = df['mid_price_H'].corr(df['mid_price_F'])
    coint_p = coint(df['mid_price_H'], df['mid_price_F'])[1]
    
    beta = np.polyfit(df['mid_price_F'], df['mid_price_H'], 1)[0]
    df['spread'] = df['mid_price_H'] - beta * df['mid_price_F']
    
    adf_p = adfuller(df['spread'])[1]
    
    # Half-life
    lag = df['spread'].shift(1)
    ret = df['spread'] - lag
    lag, ret = lag.dropna(), ret.dropna()
    alpha = np.polyfit(lag, ret, 1)[0]
    half_life = -np.log(2)/alpha if alpha < 0 else np.inf
    
    # Rolling Z-score
    window = 500
    df['mean'] = df['spread'].rolling(window).mean()
    df['std'] = df['spread'].rolling(window).std()
    df['z'] = (df['spread'] - df['mean']) / df['std']
    
    print("\n=== PAIR ANALYSIS ===")
    print("Correlation:", corr)
    print("Cointegration p:", coint_p)
    print("ADF p:", adf_p)
    print("Beta:", beta)
    print("Half-life:", half_life)
    
    plt.figure(figsize=(12,5))
    plt.plot(df['z'])
    plt.axhline(2, linestyle='--')
    plt.axhline(-2, linestyle='--')
    plt.title("Z-score")
    plt.show()
    
    return df


# =========================
# 3. VEV ANALYSIS
# =========================

def analyze_vev(df):
    vev_products = sorted([p for p in df['product'].unique() if 'VEV_' in p])
    vev_data = {p: get_series(df, p) for p in vev_products}
    
    vev_df = pd.concat(vev_data.values(), axis=1)
    vev_df.columns = vev_products
    vev_df = vev_df.dropna()
    
    print("\n=== VEV MONOTONICITY ===")
    mono_viol = 0
    for i in range(len(vev_products)-1):
        v = (vev_df[vev_products[i]] < vev_df[vev_products[i+1]]).sum()
        print(f"{vev_products[i]} < {vev_products[i+1]}:", v)
        mono_viol += v
    
    print("Total:", mono_viol)
    
    print("\n=== VEV BUTTERFLY ===")
    bf_viol = 0
    for i in range(1, len(vev_products)-1):
        b = vev_df[vev_products[i-1]] - 2*vev_df[vev_products[i]] + vev_df[vev_products[i+1]]
        v = (b < 0).sum()
        print(f"{vev_products[i-1]}, {vev_products[i]}, {vev_products[i+1]}:", v)
        bf_viol += v
    
    print("Total:", bf_viol)
    
    return vev_df


# =========================
# 4. LEAD-LAG
# =========================

def lead_lag(s1, s2, name1, name2, max_lag=300):
    lags = range(-max_lag, max_lag)
    corrs = []
    
    for lag in lags:
        corrs.append(s1.corr(s2.shift(lag)))
    
    corrs = np.array(corrs)
    idx = np.argmax(np.abs(corrs))
    
    print(f"\n=== LEAD-LAG {name1} vs {name2} ===")
    print("Best lag:", lags[idx])
    print("Correlation:", corrs[idx])


# =========================
# 5. SIGNAL QUALITY
# =========================

def signal_quality(df):
    df['future_spread'] = df['spread'].shift(-50)
    df['ret'] = df['future_spread'] - df['spread']
    
    corr = df['z'].corr(df['ret'])
    print("\nSignal quality:", corr)


# =========================
# 6. ROLLING ADF
# =========================

def rolling_adf(spread, window=1000):
    pvals = []
    
    for i in range(window, len(spread)):
        pvals.append(adfuller(spread[i-window:i])[1])
    
    plt.plot(pvals)
    plt.axhline(0.05, linestyle='--')
    plt.title("Rolling ADF")
    plt.show()


# =========================
# 7. VEV PREDICTIVE POWER
# =========================

def vev_signal_test(hydrogel, vev_df):
    combined = hydrogel.join(vev_df, how='inner')
    
    combined['future_h'] = combined['mid_price'].shift(-50)
    combined['ret'] = combined['future_h'] - combined['mid_price']
    
    corr = combined['VEV_5000'].corr(combined['ret'])
    print("\nVEV predictive power:", corr)


# =========================
# 8. VOLATILITY
# =========================

def volatility(series):
    vol = series.pct_change().rolling(200).std()
    
    plt.plot(vol)
    plt.title("Volatility")
    plt.show()


# =========================
# MAIN
# =========================

def main():
    df = load_price_data()
    df = compute_mid_price(df)
    
    hydrogel = get_series(df, "HYDROGEL_PACK")
    fruit = get_series(df, "VELVETFRUIT_EXTRACT")
    
    pair_df = analyze_pair(hydrogel, fruit)
    vev_df = analyze_vev(df)
    
    # Lead-lag
    lead_lag(pair_df['mid_price_H'], pair_df['mid_price_F'], "HYDROGEL", "FRUIT")
    lead_lag(pair_df['mid_price_H'], vev_df['VEV_5000'], "HYDROGEL", "VEV_5000")
    
    # Signal quality
    signal_quality(pair_df)
    
    # Rolling ADF
    rolling_adf(pair_df['spread'].values[::10])
    
    # VEV signal
    vev_signal_test(hydrogel, vev_df)
    
    # Volatility
    volatility(pair_df['mid_price_H'])


if __name__ == "__main__":
    main()
"""
debug_options.py
================
Drop this in your backtest folder and run:

    python debug_options.py

It replays your backtest data and prints per-strike stats:
  • actual market mid vs our anchor at each trade
  • whether we bought or sold and at what price
  • running PnL per strike
  • anchor drift over time

Usage:
    python debug_options.py --data <path_to_data_folder> --day <0|1|2>

Example:
    python debug_options.py --data backtest/data --day 1
"""

import argparse
import json
import math
import os
import csv
from statistics import NormalDist
from collections import defaultdict

_N = NormalDist()

# ── Config (must match your trader) ───────────────────────────────────
OPTION_SYMBOLS = [
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500"
]
FOCUS_STRIKES = ["VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400"]  # the losers

ANCHORS = {
    "VEV_4000": 1255, "VEV_4500": 752,
    "VEV_5000": 255,  "VEV_5100": 167,
    "VEV_5200": 96,   "VEV_5300": 47,
    "VEV_5400": 16,   "VEV_5500": 7,
    "VEV_6000": 1,    "VEV_6500": 1,
}
DEV_FULL_MAP = {
    "VEV_4000": 25, "VEV_4500": 25,
    "VEV_5000": 25, "VEV_5100": 40,
    "VEV_5200": 50, "VEV_5300": 50,
    "VEV_5400": 40, "VEV_5500": 20,
    "VEV_6000": 1,  "VEV_6500": 1,
}
EMA_ALPHA = 0.003
K         = 0.015
MAX_STEP  = 3
LIMIT     = 300

def bs_call(S, K_strike, T=0.01, sigma=0.1):
    if T <= 0:
        return max(0, S - K_strike)
    d1 = (math.log(S / K_strike) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _N.cdf(d1) - K_strike * _N.cdf(d2)

def find_data_file(data_dir, round_num, day_num):
    """Try common prosperity4bt data file naming conventions."""
    patterns = [
        f"round{round_num}_day{day_num}.csv",
        f"round{round_num}/day{day_num}.csv",
        f"round{round_num}_{day_num}.csv",
        f"prices_round_{round_num}_day_{day_num}.csv",
        f"round{round_num}/prices_round_{round_num}_day_{day_num}.csv",
    ]
    for p in patterns:
        path = os.path.join(data_dir, p)
        if os.path.exists(path):
            return path
    # Search recursively
    for root, dirs, files in os.walk(data_dir):
        for f in files:
            if f.endswith(".csv") and f"day_{day_num}" in f and f"round_{round_num}" in f:
                return os.path.join(root, f)
            if f.endswith(".csv") and f"day{day_num}" in f and f"round{round_num}" in f:
                return os.path.join(root, f)
    return None

def run_debug(data_dir, round_num, day_num):
    path = find_data_file(data_dir, round_num, day_num)
    if path is None:
        # List what's available
        print(f"Could not find data file for round {round_num} day {day_num}")
        print("Files found in data dir:")
        for root, dirs, files in os.walk(data_dir):
            for f in files:
                if f.endswith(".csv"):
                    print(f"  {os.path.join(root, f)}")
        return

    print(f"Reading: {path}\n")

    # ── Parse CSV ─────────────────────────────────────────────────────
    # Detect columns
    with open(path, newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)

    if not rows:
        print("Empty file")
        return

    print(f"Columns: {list(rows[0].keys())}")
    print(f"Total rows: {len(rows)}\n")

    # ── Simulate anchor EMA and trades per strike ──────────────────────
    anchors  = {s: ANCHORS.get(s, 100) for s in OPTION_SYMBOLS}
    positions = {s: 0 for s in OPTION_SYMBOLS}
    pnl       = {s: 0.0 for s in OPTION_SYMBOLS}
    cash      = {s: 0.0 for s in OPTION_SYMBOLS}
    trade_log = defaultdict(list)  # sym -> list of (ts, side, price, qty, anchor, mid, dev)

    underlying_mid = None

    for row in rows:
        product = row.get("product", row.get("symbol", ""))
        if not product:
            continue

        ts = int(row.get("timestamp", 0))

        # Parse bid/ask
        try:
            bid = float(row.get("bid_price_1", row.get("best_bid", 0)) or 0)
            ask = float(row.get("ask_price_1", row.get("best_ask", 0)) or 0)
        except:
            continue

        if bid <= 0 or ask <= 0:
            continue

        mid = (bid + ask) / 2

        # Track underlying
        if product == "VELVETFRUIT_EXTRACT":
            underlying_mid = mid
            continue

        if product not in OPTION_SYMBOLS:
            continue

        # Update anchor EMA
        ema_alpha = 0.005 if product in ["VEV_4000", "VEV_4500"] else EMA_ALPHA
        anchors[product] = anchors[product] + ema_alpha * (mid - anchors[product])
        anchor = anchors[product]

        dev      = mid - anchor
        dev_full = DEV_FULL_MAP.get(product, 40)
        threshold = 0.5 * K * dev_full
        pos = positions[product]

        if abs(dev) <= threshold:
            target = 0
        else:
            effective_dev = abs(dev) - threshold
            scaled = int(LIMIT * effective_dev / dev_full)
            scaled = min(LIMIT, scaled)
            target = -scaled if dev > 0 else scaled

        delta = target - pos
        delta = max(-MAX_STEP, min(MAX_STEP, delta))

        # Simulate execution
        if delta > 0 and ask > 0:
            # Buy at ask (worst case)
            qty = min(delta, LIMIT - pos)
            if qty > 0:
                positions[product] += qty
                cash[product] -= ask * qty
                pnl[product] = cash[product] + positions[product] * mid
                if product in FOCUS_STRIKES:
                    trade_log[product].append({
                        "ts": ts, "side": "BUY", "price": ask,
                        "qty": qty, "anchor": round(anchor, 2),
                        "mid": round(mid, 2), "dev": round(dev, 2),
                        "pos_after": positions[product],
                        "pnl": round(pnl[product], 0)
                    })

        elif delta < 0 and bid > 0:
            # Sell at bid (worst case)
            qty = min(-delta, LIMIT + pos)
            if qty > 0:
                positions[product] -= qty
                cash[product] += bid * qty
                pnl[product] = cash[product] + positions[product] * mid
                if product in FOCUS_STRIKES:
                    trade_log[product].append({
                        "ts": ts, "side": "SELL", "price": bid,
                        "qty": qty, "anchor": round(anchor, 2),
                        "mid": round(mid, 2), "dev": round(dev, 2),
                        "pos_after": positions[product],
                        "pnl": round(pnl[product], 0)
                    })

        # Mark-to-market
        pnl[product] = cash[product] + positions[product] * mid

    # ── Print summary ─────────────────────────────────────────────────
    print("=" * 70)
    print(f"FINAL PnL SIMULATION (round {round_num} day {day_num})")
    print("=" * 70)
    for sym in OPTION_SYMBOLS:
        marker = " ← LOSER" if pnl[sym] < -5000 else ""
        print(f"  {sym:12s}  PnL: {pnl[sym]:>12,.0f}   pos: {positions[sym]:>5d}   anchor: {anchors[sym]:.2f}{marker}")

    print()
    print("=" * 70)
    print("TRADE ANALYSIS — FOCUS STRIKES (first 20 trades each)")
    print("=" * 70)

    for sym in FOCUS_STRIKES:
        trades = trade_log[sym]
        if not trades:
            print(f"\n{sym}: NO TRADES")
            continue

        print(f"\n{sym}  ({len(trades)} total trades)")
        print(f"  {'TS':>8}  {'SIDE':>5}  {'PRICE':>8}  {'ANCHOR':>8}  {'DEV':>8}  {'POS':>5}  {'PNL':>10}")
        print(f"  {'-'*8}  {'-'*5}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*5}  {'-'*10}")

        for t in trades[:20]:
            print(f"  {t['ts']:>8}  {t['side']:>5}  {t['price']:>8.2f}  "
                  f"{t['anchor']:>8.2f}  {t['dev']:>8.2f}  "
                  f"{t['pos_after']:>5d}  {t['pnl']:>10,.0f}")

        # Pattern analysis
        buys  = [t for t in trades if t["side"] == "BUY"]
        sells = [t for t in trades if t["side"] == "SELL"]

        if buys:
            avg_buy_dev  = sum(t["dev"] for t in buys)  / len(buys)
            avg_buy_price = sum(t["price"] for t in buys) / len(buys)
        else:
            avg_buy_dev = avg_buy_price = 0

        if sells:
            avg_sell_dev  = sum(t["dev"] for t in sells) / len(sells)
            avg_sell_price = sum(t["price"] for t in sells) / len(sells)
        else:
            avg_sell_dev = avg_sell_price = 0

        print(f"\n  PATTERN:")
        print(f"    Buys:  {len(buys):>4}  avg_price={avg_buy_price:.2f}  avg_dev_at_buy={avg_buy_dev:.3f}")
        print(f"    Sells: {len(sells):>4}  avg_price={avg_sell_price:.2f}  avg_dev_at_sell={avg_sell_dev:.3f}")

        if buys and sells:
            spread_captured = avg_sell_price - avg_buy_price
            print(f"    Avg sell - avg buy price = {spread_captured:.2f}")
            if spread_captured < 0:
                print(f"    *** BUYING HIGH SELLING LOW — anchor is inverted/lagging ***")
            else:
                print(f"    *** Spread looks ok — problem may be in sizing or position accumulation ***")
        elif buys and not sells:
            print(f"    *** ONLY BUYING — stuck long, no exits ***")
        elif sells and not buys:
            print(f"    *** ONLY SELLING — stuck short, no exits ***")

        # Anchor vs actual price at end
        final_anchor = anchors[sym]
        final_trades = trades[-1] if trades else None
        if final_trades:
            print(f"    Final anchor={final_anchor:.2f}  last_mid={final_trades['mid']:.2f}  "
                  f"drift={final_trades['mid']-final_anchor:.2f}")

    print("\n" + "=" * 70)
    print("DIAGNOSIS GUIDE:")
    print("  • 'BUYING HIGH SELLING LOW' → anchor too slow, always behind actual price")
    print("  • 'ONLY BUYING / ONLY SELLING' → anchor stuck on wrong side of market")  
    print("  • Large 'drift' at end → EMA_ALPHA too small, anchor never reached fair price")
    print("  • avg_dev_at_buy negative but buying → threshold too small, noise trades")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="backtest/data", help="Path to data folder")
    parser.add_argument("--round", type=int, default=4, help="Round number")
    parser.add_argument("--day",   type=int, default=1, help="Day number (1, 2, or 3)")
    args = parser.parse_args()

    run_debug(args.data, args.round, args.day)
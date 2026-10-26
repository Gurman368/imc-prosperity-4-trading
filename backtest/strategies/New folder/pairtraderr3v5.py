from datamodel import OrderDepth, TradingState, Order
import json
import math
import numpy as np
from statistics import NormalDist

_N = NormalDist()

# =========================
# PRODUCTS
# =========================
STATIC_SYMBOL            = "HYDROGEL_PACK"
DYNAMIC_SYMBOL           = "VELVETFRUIT_EXTRACT"
OPTION_UNDERLYING_SYMBOL = "VELVETFRUIT_EXTRACT"

OPTION_SYMBOLS = [
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500"
]

FLOW_GATE_STRIKES = ["VEV_5200", "VEV_5300"]

POS_LIMITS = {
    STATIC_SYMBOL: 200,
    DYNAMIC_SYMBOL: 200,
    OPTION_UNDERLYING_SYMBOL: 300,
    **{os: 300 for os in OPTION_SYMBOLS},
}

try:
    import prosperity4bt.runner as _p4_runner
    for product, limit in POS_LIMITS.items():
        _p4_runner.LIMITS[product] = limit
except Exception:
    pass

LONG, NEUTRAL, SHORT = 1, 0, -1


# =========================
# BASE CLASS (UNCHANGED)
# =========================
class ProductTrader:

    def __init__(self, name, state, prints, new_trader_data):
        self.orders = []
        self.name = name
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data
        self.last_traderData = self.get_last_traderData()
        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0)
        self.mkt_buy_orders, self.mkt_sell_orders = self.get_order_depth()
        self.best_bid = max(self.mkt_buy_orders) if self.mkt_buy_orders else None
        self.best_ask = min(self.mkt_sell_orders) if self.mkt_sell_orders else None
        self.mid = None
        if self.best_bid and self.best_ask:
            self.mid = (self.best_bid + self.best_ask) / 2

    def get_last_traderData(self):
        try:
            return json.loads(self.state.traderData) if self.state.traderData else {}
        except:
            return {}

    def get_order_depth(self):
        depth = self.state.order_depths.get(self.name)
        if depth is None:
            return {}, {}
        return depth.buy_orders, depth.sell_orders

    def buy(self, price, volume):
        self.orders.append(Order(self.name, int(price), int(volume)))

    def sell(self, price, volume):
        self.orders.append(Order(self.name, int(price), -int(volume)))


# =========================
# FLOW GATE
# Only trade VEV directionally when the informed bot
# is active — proxied by tight 5200 AND 5300 spreads.
# =========================
def flow_gate_open(state):
    for strike in FLOW_GATE_STRIKES:
        depth = state.order_depths.get(strike)
        if depth is None:
            return False
        bids = depth.buy_orders
        asks = depth.sell_orders
        if not bids or not asks:
            return False
        # Gate: both spreads must be at or below 2 ticks
        if (min(asks) - max(bids)) > 2:
            return False
    return True


# =========================
# HYDROGEL
# Pure inventory-skewed market making.
# VWAP fair value, two-level quotes, take stale orders.
# =========================
class HydroTrader(ProductTrader):

    def get_orders(self):
        if self.mid is None:
            return {self.name: self.orders}

        def vwap(levels, n=3):
            top = sorted(levels.items(), key=lambda x: -x[0])[:n]
            total_v = sum(abs(v) for _, v in top)
            if total_v == 0:
                return None
            return sum(p * abs(v) for p, v in top) / total_v

        bid_vwap = vwap(self.mkt_buy_orders)
        ask_vwap = vwap(self.mkt_sell_orders)
        if bid_vwap is None or ask_vwap is None:
            return {self.name: self.orders}

        fair = (bid_vwap + ask_vwap) / 2
        pos  = self.initial_position
        lim  = self.position_limit

        # Skew fair value against inventory
        skewed_fair = fair - (pos / lim)

        # Take clearly mispriced orders, avoid deepening inventory
        for p, v in self.mkt_sell_orders.items():
            if p < skewed_fair - 1 and pos < lim * 0.4:
                self.buy(p, min(abs(v), 10))

        for p, v in self.mkt_buy_orders.items():
            if p > skewed_fair + 1 and pos > -lim * 0.4:
                self.sell(p, min(abs(v), 10))

        # Two-level make, size tapers with inventory lean
        long_bias  = max(0.0, pos / lim)
        short_bias = max(0.0, -pos / lim)
        s_bid = max(1, int(5 * (1 - long_bias)))
        s_ask = max(1, int(5 * (1 - short_bias)))

        self.buy( skewed_fair - 1, s_bid)
        self.buy( skewed_fair - 2, max(1, s_bid // 2))
        self.sell(skewed_fair + 1, s_ask)
        self.sell(skewed_fair + 2, max(1, s_ask // 2))

        return {self.name: self.orders}


# =========================
# VELVETFRUIT
# Regime-adaptive: Hurst proxy detects trending vs ranging.
# Slope confirmation required for trend entries.
# Gate-controlled: no new directional entries when flow gate closed.
# =========================
class FruitTrader(ProductTrader):

    def get_orders(self, gate_open):
        if self.mid is None:
            return {self.name: self.orders}

        data    = self.last_traderData.get(self.name, {})
        history = data.get("prices", [])
        history.append(self.mid)
        if len(history) > 100:
            history.pop(0)

        self.new_trader_data[self.name] = {"prices": history}

        if len(history) < 30:
            return {self.name: self.orders}

        arr  = np.array(history)
        mean = float(np.mean(arr))
        std  = float(np.std(arr))

        if std < 2:
            return {self.name: self.orders}

        pos = self.initial_position

        # Hard unwind always fires regardless of gate
        if pos > 20:
            if self.best_bid:
                self.sell(self.best_bid, min(5, pos - 20))
            return {self.name: self.orders}
        if pos < -20:
            if self.best_ask:
                self.buy(self.best_ask, min(5, -pos - 20))
            return {self.name: self.orders}

        if not gate_open:
            return {self.name: self.orders}

        # Hurst proxy: variance ratio
        lag = max(5, len(history) // 10)
        hurst_signal = NEUTRAL
        if len(history) >= lag * 2:
            var_1   = float(np.var(np.diff(arr)))
            var_lag = float(np.var(arr[lag:] - arr[:-lag]))
            if var_1 > 1e-9:
                hr = var_lag / (var_1 * lag)
                if hr > 1.1:
                    hurst_signal = LONG    # trending
                elif hr < 0.9:
                    hurst_signal = SHORT   # mean-reverting

        # Slope confirmation
        recent = arr[-min(20, len(history)):]
        slope  = float(np.polyfit(np.arange(len(recent), dtype=float), recent, 1)[0])
        norm_slope  = abs(slope) / std
        slope_strong = norm_slope > 0.05
        slope_dir    = LONG if slope > 0 else SHORT

        z = (self.mid - mean) / std

        if hurst_signal == LONG and slope_strong:
            # Trend-following: enter on pullbacks, half-limit max
            size = 2
            if slope_dir == LONG and self.mid < mean and pos < 10:
                self.buy(self.best_ask, size)
            elif slope_dir == SHORT and self.mid > mean and pos > -10:
                self.sell(self.best_bid, size)

        elif hurst_signal == SHORT and not slope_strong:
            # Mean-reversion: fade extremes, scale with z
            if abs(z) >= 2.5:
                size = min(int(2 * (1 + abs(z) - 2.5)), 20 - abs(pos))
                if size > 0:
                    if z > 2.5 and self.best_bid:
                        self.sell(self.best_bid, size)
                    elif z < -2.5 and self.best_ask:
                        self.buy(self.best_ask, size)

        return {self.name: self.orders}


# =========================
# PAIRS TRADER
# VEV z-score with ADF stationarity gate AND flow gate.
# Unwinds/stops/exits always fire; entries need both gates.
# =========================
class PairsTrader:

    def __init__(self, state, prints, new_trader_data):
        self.f     = ProductTrader(DYNAMIC_SYMBOL, state, prints, new_trader_data)
        self.state = state
        self.new_trader_data = new_trader_data
        try:
            td = json.loads(state.traderData) if state.traderData else {}
        except:
            td = {}
        self._data = td.get("pairs", {})

    def _adf_proxy(self, arr):
        # AR(1) coefficient on first differences → Dickey-Fuller proxy
        if len(arr) < 20:
            return 1.0
        ds     = np.diff(arr)
        lag    = arr[:-1]
        lag_dm = lag - lag.mean()
        ds_dm  = ds - ds.mean()
        denom  = np.dot(lag_dm, lag_dm)
        if denom < 1e-10:
            return 1.0
        phi = np.dot(ds_dm, lag_dm) / denom
        if phi < -0.19:
            return 0.01
        elif phi < -0.13:
            return 0.04
        elif phi < -0.08:
            return 0.08
        return 0.20

    def get_orders(self, gate_open):
        result = {}
        if self.f.mid is None:
            return result

        f_hist = self._data.get("f_prices", [])
        f_hist.append(self.f.mid)
        if len(f_hist) > 200:
            f_hist = f_hist[-200:]

        self.new_trader_data["pairs"] = {"f_prices": f_hist}

        if len(f_hist) < 80:
            return result

        arr = np.array(f_hist, dtype=float)
        mean = float(arr.mean())
        std  = float(arr.std())
        if std < 1e-6:
            return result

        z   = (self.f.mid - mean) / std
        pos = self.f.initial_position

        # Hard unwind
        if pos > 15:
            if self.f.best_bid:
                self.f.sell(self.f.best_bid, min(2, pos - 15))
                result[DYNAMIC_SYMBOL] = self.f.orders
            return result
        if pos < -15:
            if self.f.best_ask:
                self.f.buy(self.f.best_ask, min(2, -pos - 15))
                result[DYNAMIC_SYMBOL] = self.f.orders
            return result

        # Stop loss
        if z > 3.5 and pos < 0:
            self._close(result)
            return result
        if z < -3.5 and pos > 0:
            self._close(result)
            return result

        # Exit at mean
        if abs(z) < 0.5 and pos != 0:
            self._close(result)
            return result

        # ADF gate
        if self._adf_proxy(arr) > 0.04:
            self._unwind(result)
            return result

        # Flow gate
        if not gate_open:
            return result

        # Entry
        if abs(z) >= 2.0:
            size = min(int(2 * (1 + (abs(z) - 2.0) * 0.5)), 15 - abs(pos))
            if size <= 0:
                return result
            if z > 2.0 and self.f.best_bid:
                self.f.sell(self.f.best_bid, size)
                result[DYNAMIC_SYMBOL] = self.f.orders
            elif z < -2.0 and self.f.best_ask:
                self.f.buy(self.f.best_ask, size)
                result[DYNAMIC_SYMBOL] = self.f.orders

        return result

    def _close(self, result):
        pos = self.f.initial_position
        if pos > 0 and self.f.best_bid:
            self.f.sell(self.f.best_bid, abs(pos))
            result[DYNAMIC_SYMBOL] = self.f.orders
        elif pos < 0 and self.f.best_ask:
            self.f.buy(self.f.best_ask, abs(pos))
            result[DYNAMIC_SYMBOL] = self.f.orders

    def _unwind(self, result):
        pos = self.f.initial_position
        if pos > 0 and self.f.best_bid:
            self.f.sell(self.f.best_bid, min(2, pos))
            result[DYNAMIC_SYMBOL] = self.f.orders
        elif pos < 0 and self.f.best_ask:
            self.f.buy(self.f.best_ask, min(2, -pos))
            result[DYNAMIC_SYMBOL] = self.f.orders


# =========================
# OPTIONS
# Core strategy from the writeup:
#
# 1. IV SCALPING (primary alpha):
#    - Compute IV per strike via Newton-Raphson
#    - Fit parabola to IV vs moneyness → vol smile
#    - Fair vol per strike = smile(moneyness)
#    - Trade when market price deviates from BS(smile vol)
#    - Confirmed by both price edge AND IV deviation direction
#
# 2. GAMMA SCALPING (secondary, stable small gains):
#    - Buy underpriced options (negative IV dev, negative price dev)
#    - Rehedge delta to capture gamma from underlying moves
#    - Works even when flow gate closed: pure structural edge
#
# 3. MEAN REVERSION ON UNDERLYING (hybrid hedge):
#    - Fast EMA on VEV spot price
#    - Fixed threshold, no vol scaling (as per writeup)
#    - Gate-controlled entries only
#
# 4. CROSS-STRIKE ARB (ungated, pure no-arb):
#    - Call spread bounded by [0, K2-K1]
#    - Trade violations with liquidity filter
#
# 5. DELTA HEDGE (always runs):
#    - Offset net option delta when imbalance large enough
#    - Threshold guards against paying spread on small imbalances
# =========================
class OptionTrader:

    def __init__(self, state, prints, new_trader_data):
        self.options    = [ProductTrader(s, state, prints, new_trader_data) for s in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, prints, new_trader_data)
        self.state      = state
        self.new_trader_data = new_trader_data
        try:
            td = json.loads(state.traderData) if state.traderData else {}
        except:
            td = {}
        self._opt_data = td.get("opt", {})

    def bs_call(self, S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return max(0.0, S - K), 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * _N.cdf(d1) - K * _N.cdf(d2), _N.cdf(d1)

    def bs_vega(self, S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return 1e-8
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        return S * _N.pdf(d1) * math.sqrt(T)

    def implied_vol(self, S, K, T, market_price):
        if market_price <= max(0.0, S - K) + 1e-6:
            return None
        sigma = 0.25
        for _ in range(50):
            price, _ = self.bs_call(S, K, T, sigma)
            vega     = self.bs_vega(S, K, T, sigma)
            if abs(price - market_price) < 1e-4:
                return sigma
            if vega < 1e-8:
                break
            sigma -= (price - market_price) / vega
            sigma  = max(0.005, min(sigma, 10.0))
        return None

    def fit_smile(self, moneyness_iv_pairs):
        # Fit IV = a*m^2 + b*m + c; m = log(S/K)
        if len(moneyness_iv_pairs) < 3:
            return None
        ms  = np.array([x[0] for x in moneyness_iv_pairs])
        ivs = np.array([x[1] for x in moneyness_iv_pairs])
        try:
            return np.polyfit(ms, ivs, 2)   # returns [a, b, c]
        except:
            return None

    def smile_vol(self, coeffs, m):
        v = coeffs[0]*m**2 + coeffs[1]*m + coeffs[2]
        return max(0.01, min(v, 10.0))

    def get_orders(self, gate_open):
        if self.underlying.mid is None:
            return {}

        S      = self.underlying.mid
        T      = 0.1
        result = {}

        # -------------------------------------------------------
        # Collect all liquid strikes, compute IV and moneyness
        # Liquid = price > 5, spread <= 20, within 300pts of spot
        # -------------------------------------------------------
        strike_data = []

        for opt in self.options:
            if opt.mid is None or opt.best_bid is None or opt.best_ask is None:
                continue
            K = float(opt.name.split("_")[1])
            if abs(K - S) > 300:
                continue
            if opt.mid < 5:
                continue
            if (opt.best_ask - opt.best_bid) > 20:
                continue
            iv = self.implied_vol(S, K, T, opt.mid)
            if iv is None:
                continue
            m = math.log(S / K)
            strike_data.append((K, m, iv, opt))

        if not strike_data:
            return {}

        # -------------------------------------------------------
        # Fit vol smile parabola
        # -------------------------------------------------------
        smile_coeffs = self.fit_smile([(x[1], x[2]) for x in strike_data])

        # Fallback to median if smile fitting fails
        fallback_vol = float(np.median([x[2] for x in strike_data]))

        # -------------------------------------------------------
        # Per-strike: IV scalping + gamma scalping
        # -------------------------------------------------------
        net_delta = 0.0

        for K, m, iv, opt in strike_data:
            fair_vol = self.smile_vol(smile_coeffs, m) if smile_coeffs is not None \
                       else fallback_vol

            iv_dev             = iv - fair_vol
            theo_price, delta  = self.bs_call(S, K, T, fair_vol)
            pos                = self.state.position.get(opt.name, 0)
            price_dev          = (opt.mid - theo_price) - 0.15 * pos

            # IV SCALP — gated, both signals must agree
            if gate_open:
                if price_dev > 5 and iv_dev > 0:
                    opt.sell(opt.best_bid, 2)
                    net_delta += delta * (-2)
                elif price_dev < -5 and iv_dev < 0:
                    opt.buy(opt.best_ask, 2)
                    net_delta += delta * 2

            # GAMMA SCALP — ungated, structural edge from buying
            # underpriced options and rehedging delta
            # Only buy; never sell without IV confirmation
            if price_dev < -3 and iv_dev < 0 and not gate_open:
                opt.buy(opt.best_ask, 1)
                net_delta += delta * 1

            if opt.orders:
                result[opt.name] = opt.orders

        # -------------------------------------------------------
        # Cross-strike arb — ungated, pure no-arb bound
        # Adjacent strikes only (gap <= 200)
        # -------------------------------------------------------
        tradable = sorted(strike_data, key=lambda x: x[0])
        for i in range(len(tradable) - 1):
            K1, _, _, opt1 = tradable[i]
            K2, _, _, opt2 = tradable[i + 1]
            if K2 - K1 > 200:
                continue
            spread  = opt2.mid - opt1.mid
            pos1    = self.state.position.get(opt1.name, 0)
            pos2    = self.state.position.get(opt2.name, 0)
            if abs(pos1) > 20 or abs(pos2) > 20:
                continue
            # Spread must lie in [0, K2-K1]; trade violations
            if spread > (K2 - K1) + 3:
                if opt2.best_bid and opt1.best_ask:
                    opt2.sell(opt2.best_bid, 1)
                    opt1.buy(opt1.best_ask, 1)
                    result[opt2.name] = opt2.orders
                    result[opt1.name] = opt1.orders
            elif spread < -3:
                if opt2.best_ask and opt1.best_bid:
                    opt2.buy(opt2.best_ask, 1)
                    opt1.sell(opt1.best_bid, 1)
                    result[opt2.name] = opt2.orders
                    result[opt1.name] = opt1.orders

        # -------------------------------------------------------
        # Mean reversion on underlying — fast EMA, fixed threshold
        # From writeup: no vol scaling, keep it simple and robust
        # -------------------------------------------------------
        ema_prev = self._opt_data.get("ema", S)
        ema_curr = 0.08 * S + 0.92 * ema_prev
        self.new_trader_data["opt"] = {"ema": ema_curr}

        mr_dev  = S - ema_curr
        und_pos = self.state.position.get(OPTION_UNDERLYING_SYMBOL, 0)

        if gate_open:
            if mr_dev > 8 and und_pos > -20:
                sell_size = min(3, 20 + und_pos)
                if sell_size > 0 and self.underlying.best_bid:
                    self.underlying.sell(self.underlying.best_bid, sell_size)
                    net_delta -= sell_size
            elif mr_dev < -8 and und_pos < 20:
                buy_size = min(3, 20 - und_pos)
                if buy_size > 0 and self.underlying.best_ask:
                    self.underlying.buy(self.underlying.best_ask, buy_size)
                    net_delta += buy_size

        # -------------------------------------------------------
        # Delta hedge — always runs, threshold guards spread cost
        # -------------------------------------------------------
        hedge_pos    = self.state.position.get(OPTION_UNDERLYING_SYMBOL, 0)
        hedge_needed = -net_delta - hedge_pos

        if abs(hedge_needed) > 15:
            hedge_size = int(min(10, abs(hedge_needed)))
            if hedge_needed > 0 and self.underlying.best_ask:
                self.underlying.buy(self.underlying.best_ask, hedge_size)
            elif hedge_needed < 0 and self.underlying.best_bid:
                self.underlying.sell(self.underlying.best_bid, hedge_size)

        if self.underlying.orders:
            result[OPTION_UNDERLYING_SYMBOL] = self.underlying.orders

        return result


# =========================
# MAIN TRADER
# =========================
class Trader:

    def run(self, state: TradingState):
        prints          = {}
        new_trader_data = {}
        result          = {}

        gate_open = flow_gate_open(state)

        # HYDROGEL — always active, pure MM
        if STATIC_SYMBOL in state.order_depths:
            h = HydroTrader(STATIC_SYMBOL, state, prints, new_trader_data)
            result.update(h.get_orders())

        # VELVETFRUIT — PairsTrader primary, FruitTrader fallback
        pairs        = PairsTrader(state, prints, new_trader_data)
        pairs_orders = pairs.get_orders(gate_open)

        if DYNAMIC_SYMBOL in pairs_orders:
            result.update(pairs_orders)
        else:
            if DYNAMIC_SYMBOL in state.order_depths:
                f = FruitTrader(DYNAMIC_SYMBOL, state, prints, new_trader_data)
                result.update(f.get_orders(gate_open))

        # OPTIONS — vol smile scalp + gamma + MR + arb + hedge
        opt = OptionTrader(state, prints, new_trader_data)
        result.update(opt.get_orders(gate_open))

        return result, 0, json.dumps(new_trader_data)
from datamodel import OrderDepth, TradingState, Order
import json
import math
import numpy as np
from statistics import NormalDist

_N = NormalDist()

DEFAULT_PARAMS = {
    # Hydrogel (Market Making only)
    "h_take_size": 10,
    "h_make_edge": 1,
    "h_make_size": 5,
    # Velvetfruit solo fallback
    "f_hist_len": 100,
    "f_min_hist": 30,
    "f_min_std": 2,
    "f_max_pos": 20,
    "f_reduce_size": 5,
    "f_trade_size": 2,
    "f_z_entry": 2.5,
    # Pairs / VEV z-score
    "p_window": 200,
    "p_min_window": 80,
    "p_z_entry": 2.0,
    "p_z_exit": 0.5,
    "p_adf_threshold": 0.04,
    "p_max_pos": 15,
    "p_trade_size": 2,
    "p_stop_z": 3.5,
    # Options
    "o_t": 0.1,
    "o_atm_filter": 120,
    "o_cross_edge": 3,
    "o_inv_adj": 0.15,
    "o_single_edge": 6,
    "o_single_size": 1,
    "o_min_price": 10,
    "o_max_spread": 15,
    "o_hedge_mult": -0.5,
    "o_hedge_thr": 20,
    "o_hedge_max": 10,
    # Flow signal gate — from the tip:
    # only trade VEV when 5200 AND 5300 spreads are both <= 2 ticks
    "flow_spread_gate": 2,
}

try:
    with open("params.json", "r") as f:
        PARAMS = json.load(f)
except:
    PARAMS = DEFAULT_PARAMS

for k, v in DEFAULT_PARAMS.items():
    PARAMS.setdefault(k, v)

STATIC_SYMBOL            = "HYDROGEL_PACK"
DYNAMIC_SYMBOL           = "VELVETFRUIT_EXTRACT"
OPTION_UNDERLYING_SYMBOL = "VELVETFRUIT_EXTRACT"

OPTION_SYMBOLS = [
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500"
]

# The two strikes whose spread tightness gates the flow signal
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
# Reads the live order book for VEV_5200 and VEV_5300.
# Returns True only when BOTH spreads are <= flow_spread_gate.
# This is the condition under which the informed bot fires —
# tight surface means it can hedge, so edge is real.
# When this gate is closed, all VEV directional trades are off.
# =========================
def flow_gate_open(state):
    gate = PARAMS["flow_spread_gate"]
    for strike in FLOW_GATE_STRIKES:
        depth = state.order_depths.get(strike)
        if depth is None:
            return False
        bids = depth.buy_orders
        asks = depth.sell_orders
        if not bids or not asks:
            return False
        best_bid = max(bids)
        best_ask = min(asks)
        if (best_ask - best_bid) > gate:
            return False
    return True


# =========================
# HYDROGEL — inventory-skewed MM
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
        skew = PARAMS["h_make_edge"] * (pos / lim)
        skewed_fair = fair - skew

        take_edge = PARAMS["h_make_edge"]

        for p, v in self.mkt_sell_orders.items():
            if p < skewed_fair - take_edge:
                if pos < lim * 0.4:
                    self.buy(p, min(abs(v), PARAMS["h_take_size"]))

        for p, v in self.mkt_buy_orders.items():
            if p > skewed_fair + take_edge:
                if pos > -lim * 0.4:
                    self.sell(p, min(abs(v), PARAMS["h_take_size"]))

        e1 = PARAMS["h_make_edge"]
        e2 = e1 * 2
        long_bias  = max(0.0, pos / lim)
        short_bias = max(0.0, -pos / lim)
        s1 = max(1, int(PARAMS["h_make_size"] * (1 - long_bias)))
        s2 = max(1, int(PARAMS["h_make_size"] * (1 - short_bias)))

        self.buy( skewed_fair - e1, s1)
        self.buy( skewed_fair - e2, max(1, s1 // 2))
        self.sell(skewed_fair + e1, s2)
        self.sell(skewed_fair + e2, max(1, s2 // 2))

        return {self.name: self.orders}


# =========================
# VELVETFRUIT — regime-adaptive solo fallback
# Only runs when PairsTrader hasn't warmed up yet.
# Also gated on flow_gate_open — if the informed bot
# isn't active, there's no edge in directional VEV trades.
# =========================
class FruitTrader(ProductTrader):

    def get_orders(self, gate_open):
        if self.mid is None:
            return {self.name: self.orders}

        data    = self.last_traderData.get(self.name, {})
        history = data.get("prices", [])
        history.append(self.mid)

        if len(history) > PARAMS["f_hist_len"]:
            history.pop(0)

        self.new_trader_data[self.name] = {"prices": history}

        if len(history) < PARAMS["f_min_hist"]:
            return {self.name: self.orders}

        arr  = np.array(history)
        mean = float(np.mean(arr))
        std  = float(np.std(arr))

        if std < PARAMS["f_min_std"]:
            return {self.name: self.orders}

        position = self.initial_position

        # Hard unwind regardless of gate — always reduce excess
        if position > PARAMS["f_max_pos"]:
            if self.best_bid:
                self.sell(self.best_bid,
                          min(PARAMS["f_reduce_size"], position - PARAMS["f_max_pos"]))
            return {self.name: self.orders}

        if position < -PARAMS["f_max_pos"]:
            if self.best_ask:
                self.buy(self.best_ask,
                         min(PARAMS["f_reduce_size"], -position - PARAMS["f_max_pos"]))
            return {self.name: self.orders}

        # No new directional entries when gate is closed
        if not gate_open:
            return {self.name: self.orders}

        lag = max(5, len(history) // 10)
        if len(history) >= lag * 2:
            diffs_1   = np.diff(arr)
            diffs_lag = arr[lag:] - arr[:-lag]
            var_1     = float(np.var(diffs_1))
            var_lag   = float(np.var(diffs_lag))
            if var_1 > 1e-9:
                hurst_proxy = var_lag / (var_1 * lag)
                if hurst_proxy > 1.1:
                    hurst_signal = LONG
                elif hurst_proxy < 0.9:
                    hurst_signal = SHORT
                else:
                    hurst_signal = NEUTRAL
            else:
                hurst_signal = NEUTRAL
        else:
            hurst_signal = NEUTRAL

        window = min(20, len(history))
        recent = arr[-window:]
        xs     = np.arange(window, dtype=float)
        slope  = float(np.polyfit(xs, recent, 1)[0])
        normalised_slope = abs(slope) / std if std > 0 else 0
        slope_strong = normalised_slope > 0.05
        slope_dir    = LONG if slope > 0 else SHORT

        if hurst_signal == LONG and slope_strong:
            regime = LONG
        elif hurst_signal == SHORT and not slope_strong:
            regime = SHORT
        else:
            regime = NEUTRAL

        z = (self.mid - mean) / std

        if regime == LONG:
            size = PARAMS["f_trade_size"]
            if slope_dir == LONG:
                if self.mid < mean and self.best_ask:
                    if position < PARAMS["f_max_pos"] // 2:
                        self.buy(self.best_ask, size)
            else:
                if self.mid > mean and self.best_bid:
                    if position > -(PARAMS["f_max_pos"] // 2):
                        self.sell(self.best_bid, size)
            return {self.name: self.orders}

        if regime == SHORT:
            z_entry = PARAMS["f_z_entry"]
            if abs(z) < z_entry:
                return {self.name: self.orders}
            excess = abs(z) - z_entry
            size   = min(
                int(PARAMS["f_trade_size"] * (1.0 + excess)),
                PARAMS["f_max_pos"] - abs(position)
            )
            if size <= 0:
                return {self.name: self.orders}
            if z > z_entry and self.best_bid:
                self.sell(self.best_bid, size)
            elif z < -z_entry and self.best_ask:
                self.buy(self.best_ask, size)

        return {self.name: self.orders}


# =========================
# PAIRS TRADER — VEV z-score with ADF gate AND flow gate
# Both gates must be open to enter new positions.
# Existing positions are always unwound regardless of gates.
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

    def _adf_pvalue_proxy(self, arr):
        if len(arr) < 20:
            return 1.0
        ds     = np.diff(arr)
        lag    = arr[:-1]
        lag_dm = lag - lag.mean()
        ds_dm  = ds  - ds.mean()
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
        else:
            return 0.20

    def get_orders(self, gate_open):
        result = {}

        if self.f.mid is None:
            return result

        f_hist = self._data.get("f_prices", [])
        f_hist.append(self.f.mid)

        win = PARAMS["p_window"]
        if len(f_hist) > win:
            f_hist = f_hist[-win:]

        self.new_trader_data["pairs"] = {"f_prices": f_hist}

        if len(f_hist) < PARAMS["p_min_window"]:
            return result

        arr  = np.array(f_hist, dtype=float)
        mean = float(arr.mean())
        std  = float(arr.std())
        if std < 1e-6:
            return result

        z        = (self.f.mid - mean) / std
        position = self.f.initial_position
        max_p    = PARAMS["p_max_pos"]
        size     = PARAMS["p_trade_size"]
        z_entry  = PARAMS["p_z_entry"]
        z_exit   = PARAMS["p_z_exit"]
        z_stop   = PARAMS["p_stop_z"]

        # Hard unwind — always fires regardless of any gate
        if position > max_p:
            if self.f.best_bid:
                self.f.sell(self.f.best_bid, min(size, position - max_p))
                result[DYNAMIC_SYMBOL] = self.f.orders
            return result
        if position < -max_p:
            if self.f.best_ask:
                self.f.buy(self.f.best_ask, min(size, -position - max_p))
                result[DYNAMIC_SYMBOL] = self.f.orders
            return result

        # Stop loss — always fires regardless of any gate
        if z > z_stop and position < 0:
            self._close(result)
            return result
        if z < -z_stop and position > 0:
            self._close(result)
            return result

        # Exit at mean — always fires regardless of any gate
        if abs(z) < z_exit and position != 0:
            self._close(result)
            return result

        # ADF gate — no new entries if spread not stationary
        p_val = self._adf_pvalue_proxy(arr)
        if p_val > PARAMS["p_adf_threshold"]:
            self._unwind(result)
            return result

        # Flow gate — no new entries if 5200/5300 spreads are wide
        # This is the key new condition from the tip:
        # informed bot only hedges into a tight surface, so edge
        # only exists when both strikes are at or below 2-tick spread
        if not gate_open:
            return result

        # Entry — both gates open, signal is clean
        if abs(z) >= z_entry:
            excess     = abs(z) - z_entry
            trade_size = min(
                int(size * (1.0 + excess * 0.5)),
                max_p - abs(position)
            )
            if trade_size <= 0:
                return result

            if z > z_entry and self.f.best_bid:
                self.f.sell(self.f.best_bid, trade_size)
                result[DYNAMIC_SYMBOL] = self.f.orders
            elif z < -z_entry and self.f.best_ask:
                self.f.buy(self.f.best_ask, trade_size)
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
        pos  = self.f.initial_position
        size = PARAMS["p_trade_size"]
        if pos > 0 and self.f.best_bid:
            self.f.sell(self.f.best_bid, min(size, pos))
            result[DYNAMIC_SYMBOL] = self.f.orders
        elif pos < 0 and self.f.best_ask:
            self.f.buy(self.f.best_ask, min(size, -pos))
            result[DYNAMIC_SYMBOL] = self.f.orders


# =========================
# OPTIONS — IV surface + liquidity filters + flow gate
# Single-option IV trades are also gated on flow_gate_open.
# Cross-strike arb is NOT gated — pure arbitrage doesn't need flow.
# Delta hedge always runs.
# =========================
class OptionTrader:

    def __init__(self, state, prints, new_trader_data):
        self.options    = [ProductTrader(s, state, prints, new_trader_data) for s in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, prints, new_trader_data)
        self.state      = state
        self.new_trader_data = new_trader_data

    def bs_call(self, S, K, T, sigma=0.25):
        if T <= 0:
            return max(0, S - K), 1 if S > K else 0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        return S * _N.cdf(d1) - K * _N.cdf(d2), _N.cdf(d1)

    def bs_vega(self, S, K, T, sigma=0.25):
        if T <= 0 or sigma <= 0:
            return 1e-6
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        return S * _N.pdf(d1) * math.sqrt(T)

    def implied_vol(self, S, K, T, market_price, tol=1e-4, max_iter=30):
        sigma = 0.25
        for _ in range(max_iter):
            price, _ = self.bs_call(S, K, T, sigma)
            vega     = self.bs_vega(S, K, T, sigma)
            diff     = price - market_price
            if abs(diff) < tol:
                return sigma
            if vega < 1e-8:
                break
            sigma -= diff / vega
            sigma  = max(0.01, min(sigma, 5.0))
        return None

    def get_orders(self, gate_open):
        if self.underlying.mid is None:
            return {}

        S      = self.underlying.mid
        T      = PARAMS["o_t"]
        result = {}

        iv_surface = {}
        tradable   = []

        for opt in self.options:
            if opt.mid is None or opt.best_bid is None or opt.best_ask is None:
                continue
            K = float(opt.name.split("_")[1])
            if abs(K - S) > PARAMS["o_atm_filter"]:
                continue
            if opt.mid < PARAMS["o_min_price"]:
                continue
            spread = opt.best_ask - opt.best_bid
            if spread > PARAMS["o_max_spread"]:
                continue
            iv = self.implied_vol(S, K, T, opt.mid)
            if iv is not None:
                iv_surface[K] = iv
            tradable.append((K, opt))

        tradable.sort(key=lambda x: x[0])

        if not iv_surface:
            return {}

        fair_vol  = float(np.median(list(iv_surface.values())))
        net_delta = 0.0

        # Single-option IV trades — gated on flow signal
        # When the informed bot is active (gate open), IV
        # mispricing is more likely to be real and not noise
        if gate_open:
            for K, opt in tradable:
                strike_iv         = iv_surface.get(K, fair_vol)
                theo_price, delta = self.bs_call(S, K, T, fair_vol)
                position          = self.state.position.get(opt.name, 0)
                edge  = (opt.mid - theo_price) - PARAMS["o_inv_adj"] * position
                vol_e = strike_iv - fair_vol
                size  = PARAMS["o_single_size"]

                if edge > PARAMS["o_single_edge"] and vol_e > 0:
                    opt.sell(opt.best_bid, size)
                    net_delta += delta * (-size)
                elif edge < -PARAMS["o_single_edge"] and vol_e < 0:
                    opt.buy(opt.best_ask, size)
                    net_delta += delta * size

                if opt.orders:
                    result[opt.name] = opt.orders

        # Cross-strike arb — NOT gated, pure no-arb bound
        for i in range(len(tradable) - 1):
            K1, opt1 = tradable[i]
            K2, opt2 = tradable[i + 1]
            if K2 - K1 > 200:
                continue
            spread_market = opt2.mid - opt1.mid
            pos1 = self.state.position.get(opt1.name, 0)
            pos2 = self.state.position.get(opt2.name, 0)
            if abs(pos1) > PARAMS["f_max_pos"] or abs(pos2) > PARAMS["f_max_pos"]:
                continue
            size = PARAMS["o_single_size"]
            if spread_market > (K2 - K1) + PARAMS["o_cross_edge"]:
                if opt2.best_bid and opt1.best_ask:
                    opt2.sell(opt2.best_bid, size)
                    opt1.buy(opt1.best_ask, size)
                    result[opt2.name] = opt2.orders
                    result[opt1.name] = opt1.orders
            elif spread_market < -PARAMS["o_cross_edge"]:
                if opt2.best_ask and opt1.best_bid:
                    opt2.buy(opt2.best_ask, size)
                    opt1.sell(opt1.best_bid, size)
                    result[opt2.name] = opt2.orders
                    result[opt1.name] = opt1.orders

        # Delta hedge — always runs
        hedge_pos    = self.state.position.get(OPTION_UNDERLYING_SYMBOL, 0)
        hedge_needed = -net_delta - hedge_pos
        if abs(hedge_needed) > PARAMS["o_hedge_thr"]:
            hedge_size = int(min(PARAMS["o_hedge_max"], abs(hedge_needed)))
            if hedge_needed > 0:
                self.underlying.buy(self.underlying.best_ask, hedge_size)
            else:
                self.underlying.sell(self.underlying.best_bid, hedge_size)
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

        # Evaluate flow gate once — shared across all VEV strategies
        gate_open = flow_gate_open(state)

        # HYDROGEL — pure MM, no gate needed
        if STATIC_SYMBOL in state.order_depths:
            h = HydroTrader(STATIC_SYMBOL, state, prints, new_trader_data)
            result.update(h.get_orders())

        # VELVETFRUIT — PairsTrader first, FruitTrader as fallback
        pairs = PairsTrader(state, prints, new_trader_data)
        pairs_orders = pairs.get_orders(gate_open)

        if DYNAMIC_SYMBOL in pairs_orders:
            result.update(pairs_orders)
        else:
            if DYNAMIC_SYMBOL in state.order_depths:
                f = FruitTrader(DYNAMIC_SYMBOL, state, prints, new_trader_data)
                result.update(f.get_orders(gate_open))

        # OPTIONS — flow gate passed in
        opt = OptionTrader(state, prints, new_trader_data)
        result.update(opt.get_orders(gate_open))

        return result, 0, json.dumps(new_trader_data)
        return result, 0, json.dumps(new_trader_data)
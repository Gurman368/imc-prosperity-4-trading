from datamodel import OrderDepth, TradingState, Order
import json
import math
import numpy as np
from statistics import NormalDist

_N = NormalDist()


DEFAULT_PARAMS = {
    # Hydrogel (Market Making)
    "h_take_size": 10,
    "h_make_edge": 1,
    "h_make_size": 5,
    # Velvetfruit (Z-Score)
    "f_hist_len": 100,
    "f_min_hist": 30,
    "f_min_std": 2,
    "f_max_pos": 20,
    "f_reduce_size": 5,
    "f_trade_size": 2,
    "f_z_entry": 2.5,
    # Options
    "o_t": 0.1,
    "o_atm_filter": 150,
    "o_cross_edge": 2,
    "o_inv_adj": 0.1,
    "o_single_edge": 3,
    "o_single_size": 2,
    "o_hedge_mult": -0.5,
    "o_hedge_thr": 20,
    "o_hedge_max": 15
}

try:
    with open("params.json", "r") as f:
        PARAMS = json.load(f)
except:
    PARAMS = DEFAULT_PARAMS

# =========================
# PRODUCTS (UPDATED)
# =========================
STATIC_SYMBOL = "HYDROGEL_PACK"
DYNAMIC_SYMBOL = "VELVETFRUIT_EXTRACT"

OPTION_UNDERLYING_SYMBOL = "VELVETFRUIT_EXTRACT"

OPTION_SYMBOLS = [
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500"
]

# =========================
# LIMITS
# =========================
POS_LIMITS = {
    STATIC_SYMBOL: 200,
    DYNAMIC_SYMBOL: 200,
    OPTION_UNDERLYING_SYMBOL: 300,
    **{os: 300 for os in OPTION_SYMBOLS},
}

# 🔥 Patch prosperity4bt LIMITS properly
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
# HYDROGEL (STATIC STYLE)
# =========================
# =========================
# HYDROGEL (INVENTORY-SKEWED MARKET MAKING)
# =========================
class HydroTrader(ProductTrader):

    def get_orders(self):
        if self.mid is None:
            return {self.name: self.orders}

        # --- Fair value: VWAP of top-3 bid/ask levels ---
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

        # --- Inventory skew: shift fair value to lean against position ---
        skew = PARAMS["h_make_edge"] * (pos / lim)
        skewed_fair = fair - skew

        # --- TAKE: cross only when edge is meaningful ---
        take_edge = PARAMS["h_make_edge"]
        for p, v in self.mkt_sell_orders.items():
            if p < skewed_fair - take_edge:
                self.buy(p, min(abs(v), PARAMS["h_take_size"]))

        for p, v in self.mkt_buy_orders.items():
            if p > skewed_fair + take_edge:
                self.sell(p, min(abs(v), PARAMS["h_take_size"]))

        # --- MAKE: two-level layered quotes ---
        e1 = PARAMS["h_make_edge"]
        e2 = e1 * 2

        # Tighten size on the side we already lean toward
        long_bias  = max(0.0, pos / lim)   # 0..1, 1 = max long
        short_bias = max(0.0, -pos / lim)  # 0..1, 1 = max short

        s1 = max(1, int(PARAMS["h_make_size"] * (1 - long_bias)))
        s2 = max(1, int(PARAMS["h_make_size"] * (1 - short_bias)))

        self.buy( skewed_fair - e1, s1)
        self.buy( skewed_fair - e2, max(1, s1 // 2))
        self.sell(skewed_fair + e1, s2)
        self.sell(skewed_fair + e2, max(1, s2 // 2))

        return {self.name: self.orders}


# =========================
# VELVETFRUIT (REGIME-ADAPTIVE)
# =========================
class FruitTrader(ProductTrader):

    def get_orders(self):
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

        # -------------------------------------------------------
        # REGIME DETECTION
        # Uses two independent signals; both must agree.
        #
        # Signal A — Hurst-proxy: compare variance at two lags.
        #   var(lag=L) / var(lag=1) vs L.
        #   If ratio > L → trending (H > 0.5).
        #   If ratio < L → mean-reverting (H < 0.5).
        #
        # Signal B — ADX-proxy: directional move vs total range.
        #   Strong trend: recent directional moves dominate.
        # -------------------------------------------------------
        regime = NEUTRAL   # default: do nothing

        # --- Signal A: variance ratio (Hurst proxy) ---
        lag = max(5, len(history) // 10)
        if len(history) >= lag * 2:
            diffs_1   = np.diff(arr)
            diffs_lag = arr[lag:] - arr[:-lag]
            var_1     = float(np.var(diffs_1))
            var_lag   = float(np.var(diffs_lag))
            if var_1 > 1e-9:
                hurst_proxy = var_lag / (var_1 * lag)
                # >1.1 → trending, <0.9 → mean-reverting
                if hurst_proxy > 1.1:
                    hurst_signal = LONG    # trending (direction TBD below)
                elif hurst_proxy < 0.9:
                    hurst_signal = SHORT   # mean-reverting (reuse SHORT as flag)
                else:
                    hurst_signal = NEUTRAL
            else:
                hurst_signal = NEUTRAL
        else:
            hurst_signal = NEUTRAL

        # --- Signal B: slope strength (ADX proxy) ---
        window = min(20, len(history))
        recent = arr[-window:]
        # Fit a linear slope normalised by std
        xs     = np.arange(window, dtype=float)
        slope  = float(np.polyfit(xs, recent, 1)[0])
        normalised_slope = abs(slope) / std if std > 0 else 0
        # > 0.05 per tick = strong trend
        slope_strong = normalised_slope > 0.05
        slope_dir    = LONG if slope > 0 else SHORT

        # --- Combine ---
        if hurst_signal == LONG and slope_strong:
            regime = LONG     # trending up or down → follow slope
        elif hurst_signal == SHORT and not slope_strong:
            regime = SHORT    # mean-reverting AND slope weak → fade extremes
        else:
            regime = NEUTRAL  # conflicting signals → stay flat

        z = (self.mid - mean) / std

        # -------------------------------------------------------
        # HARD UNWIND: if position is too large, reduce regardless
        # -------------------------------------------------------
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

        # -------------------------------------------------------
        # TREND-FOLLOWING (regime == LONG, i.e. trending)
        # Only enter in direction of slope; small size; tight stop
        # via position limit.
        # -------------------------------------------------------
        if regime == LONG:
            size = PARAMS["f_trade_size"]
            if slope_dir == LONG:
                # Price trending up: buy dips (ask below mean)
                if self.mid < mean and self.best_ask:
                    if position < PARAMS["f_max_pos"] // 2:   # half-limit only
                        self.buy(self.best_ask, size)
            else:
                # Price trending down: sell rallies (bid above mean)
                if self.mid > mean and self.best_bid:
                    if position > -(PARAMS["f_max_pos"] // 2):
                        self.sell(self.best_bid, size)
            return {self.name: self.orders}

        # -------------------------------------------------------
        # MEAN-REVERSION (regime == SHORT, i.e. ranging)
        # Only trade extreme z-scores; scale size to extremity.
        # -------------------------------------------------------
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

        # regime == NEUTRAL → no orders
        return {self.name: self.orders}


# =========================
# OPTIONS (VOL SURFACE + GAMMA SCALPING + FULL DELTA HEDGE)
# =========================
class OptionTrader:

    def __init__(self, state, prints, new_trader_data):
        self.options    = [ProductTrader(s, state, prints, new_trader_data) for s in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, prints, new_trader_data)
        self.state      = state
        self.new_trader_data = new_trader_data
        self.last_traderData = new_trader_data  # shared ref

    # -------------------------
    # Black-Scholes helpers (unchanged signatures)
    # -------------------------
    def bs_call(self, S, K, T, sigma=0.25):
        if T <= 0:
            return max(0, S - K), 1 if S > K else 0
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        price = S * _N.cdf(d1) - K * _N.cdf(d2)
        delta = _N.cdf(d1)
        return price, delta

    def bs_vega(self, S, K, T, sigma=0.25):
        """Vega — sensitivity of price to vol. Used for IV solving."""
        if T <= 0 or sigma <= 0:
            return 1e-6
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        return S * _N.pdf(d1) * math.sqrt(T)

    def implied_vol(self, S, K, T, market_price, tol=1e-4, max_iter=30):
        """Newton-Raphson IV solver. Returns None if it fails to converge."""
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
            sigma  = max(0.01, min(sigma, 5.0))   # clamp to sane range
        return None

    # -------------------------
    # MAIN LOGIC
    # -------------------------
    def get_orders(self):
        if self.underlying.mid is None:
            return {}

        S      = self.underlying.mid
        T      = PARAMS["o_t"]
        result = {}

        # -------------------------------------------------------
        # STEP 1: Build implied-vol surface from tradable options
        # -------------------------------------------------------
        iv_surface = {}   # K -> implied vol
        tradable   = []

        for opt in self.options:
            if opt.mid is None or opt.best_bid is None or opt.best_ask is None:
                continue
            K = float(opt.name.split("_")[1])
            if abs(K - S) > PARAMS["o_atm_filter"]:
                continue

            iv = self.implied_vol(S, K, T, opt.mid)
            if iv is not None:
                iv_surface[K] = iv
            tradable.append((K, opt))

        tradable.sort(key=lambda x: x[0])

        if not iv_surface:
            return {}

        # Smoothed "fair" vol = median of available IVs (robust to outliers)
        fair_vol = float(np.median(list(iv_surface.values())))

        # -------------------------------------------------------
        # STEP 2: Per-strike — trade IV vs fair vol (gamma scalp)
        # -------------------------------------------------------
        net_delta = 0.0

        for K, opt in tradable:
            strike_iv   = iv_surface.get(K, fair_vol)
            theo_price, delta = self.bs_call(S, K, T, fair_vol)
            market_price      = opt.mid

            position = self.state.position.get(opt.name, 0)

            # Inventory-adjusted edge
            edge = (market_price - theo_price) - PARAMS["o_inv_adj"] * position

            # Only trade when vol mispricing is meaningful
            vol_edge = strike_iv - fair_vol   # positive = option is rich

            # Require BOTH price edge AND vol confirmation
            size = PARAMS["o_single_size"]

            if edge > PARAMS["o_single_edge"] and vol_edge > 0:
                # Option is overpriced AND IV is above fair → sell it
                opt.sell(opt.best_bid, size)
                net_delta += delta * (-size)

            elif edge < -PARAMS["o_single_edge"] and vol_edge < 0:
                # Option is underpriced AND IV is below fair → buy it
                opt.buy(opt.best_ask, size)
                net_delta += delta * size

            result[opt.name] = opt.orders

        # -------------------------------------------------------
        # STEP 3: Cross-strike arbitrage (unchanged logic, tighter)
        # -------------------------------------------------------
        for i in range(len(tradable) - 1):
            K1, opt1 = tradable[i]
            K2, opt2 = tradable[i + 1]

            # Theoretical spread between adjacent call strikes is bounded
            # by [0, K2-K1].  Any market spread outside this range is arb.
            spread_market = opt2.mid - opt1.mid
            arb_upper     = K2 - K1
            arb_lower     = 0.0

            pos1 = self.state.position.get(opt1.name, 0)
            pos2 = self.state.position.get(opt2.name, 0)

            if abs(pos1) > PARAMS["f_max_pos"] or abs(pos2) > PARAMS["f_max_pos"]:
                continue

            size = PARAMS["o_single_size"]

            # Spread too wide: sell K2, buy K1
            if spread_market > arb_upper + PARAMS["o_cross_edge"]:
                if opt2.best_bid and opt1.best_ask:
                    opt2.sell(opt2.best_bid, size)
                    opt1.buy(opt1.best_ask, size)

            # Spread inverted (K2 call cheaper than K1 call): buy K2, sell K1
            elif spread_market < arb_lower - PARAMS["o_cross_edge"]:
                if opt2.best_ask and opt1.best_bid:
                    opt2.buy(opt2.best_ask, size)
                    opt1.sell(opt1.best_bid, size)

        # -------------------------------------------------------
        # STEP 4: Full delta hedge (not partial)
        # -------------------------------------------------------
        hedge_pos    = self.state.position.get(OPTION_UNDERLYING_SYMBOL, 0)
        target_hedge = -net_delta          # full hedge: offset all option delta
        hedge_needed = target_hedge - hedge_pos

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

        prints = {}
        new_trader_data = {}

        result = {}

        # HYDRO
        if STATIC_SYMBOL in state.order_depths:
            h = HydroTrader(STATIC_SYMBOL, state, prints, new_trader_data)
            result.update(h.get_orders())

        # FRUIT
        if DYNAMIC_SYMBOL in state.order_depths:
            f = FruitTrader(DYNAMIC_SYMBOL, state, prints, new_trader_data)
            result.update(f.get_orders())

        # OPTIONS
        opt = OptionTrader(state, prints, new_trader_data)
        result.update(opt.get_orders())

        return result, 0, json.dumps(new_trader_data)
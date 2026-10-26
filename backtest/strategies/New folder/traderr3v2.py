from datamodel import OrderDepth, TradingState, Order
import json
import math
import numpy as np
from statistics import NormalDist

_N = NormalDist()

# =========================
# SYMBOLS
# =========================
STATIC_SYMBOL            = "HYDROGEL_PACK"
DYNAMIC_SYMBOL           = "VELVETFRUIT_EXTRACT"
OPTION_UNDERLYING_SYMBOL = "VELVETFRUIT_EXTRACT"

OPTION_SYMBOLS = [
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500"
]

# =========================
# LIMITS (🔥 FIX)
# =========================
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
LIMITS = POS_LIMITS  # ✅ REQUIRED FIX

LONG, NEUTRAL, SHORT = 1, 0, -1

# =========================
# BASE CLASS
# =========================
class ProductTrader:

    def __init__(self, name, state, new_trader_data):

        self.orders = []
        self.name = name
        self.state = state
        self.new_trader_data = new_trader_data

        try:
            self.last_traderData = json.loads(state.traderData) if state.traderData else {}
        except:
            self.last_traderData = {}

        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0)

        depth = self.state.order_depths.get(self.name)
        if depth:
            self.mkt_buy_orders = depth.buy_orders or {}
            self.mkt_sell_orders = depth.sell_orders or {}
        else:
            self.mkt_buy_orders, self.mkt_sell_orders = {}, {}

        self.best_bid = max(self.mkt_buy_orders) if self.mkt_buy_orders else None
        self.best_ask = min(self.mkt_sell_orders) if self.mkt_sell_orders else None

        self.mid = None
        if self.best_bid and self.best_ask:
            self.mid = (self.best_bid + self.best_ask) / 2

    def buy(self, price, volume):
        self.orders.append(Order(self.name, int(price), int(volume)))

    def sell(self, price, volume):
        self.orders.append(Order(self.name, int(price), -int(volume)))

# =========================
# HYDRO (🔥 VERIFIED EDGE)
# =========================
class HydroTrader(ProductTrader):

    EMA_ALPHA = 0.01
    ENTRY_DEV = 15.0

    def get_orders(self):

        if self.mid is None:
            return {self.name: self.orders}

        mid = self.mid
        pos = self.initial_position

        max_sell = self.position_limit + pos
        max_buy  = self.position_limit - pos

        ema_prev = self.last_traderData.get("hp_ema", mid)
        ema = ema_prev + self.EMA_ALPHA * (mid - ema_prev)
        dev = mid - ema

        self.new_trader_data["hp_ema"] = ema

        # 🔥 AGGRESSIVE SHORT
        if dev > self.ENTRY_DEV and max_sell > 0:
            for bid_p in sorted(self.mkt_buy_orders.keys(), reverse=True):
                vol = min(abs(self.mkt_buy_orders[bid_p]), max_sell)
                if vol > 0:
                    self.sell(bid_p, vol)
                    max_sell -= vol
                if max_sell <= 0:
                    break

        # passive
        if self.best_bid and self.best_ask:
            if max_sell > 0:
                ask = self.best_ask - 1
                if ask > self.best_bid:
                    self.sell(ask, min(15, max_sell))

            if max_buy > 0:
                bid = self.best_bid + 1
                if bid < self.best_ask:
                    self.buy(bid, min(15, max_buy))

        return {self.name: self.orders}

# =========================
# FRUIT (FIXED EMA MR)
# =========================
class FruitTrader(ProductTrader):

    def get_orders(self):

        if self.mid is None:
            return {}

        mid = self.mid
        pos = self.initial_position

        max_sell = self.position_limit + pos
        max_buy  = self.position_limit - pos

        ema_prev = self.last_traderData.get("fruit_ema", mid)
        ema = 0.1 * mid + 0.9 * ema_prev
        dev = mid - ema

        self.new_trader_data["fruit_ema"] = ema

        THRESHOLD = 8
        SIZE = 20

        if dev > THRESHOLD and max_sell > 0:
            self.sell(self.best_bid, min(SIZE, max_sell))

        elif dev < -THRESHOLD and max_buy > 0:
            self.buy(self.best_ask, min(SIZE, max_buy))

        return {self.name: self.orders}

# =========================
# OPTIONS (CLEANED)
# =========================
class OptionTrader:

    def __init__(self, state, new_trader_data):
        self.options = [ProductTrader(s, state, new_trader_data) for s in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, new_trader_data)
        self.state = state

    def bs_call(self, S, K, T, sigma=0.1):

        if T <= 0:
            return max(0, S - K)

        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        return S * _N.cdf(d1) - K * _N.cdf(d2)

    def get_orders(self):

        if self.underlying.mid is None:
            return {}

        S = self.underlying.mid
        T = 0.01

        result = {}

        for opt in self.options:

            if opt.mid is None:
                continue

            K = float(opt.name.split("_")[1])
            theo = self.bs_call(S, K, T)

            edge = opt.mid - theo

            if edge > 3:
                opt.sell(opt.best_bid, 3)

            elif edge < -3:
                opt.buy(opt.best_ask, 3)

            result[opt.name] = opt.orders

        return result

# =========================
# MAIN
# =========================
class Trader:

    def run(self, state: TradingState):

        new_trader_data = {}
        result = {}

        if STATIC_SYMBOL in state.order_depths:
            h = HydroTrader(STATIC_SYMBOL, state, new_trader_data)
            result.update(h.get_orders())

        if DYNAMIC_SYMBOL in state.order_depths:
            f = FruitTrader(DYNAMIC_SYMBOL, state, new_trader_data)
            result.update(f.get_orders())

        opt = OptionTrader(state, new_trader_data)
        result.update(opt.get_orders())

        return result, 0, json.dumps(new_trader_data)
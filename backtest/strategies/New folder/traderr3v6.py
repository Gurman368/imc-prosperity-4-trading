from datamodel import OrderDepth, TradingState, Order
import json
import math
import numpy as np
from statistics import NormalDist

_N = NormalDist()

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
# HYDROGEL (STATIC STYLE)
# =========================
class HydroTrader(ProductTrader):

    def get_orders(self):

        if self.mid is None:
            return {self.name: self.orders}

        fair = self.mid

        # TAKE
        for p, v in self.mkt_sell_orders.items():
            if p < fair:
                self.buy(p, min(v, 10))

        for p, v in self.mkt_buy_orders.items():
            if p > fair:
                self.sell(p, min(v, 10))

        # MAKE
        self.buy(fair - 1, 5)
        self.sell(fair + 1, 5)

        return {self.name: self.orders}


# =========================
# FRUIT (DYNAMIC STYLE)
# =========================
class FruitTrader(ProductTrader):

    def get_orders(self):

        if self.mid is None:
            return {self.name: self.orders}

        fair = self.mid

        skew = self.initial_position / self.position_limit

        bid = fair - 1 - skew
        ask = fair + 1 - skew

        self.buy(bid, 10)
        self.sell(ask, 10)

        return {self.name: self.orders}


# =========================
# OPTIONS (BLACK SCHOLES)
# =========================
class OptionTrader:

    def __init__(self, state, prints, new_trader_data):

        self.options = [ProductTrader(s, state, prints, new_trader_data) for s in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, prints, new_trader_data)

        self.state = state

    def bs_call(self, S, K, T, sigma=0.2):

        if T <= 0:
            return max(0, S - K), 1 if S > K else 0

        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        price = S * _N.cdf(d1) - K * _N.cdf(d2)
        delta = _N.cdf(d1)

        return price, delta

    def get_orders(self):

        if self.underlying.mid is None:
            return {}

        S = self.underlying.mid
        T = 0.01  # small time-to-expiry approx

        result = {}

        for opt in self.options:

            if opt.mid is None:
                continue

            K = float(opt.name.split("_")[1])

            theo, delta = self.bs_call(S, K, T)

            edge = opt.mid - theo

            if edge > 2:
                opt.sell(opt.best_bid, 5)

            elif edge < -2:
                opt.buy(opt.best_ask, 5)

            result[opt.name] = opt.orders

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
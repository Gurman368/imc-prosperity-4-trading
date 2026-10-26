from datamodel import OrderDepth, TradingState, Order
import json
import math
from statistics import NormalDist

_N = NormalDist()

# =========================
# SYMBOLS
# =========================
STATIC_SYMBOL = "HYDROGEL_PACK"
DYNAMIC_SYMBOL = "VELVETFRUIT_EXTRACT"
OPTION_UNDERLYING_SYMBOL = "VELVETFRUIT_EXTRACT"

OPTION_SYMBOLS = [
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500"
]

DISABLED_OPTIONS = {}

# =========================
# COUNTERPARTY INTELLIGENCE
# =========================
SMART_TRADERS = {"Mark 14", "Mark 01"}
DUMB_TRADERS  = {"Mark 38", "Mark 55"}
NEUTRAL_TRADERS = {"Mark 22", "Mark 49"}

def get_recent_trades(state, symbol):
    return state.market_trades.get(symbol, [])

# =========================
# LIMITS
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

LIMITS = POS_LIMITS

# =========================
# SUBMISSION HELPERS (FOR FRUIT)
# =========================
def sorted_bids(depth):
    return sorted(depth.buy_orders.items(), reverse=True)

def sorted_asks(depth):
    return sorted(depth.sell_orders.items())

def best_bid(depth):
    return max(depth.buy_orders) if depth.buy_orders else None

def best_ask(depth):
    return min(depth.sell_orders) if depth.sell_orders else None

def mid_price(depth):
    bid = best_bid(depth)
    ask = best_ask(depth)
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2

def spread_points(depth):
    bid = best_bid(depth)
    ask = best_ask(depth)
    if bid is None or ask is None:
        return None
    return ask - bid

def vwap_mid(depth):
    bid_vwap = None
    ask_vwap = None
    if depth.buy_orders:
        total_bid = sum(depth.buy_orders.values())
        if total_bid > 0:
            bid_vwap = sum(price * volume for price, volume in depth.buy_orders.items()) / total_bid
    if depth.sell_orders:
        total_ask = sum(-volume for volume in depth.sell_orders.values())
        if total_ask > 0:
            ask_vwap = sum(price * (-volume) for price, volume in depth.sell_orders.items()) / total_ask
    if bid_vwap is not None and ask_vwap is not None:
        return (bid_vwap + ask_vwap) / 2
    return bid_vwap if bid_vwap is not None else ask_vwap

def popular_mid(depth):
    bid = None
    ask = None
    if depth.buy_orders:
        bid = max(depth.buy_orders.items(), key=lambda level: (level[1], level[0]))[0]
    if depth.sell_orders:
        ask = min(depth.sell_orders.items(), key=lambda level: (level[1], level[0]))[0]
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2

def top_level_imbalance(depth):
    bid = best_bid(depth)
    ask = best_ask(depth)
    if bid is None or ask is None:
        return 0.0
    bid_volume = depth.buy_orders.get(bid, 0)
    ask_volume = -depth.sell_orders.get(ask, 0)
    denominator = bid_volume + ask_volume
    if denominator <= 0:
        return 0.0
    return (bid_volume - ask_volume) / denominator

def book_imbalance(depth, levels=3):
    bid_volume = sum(volume for _, volume in sorted_bids(depth)[:levels])
    ask_volume = sum(-volume for _, volume in sorted_asks(depth)[:levels])
    denominator = bid_volume + ask_volume
    if denominator <= 0:
        return 0.0
    return (bid_volume - ask_volume) / denominator

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

class HydroTrader(ProductTrader):
    def get_orders(self):
        if self.mid is None:
            return {self.name: self.orders}

        pos = self.initial_position
        max_buy = self.position_limit - pos
        max_sell = self.position_limit + pos

        BASE_QUOTE_SIZE = 12
        EJECT_THRESHOLD = 40
        DUMP_SIZE = 15

        my_bid = self.best_bid + 1 if self.best_bid else None
        my_ask = self.best_ask - 1 if self.best_ask else None

        if my_bid and my_ask and my_bid >= my_ask:
            my_bid = self.best_bid
            my_ask = self.best_ask

        bid_vol = max(1, BASE_QUOTE_SIZE - pos) 
        ask_vol = max(1, BASE_QUOTE_SIZE + pos)

        bid_vol = min(bid_vol, max_buy)
        ask_vol = min(ask_vol, max_sell)

        if my_ask and max_sell > 0 and pos < EJECT_THRESHOLD:
            if self.best_bid is None or my_ask > self.best_bid:
                self.sell(my_ask, ask_vol)

        if my_bid and max_buy > 0 and pos > -EJECT_THRESHOLD:
            if self.best_ask is None or my_bid < self.best_ask:
                self.buy(my_bid, bid_vol)

        if pos >= EJECT_THRESHOLD and self.best_bid:
            qty_to_dump = min(pos, DUMP_SIZE)
            self.sell(self.best_bid, qty_to_dump)

        if pos <= -EJECT_THRESHOLD and self.best_ask:
            qty_to_cover = min(-pos, DUMP_SIZE)
            self.buy(self.best_ask, qty_to_cover)

        return {self.name: self.orders}

# ==========================================
# HYBRID FRUIT TRADER (FROM SUBMISSION)
# ==========================================
class FruitTrader(ProductTrader):
    # Parameters from submission file for VELVETFRUIT_EXTRACT
    ANCHOR = 5250.0
    ALPHA = 0.80
    ANCHOR_WEIGHT = 0.15
    POPULAR_WEIGHT = 0.65
    IMBALANCE_WEIGHT = 0.35
    TAKE_EDGE = 2.0
    MAKE_EDGE = 1.0
    QUOTE_SIZE = 28
    MAX_TAKE_SIZE = 32
    SOFT_LIMIT = 140
    SKEW_K = 10.0

    def get_orders(self):
        depth = self.state.order_depths.get(self.name)
        if not depth or (not depth.buy_orders and not depth.sell_orders):
            return {self.name: []}

        pos = self.initial_position
        limit = self.position_limit
        
        # Load Fair from traderData
        fair = self.last_traderData.get("fruit_fair", self.ANCHOR)
        
        # Calculate Observed Fair
        mid = mid_price(depth) or fair
        pop = popular_mid(depth) or mid
        vwap = vwap_mid(depth) or mid
        market_fair = self.POPULAR_WEIGHT * pop + (1.0 - self.POPULAR_WEIGHT) * vwap
        spread = spread_points(depth) or 1.0
        imbalance = 0.6 * top_level_imbalance(depth) + 0.4 * book_imbalance(depth)
        anchored = self.ANCHOR_WEIGHT * self.ANCHOR + (1.0 - self.ANCHOR_WEIGHT) * market_fair
        observed = anchored + self.IMBALANCE_WEIGHT * spread * imbalance
        
        # Update Fair with EMA
        fair = self.ALPHA * observed + (1.0 - self.ALPHA) * fair
        self.new_trader_data["fruit_fair"] = fair

        buy_headroom = limit - pos
        sell_headroom = limit + pos
        
        # Taker logic
        max_buy_take = math.floor(fair - self.TAKE_EDGE)
        min_sell_take = math.ceil(fair + self.TAKE_EDGE)

        for ask_price, ask_volume in sorted_asks(depth):
            if ask_price > max_buy_take or buy_headroom <= 0:
                break
            qty = min(-ask_volume, buy_headroom, self.MAX_TAKE_SIZE)
            if qty > 0:
                self.buy(ask_price, qty)
                buy_headroom -= qty

        for bid_price, bid_volume in sorted_bids(depth):
            if bid_price < min_sell_take or sell_headroom <= 0:
                break
            qty = min(bid_volume, sell_headroom, self.MAX_TAKE_SIZE)
            if qty > 0:
                self.sell(bid_price, qty)
                sell_headroom -= qty

        # Maker logic (Quoting)
        center = fair - self.SKEW_K * pos / limit
        bid_quote = math.floor(center - self.MAKE_EDGE)
        ask_quote = math.ceil(center + self.MAKE_EDGE)
        
        best_b = best_bid(depth)
        best_a = best_ask(depth)
        
        if best_b is not None:
            bid_quote = min(best_b + 1, bid_quote)
        if best_a is not None:
            ask_quote = max(best_a - 1, ask_quote)
            
        if bid_quote >= ask_quote:
            rounded = round(center)
            bid_quote = rounded - 1
            ask_quote = rounded + 1

        if buy_headroom > 0 and pos < self.SOFT_LIMIT:
            self.buy(max(bid_quote, 0), min(self.QUOTE_SIZE, buy_headroom))
        if sell_headroom > 0 and pos > -self.SOFT_LIMIT:
            self.sell(max(ask_quote, 1), min(self.QUOTE_SIZE, sell_headroom))

        return {self.name: self.orders}
       
# =========================
# OPTIONS (UNCHANGED)
# =========================
class OptionTrader:

    # 🔥 initial anchors (priors)
    ANCHORS = {
        "VEV_4000": 1250,
        "VEV_4500": 747,
        "VEV_5000": 255,
        "VEV_5100": 167,
        "VEV_5200": 96,
        "VEV_5300": 47,
        "VEV_5400": 16,
        "VEV_5500": 7,
        "VEV_6000": 1,
        "VEV_6500": 1,
    }

    # 🔥 scaling base
    DEV_FULL_MAP = {
        "VEV_4000": 30,
        "VEV_4500": 30,
        "VEV_5000": 25,
        "VEV_5100": 20,
        "VEV_5200": 10,
        "VEV_5300": 10,
        "VEV_5400": 10,
        "VEV_5500": 10,
        "VEV_6000": 1,
        "VEV_6500": 1,
    }

    EMA_ALPHA = 0.00005
    K = 0.008   # 🔥 NEW: sensitivity control (tune this!)
    LIMIT = 300
    MAX_STEP = 5

    def __init__(self, state, new_trader_data):
        self.options = [ProductTrader(s, state, new_trader_data) for s in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, new_trader_data)

        self.state = state
        self.new_trader_data = new_trader_data

        try:
            self.last_traderData = json.loads(state.traderData) if state.traderData else {}
        except:
            self.last_traderData = {}

    # 🔵 Black-Scholes
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

            if opt.name in DISABLED_OPTIONS:
                continue

            if opt.mid is None or opt.best_bid is None or opt.best_ask is None:
                continue

            name = opt.name
            mid = opt.mid
            pos = opt.initial_position

            # =========================================================
            # 🔵 BS (deep ITM)
            # =========================================================
            if name in []:    #"VEV_4000", "VEV_4500"

                K_strike = float(name.split("_")[1])
                theo = self.bs_call(S, K_strike, T)

                edge = mid - theo

                if edge > 3:
                    opt.sell(opt.best_bid, 5)
                elif edge < -3:
                    opt.buy(opt.best_ask, 5)

                result[name] = opt.orders
                continue

            # =========================================================
            # 🔴 ANCHORED + ADAPTIVE + K FILTER
            # =========================================================

            # ---- anchor ----
            anchor_prev = self.last_traderData.get(
                f"opt_anchor_{name}",
                self.ANCHORS.get(name, mid)
            )

            anchor = anchor_prev + self.EMA_ALPHA * (mid - anchor_prev)
            self.new_trader_data[f"opt_anchor_{name}"] = anchor

            dev = mid - anchor
            dev_full = self.DEV_FULL_MAP.get(name, 40)

            # 🔥 threshold using k
            threshold = 0.5*self.K * dev_full

            # ---- only trade beyond threshold ----
            if abs(dev) <= threshold:
                target = 0
            else:
                effective_dev = abs(dev) - threshold

                scaled = int(self.LIMIT * effective_dev / dev_full)
                scaled = min(self.LIMIT, scaled)

                if dev > 0:
                    target = -scaled
                else:
                    target = scaled

            delta = target - pos

            # clamp
            if delta > 0:
                delta = min(delta, self.MAX_STEP)
            else:
                delta = max(delta, -self.MAX_STEP)

            # =========================================================
            # EXECUTION (good price only)
            # =========================================================

            if delta > 0:
                for ask_p in sorted(opt.mkt_sell_orders.keys()):
                    if ask_p >= anchor:
                        break
                    vol = min(abs(opt.mkt_sell_orders[ask_p]), delta)
                    if vol > 0:
                        opt.buy(ask_p, vol)
                        delta -= vol
                    if delta <= 0:
                        break

            elif delta < 0:
                for bid_p in sorted(opt.mkt_buy_orders.keys(), reverse=True):
                    if bid_p <= anchor:
                        break
                    vol = min(abs(opt.mkt_buy_orders[bid_p]), -delta)
                    if vol > 0:
                        opt.sell(bid_p, vol)
                        delta += vol
                    if delta >= 0:
                        break

            result[name] = opt.orders

        return result

# =========================
# MAIN
# =========================
class Trader:

    def run(self, state: TradingState):

        new_trader_data = {}
        result = {}

        if STATIC_SYMBOL in state.order_depths:
            result.update(HydroTrader(STATIC_SYMBOL, state, new_trader_data).get_orders())

        if DYNAMIC_SYMBOL in state.order_depths:
            result.update(FruitTrader(DYNAMIC_SYMBOL, state, new_trader_data).get_orders())

        result.update(OptionTrader(state, new_trader_data).get_orders())

        return result, 0, json.dumps(new_trader_data)
from datamodel import OrderDepth, TradingState, Order
import json
import math
from statistics import NormalDist

_N = NormalDist()

# =========================
# PARAMS LOADING (NEW)
# =========================
try:
    with open("params.json", "r") as f:
        PARAMS = json.load(f)
except:
    PARAMS = {}

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
# HYDRO
# =========================
class HydroTrader(ProductTrader):

    EMA_ALPHA = 0.04
    MAD_ALPHA = 0.02
    K = 3
    BASE_THRESHOLD = 20

    STOP_LOSS_DEV = 30
    COOLDOWN_PERIOD = 50

    def get_orders(self):

        if self.mid is None:
            return {self.name: self.orders}

        mid = self.mid
        pos = self.initial_position

        max_sell = self.position_limit + pos
        max_buy  = self.position_limit - pos

        cooldown = self.last_traderData.get("hp_cooldown", 0)
        cooldown = max(0, cooldown - 1)

        ema_prev = self.last_traderData.get("hp_ema", mid)
        ema = ema_prev + self.EMA_ALPHA * (mid - ema_prev)
        dev = mid - ema

        stats = self.last_traderData.get("hp_stats", {"mean": 0, "mad": 1})
        mean = stats["mean"]
        mad = stats["mad"]

        mean = mean + self.MAD_ALPHA * (dev - mean)
        mad = mad + self.MAD_ALPHA * (abs(dev - mean) - mad)

        threshold = max(self.BASE_THRESHOLD, self.K * mad)

        recent_trades = get_recent_trades(self.state, self.name)
        bias = 0

        for trade in recent_trades:
            if trade.seller in DUMB_TRADERS:
                bias += 2
            if trade.buyer in DUMB_TRADERS:
                bias -= 2

        threshold -= bias * 2
        threshold = max(5, threshold)

        self.new_trader_data["hp_ema"] = ema
        self.new_trader_data["hp_stats"] = {"mean": mean, "mad": mad}

        if pos < 0 and dev > self.STOP_LOSS_DEV:
            cover = abs(pos)
            for ask_p in sorted(self.mkt_sell_orders.keys()):
                vol = min(abs(self.mkt_sell_orders[ask_p]), cover)
                if vol > 0:
                    self.buy(ask_p, vol)
                    cover -= vol
                if cover <= 0:
                    break
            cooldown = self.COOLDOWN_PERIOD

        elif cooldown == 0 and dev > threshold and max_sell > 0:
            for bid_p in sorted(self.mkt_buy_orders.keys(), reverse=True):
                vol = min(abs(self.mkt_buy_orders[bid_p]), max_sell)
                if vol > 0:
                    self.sell(bid_p, vol)
                    max_sell -= vol
                if max_sell <= 0:
                    break

        if cooldown == 0 and self.best_bid and self.best_ask:

            if max_sell > 0:
                ask = self.best_ask - 1
                if ask > self.best_bid:
                    self.sell(ask, min(15, max_sell))

            if max_buy > 0:
                bid = self.best_bid + 1
                if bid < self.best_ask:
                    self.buy(bid, min(15, max_buy))

        self.new_trader_data["hp_cooldown"] = cooldown

        return {self.name: self.orders}

# =========================
# FRUIT
# =========================
class FruitTrader(ProductTrader):

    EMA_ALPHA = 0.04
    BASE_SPREAD = 8
    INVENTORY_AVERSION = 0.01
    MAX_POS_RATIO = 0.8

    STOP_LOSS = 80
    COOLDOWN = 30

    def get_orders(self):

        if self.mid is None:
            return {self.name: self.orders}

        mid = self.mid
        pos = self.initial_position
        limit = self.position_limit

        max_buy  = limit - pos
        max_sell = limit + pos

        cooldown = self.last_traderData.get("fruit_cd", 0)
        cooldown = max(0, cooldown - 1)

        ema_prev = self.last_traderData.get("fruit_ema", mid)
        ema = ema_prev + self.EMA_ALPHA * (mid - ema_prev)

        self.new_trader_data["fruit_ema"] = ema

        if abs(pos) > self.STOP_LOSS:
            if pos > 0:
                self.sell(self.best_bid, pos)
            else:
                self.buy(self.best_ask, -pos)

            cooldown = self.COOLDOWN
            self.new_trader_data["fruit_cd"] = cooldown
            return {self.name: self.orders}

        fair_price = ema - self.INVENTORY_AVERSION * pos

        bid_price = fair_price - self.BASE_SPREAD
        ask_price = fair_price + self.BASE_SPREAD

        signal = 0
        for t in get_recent_trades(self.state, self.name):
            if t.seller in DUMB_TRADERS:
                signal += 1
            if t.buyer in DUMB_TRADERS:
                signal -= 1

        signal = max(-2, min(2, signal))

        bid_price += signal
        ask_price += signal

        max_pos = int(self.MAX_POS_RATIO * limit)

        if cooldown == 0:

            if pos < max_pos and max_buy > 0:
                price = min(bid_price, self.best_ask - 1) if self.best_ask else bid_price
                self.buy(price, min(15, max_buy))

            if pos > -max_pos and max_sell > 0:
                price = max(ask_price, self.best_bid + 1) if self.best_bid else ask_price
                self.sell(price, min(15, max_sell))

        if pos > 0 and mid > ema:
            self.sell(self.best_bid, min(pos, 20))
        elif pos < 0 and mid < ema:
            self.buy(self.best_ask, min(-pos, 20))

        self.new_trader_data["fruit_cd"] = cooldown

        return {self.name: self.orders}

# =========================
# OPTIONS (UPDATED)
# =========================
class OptionTrader:

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

    DEV_FULL_MAP = {
        "VEV_4000": 50,
        "VEV_4500": 50,
        "VEV_5000": 25,
        "VEV_5100": 35,
        "VEV_5200": 50,
        "VEV_5300": 30,
        "VEV_5400": 15,
        "VEV_5500": 15,
        "VEV_6000": 5,
        "VEV_6500": 5,
    }

    EMA_ALPHA = 0.0002
    K = 0.008
    LIMIT = 300
    MAX_STEP = 10

    def __init__(self, state, new_trader_data):
        self.options = [ProductTrader(s, state, new_trader_data) for s in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, new_trader_data)

        self.state = state
        self.new_trader_data = new_trader_data

        # 🔥 use optimized dev_map if provided
        self.dev_map = PARAMS.get("dev_map", self.DEV_FULL_MAP)

        try:
            self.last_traderData = json.loads(state.traderData) if state.traderData else {}
        except:
            self.last_traderData = {}

    def get_orders(self):

        if self.underlying.mid is None:
            return {}

        result = {}

        for opt in self.options:

            if opt.name in DISABLED_OPTIONS:
                continue

            if opt.mid is None or opt.best_bid is None or opt.best_ask is None:
                continue

            name = opt.name
            mid = opt.mid
            pos = opt.initial_position

            anchor_prev = self.last_traderData.get(
                f"opt_anchor_{name}",
                self.ANCHORS.get(name, mid)
            )

            anchor = anchor_prev + self.EMA_ALPHA * (mid - anchor_prev)
            self.new_trader_data[f"opt_anchor_{name}"] = anchor

            dev = mid - anchor
            dev_full = self.dev_map.get(name, 40)

            threshold = self.K * dev_full

            if abs(dev) <= threshold:
                target = 0
            else:
                effective_dev = abs(dev) - threshold
                scaled = min(self.LIMIT, int(self.LIMIT * effective_dev / dev_full))
                target = -scaled if dev > 0 else scaled

            delta = max(-self.MAX_STEP, min(self.MAX_STEP, target - pos))

            if delta > 0:
                for ask in sorted(opt.mkt_sell_orders):
                    if ask >= anchor:
                        break
                    vol = min(abs(opt.mkt_sell_orders[ask]), delta)
                    if vol > 0:
                        opt.buy(ask, vol)
                        delta -= vol
                    if delta <= 0:
                        break

            elif delta < 0:
                for bid in sorted(opt.mkt_buy_orders, reverse=True):
                    if bid <= anchor:
                        break
                    vol = min(abs(opt.mkt_buy_orders[bid]), -delta)
                    if vol > 0:
                        opt.sell(bid, vol)
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
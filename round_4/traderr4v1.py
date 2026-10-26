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
# HYDRO (WITH FLOW BIAS)
# =========================
class HydroTrader(ProductTrader):

    EMA_ALPHA = 0.01
    MAD_ALPHA = 0.02
    K = 3
    BASE_THRESHOLD = 15

    STOP_LOSS_DEV = 35
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

        # 🔥 FLOW BIAS
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
# FRUIT (WITH FLOW OVERRIDE)
# =========================
class FruitTrader(ProductTrader):

    EMA_ALPHA = 0.01
    MAD_ALPHA = 0.03
    K = 3
    BASE_THRESHOLD = 13

    STOP_LOSS_DEV = 30
    COOLDOWN_PERIOD = 40

    def get_orders(self):

        if self.mid is None:
            return {self.name: self.orders}

        mid = self.mid
        pos = self.initial_position

        max_sell = self.position_limit + pos
        max_buy  = self.position_limit - pos

        cooldown = self.last_traderData.get("fruit_cooldown", 0)
        cooldown = max(0, cooldown - 1)

        ema_prev = self.last_traderData.get("fruit_ema", mid)
        ema = ema_prev + self.EMA_ALPHA * (mid - ema_prev)
        dev = mid - ema

        stats = self.last_traderData.get("fruit_stats", {"mean": 0, "mad": 1})
        mean = stats["mean"]
        mad = stats["mad"]

        mean = mean + self.MAD_ALPHA * (dev - mean)
        mad = mad + self.MAD_ALPHA * (abs(dev - mean) - mad)

        threshold = max(self.BASE_THRESHOLD, self.K * mad)

        self.new_trader_data["fruit_ema"] = ema
        self.new_trader_data["fruit_stats"] = {"mean": mean, "mad": mad}

        # =========================
        # 🔥 COUNTERPARTY SIGNAL
        # =========================
        recent_trades = get_recent_trades(self.state, self.name)

        signal_buy = 0
        signal_sell = 0

        for trade in recent_trades:

            if trade.seller in SMART_TRADERS:
                signal_buy += 2
            if trade.buyer in SMART_TRADERS:
                signal_sell += 1

            if trade.seller in DUMB_TRADERS:
                signal_buy += 3
            if trade.buyer in DUMB_TRADERS:
                signal_sell += 3

            # 🚀 MAX EDGE
            if trade.seller == "Mark 38" and trade.buyer == "Mark 14":
                signal_buy += 5

        signal_buy = min(signal_buy, 5)
        signal_sell = min(signal_sell, 5)

        # =========================
        # PRIORITY TRADING
        # =========================
        if cooldown == 0:

            if signal_buy > 0 and max_buy > 0:
                size = min(max_buy, 5 * signal_buy)

                for ask_p in sorted(self.mkt_sell_orders.keys()):
                    vol = min(abs(self.mkt_sell_orders[ask_p]), size)
                    if vol > 0:
                        self.buy(ask_p, vol)
                        size -= vol
                    if size <= 0:
                        break

            elif signal_sell > 0 and max_sell > 0:
                size = min(max_sell, 5 * signal_sell)

                for bid_p in sorted(self.mkt_buy_orders.keys(), reverse=True):
                    vol = min(abs(self.mkt_buy_orders[bid_p]), size)
                    if vol > 0:
                        self.sell(bid_p, vol)
                        size -= vol
                    if size <= 0:
                        break

            elif dev > threshold and max_sell > 0:
                for bid_p in sorted(self.mkt_buy_orders.keys(), reverse=True):
                    vol = min(abs(self.mkt_buy_orders[bid_p]), max_sell)
                    if vol > 0:
                        self.sell(bid_p, vol)
                        max_sell -= vol
                    if max_sell <= 0:
                        break

            elif dev < -threshold and max_buy > 0:
                for ask_p in sorted(self.mkt_sell_orders.keys()):
                    vol = min(abs(self.mkt_sell_orders[ask_p]), max_buy)
                    if vol > 0:
                        self.buy(ask_p, vol)
                        max_buy -= vol
                    if max_buy <= 0:
                        break

        if cooldown == 0 and self.best_bid and self.best_ask:

            if max_sell > 0:
                ask = self.best_ask - 1
                if ask > self.best_bid:
                    self.sell(ask, min(10, max_sell))

            if max_buy > 0:
                bid = self.best_bid + 1
                if bid < self.best_ask:
                    self.buy(bid, min(10, max_buy))

        self.new_trader_data["fruit_cooldown"] = cooldown

        return {self.name: self.orders}

# =========================
# OPTIONS (UNCHANGED)
# =========================
class OptionTrader:

    # 🔥 initial anchors (priors)
    ANCHORS = {
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
        "VEV_5000": 25,
        "VEV_5100": 35,
        "VEV_5200": 60,
        "VEV_5300": 60,
        "VEV_5400": 30,
        "VEV_5500": 20,
        "VEV_6000": 5,
        "VEV_6500": 5,
    }

    EMA_ALPHA = 0.001
    K = 0.001   # 🔥 NEW: sensitivity control (tune this!)
    LIMIT = 300
    MAX_STEP = 25

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
            if name in ["VEV_4000", "VEV_4500"]:

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
            threshold = self.K * dev_full

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
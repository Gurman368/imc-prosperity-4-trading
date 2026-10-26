from datamodel import OrderDepth, TradingState, Order
import json
import math
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

# ❌ Disable bad strikes
DISABLED_OPTIONS = {}

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
# HYDRO (WINNER)
# =========================
class HydroTrader(ProductTrader):

    # =========================
    # PARAMETERS (from their strat)
    # =========================
    TAKE_WIDTH = 1
    CLEAR_WIDTH = 0
    MIN_EDGE = 2.5
    ADVERSE_VOLUME = 15
    PREVENT_ADVERSE = True
    REVERSION_BETA = -0.5

    TRUE_PRICE = 10000
    TRUE_STD = 5.5

    HISTORY_SIZE = 6

    def get_orders(self):

        if self.best_bid is None or self.best_ask is None:
            return {self.name: self.orders}

        pos = self.initial_position

        # =========================
        # LOAD STATE
        # =========================
        history = self.last_traderData.get("hp_history", [])

        # =========================
        # FAIR VALUE (THEIR LOGIC)
        # =========================
        bids = self.mkt_buy_orders
        asks = self.mkt_sell_orders

        best_bid = self.best_bid
        best_ask = self.best_ask

        # Filter large orders (avoid noise)
        large_bids = [p for p, v in bids.items() if v >= self.ADVERSE_VOLUME]
        large_asks = [p for p, v in asks.items() if -v >= self.ADVERSE_VOLUME]

        mm_bid = max(large_bids) if large_bids else None
        mm_ask = min(large_asks) if large_asks else None

        if mm_bid is None or mm_ask is None:
            mid = (best_bid + best_ask) / 2
        else:
            mid = (mm_bid + mm_ask) / 2

        # Reversion adjustment
        if history:
            last_price = history[-1]
            ret = (mid - last_price) / last_price if last_price != 0 else 0
            fair = mid + mid * (ret * self.REVERSION_BETA)
        else:
            fair = mid

        # update history
        history.append(mid)
        if len(history) > self.HISTORY_SIZE:
            history.pop(0)

        # =========================
        # Z-SCORE
        # =========================
        z = (mid - self.TRUE_PRICE) / self.TRUE_STD

        max_buy  = self.position_limit - pos
        max_sell = self.position_limit + pos

        bought = 0
        sold = 0

        # =========================
        # 🔥 1. Z-SCORE AGGRESSIVE TRADING
        # =========================
        if z <= -3 and asks:
            best_ask = min(asks)
            vol = min(-asks[best_ask], max_buy)
            if vol > 0:
                self.buy(best_ask, vol)
                bought += vol

        elif z >= 3 and bids:
            best_bid = max(bids)
            vol = min(bids[best_bid], max_sell)
            if vol > 0:
                self.sell(best_bid, vol)
                sold += vol

        # =========================
        # 🟢 2. TAKE ORDERS (EDGE)
        # =========================
        if asks:
            best_ask = min(asks)
            ask_vol = -asks[best_ask]

            if ((ask_vol < self.ADVERSE_VOLUME or not self.PREVENT_ADVERSE)
                and best_ask <= fair - self.TAKE_WIDTH):

                qty = min(2 * ask_vol, max_buy - bought)
                if qty > 0:
                    self.buy(best_ask, qty)
                    bought += qty

        if bids:
            best_bid = max(bids)
            bid_vol = bids[best_bid]

            if ((bid_vol < self.ADVERSE_VOLUME or not self.PREVENT_ADVERSE)
                and best_bid >= fair + self.TAKE_WIDTH):

                qty = min(2 * bid_vol, max_sell - sold)
                if qty > 0:
                    self.sell(best_bid, qty)
                    sold += qty

        # =========================
        # 🟡 3. CLEAR INVENTORY
        # =========================
        pos_after = pos + bought - sold

        clear_bid = round(fair - self.CLEAR_WIDTH)
        clear_ask = round(fair + self.CLEAR_WIDTH)

        if pos_after > 0 and bids:
            qty = min(pos_after, max_sell - sold)
            if qty > 0:
                self.sell(clear_ask, qty)
                sold += qty

        if pos_after < 0 and asks:
            qty = min(-pos_after, max_buy - bought)
            if qty > 0:
                self.buy(clear_bid, qty)
                bought += qty

        # =========================
        # 🔵 4. MARKET MAKING
        # =========================
        passive_bid = round(fair - self.MIN_EDGE)
        passive_ask = round(fair + self.MIN_EDGE)

        if max_buy - bought > 0:
            self.buy(passive_bid, max_buy - bought)

        if max_sell - sold > 0:
            self.sell(passive_ask, max_sell - sold)

        # =========================
        # SAVE STATE
        # =========================
        self.new_trader_data["hp_history"] = history

        return {self.name: self.orders}
    
# =========================
# 🍇 FRUIT (THEIR Z-SCORE STRATEGY)
# =========================
class FruitTrader(ProductTrader):

    WINDOW = 60
    Z_THRESHOLD = 1.1
    TRADE_SIZE = 6

    def get_orders(self):

        if self.best_bid is None or self.best_ask is None:
            return {self.name: self.orders}

        mid = (self.best_bid + self.best_ask) / 2
        pos = self.initial_position

        max_buy  = self.position_limit - pos
        max_sell = self.position_limit + pos

        # =========================
        # LOAD STATE
        # =========================
        prices = self.last_traderData.get("fruit_prices", [])
        last_ema = self.last_traderData.get("fruit_ema", None)

        prices.append(mid)

        # =========================
        # NEED ENOUGH DATA
        # =========================
        if len(prices) < self.WINDOW:
            self.new_trader_data["fruit_prices"] = prices
            self.new_trader_data["fruit_ema"] = last_ema
            return {self.name: self.orders}

        # =========================
        # EMA CALCULATION
        # =========================
        alpha = 2 / (self.WINDOW + 1)

        if last_ema is None:
            ema = sum(prices[-self.WINDOW:]) / self.WINDOW
        else:
            ema = alpha * mid + (1 - alpha) * last_ema

        # =========================
        # STD + Z-SCORE
        # =========================
        recent = prices[-self.WINDOW:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std = math.sqrt(variance)

        z = 0 if std == 0 else (mid - ema) / std

        # =========================
        # TRADING LOGIC (THEIR CORE EDGE)
        # =========================
        if z < -self.Z_THRESHOLD and max_buy > 0:
            qty = min(self.TRADE_SIZE, max_buy)
            self.buy(int(self.best_bid + 1), qty)

        elif z > self.Z_THRESHOLD and max_sell > 0:
            qty = min(self.TRADE_SIZE, max_sell)
            self.sell(int(self.best_ask - 1), qty)

        # =========================
        # SAVE STATE
        # =========================
        self.new_trader_data["fruit_prices"] = prices[-self.WINDOW:]
        self.new_trader_data["fruit_ema"] = ema

        return {self.name: self.orders}


# =========================
# OPTIONS (ANCHOR MEAN REVERSION)
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
            h = HydroTrader(STATIC_SYMBOL, state, new_trader_data)
            result.update(h.get_orders())

        if DYNAMIC_SYMBOL in state.order_depths:
            f = FruitTrader(DYNAMIC_SYMBOL, state, new_trader_data)
            result.update(f.get_orders())

        opt = OptionTrader(state, new_trader_data)
        result.update(opt.get_orders())

        return result, 0, json.dumps(new_trader_data)
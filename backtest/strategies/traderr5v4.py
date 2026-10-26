from datamodel import OrderDepth, TradingState, Order
import json, numpy as np

DEFAULT_LIMIT = 10

def ensure_limits(state):
    try:
        import prosperity4bt.runner as _p4_runner
        for p in state.order_depths:
            if p not in _p4_runner.LIMITS:
                _p4_runner.LIMITS[p] = DEFAULT_LIMIT
    except:
        pass

def best_bid(d): return max(d.buy_orders)  if d.buy_orders  else None
def best_ask(d): return min(d.sell_orders) if d.sell_orders else None
def mid(d):
    b, a = best_bid(d), best_ask(d)
    return (b + a) / 2 if b and a else None

LIMIT = 10


# =========================
# 🔵 TREND FOLLOWER (cleaned)
# =========================
class TrendFollower:

    PRODUCTS = [
        ("UV_VISOR_ORANGE",          1.010),
        ("UV_VISOR_RED",             1.010),
        ("TRANSLATOR_GRAPHITE_MIST", 1.005),
        ("SLEEP_POD_COTTON",         1.005),
    ]

    MA_WIN = 100

    def __init__(self, state, td):
        self.state  = state
        self.td     = td
        self.orders = {}

    def place(self, p, price, qty):
        self.orders.setdefault(p, []).append(Order(p, int(price), int(qty)))

    def _mean(self, p, price):
        h = self.td.setdefault(f"h_{p}", [])
        h.append(float(price))
        if len(h) > self.MA_WIN:
            h.pop(0)
        return sum(h) / len(h)

    def run(self):
        for p, gate in self.PRODUCTS:
            if p not in self.state.order_depths:
                continue
            ask = best_ask(self.state.order_depths[p])
            if ask is None:
                continue

            mean = self._mean(p, ask)
            pos  = self.state.position.get(p, 0)
            want = LIMIT - pos

            if want > 0 and ask < mean * gate:
                self.place(p, ask, min(want, LIMIT))

        return self.orders


# =========================
# 🔴 SHORT SELLER (unchanged)
# =========================
class ShortSeller:

    SHORTS = ["UV_VISOR_AMBER"]

    MA_WIN = 100

    def __init__(self, state, td):
        self.state  = state
        self.td     = td
        self.orders = {}

    def place(self, p, price, qty):
        self.orders.setdefault(p, []).append(Order(p, int(price), int(qty)))

    def _mean(self, p, price):
        h = self.td.setdefault(f"hs_{p}", [])
        h.append(float(price))
        if len(h) > self.MA_WIN:
            h.pop(0)
        return sum(h) / len(h)

    def run(self):
        for p in self.SHORTS:
            if p not in self.state.order_depths:
                continue

            bid = best_bid(self.state.order_depths[p])
            if bid is None:
                continue

            mean = self._mean(p, bid)
            pos  = self.state.position.get(p, 0)
            want = -LIMIT - pos

            if want < 0 and bid < mean * 1.002:
                self.place(p, bid, max(want, -LIMIT))

        return self.orders


# =========================
# 🟣 BOLLINGER REVERSAL (NEW)
# =========================
class BollingerReversion:

    PRODUCTS = [
        # --- Original loss-makers ---
        "GALAXY_SOUNDS_BLACK_HOLES",
        "MICROCHIP_SQUARE",
        "OXYGEN_SHAKE_GARLIC",
        "PANEL_2X4",
        "PEBBLES_L",
        "PEBBLES_XS",
        "SLEEP_POD_POLYESTER",
        "SNACKPACK_RASPBERRY",
        "SNACKPACK_STRAWBERRY",
        "SNACKPACK_VANILLA",
        "UV_VISOR_MAGENTA",

        # --- NEW: zero-PnL products added ---
        "GALAXY_SOUNDS_DARK_MATTER",      # NEW
        "GALAXY_SOUNDS_PLANETARY_RINGS",  # NEW
        "GALAXY_SOUNDS_SOLAR_FLAMES",     # NEW
        "GALAXY_SOUNDS_SOLAR_WINDS",      # NEW

        "MICROCHIP_OVAL",                 # NEW
        "MICROCHIP_RECTANGLE",            # NEW
        "MICROCHIP_TRIANGLE",             # NEW

        "OXYGEN_SHAKE_MINT",              # NEW
        "OXYGEN_SHAKE_MORNING_BREATH",    # NEW

        "PANEL_1X2",                      # NEW
        "PANEL_1X4",                      # NEW
        "PANEL_2X2",                      # NEW
        "PANEL_4X4",                      # NEW

        "PEBBLES_M",                      # NEW
        "PEBBLES_S",                      # NEW
        "PEBBLES_XL",                     # NEW

        "SLEEP_POD_LAMB_WOOL",            # NEW
        "SLEEP_POD_NYLON",                # NEW
        "SLEEP_POD_SUEDE",                # NEW

        "TRANSLATOR_ASTRO_BLACK",         # NEW
        "TRANSLATOR_SPACE_GRAY",          # NEW
        "TRANSLATOR_VOID_BLUE",           # NEW

        "UV_VISOR_YELLOW",                # NEW
    ]



    WINDOW_MAP = {
        # --- Original ---
        "MICROCHIP_SQUARE": 1700,
        "GALAXY_SOUNDS_BLACK_HOLES": 2000,
        "OXYGEN_SHAKE_GARLIC": 2000,
        "PANEL_2X4": 3500,
        "PEBBLES_L": 900,
        "PEBBLES_XS": 500,
        "SLEEP_POD_POLYESTER": 3000,
        "SNACKPACK_RASPBERRY": 2000,
        "SNACKPACK_STRAWBERRY": 1500,
        "SNACKPACK_VANILLA": 3500,
        "UV_VISOR_MAGENTA": 1000,

        # --- NEW: mapped by group ---
        # Galaxy → same as BLACK_HOLES
        "GALAXY_SOUNDS_DARK_MATTER": 2000,      # NEW
        "GALAXY_SOUNDS_PLANETARY_RINGS": 2000,  # NEW
        "GALAXY_SOUNDS_SOLAR_FLAMES": 2000,     # N
        "GALAXY_SOUNDS_SOLAR_WINDS": 2000,      # NEW

        # Microchip → same as SQUARE
        "MICROCHIP_OVAL": 1700,                 # NEW
        "MICROCHIP_RECTANGLE": 1700,            # NEW
        "MICROCHIP_TRIANGLE": 1700,             # NEW

        # Oxygen → same as GARLIC
        "OXYGEN_SHAKE_MINT": 2000,              # NEW
        "OXYGEN_SHAKE_MORNING_BREATH": 2000,    # NEW

        # Panel → same as 2X4
        "PANEL_1X2": 3500,                     # N
        "PANEL_1X4": 3500,                     # NEW
        "PANEL_2X2": 3500,                     # NEW
        "PANEL_4X4": 3500,                     # NEW

        # Pebbles → interpolate sizes
        "PEBBLES_M": 700,                      # NEW (between XS=500, L=900)
        "PEBBLES_S": 600,                      # NEW
        "PEBBLES_XL": 1000,                    # NEW

        # Sleep pods → same as POLYESTER
        "SLEEP_POD_LAMB_WOOL": 3000,           # NEW
        "SLEEP_POD_NYLON": 3000,               # NEW
        "SLEEP_POD_SUEDE": 3000,               # NEW

        # Translator → same as GRAPHITE_MIST (~mid)
        "TRANSLATOR_ASTRO_BLACK": 1500,        # NEW
        "TRANSLATOR_SPACE_GRAY": 1500,         # NEW
        "TRANSLATOR_VOID_BLUE": 1500,          # NEW

        # UV visor → same as MAGENTA
        "UV_VISOR_YELLOW": 1000,               # NEW
    }

    K = 2

    def __init__(self, state, td):
        self.state  = state
        self.td     = td
        self.orders = {}

    def place(self, p, price, qty):
        self.orders.setdefault(p, []).append(Order(p, int(price), int(qty)))

    def _update_hist(self, key, val, maxlen):
        h = self.td.setdefault(key, [])
        h.append(val)
        if len(h) > maxlen:
            h.pop(0)
        return h

    def _ema(self, series, span):
        if len(series) < span:
            return None
        alpha = 2 / (span + 1)
        ema = series[0]
        for x in series[1:]:
            ema = alpha * x + (1 - alpha) * ema
        return ema

    def run(self):
        for p in self.PRODUCTS:
            if p not in self.state.order_depths:
                continue

            d = self.state.order_depths[p]
            m = mid(d)
            if m is None:
                continue

            pos = self.state.position.get(p, 0)
            win = self.WINDOW_MAP[p]

            hist = self._update_hist(f"bb_{p}", m, win)

            if len(hist) < 20:
                continue

            mean = np.mean(hist)
            std  = np.std(hist)

            upper = mean + self.K * std
            lower = mean - self.K * std

            # 🔥 TREND FILTER
            ema_fast = self._ema(hist[-50:], 10)
            ema_slow = self._ema(hist[-200:], 30)

            trending = False
            if ema_fast and ema_slow:
                trending = abs(ema_fast - ema_slow) > std * 0.5

            size = 3  # partial sizing

            # 🚫 Skip if trending strongly
            if trending:
                continue

            # BUY LOW
            if m < lower and pos < LIMIT:
                if best_ask(d):
                    self.place(p, best_ask(d), min(size, LIMIT - pos))

            # SELL HIGH
            elif m > upper and pos > -LIMIT:
                if best_bid(d):
                    self.place(p, best_bid(d), -min(size, LIMIT + pos))

            # EXIT near mean
            elif abs(m - mean) < 0.1:
                if pos > 0 and best_bid(d):
                    self.place(p, best_bid(d), -pos)
                elif pos < 0 and best_ask(d):
                    self.place(p, best_ask(d), -pos)

        return self.orders


# =========================
# 🟢 SAFE MM (unchanged)
# =========================
class SafeMM:
    PRODUCTS = ["TRANSLATOR_ECLIPSE_CHARCOAL", "ROBOT_DISHES"]
    SIZE = 2

    def __init__(self, state):
        self.state  = state
        self.orders = {}

    def place(self, p, price, qty):
        self.orders.setdefault(p, []).append(Order(p, int(price), int(qty)))

    def run(self):
        for p in self.PRODUCTS:
            if p not in self.state.order_depths:
                continue

            d = self.state.order_depths[p]
            b, a = best_bid(d), best_ask(d)

            if b and a and (a - b) <= 3:
                self.place(p, b,  self.SIZE)
                self.place(p, a, -self.SIZE)

        return self.orders


# =========================
# 🚀 MAIN TRADER
# =========================
class Trader:

    def run(self, state: TradingState):
        ensure_limits(state)

        try:
            td = json.loads(state.traderData) if state.traderData else {}
        except:
            td = {}

        result = {}

        for orders in [
            TrendFollower(state, td).run(),
            ShortSeller(state, td).run(),
            BollingerReversion(state, td).run(),  # 🔥 NEW CORE FIX
            SafeMM(state).run(),
        ]:
            for p, ol in orders.items():
                result.setdefault(p, []).extend(ol)

        return result, 0, json.dumps(td)
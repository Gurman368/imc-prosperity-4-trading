from datamodel import OrderDepth, TradingState, Order
import json, numpy as np
from typing import Dict, List, Tuple

# =======================
# STRATEGY v3 ENHANCED
# =======================
# v2 Analysis: 15 products losing money
# Solution: Add CONSERVATIVE FALLBACK STRATEGY
# 
# Strategy routing:
# 1. V1 modules (18) → TrendFollower, ShortSeller, Bollinger, SafeMM
# 2. TR.PY (32) → Advanced fair-value engine
# 3. FALLBACK (15) → Conservative quotes near mid for loss-making products
#
# Products to move to FALLBACK:
#   SLEEP_POD_POLYESTER (-12.4K), OXYGEN_SHAKE_GARLIC (-10.8K), PANEL_1X2 (-9.3K),
#   GALAXY_SOUNDS_SOLAR_FLAMES (-8.8K), TRANSLATOR_GRAPHITE_MIST (-6.7K),
#   PANEL_4X4 (-6.2K), ROBOT_MOPPING (-5.6K), PEBBLES_S (-3.1K),
#   OXYGEN_SHAKE_MINT (-3.0K), GALAXY_SOUNDS_SOLAR_WINDS (-2.9K),
#   PEBBLES_M (-1.9K), UV_VISOR_YELLOW (-1.7K), PEBBLES_L (-1.3K),
#   UV_VISOR_MAGENTA (-1.3K), PANEL_2X4 (-0.4K)

DEFAULT_LIMIT = 10
LIMIT = 10

def ensure_limits(state):
    try:
        import prosperity4bt.runner as _p4_runner
        for p in state.order_depths:
            if p not in _p4_runner.LIMITS:
                _p4_runner.LIMITS[p] = DEFAULT_LIMIT
    except:
        pass

def best_bid(d): 
    return max(d.buy_orders) if d.buy_orders else None

def best_ask(d): 
    return min(d.sell_orders) if d.sell_orders else None

def mid(d):
    b, a = best_bid(d), best_ask(d)
    return (b + a) / 2 if b and a else None


# ========================
# V1 MODULES
# ========================

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


class BollingerReversion:
    PRODUCTS = [
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
    ]

    WINDOW_MAP = {
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
            ema_fast = self._ema(hist[-50:], 10)
            ema_slow = self._ema(hist[-200:], 30)
            trending = False
            if ema_fast and ema_slow:
                trending = abs(ema_fast - ema_slow) > std * 0.5
            size = 3
            if trending:
                continue
            if m < lower and pos < LIMIT:
                if best_ask(d):
                    self.place(p, best_ask(d), min(size, LIMIT - pos))
            elif m > upper and pos > -LIMIT:
                if best_bid(d):
                    self.place(p, best_bid(d), -min(size, LIMIT + pos))
            elif abs(m - mean) < 0.1:
                if pos > 0 and best_bid(d):
                    self.place(p, best_bid(d), -pos)
                elif pos < 0 and best_ask(d):
                    self.place(p, best_ask(d), -pos)
        return self.orders


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


# ========================
# TR.PY ENGINE (Advanced)
# ========================



PRODUCT_GROUPS: Dict[str, List[str]] = {
    "GALAXY":  ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "MICRO":   ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "OXYGEN":  ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC"],
    "PANEL":   ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "PEBBLES": ["PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
    "ROBOT":   ["ROBOT_VACUUMING", "ROBOT_MOPPING", "ROBOT_DISHES",
                "ROBOT_LAUNDRY", "ROBOT_IRONING"],
    "SLEEP":   ["SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL", "SLEEP_POD_POLYESTER",
                "SLEEP_POD_NYLON", "SLEEP_POD_COTTON"],
    "SNACK":   ["SNACKPACK_CHOCOLATE", "SNACKPACK_VANILLA", "SNACKPACK_PISTACHIO",
                "SNACKPACK_STRAWBERRY", "SNACKPACK_RASPBERRY"],
    "TRANS":   ["TRANSLATOR_SPACE_GRAY", "TRANSLATOR_ASTRO_BLACK",
                "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_GRAPHITE_MIST",
                "TRANSLATOR_VOID_BLUE"],
    "UV":      ["UV_VISOR_YELLOW", "UV_VISOR_AMBER", "UV_VISOR_ORANGE",
                "UV_VISOR_RED", "UV_VISOR_MAGENTA"],
}

POSITION_LIMITS: Dict[str, int] = {
    "GALAXY_SOUNDS_BLACK_HOLES": 10, "GALAXY_SOUNDS_DARK_MATTER": 10,
    "GALAXY_SOUNDS_PLANETARY_RINGS": 10, "GALAXY_SOUNDS_SOLAR_FLAMES": 10,
    "GALAXY_SOUNDS_SOLAR_WINDS": 10,
    "MICROCHIP_CIRCLE": 10, "MICROCHIP_OVAL": 10, "MICROCHIP_RECTANGLE": 10,
    "MICROCHIP_SQUARE": 10, "MICROCHIP_TRIANGLE": 10,
    "OXYGEN_SHAKE_CHOCOLATE": 10, "OXYGEN_SHAKE_EVENING_BREATH": 10,
    "OXYGEN_SHAKE_GARLIC": 10, "OXYGEN_SHAKE_MINT": 10, "OXYGEN_SHAKE_MORNING_BREATH": 10,
    "PANEL_1X2": 10, "PANEL_1X4": 10, "PANEL_2X2": 9, "PANEL_2X4": 10, "PANEL_4X4": 10,
    "PEBBLES_L": 10, "PEBBLES_M": 10, "PEBBLES_S": 10, "PEBBLES_XL": 10,
    "ROBOT_DISHES": 10, "ROBOT_IRONING": 10, "ROBOT_LAUNDRY": 10,
    "ROBOT_MOPPING": 10, "ROBOT_VACUUMING": 10,
    "SLEEP_POD_COTTON": 10, "SLEEP_POD_LAMB_WOOL": 10, "SLEEP_POD_NYLON": 10,
    "SLEEP_POD_POLYESTER": 10, "SLEEP_POD_SUEDE": 10,
    "SNACKPACK_CHOCOLATE": 10, "SNACKPACK_PISTACHIO": 10, "SNACKPACK_RASPBERRY": 10,
    "SNACKPACK_STRAWBERRY": 10, "SNACKPACK_VANILLA": 10,
    "TRANSLATOR_ASTRO_BLACK": 10, "TRANSLATOR_ECLIPSE_CHARCOAL": 10,
    "TRANSLATOR_GRAPHITE_MIST": 10, "TRANSLATOR_SPACE_GRAY": 10, "TRANSLATOR_VOID_BLUE": 10,
    "UV_VISOR_AMBER": 10, "UV_VISOR_MAGENTA": 10, "UV_VISOR_ORANGE": 10,
    "UV_VISOR_RED": 10, "UV_VISOR_YELLOW": 10,
}

ENABLED_PRODUCTS = {p for group in PRODUCT_GROUPS.values() for p in group}

PARAMS = {
    "default_edge":        3,
    "default_join_edge":   1,
    "default_quote_size":  5,
    "inventory_skew":      0.13269814793642895,
    "micro_residual_blend": 0.5,
    "micro_residual_clip": 6.0,
    "oxygen_snack_lag":    -0.95,
    "pebbles_quote_edge":  3,
    "pebbles_quote_size":  8,
    "pebbles_sum":         49999.0,
    "pebbles_take_edge":   3,
    "uv_inventory_skew":   0.42106805190363733,
    "uv_quote_edge":       0,
    "uv_quote_size":       5,
    "uv_take_edge":        3,
}

PRODUCT_PARAMS = {
    "GALAXY_SOUNDS_BLACK_HOLES":  {"inventory_skew": 0.5,    "quote_edge": 1, "quote_size": 2, "take_edge": 3},
    "GALAXY_SOUNDS_DARK_MATTER":  {"inventory_skew": 0.35,   "quote_edge": 3, "quote_size": 4, "take_edge": 3},
    "GALAXY_SOUNDS_SOLAR_WINDS":  {"inventory_skew": 1.75,   "quote_edge": 2, "quote_size": 4, "take_edge": 3},
    "MICROCHIP_RECTANGLE":        {"inventory_skew": 0.35,   "quote_edge": 3, "quote_size": 3, "take_edge": 5},
    "MICROCHIP_SQUARE":           {"inventory_skew": 0.25,   "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "PANEL_1X4":                  {"inventory_skew": 0.15,   "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "PANEL_2X2":                  {"inventory_skew": 0.05,   "quote_edge": 1, "quote_size": 3, "take_edge": 3},
    "PANEL_2X4":                  {"inventory_skew": 0.15,   "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "ROBOT_DISHES":               {"inventory_skew": 0.5,    "quote_edge": 0, "quote_size": 3, "take_edge": 3},
    "ROBOT_IRONING":              {"inventory_skew": 0.1,    "quote_edge": 1, "quote_size": 1, "take_edge": 3},
    "ROBOT_LAUNDRY":              {"inventory_skew": 0.35,   "quote_edge": 1, "quote_size": 2, "take_edge": 3},
    "ROBOT_VACUUMING":            {"inventory_skew": 0.35,   "quote_edge": 1, "quote_size": 2, "take_edge": 3},
    "SLEEP_POD_COTTON":           {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SLEEP_POD_LAMB_WOOL":        {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SLEEP_POD_NYLON":            {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SLEEP_POD_POLYESTER":        {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SLEEP_POD_SUEDE":            {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SNACKPACK_CHOCOLATE":        {"inventory_skew": 0.2,    "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "SNACKPACK_PISTACHIO":        {"inventory_skew": 0.2,    "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "SNACKPACK_RASPBERRY":        {"inventory_skew": 0.2,    "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "SNACKPACK_STRAWBERRY":       {"inventory_skew": 0.4,    "quote_edge": 1, "quote_size": 2, "take_edge": 3},
    "SNACKPACK_VANILLA":          {"inventory_skew": 0.35,   "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "TRANSLATOR_ASTRO_BLACK":     {"inventory_skew": 0.35,   "quote_edge": 2, "quote_size": 4, "take_edge": 3},
    "TRANSLATOR_ECLIPSE_CHARCOAL":{"inventory_skew": 0.15,   "quote_edge": 1, "quote_size": 1, "take_edge": 3},
    "TRANSLATOR_VOID_BLUE":       {"inventory_skew": 0.0,    "quote_edge": 2, "quote_size": 1, "take_edge": 3},
    "UV_VISOR_MAGENTA":           {"inventory_skew": 0.2,    "quote_edge": 1, "quote_size": 1, "take_edge": 3},
    "UV_VISOR_YELLOW":            {"inventory_skew": 0.2,    "quote_edge": 2, "quote_size": 4, "take_edge": 3},
}

OXYGEN_SNACK_COEFF = -0.95
UV_SNACK_COEFFS = {
    "UV_VISOR_YELLOW":  -1.1,
    "UV_VISOR_RED":     -1.02,
    "UV_VISOR_MAGENTA": -1.25,
}
TRANS_SNACK_COEFFS = {
    "TRANSLATOR_ASTRO_BLACK": -0.375,
}

MICRO_RESIDUAL_COEFS = {
    "MICROCHIP_CIRCLE":    {"intercept": 14328.038892180744,  "coefs": {"MICROCHIP_OVAL": -0.2144216225704393, "MICROCHIP_RECTANGLE": 0.12396982342286221, "MICROCHIP_SQUARE": -0.16261948563584036, "MICROCHIP_TRIANGLE": -0.23032920612291993}},
    "MICROCHIP_OVAL":      {"intercept": -490.56042074518695, "coefs": {"MICROCHIP_CIRCLE": -0.32945233665896556, "MICROCHIP_RECTANGLE": 0.4548644568807814, "MICROCHIP_SQUARE": -0.23348490993800003, "MICROCHIP_TRIANGLE": 1.1261280731367855}},
    "MICROCHIP_RECTANGLE": {"intercept": 12595.888646662721,  "coefs": {"MICROCHIP_CIRCLE": 0.10560729802045682, "MICROCHIP_OVAL": 0.2521946892833303, "MICROCHIP_SQUARE": -0.2712089572427364, "MICROCHIP_TRIANGLE": -0.33164490797022006}},
    "MICROCHIP_SQUARE":    {"intercept": 34622.46568370466,   "coefs": {"MICROCHIP_CIRCLE": -0.6668321009567493, "MICROCHIP_OVAL": -0.6231300836088985, "MICROCHIP_RECTANGLE": -1.3054793169494834, "MICROCHIP_TRIANGLE": 0.16662933657279733}},
    "MICROCHIP_TRIANGLE":  {"intercept": 8897.550320098617,   "coefs": {"MICROCHIP_CIRCLE": -0.17718531128501464, "MICROCHIP_OVAL": 0.5638225951568637, "MICROCHIP_RECTANGLE": -0.299484320697988, "MICROCHIP_SQUARE": 0.03125980431842272}},
}
MICRO_RESIDUAL_CLIPS = {"MICROCHIP_OVAL": 6.5}

FAMILY_OLS_SIGN_ENABLED = ("GALAXY", "PANEL", "PEBBLES", "ROBOT", "SLEEP", "SNACK", "UV")
FAMILY_OLS_SIGN_CLIP = 2.5
FAMILY_OLS_SIGN_MODELS = {"GALAXY": {"GALAXY_SOUNDS_DARK_MATTER": {"intercept": 8960.3321419222, "coefs": {"GALAXY_SOUNDS_BLACK_HOLES": -0.006148537, "GALAXY_SOUNDS_PLANETARY_RINGS": 0.1901645717, "GALAXY_SOUNDS_SOLAR_WINDS": -0.0364035809, "GALAXY_SOUNDS_SOLAR_FLAMES": -0.0298074842}}, "GALAXY_SOUNDS_BLACK_HOLES": {"intercept": 1636.6126227244, "coefs": {"GALAXY_SOUNDS_DARK_MATTER": -0.0499588742, "GALAXY_SOUNDS_PLANETARY_RINGS": 0.0506851413, "GALAXY_SOUNDS_SOLAR_WINDS": 0.842634353, "GALAXY_SOUNDS_SOLAR_FLAMES": 0.0901890508}}, "GALAXY_SOUNDS_PLANETARY_RINGS": {"intercept": -1891.3917742908, "coefs": {"GALAXY_SOUNDS_DARK_MATTER": 1.0112819695, "GALAXY_SOUNDS_BLACK_HOLES": 0.0331728256, "GALAXY_SOUNDS_SOLAR_WINDS": 0.1227711663, "GALAXY_SOUNDS_SOLAR_FLAMES": 0.0589771496}}, "GALAXY_SOUNDS_SOLAR_WINDS": {"intercept": 11778.8258799864, "coefs": {"GALAXY_SOUNDS_DARK_MATTER": -0.0843925073, "GALAXY_SOUNDS_BLACK_HOLES": 0.2404130808, "GALAXY_SOUNDS_PLANETARY_RINGS": 0.0535196804, "GALAXY_SOUNDS_SOLAR_FLAMES": -0.343585179}}, "GALAXY_SOUNDS_SOLAR_FLAMES": {"intercept": 14350.2933170199, "coefs": {"GALAXY_SOUNDS_DARK_MATTER": -0.0604980391, "GALAXY_SOUNDS_BLACK_HOLES": 0.022528327, "GALAXY_SOUNDS_PLANETARY_RINGS": 0.0225090466, "GALAXY_SOUNDS_SOLAR_WINDS": -0.3008088524}}}, "PANEL": {"PANEL_1X2": {"intercept": 18880.8368644951, "coefs": {"PANEL_2X2": -0.5968901312, "PANEL_1X4": -0.0285265886, "PANEL_2X4": -0.2293510862, "PANEL_4X4": -0.1407190819}}, "PANEL_2X2": {"intercept": 21783.2532083775, "coefs": {"PANEL_1X2": -0.3431742449, "PANEL_1X4": 0.1810437354, "PANEL_2X4": -0.4114980013, "PANEL_4X4": -0.628654226}}, "PANEL_1X4": {"intercept": 14811.6341935249, "coefs": {"PANEL_1X2": -0.0387280047, "PANEL_2X2": 0.4275023411, "PANEL_2X4": -0.6069336034, "PANEL_4X4": -0.2353725067}}, "PANEL_2X4": {"intercept": 27117.4029813609, "coefs": {"PANEL_1X2": -0.1604564726, "PANEL_2X2": -0.5007303106, "PANEL_1X4": -0.3127680185, "PANEL_4X4": -0.6767845525}}, "PANEL_4X4": {"intercept": 20965.5535483732, "coefs": {"PANEL_1X2": -0.0643244704, "PANEL_2X2": -0.4998213206, "PANEL_1X4": -0.0792508037, "PANEL_2X4": -0.4421984588}}}, "PEBBLES": {"PEBBLES_XS": {"intercept": 49999.6913227177, "coefs": {"PEBBLES_S": -1.0000012599, "PEBBLES_M": -1.0000011192, "PEBBLES_L": -0.9999819254, "PEBBLES_XL": -0.9999934137}}, "PEBBLES_S": {"intercept": 49997.4366084325, "coefs": {"PEBBLES_XS": -0.999926002, "PEBBLES_M": -0.9999516515, "PEBBLES_L": -0.9999269781, "PEBBLES_XL": -0.99994587}}, "PEBBLES_M": {"intercept": 49998.6157521681, "coefs": {"PEBBLES_XS": -0.9999671899, "PEBBLES_S": -0.9999929811, "PEBBLES_L": -0.9999446471, "PEBBLES_XL": -0.9999655953}}, "PEBBLES_L": {"intercept": 49999.61589146, "coefs": {"PEBBLES_XS": -0.9999869766, "PEBBLES_S": -1.0000072873, "PEBBLES_M": -0.9999836268, "PEBBLES_XL": -0.9999906009}}, "PEBBLES_XL": {"intercept": 49999.939025667, "coefs": {"PEBBLES_XS": -0.999993723, "PEBBLES_S": -1.0000214387, "PEBBLES_M": -0.9999998339, "PEBBLES_L": -0.999985859}}}, "ROBOT": {"ROBOT_VACUUMING": {"intercept": 13467.0591828733, "coefs": {"ROBOT_MOPPING": -0.3170541123, "ROBOT_DISHES": -0.2870024308, "ROBOT_LAUNDRY": 0.1620715043, "ROBOT_IRONING": 0.0577339264}}, "ROBOT_MOPPING": {"intercept": 30082.6013210368, "coefs": {"ROBOT_VACUUMING": -0.6002796157, "ROBOT_DISHES": -0.5458901179, "ROBOT_LAUNDRY": -0.3338836486, "ROBOT_IRONING": -0.543718051}}, "ROBOT_DISHES": {"intercept": 26351.8560869757, "coefs": {"ROBOT_VACUUMING": -0.4479851594, "ROBOT_MOPPING": -0.4500523971, "ROBOT_LAUNDRY": -0.4464942037, "ROBOT_IRONING": -0.3270074081}}, "ROBOT_LAUNDRY": {"intercept": 14981.2504138373, "coefs": {"ROBOT_VACUUMING": 0.2554560119, "ROBOT_MOPPING": -0.2779613486, "ROBOT_DISHES": -0.4508657423, "ROBOT_IRONING": 0.0117390912}}, "ROBOT_IRONING": {"intercept": 18545.6588681297, "coefs": {"ROBOT_VACUUMING": 0.1213313931, "ROBOT_MOPPING": -0.6035255162, "ROBOT_DISHES": -0.4402725705, "ROBOT_LAUNDRY": 0.0156519013}}}, "SLEEP": {"SLEEP_POD_SUEDE": {"intercept": 2761.3840070996, "coefs": {"SLEEP_POD_LAMB_WOOL": 0.0576893789, "SLEEP_POD_POLYESTER": 0.9673055369, "SLEEP_POD_NYLON": -0.1226003829, "SLEEP_POD_COTTON": -0.195472198}}, "SLEEP_POD_LAMB_WOOL": {"intercept": 7263.8085984272, "coefs": {"SLEEP_POD_SUEDE": 0.0350993912, "SLEEP_POD_POLYESTER": -0.1651278456, "SLEEP_POD_NYLON": 0.4424417776, "SLEEP_POD_COTTON": 0.0632584393}}, "SLEEP_POD_POLYESTER": {"intercept": 84.6408404629, "coefs": {"SLEEP_POD_SUEDE": 0.5185851714, "SLEEP_POD_LAMB_WOOL": -0.1455033576, "SLEEP_POD_NYLON": 0.0699050607, "SLEEP_POD_COTTON": 0.5837152772}}, "SLEEP_POD_NYLON": {"intercept": 1250.0974254945, "coefs": {"SLEEP_POD_SUEDE": -0.0976280836, "SLEEP_POD_LAMB_WOOL": 0.5790757071, "SLEEP_POD_POLYESTER": 0.103832936, "SLEEP_POD_COTTON": 0.1798028911}}, "SLEEP_POD_COTTON": {"intercept": 78.1509839515, "coefs": {"SLEEP_POD_SUEDE": -0.1604047069, "SLEEP_POD_LAMB_WOOL": 0.0853192176, "SLEEP_POD_POLYESTER": 0.8934633677, "SLEEP_POD_NYLON": 0.1852873817}}}, "SNACK": {"SNACKPACK_CHOCOLATE": {"intercept": 19500.956658179, "coefs": {"SNACKPACK_VANILLA": -0.9220839604, "SNACKPACK_PISTACHIO": 0.1120197239, "SNACKPACK_STRAWBERRY": -0.1423269673, "SNACKPACK_RASPBERRY": 0.0112219739}}, "SNACKPACK_VANILLA": {"intercept": 20483.2542344985, "coefs": {"SNACKPACK_CHOCOLATE": -0.996916863, "SNACKPACK_PISTACHIO": 0.0889421363, "SNACKPACK_STRAWBERRY": -0.1370021971, "SNACKPACK_RASPBERRY": 0.0048938859}}, "SNACKPACK_PISTACHIO": {"intercept": 13853.2654741964, "coefs": {"SNACKPACK_CHOCOLATE": 0.4352196503, "SNACKPACK_VANILLA": 0.3196193613, "SNACKPACK_STRAWBERRY": -0.3067256211, "SNACKPACK_RASPBERRY": -0.8518468584}}, "SNACKPACK_STRAWBERRY": {"intercept": 67692.3929098779, "coefs": {"SNACKPACK_CHOCOLATE": -1.8195189506, "SNACKPACK_VANILLA": -1.6199754943, "SNACKPACK_PISTACHIO": -1.0092655388, "SNACKPACK_RASPBERRY": -1.3032960416}}, "SNACKPACK_RASPBERRY": {"intercept": 20719.311282389, "coefs": {"SNACKPACK_CHOCOLATE": 0.0395774683, "SNACKPACK_VANILLA": 0.0159640884, "SNACKPACK_PISTACHIO": -0.7732613182, "SNACKPACK_STRAWBERRY": -0.359544331}}}, "UV": {"UV_VISOR_YELLOW": {"intercept": 25282.300224443, "coefs": {"UV_VISOR_AMBER": -0.4210596715, "UV_VISOR_ORANGE": -0.2513172083, "UV_VISOR_RED": -0.8739096888, "UV_VISOR_MAGENTA": 0.1165551453}}, "UV_VISOR_AMBER": {"intercept": 31353.2846011408, "coefs": {"UV_VISOR_YELLOW": -0.1666341744, "UV_VISOR_ORANGE": -0.3846906513, "UV_VISOR_RED": -0.6172586636, "UV_VISOR_MAGENTA": -0.9697631824}}, "UV_VISOR_ORANGE": {"intercept": 19557.7589743411, "coefs": {"UV_VISOR_YELLOW": -0.1382583999, "UV_VISOR_AMBER": -0.5347619581, "UV_VISOR_RED": -0.1713385808, "UV_VISOR_MAGENTA": -0.1340781439}}, "UV_VISOR_RED": {"intercept": 27273.0191036094, "coefs": {"UV_VISOR_YELLOW": -0.3820067579, "UV_VISOR_AMBER": -0.681790992, "UV_VISOR_ORANGE": -0.1361414455, "UV_VISOR_MAGENTA": -0.4688981022}}, "UV_VISOR_MAGENTA": {"intercept": 19824.9776194823, "coefs": {"UV_VISOR_YELLOW": 0.0312302762, "UV_VISOR_AMBER": -0.6565830083, "UV_VISOR_ORANGE": -0.0653029897, "UV_VISOR_RED": -0.2874209085}}}}

PANEL_INTRADAY_SIGNALS = (
    {"product": "PANEL_1X4", "start": 600000, "end": 800000,
     "lookback": 500, "direction":  1.0, "move_per_tick": 100.0, "max_ticks": 2.0},
    {"product": "PANEL_2X4", "start":      0, "end": 100000,
     "lookback": 500, "direction": -1.0, "move_per_tick": 100.0, "max_ticks": 2.0},
)

def _mid(depth: OrderDepth) -> float | None:
    if not depth.buy_orders or not depth.sell_orders:
        return None
    return (max(depth.buy_orders) + min(depth.sell_orders)) / 2.0

def _best(depth: OrderDepth) -> Tuple[int | None, int | None]:
    bid = max(depth.buy_orders) if depth.buy_orders else None
    ask = min(depth.sell_orders) if depth.sell_orders else None
    return bid, ask

def _state_mem(raw: str) -> Dict[str, object]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}

def _clip_buy(product: str, position: int, requested: int) -> int:
    return max(0, min(requested, POSITION_LIMITS[product] - position))

def _clip_sell(product: str, position: int, requested: int) -> int:
    return max(0, min(requested, POSITION_LIMITS[product] + position))


# ========================
# FALLBACK STRATEGY
# ========================
# For products that lost money in v2:
# Conservative quotes near mid with tight edges

class FallbackStrategy:
    """
    Adaptive fallback for previously-losing products.
    - Uses Bollinger bands but only trades when market is ranging (not trending)
    - Quotes passively near mid when no signal, but ONLY on the safe side given position
    - Hard stop: never adds to a losing position
    """

    FALLBACK_PRODUCTS = {
        # ✅ genuinely unhandled losers only
        "GALAXY_SOUNDS_SOLAR_FLAMES",
        "GALAXY_SOUNDS_SOLAR_WINDS",
        "ROBOT_MOPPING",
        "PEBBLES_S",
        "PEBBLES_M",
        "OXYGEN_SHAKE_MINT",
        "UV_VISOR_YELLOW",
        "PANEL_1X2",
        "PANEL_4X4",

    }

    # Conservative window — same for all fallback products
    # Long window = slow-moving mean = less false signals
    WINDOW = 1200

    # Wide band = only trade extreme deviations
    K = 2.8

    # Trend filter: if EMA gap > this fraction of std, skip
    TREND_THRESHOLD = 0.4

    # Max size per trade — very small
    SIZE = 1

    def __init__(self, state: TradingState, td: dict):
        self.state = state
        self.td    = td
        self.orders = {}

    def place(self, p, price, qty):
        self.orders.setdefault(p, []).append(Order(p, int(price), int(qty)))

    def _update_hist(self, key, val):
        h = self.td.setdefault(key, [])
        h.append(float(val))
        if len(h) > self.WINDOW:
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

    def _is_trending(self, hist, std):
        """True if market is trending — skip all trades"""
        if std < 0.01:
            return True  # flat/dead market, skip
        ema_fast = self._ema(hist[-100:], 20)
        ema_slow = self._ema(hist[-400:], 80)
        if ema_fast is None or ema_slow is None:
            return True  # not enough data, stay out
        return abs(ema_fast - ema_slow) > std * self.TREND_THRESHOLD

    def _at_loss(self, p, pos, mid_price):
        """Rough check: is current position underwater?"""
        avg_key = f"avg_{p}"
        avg = self.td.get(avg_key)
        if avg is None:
            return False
        if pos > 0 and mid_price < avg:
            return True
        if pos < 0 and mid_price > avg:
            return True
        return False

    def _update_avg(self, p, pos, mid_price):
        """Track rough average entry price"""
        avg_key = f"avg_{p}"
        if pos == 0:
            self.td[avg_key] = mid_price
        else:
            prev = self.td.get(avg_key, mid_price)
            # Exponential blend toward new price
            self.td[avg_key] = 0.9 * prev + 0.1 * mid_price

    def run(self):
        for p in self.FALLBACK_PRODUCTS:
            if p not in self.state.order_depths:
                continue

            d = self.state.order_depths[p]
            m = _mid(d)
            if m is None:
                continue

            bid, ask = _best(d)
            pos = int(self.state.position.get(p, 0))
            limit = POSITION_LIMITS.get(p, LIMIT)

            self._update_avg(p, pos, m)
            hist = self._update_hist(f"fb_{p}", m)

            # Need at least 50 ticks before doing anything
            if len(hist) < 50:
                continue

            mean = np.mean(hist)
            std  = np.std(hist)

            # ── TREND GUARD: sit out if trending ─────────────────────
            if self._is_trending(hist, std):
                # Only action allowed: exit existing position near mean
                if pos > 0 and bid and abs(m - mean) < std * 0.3:
                    self.place(p, bid, -min(pos, self.SIZE))
                elif pos < 0 and ask and abs(m - mean) < std * 0.3:
                    self.place(p, ask,  min(-pos, self.SIZE))
                continue

            upper = mean + self.K * std
            lower = mean - self.K * std

            # ── HARD RULE: never add to a losing position ─────────────
            if self._at_loss(p, pos, m):
                # Only exit, never enter
                if pos > 0 and bid:
                    self.place(p, bid, -min(pos, self.SIZE))
                elif pos < 0 and ask:
                    self.place(p, ask,  min(-pos, self.SIZE))
                continue

            # ── SIGNAL: buy extreme low ───────────────────────────────
            if m < lower and pos < limit:
                if ask:
                    qty = min(self.SIZE, limit - pos)
                    self.place(p, ask, qty)

            # ── SIGNAL: sell extreme high ─────────────────────────────
            elif m > upper and pos > -limit:
                if bid:
                    qty = min(self.SIZE, limit + pos)
                    self.place(p, bid, -qty)

            # ── EXIT: unwind near mean ────────────────────────────────
            elif abs(m - mean) < std * 0.2:
                if pos > 0 and bid:
                    self.place(p, bid, -min(pos, self.SIZE * 2))
                elif pos < 0 and ask:
                    self.place(p, ask,  min(-pos, self.SIZE * 2))

        return self.orders


class AdvancedMMEngine:
    """TR.PY's fair-value engine with OLS models, lead-lag, and correlations"""
    # Do NOT let TR.PY touch Bollinger products
    SKIP_PRODUCTS = {
        "GALAXY_SOUNDS_BLACK_HOLES",
        "MICROCHIP_SQUARE",
        "PANEL_2X4",
        "PEBBLES_L",
        "PEBBLES_XS",
        "SNACKPACK_RASPBERRY",
        "SNACKPACK_STRAWBERRY",
        "SNACKPACK_VANILLA",
        "UV_VISOR_MAGENTA",
    }
    # Products that should NOT use fallback (use TR.PY only)
    SKIP_FALLBACK = {
        "UV_VISOR_ORANGE", "UV_VISOR_RED", "TRANSLATOR_GRAPHITE_MIST", "SLEEP_POD_COTTON",
        "UV_VISOR_AMBER",
        "GALAXY_SOUNDS_BLACK_HOLES", "MICROCHIP_SQUARE",
        "SNACKPACK_RASPBERRY", "SNACKPACK_STRAWBERRY", "SNACKPACK_VANILLA",
        "TRANSLATOR_ECLIPSE_CHARCOAL", "ROBOT_DISHES",
    }

    def __init__(self, state: TradingState, mem: Dict[str, object]):
        self.state = state
        self.mem = mem
        self.orders = {}

    def place(self, p, price, qty):
        self.orders.setdefault(p, []).append(Order(p, int(price), int(qty)))

    def run(self):
        fair_values = self._fair_values()
        
        for product, depth in self.state.order_depths.items():
            if product not in ENABLED_PRODUCTS:
                continue
            if product in FallbackStrategy.FALLBACK_PRODUCTS:
                continue  # Let fallback handle it
            if product in self.SKIP_PRODUCTS:
                continue
            fair = fair_values.get(product)
            if fair is None:
                continue
            position = int(self.state.position.get(product, 0))
            orders = self._orders_for_product(product, depth, position, fair)
            for order in orders:
                self.orders.setdefault(product, []).append(order)
        
        return self.orders

    def _fair_values(self) -> Dict[str, float]:
        mids: Dict[str, float] = {}
        for product, depth in self.state.order_depths.items():
            m = _mid(depth)
            if m is not None:
                mids[product] = m

        fair: Dict[str, float] = dict(mids)

        prev_mids = self.mem.get("prev_mids") or {}
        snack_delta = self._group_delta("SNACK", mids, prev_mids)
        if snack_delta is not None:
            for product in PRODUCT_GROUPS["OXYGEN"]:
                if product in fair:
                    fair[product] += OXYGEN_SNACK_COEFF * snack_delta
            for product, coeff in UV_SNACK_COEFFS.items():
                if product in fair:
                    fair[product] += coeff * snack_delta
            for product, coeff in TRANS_SNACK_COEFFS.items():
                if product in fair:
                    fair[product] += coeff * snack_delta
        self.mem["prev_mids"] = mids

        pebbles = PRODUCT_GROUPS["PEBBLES"]
        if all(p in mids for p in pebbles):
            for product in pebbles:
                fair[product] = PARAMS["pebbles_sum"] - sum(
                    mids[other] for other in pebbles if other != product
                )

        micro_clip_default = float(PARAMS["micro_residual_clip"])
        for product, model in MICRO_RESIDUAL_COEFS.items():
            if product not in fair or product not in mids:
                continue
            predicted = float(model["intercept"])
            usable = True
            for other, coeff in model["coefs"].items():
                if other not in mids:
                    usable = False
                    break
                predicted += float(coeff) * mids[other]
            if not usable:
                continue
            clip = float(MICRO_RESIDUAL_CLIPS.get(product, micro_clip_default))
            diff = predicted - mids[product]
            fair[product] += clip if diff > 0 else (-clip if diff < 0 else 0.0)

        self._apply_family_ols_sign(fair, mids)
        self._apply_panel_intraday(fair, mids, self.state.timestamp)
        return fair

    def _apply_family_ols_sign(self, fair: Dict[str, float], mids: Dict[str, float]) -> None:
        for family in FAMILY_OLS_SIGN_ENABLED:
            for product, model in FAMILY_OLS_SIGN_MODELS.get(family, {}).items():
                if product not in fair or product not in mids:
                    continue
                predicted = float(model["intercept"])
                usable = True
                for other, coeff in model["coefs"].items():
                    if other not in mids:
                        usable = False
                        break
                    predicted += float(coeff) * mids[other]
                if not usable:
                    continue
                diff = predicted - mids[product]
                if diff > 0:
                    fair[product] += FAMILY_OLS_SIGN_CLIP
                elif diff < 0:
                    fair[product] -= FAMILY_OLS_SIGN_CLIP

    def _apply_panel_intraday(self, fair: Dict[str, float], mids: Dict[str, float], timestamp: int) -> None:
        histories = self.mem.get("panel_hist") or {}
        for cfg in PANEL_INTRADAY_SIGNALS:
            product  = str(cfg["product"])
            lookback = int(cfg["lookback"])
            if product not in mids:
                continue
            hist = histories.get(product) or []
            if (product in fair
                    and int(cfg["start"]) <= timestamp < int(cfg["end"])
                    and len(hist) >= lookback):
                try:
                    move = mids[product] - float(hist[-lookback])
                except (TypeError, ValueError):
                    move = 0.0
                ticks = float(cfg["direction"]) * move / float(cfg["move_per_tick"])
                ticks = max(-float(cfg["max_ticks"]), min(float(cfg["max_ticks"]), ticks))
                fair[product] += ticks
            hist.append(round(mids[product], 1))
            if len(hist) > lookback + 1:
                del hist[: len(hist) - lookback - 1]
            histories[product] = hist
        self.mem["panel_hist"] = histories

    def _group_delta(self, group: str, mids: Dict[str, float], prev_mids: Dict[str, object]) -> float | None:
        cur, prev = [], []
        for product in PRODUCT_GROUPS[group]:
            if product not in mids or product not in prev_mids:
                continue
            try:
                p = float(prev_mids[product])
            except (TypeError, ValueError):
                continue
            cur.append(mids[product])
            prev.append(p)
        if not cur:
            return None
        return sum(cur) / len(cur) - sum(prev) / len(prev)

    def _orders_for_product(self, product: str, depth: OrderDepth, position: int, fair: float) -> List[Order]:
        bid, ask = _best(depth)
        if bid is None or ask is None or bid >= ask:
            return []

        pp = PRODUCT_PARAMS.get(product)
        if pp is not None:
            take_edge      = int(pp["take_edge"])
            quote_edge     = int(pp["quote_edge"])
            quote_size     = int(pp["quote_size"])
            inventory_skew = float(pp["inventory_skew"])
        elif product in PRODUCT_GROUPS["PEBBLES"]:
            take_edge      = PARAMS["pebbles_take_edge"]
            quote_edge     = PARAMS["pebbles_quote_edge"]
            quote_size     = PARAMS["pebbles_quote_size"]
            inventory_skew = PARAMS["inventory_skew"]
        elif product in PRODUCT_GROUPS["UV"]:
            take_edge      = PARAMS["uv_take_edge"]
            quote_edge     = PARAMS["uv_quote_edge"]
            quote_size     = PARAMS["uv_quote_size"]
            inventory_skew = PARAMS["uv_inventory_skew"]
        else:
            take_edge      = PARAMS["default_edge"]
            quote_edge     = PARAMS["default_join_edge"]
            quote_size     = PARAMS["default_quote_size"]
            inventory_skew = PARAMS["inventory_skew"]

        orders: List[Order] = []
        buy_cap  = _clip_buy(product, position, POSITION_LIMITS[product])
        sell_cap = _clip_sell(product, position, POSITION_LIMITS[product])

        if ask <= fair - take_edge:
            vol = min(-int(depth.sell_orders[ask]), buy_cap, quote_size)
            if vol > 0:
                orders.append(Order(product, ask, vol))
                buy_cap  -= vol
                position += vol
                sell_cap  = _clip_sell(product, position, POSITION_LIMITS[product])

        if bid >= fair + take_edge:
            vol = min(int(depth.buy_orders[bid]), sell_cap, quote_size)
            if vol > 0:
                orders.append(Order(product, bid, -vol))
                sell_cap -= vol
                position -= vol
                buy_cap   = _clip_buy(product, position, POSITION_LIMITS[product])

        skewed_fair = fair - inventory_skew * position
        buy_price   = min(bid + 1, int(skewed_fair - quote_edge))
        sell_price  = max(ask - 1, int(skewed_fair + quote_edge))
        if buy_price >= sell_price:
            buy_price, sell_price = bid, ask

        if buy_cap > 0 and buy_price < ask:
            orders.append(Order(product, buy_price, min(buy_cap, quote_size)))
        if sell_cap > 0 and sell_price > bid:
            orders.append(Order(product, sell_price, -min(sell_cap, quote_size)))

        return orders


# ========================
# MAIN TRADER (Router)
# ========================

class Trader:
    V1_PRODUCTS = {
        "UV_VISOR_ORANGE", "UV_VISOR_RED", "TRANSLATOR_GRAPHITE_MIST", "SLEEP_POD_COTTON",
        "UV_VISOR_AMBER",
        "GALAXY_SOUNDS_BLACK_HOLES", "MICROCHIP_SQUARE", "OXYGEN_SHAKE_GARLIC", "PANEL_2X4",
        "PEBBLES_L", "PEBBLES_XS", "SLEEP_POD_POLYESTER", "SNACKPACK_RASPBERRY",
        "SNACKPACK_STRAWBERRY", "SNACKPACK_VANILLA", "UV_VISOR_MAGENTA",
        "TRANSLATOR_ECLIPSE_CHARCOAL", "ROBOT_DISHES",
    }

    def run(self, state: TradingState):
        ensure_limits(state)

        try:
            td = json.loads(state.traderData) if state.traderData else {}
        except:
            td = {}

        result = {}

        # V1 Modules
        for orders in [
            TrendFollower(state, td).run(),
            ShortSeller(state, td).run(),
            BollingerReversion(state, td).run(),
            SafeMM(state).run(),
        ]:
            for p, ol in orders.items():
                result.setdefault(p, []).extend(ol)

        # Fallback strategy for losers
        fallback = FallbackStrategy(state, td)
        fallback_orders = fallback.run()
        for p, ol in fallback_orders.items():
            result.setdefault(p, []).extend(ol)

        # TR.PY Advanced engine for remaining
        engine = AdvancedMMEngine(state, td)
        adv_orders = engine.run()
        for p, ol in adv_orders.items():
            result.setdefault(p, []).extend(ol)

        return result, 0, json.dumps(td)
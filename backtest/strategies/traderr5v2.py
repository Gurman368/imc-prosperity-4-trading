from __future__ import annotations

import json
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

from datamodel import Order
from datamodel import *
from typing import Any, TypeAlias

from math import log, sqrt, exp, floor, ceil
from statistics import NormalDist
from abc import abstractmethod
from collections import deque
import math
import json

normalDist = NormalDist(0, 1)

JSON: TypeAlias = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None

# DON'T MODIFY LOGGER CLASS
class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(self.to_json([
            self.compress_state(state, ""),
            self.compress_orders(orders),
            conversions,
            "",
            "",
        ]))

        max_item_length = (self.max_log_length - base_length) // 3

        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append([
                    trade.symbol,
                    trade.price,
                    trade.quantity,
                    trade.buyer,
                    trade.seller,
                    trade.timestamp,
                ])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return value[:max_length - 3] + "..."

logger = Logger()


# ── Product catalogue ──────────────────────────────────────────────────────────
PRODUCT_GROUPS: Dict[str, List[str]] = {
    "GALAXY":  ["GALAXY_SOUNDS_DARK_MATTER", "GALAXY_SOUNDS_BLACK_HOLES",
                "GALAXY_SOUNDS_PLANETARY_RINGS", "GALAXY_SOUNDS_SOLAR_WINDS",
                "GALAXY_SOUNDS_SOLAR_FLAMES"],
    "MICRO":   ["MICROCHIP_CIRCLE", "MICROCHIP_OVAL", "MICROCHIP_SQUARE",
                "MICROCHIP_RECTANGLE", "MICROCHIP_TRIANGLE"],
    "OXYGEN":  ["OXYGEN_SHAKE_MORNING_BREATH", "OXYGEN_SHAKE_EVENING_BREATH",
                "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_CHOCOLATE", "OXYGEN_SHAKE_GARLIC"],
    "PANEL":   ["PANEL_1X2", "PANEL_2X2", "PANEL_1X4", "PANEL_2X4", "PANEL_4X4"],
    "PEBBLES": ["PEBBLES_XS", "PEBBLES_S", "PEBBLES_M", "PEBBLES_L", "PEBBLES_XL"],
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
    "PEBBLES_L": 10, "PEBBLES_M": 10, "PEBBLES_S": 10, "PEBBLES_XL": 10, "PEBBLES_XS": 10,
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

# ── Products to completely skip (consistent losers confirmed across 3-day BT) ──
# PANEL_1X2:              -18,458  (0/3 days positive, loses every single day)
# PEBBLES_M:              -10,268  (wildly volatile, -20k on day3, too risky)
# OXYGEN_SHAKE_MINT:       -9,097  (0/3 days positive, loses every single day)
# GALAXY_SOUNDS_SOLAR_FLAMES: -8,898 (2/3 days negative, structural downtrend)
# TRANSLATOR_SPACE_GRAY:   -4,834  (day4 disaster -14k, net negative)
# TRANSLATOR_GRAPHITE_MIST: -1,337 (net negative, small but consistent drag)
# PANEL_4X4:               -1,197  (net negative)
SKIP_PRODUCTS = {
    "PANEL_1X2",
    "PEBBLES_M",
    "OXYGEN_SHAKE_MINT",
    "GALAXY_SOUNDS_SOLAR_FLAMES",
    "TRANSLATOR_SPACE_GRAY",
    "TRANSLATOR_GRAPHITE_MIST",
    "PANEL_4X4",
}

ENABLED_PRODUCTS = {p for group in PRODUCT_GROUPS.values() for p in group} - SKIP_PRODUCTS

# ── Global defaults ────────────────────────────────────────────────────────────
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

# ── Per-product overrides ──────────────────────────────────────────────────────
PRODUCT_PARAMS = {
    # ── GALAXY SOUNDS ──────────────────────────────────────────────────────────
    # BLACK_HOLES: +21k, let OLS handle → keep
    "GALAXY_SOUNDS_BLACK_HOLES":     {"inventory_skew": 0.5,    "quote_edge": 1, "quote_size": 2, "take_edge": 3},
    "GALAXY_SOUNDS_DARK_MATTER":     {"inventory_skew": 0.35,   "quote_edge": 3, "quote_size": 4, "take_edge": 3},
    # SOLAR_WINDS: +18k 2/3 → lean LONG (v2: was 1.75 fighting it)
    "GALAXY_SOUNDS_SOLAR_WINDS":     {"inventory_skew": -0.5,   "quote_edge": 2, "quote_size": 4, "take_edge": 3},
    # PLANETARY_RINGS: volatile +19k (d2=+23k, d4=-7k) → moderate neutral skew
    "GALAXY_SOUNDS_PLANETARY_RINGS": {"inventory_skew": 0.3,    "quote_edge": 2, "quote_size": 3, "take_edge": 3},

    # ── MICROCHIP ──────────────────────────────────────────────────────────────
    # All microchip products earning well via OLS models → keep
    "MICROCHIP_RECTANGLE":           {"inventory_skew": 0.35,   "quote_edge": 3, "quote_size": 3, "take_edge": 5},
    "MICROCHIP_SQUARE":              {"inventory_skew": 0.25,   "quote_edge": 1, "quote_size": 4, "take_edge": 3},

    # ── PANELS ─────────────────────────────────────────────────────────────────
    # PANEL_1X4: +26k 3/3 → lean LONG
    "PANEL_1X4":                     {"inventory_skew": -0.2,   "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    # PANEL_2X2: +9k 3/3 → lean LONG (v3: was 0.05)
    "PANEL_2X2":                     {"inventory_skew": -0.15,  "quote_edge": 1, "quote_size": 3, "take_edge": 3},
    # PANEL_2X4: +18k 3/3 → lean LONG
    "PANEL_2X4":                     {"inventory_skew": -0.1,   "quote_edge": 1, "quote_size": 4, "take_edge": 3},

    # ── PEBBLES ────────────────────────────────────────────────────────────────
    "PEBBLES_XS":                    {"inventory_skew": 0.35,   "quote_edge": 2, "quote_size": 5, "take_edge": 3},
    # PEBBLES_S: simple BT +40k LONG, 566327 was +155 → LEAN LONG hard
    "PEBBLES_S":                     {"inventory_skew": -1.5,   "quote_edge": 2, "quote_size": 5, "take_edge": 3},
    # PEBBLES_L: -16k → LEAN SHORT hard
    "PEBBLES_L":                     {"inventory_skew": 2.5,    "quote_edge": 2, "quote_size": 5, "take_edge": 3},

    # ── ROBOTS ─────────────────────────────────────────────────────────────────
    "ROBOT_DISHES":                  {"inventory_skew": 0.5,    "quote_edge": 0, "quote_size": 3, "take_edge": 3},
    "ROBOT_IRONING":                 {"inventory_skew": 0.1,    "quote_edge": 1, "quote_size": 1, "take_edge": 3},
    "ROBOT_LAUNDRY":                 {"inventory_skew": 0.35,   "quote_edge": 1, "quote_size": 2, "take_edge": 3},
    "ROBOT_VACUUMING":               {"inventory_skew": 0.4,    "quote_edge": 1, "quote_size": 2, "take_edge": 3},
    # ROBOT_MOPPING: -11k 2/3 days → LEAN SHORT hard
    "ROBOT_MOPPING":                 {"inventory_skew": 2.5,    "quote_edge": 1, "quote_size": 3, "take_edge": 3},

    # ── SLEEP PODS ─────────────────────────────────────────────────────────────
    # All sleep pods +23-28k, all 3/3 days → keep very low skew (lean long)
    "SLEEP_POD_COTTON":              {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SLEEP_POD_LAMB_WOOL":           {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SLEEP_POD_NYLON":               {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SLEEP_POD_POLYESTER":           {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},
    "SLEEP_POD_SUEDE":               {"inventory_skew": 0.006876362272190462, "quote_edge": 3, "quote_size": 6, "take_edge": 2},

    # ── SNACKPACKS ─────────────────────────────────────────────────────────────
    "SNACKPACK_CHOCOLATE":           {"inventory_skew": 0.2,    "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "SNACKPACK_PISTACHIO":           {"inventory_skew": 0.2,    "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "SNACKPACK_RASPBERRY":           {"inventory_skew": 0.2,    "quote_edge": 1, "quote_size": 4, "take_edge": 3},
    "SNACKPACK_STRAWBERRY":          {"inventory_skew": 0.4,    "quote_edge": 1, "quote_size": 2, "take_edge": 3},
    "SNACKPACK_VANILLA":             {"inventory_skew": 0.45,   "quote_edge": 2, "quote_size": 2, "take_edge": 4},

    # ── TRANSLATORS ────────────────────────────────────────────────────────────
    # ASTRO_BLACK: +11k 3/3 → lean more LONG (v3: was 0.35)
    "TRANSLATOR_ASTRO_BLACK":        {"inventory_skew": 0.0,    "quote_edge": 2, "quote_size": 4, "take_edge": 3},
    # ECLIPSE_CHARCOAL: +21k 3/3 → lean more LONG (v3: was 0.15)
    "TRANSLATOR_ECLIPSE_CHARCOAL":   {"inventory_skew": 0.0,    "quote_edge": 1, "quote_size": 1, "take_edge": 3},
    # VOID_BLUE: +22k 2/3 → already 0.0 ✓
    "TRANSLATOR_VOID_BLUE":          {"inventory_skew": 0.0,    "quote_edge": 2, "quote_size": 1, "take_edge": 3},

    # ── UV VISORS ──────────────────────────────────────────────────────────────
    # All UV strongly positive → keep, UV_SNACK_COEFFS already reduced in v3
    "UV_VISOR_MAGENTA":              {"inventory_skew": 0.2,    "quote_edge": 1, "quote_size": 1, "take_edge": 3},
    "UV_VISOR_YELLOW":               {"inventory_skew": 0.2,    "quote_edge": 2, "quote_size": 4, "take_edge": 3},

    # ── OXYGEN SHAKES ──────────────────────────────────────────────────────────
    # GARLIC: 566327 +7k but simple BT +38k → LEAN LONG strongly
    # OXYGEN_SNACK_COEFF now +0.35 (was -0.95) also helps all OXYGEN products
    "OXYGEN_SHAKE_GARLIC":           {"inventory_skew": -1.0,   "quote_edge": 2, "quote_size": 4, "take_edge": 3},
}

# ── SNACK lead-lag adjustments (applied when SNACK group moves) ────────────────
# OXYGEN: group-wide coefficient; UV/TRANS: per-product coefficients
# FIX: was -0.95 (SNACK up → sell OXYGEN) but ALL OXYGEN products go UP → coeff should be POSITIVE
OXYGEN_SNACK_COEFF = 0.35
# FIX: UV products all go UP strongly (RED +41k, YELLOW +31k, MAGENTA +25k)
# Original coefficients were large-negative: SNACK up → aggressively sell UV
# But UV products trend UP, so we reduce magnitude to stop fighting the uptrend
UV_SNACK_COEFFS = {
    "UV_VISOR_YELLOW":  -0.4,   # was -1.1, YELLOW +31k 2/3 days
    "UV_VISOR_RED":     -0.3,   # was -1.02, RED +41k 3/3 days
    "UV_VISOR_MAGENTA": -0.2,   # was -1.25, MAGENTA +25k 3/3 days
}
TRANS_SNACK_COEFFS = {
    "TRANSLATOR_ASTRO_BLACK": -0.375,
}

# ── MICROCHIP intra-cluster OLS residual ──────────────────────────────────────
MICRO_RESIDUAL_COEFS = {
    "MICROCHIP_CIRCLE":    {"intercept": 14328.038892180744,  "coefs": {"MICROCHIP_OVAL": -0.2144216225704393, "MICROCHIP_RECTANGLE": 0.12396982342286221, "MICROCHIP_SQUARE": -0.16261948563584036, "MICROCHIP_TRIANGLE": -0.23032920612291993}},
    "MICROCHIP_OVAL":      {"intercept": -490.56042074518695, "coefs": {"MICROCHIP_CIRCLE": -0.32945233665896556, "MICROCHIP_RECTANGLE": 0.4548644568807814, "MICROCHIP_SQUARE": -0.23348490993800003, "MICROCHIP_TRIANGLE": 1.1261280731367855}},
    "MICROCHIP_RECTANGLE": {"intercept": 12595.888646662721,  "coefs": {"MICROCHIP_CIRCLE": 0.10560729802045682, "MICROCHIP_OVAL": 0.2521946892833303, "MICROCHIP_SQUARE": -0.2712089572427364, "MICROCHIP_TRIANGLE": -0.33164490797022006}},
    "MICROCHIP_SQUARE":    {"intercept": 34622.46568370466,   "coefs": {"MICROCHIP_CIRCLE": -0.6668321009567493, "MICROCHIP_OVAL": -0.6231300836088985, "MICROCHIP_RECTANGLE": -1.3054793169494834, "MICROCHIP_TRIANGLE": 0.16662933657279733}},
    "MICROCHIP_TRIANGLE":  {"intercept": 8897.550320098617,   "coefs": {"MICROCHIP_CIRCLE": -0.17718531128501464, "MICROCHIP_OVAL": 0.5638225951568637, "MICROCHIP_RECTANGLE": -0.299484320697988, "MICROCHIP_SQUARE": 0.03125980431842272}},
}
# Increased OVAL clip 6.5 → 8.0: OVAL earns +31k but simple hold shows +44k potential
MICRO_RESIDUAL_CLIPS = {"MICROCHIP_OVAL": 8.0}

# ── Family OLS sign signal ─────────────────────────────────────────────────────
FAMILY_OLS_SIGN_ENABLED = ("GALAXY", "PANEL", "PEBBLES", "ROBOT", "SLEEP", "SNACK", "UV")
# Increased from 2.5 → 3.5: stronger signal response for mispricing detection
FAMILY_OLS_SIGN_CLIP = 3.5
FAMILY_OLS_SIGN_MODELS = {"GALAXY": {"GALAXY_SOUNDS_DARK_MATTER": {"intercept": 8960.3321419222, "coefs": {"GALAXY_SOUNDS_BLACK_HOLES": -0.006148537, "GALAXY_SOUNDS_PLANETARY_RINGS": 0.1901645717, "GALAXY_SOUNDS_SOLAR_WINDS": -0.0364035809, "GALAXY_SOUNDS_SOLAR_FLAMES": -0.0298074842}}, "GALAXY_SOUNDS_BLACK_HOLES": {"intercept": 1636.6126227244, "coefs": {"GALAXY_SOUNDS_DARK_MATTER": -0.0499588742, "GALAXY_SOUNDS_PLANETARY_RINGS": 0.0506851413, "GALAXY_SOUNDS_SOLAR_WINDS": 0.842634353, "GALAXY_SOUNDS_SOLAR_FLAMES": 0.0901890508}}, "GALAXY_SOUNDS_PLANETARY_RINGS": {"intercept": -1891.3917742908, "coefs": {"GALAXY_SOUNDS_DARK_MATTER": 1.0112819695, "GALAXY_SOUNDS_BLACK_HOLES": 0.0331728256, "GALAXY_SOUNDS_SOLAR_WINDS": 0.1227711663, "GALAXY_SOUNDS_SOLAR_FLAMES": 0.0589771496}}, "GALAXY_SOUNDS_SOLAR_WINDS": {"intercept": 11778.8258799864, "coefs": {"GALAXY_SOUNDS_DARK_MATTER": -0.0843925073, "GALAXY_SOUNDS_BLACK_HOLES": 0.2404130808, "GALAXY_SOUNDS_PLANETARY_RINGS": 0.0535196804, "GALAXY_SOUNDS_SOLAR_FLAMES": -0.343585179}}, "GALAXY_SOUNDS_SOLAR_FLAMES": {"intercept": 14350.2933170199, "coefs": {"GALAXY_SOUNDS_DARK_MATTER": -0.0604980391, "GALAXY_SOUNDS_BLACK_HOLES": 0.022528327, "GALAXY_SOUNDS_PLANETARY_RINGS": 0.0225090466, "GALAXY_SOUNDS_SOLAR_WINDS": -0.3008088524}}}, "PANEL": {"PANEL_1X2": {"intercept": 18880.8368644951, "coefs": {"PANEL_2X2": -0.5968901312, "PANEL_1X4": -0.0285265886, "PANEL_2X4": -0.2293510862, "PANEL_4X4": -0.1407190819}}, "PANEL_2X2": {"intercept": 21783.2532083775, "coefs": {"PANEL_1X2": -0.3431742449, "PANEL_1X4": 0.1810437354, "PANEL_2X4": -0.4114980013, "PANEL_4X4": -0.628654226}}, "PANEL_1X4": {"intercept": 14811.6341935249, "coefs": {"PANEL_1X2": -0.0387280047, "PANEL_2X2": 0.4275023411, "PANEL_2X4": -0.6069336034, "PANEL_4X4": -0.2353725067}}, "PANEL_2X4": {"intercept": 27117.4029813609, "coefs": {"PANEL_1X2": -0.1604564726, "PANEL_2X2": -0.5007303106, "PANEL_1X4": -0.3127680185, "PANEL_4X4": -0.6767845525}}, "PANEL_4X4": {"intercept": 20965.5535483732, "coefs": {"PANEL_1X2": -0.0643244704, "PANEL_2X2": -0.4998213206, "PANEL_1X4": -0.0792508037, "PANEL_2X4": -0.4421984588}}}, "PEBBLES": {"PEBBLES_XS": {"intercept": 49999.6913227177, "coefs": {"PEBBLES_S": -1.0000012599, "PEBBLES_M": -1.0000011192, "PEBBLES_L": -0.9999819254, "PEBBLES_XL": -0.9999934137}}, "PEBBLES_S": {"intercept": 49997.4366084325, "coefs": {"PEBBLES_XS": -0.999926002, "PEBBLES_M": -0.9999516515, "PEBBLES_L": -0.9999269781, "PEBBLES_XL": -0.99994587}}, "PEBBLES_M": {"intercept": 49998.6157521681, "coefs": {"PEBBLES_XS": -0.9999671899, "PEBBLES_S": -0.9999929811, "PEBBLES_L": -0.9999446471, "PEBBLES_XL": -0.9999655953}}, "PEBBLES_L": {"intercept": 49999.61589146, "coefs": {"PEBBLES_XS": -0.9999869766, "PEBBLES_S": -1.0000072873, "PEBBLES_M": -0.9999836268, "PEBBLES_XL": -0.9999906009}}, "PEBBLES_XL": {"intercept": 49999.939025667, "coefs": {"PEBBLES_XS": -0.999993723, "PEBBLES_S": -1.0000214387, "PEBBLES_M": -0.9999998339, "PEBBLES_L": -0.999985859}}}, "ROBOT": {"ROBOT_VACUUMING": {"intercept": 13467.0591828733, "coefs": {"ROBOT_MOPPING": -0.3170541123, "ROBOT_DISHES": -0.2870024308, "ROBOT_LAUNDRY": 0.1620715043, "ROBOT_IRONING": 0.0577339264}}, "ROBOT_MOPPING": {"intercept": 30082.6013210368, "coefs": {"ROBOT_VACUUMING": -0.6002796157, "ROBOT_DISHES": -0.5458901179, "ROBOT_LAUNDRY": -0.3338836486, "ROBOT_IRONING": -0.543718051}}, "ROBOT_DISHES": {"intercept": 26351.8560869757, "coefs": {"ROBOT_VACUUMING": -0.4479851594, "ROBOT_MOPPING": -0.4500523971, "ROBOT_LAUNDRY": -0.4464942037, "ROBOT_IRONING": -0.3270074081}}, "ROBOT_LAUNDRY": {"intercept": 14981.2504138373, "coefs": {"ROBOT_VACUUMING": 0.2554560119, "ROBOT_MOPPING": -0.2779613486, "ROBOT_DISHES": -0.4508657423, "ROBOT_IRONING": 0.0117390912}}, "ROBOT_IRONING": {"intercept": 18545.6588681297, "coefs": {"ROBOT_VACUUMING": 0.1213313931, "ROBOT_MOPPING": -0.6035255162, "ROBOT_DISHES": -0.4402725705, "ROBOT_LAUNDRY": 0.0156519013}}}, "SLEEP": {"SLEEP_POD_SUEDE": {"intercept": 2761.3840070996, "coefs": {"SLEEP_POD_LAMB_WOOL": 0.0576893789, "SLEEP_POD_POLYESTER": 0.9673055369, "SLEEP_POD_NYLON": -0.1226003829, "SLEEP_POD_COTTON": -0.195472198}}, "SLEEP_POD_LAMB_WOOL": {"intercept": 7263.8085984272, "coefs": {"SLEEP_POD_SUEDE": 0.0350993912, "SLEEP_POD_POLYESTER": -0.1651278456, "SLEEP_POD_NYLON": 0.4424417776, "SLEEP_POD_COTTON": 0.0632584393}}, "SLEEP_POD_POLYESTER": {"intercept": 84.6408404629, "coefs": {"SLEEP_POD_SUEDE": 0.5185851714, "SLEEP_POD_LAMB_WOOL": -0.1455033576, "SLEEP_POD_NYLON": 0.0699050607, "SLEEP_POD_COTTON": 0.5837152772}}, "SLEEP_POD_NYLON": {"intercept": 1250.0974254945, "coefs": {"SLEEP_POD_SUEDE": -0.0976280836, "SLEEP_POD_LAMB_WOOL": 0.5790757071, "SLEEP_POD_POLYESTER": 0.103832936, "SLEEP_POD_COTTON": 0.1798028911}}, "SLEEP_POD_COTTON": {"intercept": 78.1509839515, "coefs": {"SLEEP_POD_SUEDE": -0.1604047069, "SLEEP_POD_LAMB_WOOL": 0.0853192176, "SLEEP_POD_POLYESTER": 0.8934633677, "SLEEP_POD_NYLON": 0.1852873817}}}, "SNACK": {"SNACKPACK_CHOCOLATE": {"intercept": 19500.956658179, "coefs": {"SNACKPACK_VANILLA": -0.9220839604, "SNACKPACK_PISTACHIO": 0.1120197239, "SNACKPACK_STRAWBERRY": -0.1423269673, "SNACKPACK_RASPBERRY": 0.0112219739}}, "SNACKPACK_VANILLA": {"intercept": 20483.2542344985, "coefs": {"SNACKPACK_CHOCOLATE": -0.996916863, "SNACKPACK_PISTACHIO": 0.0889421363, "SNACKPACK_STRAWBERRY": -0.1370021971, "SNACKPACK_RASPBERRY": 0.0048938859}}, "SNACKPACK_PISTACHIO": {"intercept": 13853.2654741964, "coefs": {"SNACKPACK_CHOCOLATE": 0.4352196503, "SNACKPACK_VANILLA": 0.3196193613, "SNACKPACK_STRAWBERRY": -0.3067256211, "SNACKPACK_RASPBERRY": -0.8518468584}}, "SNACKPACK_STRAWBERRY": {"intercept": 67692.3929098779, "coefs": {"SNACKPACK_CHOCOLATE": -1.8195189506, "SNACKPACK_VANILLA": -1.6199754943, "SNACKPACK_PISTACHIO": -1.0092655388, "SNACKPACK_RASPBERRY": -1.3032960416}}, "SNACKPACK_RASPBERRY": {"intercept": 20719.311282389, "coefs": {"SNACKPACK_CHOCOLATE": 0.0395774683, "SNACKPACK_VANILLA": 0.0159640884, "SNACKPACK_PISTACHIO": -0.7732613182, "SNACKPACK_STRAWBERRY": -0.359544331}}}, "UV": {"UV_VISOR_YELLOW": {"intercept": 25282.300224443, "coefs": {"UV_VISOR_AMBER": -0.4210596715, "UV_VISOR_ORANGE": -0.2513172083, "UV_VISOR_RED": -0.8739096888, "UV_VISOR_MAGENTA": 0.1165551453}}, "UV_VISOR_AMBER": {"intercept": 31353.2846011408, "coefs": {"UV_VISOR_YELLOW": -0.1666341744, "UV_VISOR_ORANGE": -0.3846906513, "UV_VISOR_RED": -0.6172586636, "UV_VISOR_MAGENTA": -0.9697631824}}, "UV_VISOR_ORANGE": {"intercept": 19557.7589743411, "coefs": {"UV_VISOR_YELLOW": -0.1382583999, "UV_VISOR_AMBER": -0.5347619581, "UV_VISOR_RED": -0.1713385808, "UV_VISOR_MAGENTA": -0.1340781439}}, "UV_VISOR_RED": {"intercept": 27273.0191036094, "coefs": {"UV_VISOR_YELLOW": -0.3820067579, "UV_VISOR_AMBER": -0.681790992, "UV_VISOR_ORANGE": -0.1361414455, "UV_VISOR_MAGENTA": -0.4688981022}}, "UV_VISOR_MAGENTA": {"intercept": 19824.9776194823, "coefs": {"UV_VISOR_YELLOW": 0.0312302762, "UV_VISOR_AMBER": -0.6565830083, "UV_VISOR_ORANGE": -0.0653029897, "UV_VISOR_RED": -0.2874209085}}}}

# ── PANEL intraday momentum signals ───────────────────────────────────────────
PANEL_INTRADAY_SIGNALS = (
    {"product": "PANEL_1X4", "start": 600000, "end": 800000,
     "lookback": 500, "direction":  1.0, "move_per_tick": 100.0, "max_ticks": 2.0},
    {"product": "PANEL_2X4", "start":      0, "end": 100000,
     "lookback": 500, "direction": -1.0, "move_per_tick": 100.0, "max_ticks": 2.0},
)


# ── Helpers ────────────────────────────────────────────────────────────────────
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


# ── Trader ─────────────────────────────────────────────────────────────────────
class Trader:

    def run(self, state: TradingState):
        mem = _state_mem(state.traderData)
        fair_values = self._fair_values(state, mem)
        result: Dict[str, List[Order]] = {}

        for product, depth in state.order_depths.items():
            if product not in POSITION_LIMITS:          # ← ADD THIS CHECK
                continue
            if product not in ENABLED_PRODUCTS:
                result[product] = []
                continue
            fair = fair_values.get(product)
            if fair is None:
                result[product] = []
                continue
            position = int(state.position.get(product, 0))
            result[product] = self._orders_for_product(product, depth, position, fair)

        return result, 0, json.dumps(mem, separators=(",", ":"))

    def _fair_values(self, state: TradingState, mem: Dict[str, object]) -> Dict[str, float]:
        mids: Dict[str, float] = {}
        for product, depth in state.order_depths.items():
            mid = _mid(depth)
            if mid is not None:
                mids[product] = mid

        fair: Dict[str, float] = dict(mids)

        # ── SNACK lead-lag: adjust OXYGEN, selective UV, selective TRANS ──────
        prev_mids = mem.get("prev_mids") or {}
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
        mem["prev_mids"] = mids

        # ── PEBBLES basket: fair = sum_constant − sum_of_others ──────────────
        pebbles = PRODUCT_GROUPS["PEBBLES"]
        if all(p in mids for p in pebbles):
            for product in pebbles:
                fair[product] = PARAMS["pebbles_sum"] - sum(
                    mids[other] for other in pebbles if other != product
                )

        # ── MICROCHIP intra-cluster OLS residual ──────────────────────────────
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
        self._apply_panel_intraday(fair, mids, mem, state.timestamp)
        return fair

    def _apply_family_ols_sign(
        self,
        fair: Dict[str, float],
        mids: Dict[str, float],
    ) -> None:
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

    def _apply_panel_intraday(
        self,
        fair: Dict[str, float],
        mids: Dict[str, float],
        mem: Dict[str, object],
        timestamp: int,
    ) -> None:
        histories = mem.get("panel_hist") or {}
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
        mem["panel_hist"] = histories

    def _group_delta(
        self,
        group: str,
        mids: Dict[str, float],
        prev_mids: Dict[str, object],
    ) -> float | None:
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

    def _orders_for_product(
        self,
        product: str,
        depth: OrderDepth,
        position: int,
        fair: float,
    ) -> List[Order]:
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
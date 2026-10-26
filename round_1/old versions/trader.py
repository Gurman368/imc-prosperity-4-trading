from typing import Dict, List, Tuple
from datamodel import OrderDepth, TradingState, Order
import json
import math


ASH = "ASH_COATED_OSMIUM"
ROOT = "INTARIAN_PEPPER_ROOT"
EMERALDS = "EMERALDS"
TOMATOES = "TOMATOES"

MEAN_REVERT_SYMBOLS = {ASH, EMERALDS}
TREND_SYMBOLS = {ROOT, TOMATOES}
SUPPORTED = MEAN_REVERT_SYMBOLS | TREND_SYMBOLS


PARAMS = {
    f"{ASH}_POS_LIMIT": 50,
    f"{ROOT}_POS_LIMIT": 50,
    f"{EMERALDS}_POS_LIMIT": 20,
    f"{TOMATOES}_POS_LIMIT": 20,

    f"{ASH}_INV_K": 0.05,
    f"{ROOT}_INV_K": 0.04,
    f"{EMERALDS}_INV_K": 0.03,
    f"{TOMATOES}_INV_K": 0.03,

    f"{ASH}_BASE_MAKE": 1.0,
    f"{ROOT}_BASE_MAKE": 1.0,
    f"{EMERALDS}_BASE_MAKE": 1.0,
    f"{TOMATOES}_BASE_MAKE": 1.0,

    f"{ASH}_TAKE_Z": 1.2,
    f"{ROOT}_TAKE_Z": 0.6,
    f"{EMERALDS}_TAKE_Z": 1.0,
    f"{TOMATOES}_TAKE_Z": 0.6,

    "EMA_SLOW_ALPHA": 0.02,
    "EMA_FAST_ALPHA": 0.10,
    "DEV_ALPHA": 0.03,
    "SIGMA_FLOOR": 0.5,

    "OBI_TOP_N": 3,
    "OBI_THRESHOLD": 0.22,

    "TREND_HORIZON_TICKS": 20.0,
    "TREND_BIAS_CAP": 6.0,

    "MAX_ORDER_SIZE": 15,
}


def _load_data(raw: str) -> Dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _best_bid_ask(depth: OrderDepth) -> Tuple[int | None, int | None]:
    best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
    best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
    return best_bid, best_ask


def _obi(depth: OrderDepth, top_n: int) -> float:
    bids = sorted(depth.buy_orders.items(), key=lambda kv: kv[0], reverse=True)[:top_n]
    asks = sorted(depth.sell_orders.items(), key=lambda kv: kv[0])[:top_n]
    bid_v = sum(abs(v) for _, v in bids)
    ask_v = sum(abs(v) for _, v in asks)
    denom = bid_v + ask_v
    if denom <= 0:
        return 0.0
    return (bid_v - ask_v) / denom


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class Trader:
    def run(self, state: TradingState) -> Dict[str, List[Order]]:
        result: Dict[str, List[Order]] = {}
        data = _load_data(state.traderData)
        next_data = dict(data)

        for symbol, depth in state.order_depths.items():
            if symbol not in SUPPORTED:
                continue

            orders: List[Order] = []
            best_bid, best_ask = _best_bid_ask(depth)
            if best_bid is None or best_ask is None:
                result[symbol] = orders
                continue

            mid = (best_bid + best_ask) / 2.0
            pos = int(state.position.get(symbol, 0))
            limit = int(PARAMS.get(f"{symbol}_POS_LIMIT", 20))

            buy_cap = max(0, limit - pos)
            sell_cap = max(0, limit + pos)
            max_order = int(PARAMS["MAX_ORDER_SIZE"])

            s = next_data.get(symbol, {}) if isinstance(next_data.get(symbol, {}), dict) else {}
            ticks = int(s.get("ticks", 0)) + 1

            ema_slow_prev = float(s.get("ema_slow", mid))
            ema_fast_prev = float(s.get("ema_fast", mid))
            dev_prev = float(s.get("dev", PARAMS["SIGMA_FLOOR"]))

            a_slow = float(PARAMS["EMA_SLOW_ALPHA"])
            a_fast = float(PARAMS["EMA_FAST_ALPHA"])
            a_dev = float(PARAMS["DEV_ALPHA"])

            ema_slow = (1.0 - a_slow) * ema_slow_prev + a_slow * mid
            ema_fast = (1.0 - a_fast) * ema_fast_prev + a_fast * mid
            dev = (1.0 - a_dev) * dev_prev + a_dev * abs(mid - ema_slow)
            sigma = max(float(PARAMS["SIGMA_FLOOR"]), dev)

            if symbol in MEAN_REVERT_SYMBOLS:
                fair = ema_slow
            else:
                n = int(s.get("n", 0)) + 1
                sum_t = float(s.get("sum_t", 0.0)) + ticks
                sum_y = float(s.get("sum_y", 0.0)) + mid
                sum_tt = float(s.get("sum_tt", 0.0)) + ticks * ticks
                sum_ty = float(s.get("sum_ty", 0.0)) + ticks * mid

                denom = n * sum_tt - sum_t * sum_t
                if abs(denom) > 1e-9:
                    slope = (n * sum_ty - sum_t * sum_y) / denom
                else:
                    slope = float(s.get("slope", 0.0))
                intercept = (sum_y - slope * sum_t) / max(1, n)

                trend_now = intercept + slope * ticks
                trend_bias = _clip(slope * float(PARAMS["TREND_HORIZON_TICKS"]), -float(PARAMS["TREND_BIAS_CAP"]), float(PARAMS["TREND_BIAS_CAP"]))
                fair = trend_now + trend_bias

                s["n"] = n
                s["sum_t"] = sum_t
                s["sum_y"] = sum_y
                s["sum_tt"] = sum_tt
                s["sum_ty"] = sum_ty
                s["slope"] = float(slope)
                s["intercept"] = float(intercept)

            inv_k = float(PARAMS.get(f"{symbol}_INV_K", 0.03))
            fair -= inv_k * pos

            z = (mid - fair) / sigma
            take_z = float(PARAMS.get(f"{symbol}_TAKE_Z", 1.0))

            base_make = float(PARAMS.get(f"{symbol}_BASE_MAKE", 1.0))
            make_edge = max(0.5, base_make + 0.35 * sigma)

            obi = _obi(depth, int(PARAMS["OBI_TOP_N"]))
            obi_thr = float(PARAMS["OBI_THRESHOLD"])
            block_bid = obi < -obi_thr
            block_ask = obi > obi_thr

            if z < -take_z:
                for ask_px, ask_vol in sorted(depth.sell_orders.items(), key=lambda kv: kv[0]):
                    if buy_cap <= 0:
                        break
                    ask_qty = abs(int(ask_vol))
                    if ask_px <= fair - 0.2 * sigma:
                        q = min(ask_qty, buy_cap, max_order)
                        if q > 0:
                            orders.append(Order(symbol, int(ask_px), int(q)))
                            buy_cap -= q

            if z > take_z:
                for bid_px, bid_vol in sorted(depth.buy_orders.items(), key=lambda kv: kv[0], reverse=True):
                    if sell_cap <= 0:
                        break
                    bid_qty = abs(int(bid_vol))
                    if bid_px >= fair + 0.2 * sigma:
                        q = min(bid_qty, sell_cap, max_order)
                        if q > 0:
                            orders.append(Order(symbol, int(bid_px), -int(q)))
                            sell_cap -= q

            bid_quote = int(math.floor(fair - make_edge))
            ask_quote = int(math.ceil(fair + make_edge))

            if buy_cap > 0 and not block_bid:
                q = min(max_order, buy_cap)
                orders.append(Order(symbol, bid_quote, int(q)))

            if sell_cap > 0 and not block_ask:
                q = min(max_order, sell_cap)
                orders.append(Order(symbol, ask_quote, -int(q)))

            s["ticks"] = ticks
            s["ema_slow"] = float(ema_slow)
            s["ema_fast"] = float(ema_fast)
            s["dev"] = float(dev)
            s["fair"] = float(fair)
            s["z"] = float(z)
            s["obi"] = float(obi)
            next_data[symbol] = s

            result[symbol] = orders

        trader_data = json.dumps(next_data)
        conversions = 0
        return result, conversions, trader_data
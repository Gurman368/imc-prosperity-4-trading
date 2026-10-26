import json
from typing import Dict, List, Tuple
from datamodel import Order, OrderDepth, TradingState

# ================== CONSTANTS ==================
IPR_SYMBOL = "INTARIAN_PEPPER_ROOT"
OSMIUM_SYMBOL = "ASH_COATED_OSMIUM"

POSITION_LIMIT = {
    IPR_SYMBOL: 80,
    OSMIUM_SYMBOL: 80
}

# ================== TRADER ==================
class Trader:

    # ---------- IPR PARAMS ----------
    IPR_WARMUP_TICKS = 1000
    IPR_WARMUP_TAKE_EDGE = 7.0
    IPR_NORMAL_TAKE_EDGE = 9.0
    IPR_SPIKE_THRESHOLD = 2.0
    IPR_SPIKE_QTY = 8
    IPR_SELL_MIN_POS = 72

    # ---------- OSMIUM PARAMS ----------
    FAIR_VALUE = 10000
    BASE_SPREAD = 1.5

    # ================== MAIN ==================
    def run(self, state: TradingState):
        result = {}
        memory = self._load(state.traderData)

        next_memory = {
            "reached_80": memory.get("reached_80", False)
        }

        for symbol, depth in state.order_depths.items():
            position = state.position.get(symbol, 0)

            if symbol == IPR_SYMBOL:
                reached = next_memory["reached_80"]

                if position >= POSITION_LIMIT[IPR_SYMBOL]:
                    reached = True

                orders = self.trade_ipr(depth, position, state.timestamp, reached)
                next_memory["reached_80"] = reached

            elif symbol == OSMIUM_SYMBOL:
                orders = self.trade_osmium(depth, position)

            else:
                orders = []

            result[symbol] = orders

        return result, 0, json.dumps(next_memory)

    # ================== MEMORY ==================
    def _load(self, data):
        try:
            return json.loads(data) if data else {}
        except:
            return {}

    # ================== FAIR ==================
    def ipr_fair(self, mid, t):
        base = round((mid - t / 1000) / 1000) * 1000
        return base + t / 1000

    # ================== IPR STRATEGY ==================
    def trade_ipr(self, depth, pos, t, reached_80):

        orders = []

        best_bid = max(depth.buy_orders) if depth.buy_orders else None
        best_ask = min(depth.sell_orders) if depth.sell_orders else None

        if best_bid is None and best_ask is None:
            return orders

        # ---- MID ----
        if best_bid and best_ask:
            mid = (best_bid + best_ask) / 2
        elif best_bid:
            mid = best_bid
        else:
            mid = best_ask

        fair = self.ipr_fair(mid, t)

        buy_cap = POSITION_LIMIT[IPR_SYMBOL] - pos
        sell_cap = POSITION_LIMIT[IPR_SYMBOL] + pos

        # ================= ACCUMULATION =================
        if not reached_80:

            edge = self.IPR_WARMUP_TAKE_EDGE if t < self.IPR_WARMUP_TICKS else self.IPR_NORMAL_TAKE_EDGE

            # --- TAKE ASK ---
            for ask in sorted(depth.sell_orders):
                if ask > fair + edge or buy_cap <= 0:
                    break
                qty = min(-depth.sell_orders[ask], buy_cap)
                orders.append(Order(IPR_SYMBOL, ask, qty))
                buy_cap -= qty

            # --- PASSIVE BID ---
            if buy_cap > 0 and best_bid:
                price = best_bid + 1
                if best_ask and price >= best_ask:
                    price = best_ask - 1
                orders.append(Order(IPR_SYMBOL, price, buy_cap))

            # --- SELL OVERLAY ---
            if pos >= self.IPR_SELL_MIN_POS:

                # spike sell
                sold = 0
                for bid in sorted(depth.buy_orders, reverse=True):
                    if sell_cap <= 0:
                        break
                    if bid - fair < self.IPR_SPIKE_THRESHOLD:
                        break

                    qty = min(
                        depth.buy_orders[bid],
                        self.IPR_SPIKE_QTY - sold,
                        sell_cap,
                        pos - self.IPR_SELL_MIN_POS
                    )

                    if qty <= 0:
                        break

                    orders.append(Order(IPR_SYMBOL, bid, -qty))
                    sold += qty
                    sell_cap -= qty

                # passive ask
                if sell_cap > 0 and best_ask:
                    price = max(best_ask - 1, int(fair) + 1)
                    qty = min(sell_cap, self.IPR_SPIKE_QTY, pos - self.IPR_SELL_MIN_POS)
                    if qty > 0:
                        orders.append(Order(IPR_SYMBOL, price, -qty))

            return orders

        # ================= STEADY =================

        # BUY
        if buy_cap > 0:
            for ask in sorted(depth.sell_orders):
                if ask >= fair:
                    break
                qty = min(-depth.sell_orders[ask], buy_cap)
                orders.append(Order(IPR_SYMBOL, ask, qty))
                buy_cap -= qty

            if best_bid:
                price = min(best_bid + 1, int(fair) - 1)
                if price > 0:
                    orders.append(Order(IPR_SYMBOL, price, buy_cap))

        # SELL
        if pos >= self.IPR_SELL_MIN_POS:

            sold = 0
            for bid in sorted(depth.buy_orders, reverse=True):
                if sell_cap <= 0:
                    break
                if bid - fair < self.IPR_SPIKE_THRESHOLD:
                    break

                qty = min(
                    depth.buy_orders[bid],
                    self.IPR_SPIKE_QTY - sold,
                    sell_cap,
                    pos - self.IPR_SELL_MIN_POS
                )

                if qty <= 0:
                    break

                orders.append(Order(IPR_SYMBOL, bid, -qty))
                sold += qty
                sell_cap -= qty

            if sell_cap > 0 and best_ask:
                price = max(best_ask - 1, int(fair) + 1)
                qty = min(sell_cap, self.IPR_SPIKE_QTY, pos - self.IPR_SELL_MIN_POS)
                if qty > 0:
                    orders.append(Order(IPR_SYMBOL, price, -qty))

        return orders

    # ================== OSMIUM STRATEGY ==================
    def trade_osmium(self, depth, pos):

        orders = []

        best_bid = max(depth.buy_orders) if depth.buy_orders else None
        best_ask = min(depth.sell_orders) if depth.sell_orders else None

        if best_bid is None or best_ask is None:
            return orders

        fair = self.FAIR_VALUE
        spread = best_ask - best_bid

        buy_cap = POSITION_LIMIT[OSMIUM_SYMBOL] - pos
        sell_cap = POSITION_LIMIT[OSMIUM_SYMBOL] + pos

        bid_target = fair - self.BASE_SPREAD
        ask_target = fair + self.BASE_SPREAD

        # TAKE
        for ask in depth.sell_orders:
            if ask <= bid_target:
                qty = min(-depth.sell_orders[ask], buy_cap)
                orders.append(Order(OSMIUM_SYMBOL, ask, qty))
                buy_cap -= qty

        for bid in depth.buy_orders:
            if bid >= ask_target:
                qty = min(depth.buy_orders[bid], sell_cap)
                orders.append(Order(OSMIUM_SYMBOL, bid, -qty))
                sell_cap -= qty

        # MARKET MAKING
        if buy_cap > 0:
            orders.append(Order(OSMIUM_SYMBOL, best_bid + 1, buy_cap))

        if sell_cap > 0:
            orders.append(Order(OSMIUM_SYMBOL, best_ask - 1, -sell_cap))

        return orders
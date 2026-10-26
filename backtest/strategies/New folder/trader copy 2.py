from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order
import json
import math

STATIC_SYMBOL = "EMERALDS"
DYNAMIC_SYMBOL = "TOMATOES"

POS_LIMITS = {
    STATIC_SYMBOL: 20,
    DYNAMIC_SYMBOL: 50,
}

#############################################
# BASE TRADER
#############################################

class ProductTrader:

    def __init__(self, name, state, prints, new_trader_data):

        self.name = name
        self.state = state
        self.orders = []
        self.prints = prints
        self.new_trader_data = new_trader_data

        self.position_limit = POS_LIMITS[self.name]
        self.initial_position = state.position.get(self.name, 0)

        self.mkt_buy_orders, self.mkt_sell_orders = self.get_order_depth()

        self.best_bid, self.best_ask = self.get_best_bid_ask()

        if self.best_bid and self.best_ask:
            self.mid = (self.best_bid + self.best_ask) / 2
        else:
            self.mid = None

        self.max_allowed_buy_volume = self.position_limit - self.initial_position
        self.max_allowed_sell_volume = self.position_limit + self.initial_position


    def get_order_depth(self):

        depth: OrderDepth = self.state.order_depths[self.name]

        buy = {p: abs(v) for p, v in sorted(depth.buy_orders.items(), reverse=True)}
        sell = {p: abs(v) for p, v in sorted(depth.sell_orders.items())}

        return buy, sell


    def get_best_bid_ask(self):

        best_bid = None
        best_ask = None

        if len(self.mkt_buy_orders) > 0:
            best_bid = max(self.mkt_buy_orders.keys())

        if len(self.mkt_sell_orders) > 0:
            best_ask = min(self.mkt_sell_orders.keys())

        return best_bid, best_ask


    def bid(self, price, volume):

        vol = min(volume, self.max_allowed_buy_volume)

        if vol > 0:
            self.orders.append(Order(self.name, int(price), int(vol)))
            self.max_allowed_buy_volume -= vol


    def ask(self, price, volume):

        vol = min(volume, self.max_allowed_sell_volume)

        if vol > 0:
            self.orders.append(Order(self.name, int(price), -int(vol)))
            self.max_allowed_sell_volume -= vol


#############################################
# EMERALDS MARKET MAKER (ORIGINAL STYLE)
#############################################

class StaticTrader(ProductTrader):

    def get_orders(self):

        if self.best_bid is None or self.best_ask is None:
            return {self.name: self.orders}

        fair_price = self.mid

        # TAKE MISPRICED ORDERS
        for sp, sv in self.mkt_sell_orders.items():

            if sp < fair_price and self.max_allowed_buy_volume > 0:
                self.bid(sp, sv)

        for bp, bv in self.mkt_buy_orders.items():

            if bp > fair_price and self.max_allowed_sell_volume > 0:
                self.ask(bp, bv)

        # MARKET MAKING
        bid_price = int(fair_price - 1)
        ask_price = int(fair_price + 1)

        self.bid(bid_price, self.max_allowed_buy_volume)
        self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


#############################################
# TOMATOES ALPHA STRATEGY
#############################################

class AlphaTrader(ProductTrader):

    def microprice(self):

        bid_vol = self.mkt_buy_orders.get(self.best_bid, 1)
        ask_vol = self.mkt_sell_orders.get(self.best_ask, 1)

        return (self.best_ask * bid_vol + self.best_bid * ask_vol) / (bid_vol + ask_vol)


    def queue_imbalance(self):

        bid_vol = self.mkt_buy_orders.get(self.best_bid, 0)
        ask_vol = self.mkt_sell_orders.get(self.best_ask, 0)

        if bid_vol + ask_vol == 0:
            return 0

        return (bid_vol - ask_vol) / (bid_vol + ask_vol)


    def trade_imbalance(self):

        bid_vol = sum(self.mkt_buy_orders.values())
        ask_vol = sum(self.mkt_sell_orders.values())

        if bid_vol + ask_vol == 0:
            return 0

        return (bid_vol - ask_vol) / (bid_vol + ask_vol)


    def inventory_skew(self):

        return self.initial_position / self.position_limit


    def get_orders(self):

        if self.best_bid is None or self.best_ask is None:
            return {self.name: self.orders}

        micro = self.microprice()
        qi = self.queue_imbalance()
        ti = self.trade_imbalance()
        inv = self.inventory_skew()

        signal = (
            (micro - self.mid)
            + 2 * qi
            + 0.5 * ti
            - 1.5 * inv
        )

        fair_price = self.mid + signal

        bid_price = int(fair_price - 1)
        ask_price = int(fair_price + 1)

        # TAKE MISPRICED ORDERS
        for sp, sv in self.mkt_sell_orders.items():

            if sp < fair_price and self.max_allowed_buy_volume > 0:
                self.bid(sp, sv)

        for bp, bv in self.mkt_buy_orders.items():

            if bp > fair_price and self.max_allowed_sell_volume > 0:
                self.ask(bp, bv)

        # MARKET MAKING
        self.bid(bid_price, self.max_allowed_buy_volume)
        self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


#############################################
# MAIN TRADER
#############################################

class Trader:

    def run(self, state: TradingState):

        result: Dict[str, List[Order]] = {}
        new_trader_data = {}
        prints = {}

        product_map = {
            STATIC_SYMBOL: StaticTrader,
            DYNAMIC_SYMBOL: AlphaTrader,
        }

        conversions = 0

        for symbol in state.order_depths:

            if symbol in product_map:

                try:

                    trader_class = product_map[symbol]
                    trader = trader_class(symbol, state, prints, new_trader_data)

                    result.update(trader.get_orders())

                except Exception:
                    pass

        try:
            final_trader_data = json.dumps(new_trader_data)
        except:
            final_trader_data = ""

        return result, conversions, final_trader_data
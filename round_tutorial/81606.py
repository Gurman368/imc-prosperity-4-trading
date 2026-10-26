from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order
import json
import math

####### GENERAL CONSTANTS #######

STATIC_SYMBOL = 'ASH_COATED_OSMIUM'
DYNAMIC_SYMBOL = 'INTARIAN_PEPPER_ROOT'

POS_LIMITS = {
    STATIC_SYMBOL: 80,
    DYNAMIC_SYMBOL: 80,
}

####### TUNING PARAMETERS (TOMATOES) #######
FAST_EMA_ALPHA = 0.45
SLOW_EMA_ALPHA = 0.04
OBI_WEIGHT = 10.0
TOMATOES_LEAN_MULTIPLIER = 0.5

####### TUNING PARAMETERS (EMERALDS) #######
EMERALDS_FAIR_VALUE = 10000
EMERALDS_SKEW_FACTOR = 4.0


##################################

class ProductTrader:

    def __init__(self, name, state, prints, new_trader_data, product_group=None):

        self.orders = []

        self.name = name
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data
        self.product_group = name if product_group is None else product_group

        self.last_traderData = self.get_last_traderData()

        self.position_limit = POS_LIMITS.get(self.name, 80)
        self.initial_position = self.state.position.get(self.name, 0)

        self.mkt_buy_orders, self.mkt_sell_orders = self.get_order_depth()
        self.bid_wall, self.wall_mid, self.ask_wall = self.get_walls()
        self.best_bid, self.best_ask = self.get_best_bid_ask()

        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self.get_max_allowed_volume()
        self.total_mkt_buy_volume, self.total_mkt_sell_volume = self.get_total_market_buy_sell_volume()

        self.obi = self.get_orderbook_imbalance()

    def get_last_traderData(self):
        last_traderData = {}
        try:
            if self.state.traderData != '':
                last_traderData = json.loads(self.state.traderData)
        except:
            pass
        return last_traderData

    def get_best_bid_ask(self):
        best_bid = best_ask = None
        try:
            if len(self.mkt_buy_orders) > 0:
                best_bid = max(self.mkt_buy_orders.keys())
            if len(self.mkt_sell_orders) > 0:
                best_ask = min(self.mkt_sell_orders.keys())
        except:
            pass
        return best_bid, best_ask

    def get_walls(self):
        bid_wall = wall_mid = ask_wall = None
        try:
            bid_wall = min([x for x, _ in self.mkt_buy_orders.items()])
        except:
            pass
        try:
            ask_wall = max([x for x, _ in self.mkt_sell_orders.items()])
        except:
            pass
        try:
            wall_mid = (bid_wall + ask_wall) / 2
        except:
            pass
        return bid_wall, wall_mid, ask_wall

    def get_total_market_buy_sell_volume(self):
        market_bid_volume = market_ask_volume = 0
        try:
            market_bid_volume = sum([v for p, v in self.mkt_buy_orders.items()])
            market_ask_volume = sum([v for p, v in self.mkt_sell_orders.items()])
        except:
            pass
        return market_bid_volume, market_ask_volume

    def get_orderbook_imbalance(self):
        bid_vol = sum(self.mkt_buy_orders.values())
        ask_vol = sum(self.mkt_sell_orders.values())
        if bid_vol + ask_vol == 0:
            return 0
        return (bid_vol - ask_vol) / (bid_vol + ask_vol)

    def get_max_allowed_volume(self):
        max_allowed_buy_volume = self.position_limit - self.initial_position
        max_allowed_sell_volume = self.position_limit + self.initial_position
        return max_allowed_buy_volume, max_allowed_sell_volume

    def get_order_depth(self):
        order_depth, buy_orders, sell_orders = {}, {}, {}
        try:
            order_depth: OrderDepth = self.state.order_depths[self.name]
        except:
            pass
        try:
            buy_orders = {bp: abs(bv) for bp, bv in
                          sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)}
        except:
            pass
        try:
            sell_orders = {sp: abs(sv) for sp, sv in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])}
        except:
            pass
        return buy_orders, sell_orders

    def bid(self, price, volume):
        abs_volume = min(abs(int(volume)), self.max_allowed_buy_volume)
        if abs_volume > 0:
            order = Order(self.name, int(price), abs_volume)
            self.max_allowed_buy_volume -= abs_volume
            self.orders.append(order)

    def ask(self, price, volume):
        abs_volume = min(abs(int(volume)), self.max_allowed_sell_volume)
        if abs_volume > 0:
            order = Order(self.name, int(price), -abs_volume)
            self.max_allowed_sell_volume -= abs_volume
            self.orders.append(order)

    def get_orders(self):
        return {}


class EmeraldTrader(ProductTrader):

    def __init__(self, name, state, prints, new_trader_data):
        super().__init__(name, state, prints, new_trader_data)

    def get_orders(self):
        if self.wall_mid is None:
            return {self.name: self.orders}

        inventory_lean = -(self.initial_position / self.position_limit) * EMERALDS_SKEW_FACTOR
        fair_value = EMERALDS_FAIR_VALUE + inventory_lean

        # TAKING
        for sp, sv in self.mkt_sell_orders.items():
            if sp <= fair_value - 1:
                self.bid(sp, sv)
            elif sp <= fair_value and self.initial_position < 0:
                volume = min(sv, abs(self.initial_position))
                self.bid(sp, volume)

        for bp, bv in self.mkt_buy_orders.items():
            if bp >= fair_value + 1:
                self.ask(bp, bv)
            elif bp >= fair_value and self.initial_position > 0:
                volume = min(bv, self.initial_position)
                self.ask(bp, volume)

        # MAKING
        bid_price = int(self.bid_wall + 1)
        ask_price = int(self.ask_wall - 1)

        for bp, bv in self.mkt_buy_orders.items():
            overbidding_price = bp + 1
            if bv > 1 and overbidding_price < fair_value:
                bid_price = max(bid_price, overbidding_price)
                break
            elif bp < fair_value:
                bid_price = max(bid_price, bp)
                break

        for sp, sv in self.mkt_sell_orders.items():
            underbidding_price = sp - 1
            if sv > 1 and underbidding_price > fair_value:
                ask_price = min(ask_price, underbidding_price)
                break
            elif sp > fair_value:
                ask_price = min(ask_price, sp)
                break

        self.bid(bid_price, self.max_allowed_buy_volume)
        self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


class TomatoTrader(ProductTrader):

    def __init__(self, name, state, prints, new_trader_data):
        super().__init__(name, state, prints, new_trader_data)

    def get_orders(self):
        if self.wall_mid is None:
            return {self.name: self.orders}

        ##########################################################
        # EMA FAIR VALUE
        ##########################################################
        last_fast = self.last_traderData.get('fast_ema', self.wall_mid)
        last_slow = self.last_traderData.get('slow_ema', self.wall_mid)

        fast_ema = last_fast + FAST_EMA_ALPHA * (self.wall_mid - last_fast)
        slow_ema = last_slow + SLOW_EMA_ALPHA * (self.wall_mid - last_slow)

        self.new_trader_data['fast_ema'] = fast_ema
        self.new_trader_data['slow_ema'] = slow_ema

        trend_shift = fast_ema - slow_ema
        obi_shift = self.obi * OBI_WEIGHT
        inventory_lean = -(self.initial_position / self.position_limit) * TOMATOES_LEAN_MULTIPLIER

        fair_value = self.wall_mid + trend_shift + obi_shift + inventory_lean

        ##########################################################
        # TAKING
        ##########################################################
        for sp, sv in self.mkt_sell_orders.items():
            if sp <= fair_value - 1:
                self.bid(sp, sv)
            elif sp <= fair_value and self.initial_position < 0:
                volume = min(sv, abs(self.initial_position))
                self.bid(sp, volume)

        for bp, bv in self.mkt_buy_orders.items():
            if bp >= fair_value + 1:
                self.ask(bp, bv)
            elif bp >= fair_value and self.initial_position > 0:
                volume = min(bv, self.initial_position)
                self.ask(bp, volume)

        ##########################################################
        # MAKING
        ##########################################################
        bid_price = int(self.bid_wall + 1)
        ask_price = int(self.ask_wall - 1)

        for bp, bv in self.mkt_buy_orders.items():
            overbidding_price = bp + 1
            if bv > 1 and overbidding_price < fair_value:
                bid_price = max(bid_price, overbidding_price)
                break
            elif bp < fair_value:
                bid_price = max(bid_price, bp)
                break

        for sp, sv in self.mkt_sell_orders.items():
            underbidding_price = sp - 1
            if sv > 1 and underbidding_price > fair_value:
                ask_price = min(ask_price, underbidding_price)
                break
            elif sp > fair_value:
                ask_price = min(ask_price, sp)
                break

        self.bid(bid_price, self.max_allowed_buy_volume)
        self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


class Trader:

    def run(self, state: TradingState) -> Dict[str, List[Order]]:

        result: dict[str, list[Order]] = {}
        new_trader_data = {}
        prints = {}

        product_map = {
            STATIC_SYMBOL: (EmeraldTrader, STATIC_SYMBOL),
            DYNAMIC_SYMBOL: (TomatoTrader, DYNAMIC_SYMBOL),
        }

        conversions = 0

        for symbol in state.order_depths:
            if symbol in product_map:
                try:
                    trader_class, name = product_map[symbol]
                    trader = trader_class(name, state, prints, new_trader_data)
                    result.update(trader.get_orders())
                except:
                    pass

        try:
            final_trader_data = json.dumps(new_trader_data)
        except:
            final_trader_data = ''

        return result, conversions, final_trader_data
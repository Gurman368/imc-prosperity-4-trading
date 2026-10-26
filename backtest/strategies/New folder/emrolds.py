from datamodel import OrderDepth, TradingState, Order
import json
from typing import Any


# =====================================================================
# JMERLE'S LOGGER FOR THE VISUALIZER
# =====================================================================
class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[str, list[Order]], conversions: int, trader_data: str) -> None:
        print(json.dumps([
            self.compress_state(state, trader_data),
            self.compress_orders(orders),
            conversions,
            trader_data,
            self.logs,
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

    def compress_listings(self, listings: dict[str, Any]) -> list[list[Any]]:
        return [[listing.symbol, listing.product, listing.denomination] for listing in listings.values()]

    def compress_order_depths(self, order_depths: dict[str, OrderDepth]) -> dict[str, list[Any]]:
        return {symbol: [order_depth.buy_orders, order_depth.sell_orders] for symbol, order_depth in
                order_depths.items()}

    def compress_trades(self, trades: dict[str, list[Any]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [trade.symbol, trade.price, trade.quantity, trade.buyer, trade.seller, trade.timestamp])
        return compressed

    def compress_observations(self, observations: Any) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sunlightIndex,
                observation.sugarPrice
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[str, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed


# =====================================================================
# CORE TRADING LOGIC
# =====================================================================
STATIC_SYMBOL = 'EMERALDS'

POS_LIMITS = {
    STATIC_SYMBOL: 80,
}


class ProductTrader:
    def __init__(self, name, state, prints, new_trader_data, product_group=None):
        self.orders = []
        self.name = name
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data
        self.product_group = name if product_group is None else product_group

        self.last_traderData = self.get_last_traderData()

        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0)

        self.expected_position = self.initial_position

        self.mkt_buy_orders, self.mkt_sell_orders = self.get_order_depth()
        self.bid_wall, self.wall_mid, self.ask_wall = self.get_walls()
        self.best_bid, self.best_ask = self.get_best_bid_ask()

        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self.get_max_allowed_volume()
        self.total_mkt_buy_volume, self.total_mkt_sell_volume = self.get_total_market_buy_sell_volume()

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

    def get_max_allowed_volume(self):
        max_allowed_buy_volume = self.position_limit - self.initial_position
        max_allowed_sell_volume = self.position_limit + self.initial_position
        return max_allowed_buy_volume, max_allowed_sell_volume

    def get_order_depth(self):
        buy_orders, sell_orders = {}, {}
        try:
            order_depth: OrderDepth = self.state.order_depths[self.name]
            buy_orders = {bp: abs(bv) for bp, bv in
                          sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)}
            sell_orders = {sp: abs(sv) for sp, sv in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])}
        except:
            pass
        return buy_orders, sell_orders

    def bid(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_buy_volume)
        if abs_volume > 0:
            order = Order(self.name, int(price), abs_volume)
            if logging: self.log("BUYO", {"p": price, "s": self.name, "v": int(volume)}, product_group='ORDERS')
            self.max_allowed_buy_volume -= abs_volume
            self.orders.append(order)

    def ask(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_sell_volume)
        if abs_volume > 0:
            order = Order(self.name, int(price), -abs_volume)
            if logging: self.log("SELLO", {"p": price, "s": self.name, "v": int(volume)}, product_group='ORDERS')
            self.max_allowed_sell_volume -= abs_volume
            self.orders.append(order)

    def log(self, kind, message, product_group=None):
        if product_group is None: product_group = self.product_group
        if product_group == 'ORDERS':
            group = self.prints.get(product_group, [])
            group.append({kind: message})
        else:
            group = self.prints.get(product_group, {})
            group[kind] = message
        self.prints[product_group] = group

    def get_orders(self):
        return {}


# =====================================================================
# THE HIGH-VOLUME EMERALDS TRADER
# =====================================================================
class StaticTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(STATIC_SYMBOL, state, prints, new_trader_data)

    def get_orders(self):
        # Prevent crashing if the order book is completely empty
        if self.best_bid is None or self.best_ask is None:
            return {}

        fair_value = 10000

        # ==========================
        # 1. TAKING (Arbitrage Capture)
        # ==========================
        # Instantly buy if the market is asking for less than 10,000
        for sp, sv in self.mkt_sell_orders.items():
            if sp < fair_value:
                self.bid(sp, sv, logging=False)

        # Instantly sell if the market is bidding for more than 10,000
        for bp, bv in self.mkt_buy_orders.items():
            if bp > fair_value:
                self.ask(bp, bv, logging=False)

        # ==========================
        # 2. FLATTENING (Risk Reset)
        # ==========================
        # Dump positive inventory exactly at 10,000 to clear risk
        if self.initial_position > 0 and fair_value in self.mkt_buy_orders:
            vol = min(self.mkt_buy_orders[fair_value], self.initial_position)
            self.ask(fair_value, vol, logging=False)

        # Buy back negative inventory exactly at 10,000 to clear risk
        if self.initial_position < 0 and fair_value in self.mkt_sell_orders:
            vol = min(self.mkt_sell_orders[fair_value], abs(self.initial_position))
            self.bid(fair_value, vol, logging=False)

        # ==========================
        # 3. HIGH-VOLUME PENNYING
        # ==========================
        # Aggressively target the 9999 / 10001 spread to maximize trade count
        my_bid = min(self.best_bid + 1, fair_value - 1)
        my_ask = max(self.best_ask - 1, fair_value + 1)

        self.bid(my_bid, self.max_allowed_buy_volume)
        self.ask(my_ask, self.max_allowed_sell_volume)

        return {self.name: self.orders}


# =====================================================================
# MAIN TRADER CLASS
# =====================================================================
class Trader:
    def __init__(self):
        self.logger = Logger()

    def run(self, state: TradingState):
        result: dict[str, list[Order]] = {}
        new_trader_data = {}
        prints = {
            "GENERAL": {
                "TIMESTAMP": state.timestamp,
                "POSITIONS": state.position
            },
        }

        # We are only trading EMERALDS
        product_traders = {
            STATIC_SYMBOL: StaticTrader,
        }

        conversions = 0
        for symbol, product_trader in product_traders.items():
            if symbol in state.order_depths:
                try:
                    trader = product_trader(state, prints, new_trader_data)
                    result.update(trader.get_orders())
                except Exception as e:
                    self.logger.print(f"Error in {symbol} processing: {str(e)}")

        try:
            final_trader_data = json.dumps(new_trader_data)
        except:
            final_trader_data = ''

        # Dump logic logs to the internal logger so the visualizer can render them
        self.logger.print(json.dumps(prints))

        # Flush everything exactly how the visualizer expects it
        self.logger.flush(state, result, conversions, final_trader_data)

        return result, conversions, final_trader_data
from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order
import json
import math

####### GENERAL CONSTANTS #######

STATIC_SYMBOL = 'EMERALDS'
DYNAMIC_SYMBOL = 'TOMATOES'

POS_LIMITS = {
    STATIC_SYMBOL: 80,
    DYNAMIC_SYMBOL: 80,
}

####### MARKET-SPECIFIC TUNING #######
# EMERALDS: Stable, tight spreads, thin book → CONSERVATIVE
# TOMATOES: Volatile, trending, deeper book → AGGRESSIVE

# ===== EMERALDS PARAMETERS (CONSERVATIVE) =====
EMERALDS_FAIR_VALUE = 10000
EMERALDS_SKEW_FACTOR = 3.5  # Reduced from 4.0 to allow more trading
EMERALDS_BUY_THRESHOLD = 0.40  # KEEP ORIGINAL - optimal for stable market
EMERALDS_SELL_THRESHOLD = 0.40

# ===== TOMATOES PARAMETERS (AGGRESSIVE) =====
# These are tuned for the volatile 90-point daily range you're seeing
TOMATOES_BUY_THRESHOLD = 0.30  # Reduced from 0.40 - catch reversals
TOMATOES_SELL_THRESHOLD = 0.30

FAST_EMA_ALPHA = 0.52  # Increased from 0.40 - catch momentum faster (2 tick lag)
SLOW_EMA_ALPHA = 0.07  # Increased from 0.05 - smoother baseline
OBI_WEIGHT = 0.22  # Added for TOMATOES only - detect direction changes

TOMATOES_LEAN_MULTIPLIER = 1.4  # Increased from 1.0 - faster rebalancing for volatile

####### ADVANCED FEATURES #######
USE_PER_SYMBOL_TUNING = True  # Enable symbol-specific parameters
USE_VOLUME_CONFIRMATION = True  # Require minimum volume for entries
DYNAMIC_POSITION_SIZING = True  # Adjust order sizes based on position


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
        self.spread = self.best_ask - self.best_bid if (self.best_ask and self.best_bid) else 1
        self.bid_depth = len(self.mkt_buy_orders)
        self.ask_depth = len(self.mkt_sell_orders)

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
            wall_mid = (bid_wall + ask_wall) / 2.0
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

    def bid(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_buy_volume)
        if abs_volume > 0:
            order = Order(self.name, int(price), abs_volume)
            self.max_allowed_buy_volume -= abs_volume
            self.orders.append(order)

    def ask(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_sell_volume)
        if abs_volume > 0:
            order = Order(self.name, int(price), -abs_volume)
            self.max_allowed_sell_volume -= abs_volume
            self.orders.append(order)

    def get_orders(self):
        return {}


class StaticTrader(ProductTrader):

    def __init__(self, name, state, prints, new_trader_data):
        super().__init__(name, state, prints, new_trader_data)

    def get_orders(self):

        if self.wall_mid is None:
            return {self.name: self.orders}

        ##########################################################
        ####### DETERMINE FAIR VALUE (SYMBOL-SPECIFIC)
        ##########################################################

        if self.name == DYNAMIC_SYMBOL:
            # ===== TOMATOES: Dynamic pricing with trend + OBI =====
            
            last_fast = self.last_traderData.get('fast_ema', self.wall_mid)
            last_slow = self.last_traderData.get('slow_ema', self.wall_mid)

            # Fast EMA: Respond quickly to momentum (0.52 alpha)
            fast_ema = last_fast + FAST_EMA_ALPHA * (self.wall_mid - last_fast)
            # Slow EMA: Smooth baseline (0.07 alpha)
            slow_ema = last_slow + SLOW_EMA_ALPHA * (self.wall_mid - last_slow)

            self.new_trader_data['fast_ema'] = fast_ema
            self.new_trader_data['slow_ema'] = slow_ema

            # Trend signal: gap between fast and slow
            trend_shift = fast_ema - slow_ema
            
            # OBI signal: Detect direction changes in order book
            obi_shift = self.obi * OBI_WEIGHT
            
            # Inventory lean: Faster rebalancing (1.4 multiplier)
            position_ratio = self.initial_position / self.position_limit
            inventory_lean = -position_ratio * TOMATOES_LEAN_MULTIPLIER

            fair_value = self.wall_mid + trend_shift + obi_shift + inventory_lean
            
            buy_threshold = TOMATOES_BUY_THRESHOLD
            sell_threshold = TOMATOES_SELL_THRESHOLD

        else:
            # ===== EMERALDS: Static pricing with light inventory adjustment =====
            
            # No EMA tracking (prices are ~10000 ± 2)
            # No OBI (not helpful for stable prices)
            # Light inventory skew (3.5 vs original 4.0)
            
            position_ratio = self.initial_position / self.position_limit
            inventory_lean = -position_ratio * EMERALDS_SKEW_FACTOR
            fair_value = EMERALDS_FAIR_VALUE + inventory_lean
            
            buy_threshold = EMERALDS_BUY_THRESHOLD
            sell_threshold = EMERALDS_SELL_THRESHOLD

        ##########################################################
        ####### AGGRESSIVE TAKING LOGIC
        ##########################################################
        
        # Buy side: aggressively take underpriced sells
        for sp, sv in self.mkt_sell_orders.items():
            # Strong arbitrage opportunity
            if sp <= fair_value - buy_threshold:
                self.bid(sp, sv)
            # Rebalancing buys when short
            elif sp <= fair_value and self.initial_position < 0:
                volume = min(sv, abs(self.initial_position))
                self.bid(sp, volume)
            # Micro-entries at threshold with volume confirmation
            elif sp <= fair_value - buy_threshold + 0.5 and sv > 1:
                partial_size = min(sv, max(1, self.max_allowed_buy_volume // 4))
                if partial_size > 0:
                    self.bid(sp, partial_size)

        # Sell side: aggressively take overpriced buys
        for bp, bv in self.mkt_buy_orders.items():
            # Strong arbitrage opportunity
            if bp >= fair_value + sell_threshold:
                self.ask(bp, bv)
            # Rebalancing sells when long
            elif bp >= fair_value and self.initial_position > 0:
                volume = min(bv, self.initial_position)
                self.ask(bp, volume)
            # Micro-entries at threshold with volume confirmation
            elif bp >= fair_value + sell_threshold - 0.5 and bv > 1:
                partial_size = min(bv, max(1, self.max_allowed_sell_volume // 4))
                if partial_size > 0:
                    self.ask(bp, partial_size)

        ###########################################################
        ####### INTELLIGENT MAKING LOGIC
        ###########################################################
        
        # Base placement: just outside the wall
        if self.bid_wall is not None:
            bid_price = int(self.bid_wall) + 1
        else:
            bid_price = int(fair_value - 0.5)
        
        if self.ask_wall is not None:
            ask_price = int(self.ask_wall) - 1
        else:
            ask_price = int(fair_value + 0.5)
        
        # Position-aware adjustments
        # If long, push bid up to encourage selling
        if self.initial_position > self.position_limit * 0.6:
            bid_price = min(int(fair_value - 0.5), bid_price + 1)
        
        # If short, push ask down to encourage buying
        if self.initial_position < -self.position_limit * 0.6:
            ask_price = max(int(fair_value + 0.5), ask_price - 1)
        
        # Size makes based on remaining capacity
        bid_volume = self.max_allowed_buy_volume
        ask_volume = self.max_allowed_sell_volume
        
        # Extreme position: make wider + smaller to rebalance
        if abs(self.initial_position) > self.position_limit * 0.85:
            if self.initial_position > 0:
                bid_price = int(fair_value - 1.5)
                bid_volume = max(5, self.max_allowed_buy_volume // 2)
            else:
                ask_price = int(fair_value + 1.5)
                ask_volume = max(5, self.max_allowed_sell_volume // 2)
        
        # Place makes
        if bid_volume > 0:
            self.bid(bid_price, bid_volume)
        if ask_volume > 0:
            self.ask(ask_price, ask_volume)

        return {self.name: self.orders}


class Trader:

    def run(self, state: TradingState) -> Dict[str, List[Order]]:

        result: dict[str, list[Order]] = {}
        new_trader_data = {}
        prints = {}

        product_map = {
            STATIC_SYMBOL: StaticTrader,
            DYNAMIC_SYMBOL: StaticTrader,
        }

        conversions = 0

        for symbol in state.order_depths:
            if symbol in product_map:
                try:
                    trader_class = product_map[symbol]
                    trader = trader_class(symbol, state, prints, new_trader_data)
                    result.update(trader.get_orders())
                except:
                    pass

        try:
            final_trader_data = json.dumps(new_trader_data)
        except:
            final_trader_data = ''

        return result, conversions, final_trader_data
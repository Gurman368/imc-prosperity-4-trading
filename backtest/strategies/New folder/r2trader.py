from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order
import json

####### GENERAL CONSTANTS #######

STATIC_SYMBOL = 'ASH_COATED_OSMIUM'
DYNAMIC_SYMBOL = 'INTARIAN_PEPPER_ROOT'

# Also keep tutorial aliases for compatibility
TUTORIAL_STATIC = 'EMERALDS'
TUTORIAL_DYNAMIC = 'TOMATOES'

POS_LIMITS = {
    STATIC_SYMBOL: 80,
    DYNAMIC_SYMBOL: 80,
    TUTORIAL_STATIC: 20,
    TUTORIAL_DYNAMIC: 20,
}

# Backtester-facing limits export.
LIMITS = POS_LIMITS

# Compatibility shim for older/global prosperity4bt installs.
try:
    import prosperity4bt.runner as _p4_runner

    _p4_runner.LIMITS.setdefault(STATIC_SYMBOL, POS_LIMITS[STATIC_SYMBOL])
    _p4_runner.LIMITS.setdefault(DYNAMIC_SYMBOL, POS_LIMITS[DYNAMIC_SYMBOL])
except Exception:
    pass

####### TUNING PARAMETERS (ASH / EMERALDS) #######
ACO_FAIR_VALUE = 10000.0
ACO_USE_EMA_FAIR_VALUE = False
ACO_FAIR_EMA_ALPHA = 0.03
ACO_BASE_HALF_SPREAD = 2.0
ACO_SPREAD_WIDEN_WEIGHT = 0.0
ACO_INV_SKEW_THRESHOLD_1 = 15
ACO_INV_SKEW_THRESHOLD_2 = 50.0
ACO_INV_SKEW_STEP_1 = 1.5
ACO_INV_SKEW_STEP_2 = 3.0
ACO_PASSIVE_JOIN_TICKS = 0.0625
ACO_AGGRESSIVE_TAKE_EDGE = 0.5
ACO_OBI_WEIGHT = 0.03125
ACO_MICRO_SHIFT_WEIGHT = 0.0
ACO_MOMENTUM_WEIGHT = 0.3
ACO_MID_MOM_ALPHA = 0.025
ACO_VOL_EMA_ALPHA = 0.2
ACO_VOL_PENALTY = 0.0
ACO_SIGNAL_CLIP = 3.0
ACO_SIGNAL_TICK_SCALE = 1.0


####### TUNING PARAMETERS (INTARIAN / TOMATOES) #######
IPR_FAST_EMA_ALPHA = 0.3
IPR_SLOW_EMA_ALPHA = 0.015
IPR_OBI_WEIGHT = 9.0
IPR_OBI_MOM_WEIGHT = 0.0
IPR_MICROPRICE_WEIGHT = 0.8
IPR_TREND_PERSIST_WEIGHT = 0.8
IPR_MIN_TARGET = 16
IPR_TAKE_EDGE = 1
IPR_TREND_AGGRESSION = 1.8
IPR_VOL_ALPHA = 0.08
IPR_VOL_PENALTY = 0.0
IPR_VOL_TAKE_WEIGHT = 0.06
IPR_OBI_CLIP = 1.0
IPR_TREND_CLIP = 50.0
IPR_FLOW_ALPHA = 0.2
IPR_FLOW_WEIGHT = 0.0
IPR_BASE_LONG_TARGET = 80
IPR_DRIFT_TO_TARGET = 20.0
IPR_AGGRESSIVE_EDGE = 3.0
IPR_SUPPORT_BID_FRACTION = 1.0
IPR_OVER_TARGET_TRIM = 20.0
IPR_STARTUP_RAMP_WINDOW = 2000
IPR_STARTUP_AGGR_CAP_REDUCTION = 10.0
IPR_STARTUP_RELOAD_FRACTION = 0.82
IPR_STARTUP_SUPPORT_BID_FRACTION = 0.9

# IPR-v6 structure parameters
IPR_WARMUP_TICKS = 1000
IPR_WARMUP_TAKE_EDGE = 7.0
IPR_NORMAL_TAKE_EDGE = 9.0
IPR_SPIKE_THRESHOLD = 2.0
IPR_SPIKE_QTY = 8
IPR_SELL_MIN_POS = 72


####### STOP LOSS #######
# Trailing stop-loss controls to protect against sudden adverse moves / manipulation-like spikes.
# For long positions: trigger when price drops from recent peak by STOPLOSS_DROP_TICKS.
# For short positions: trigger when price rises from recent trough by STOPLOSS_DROP_TICKS.
STOPLOSS_ENABLE_ACO = False
STOPLOSS_ENABLE_IPR = True
STOPLOSS_ACO_DROP_TICKS = 14.0
STOPLOSS_IPR_DROP_TICKS = 300
STOPLOSS_UNWIND_FRACTION = 0.65
STOPLOSS_COOLDOWN_MS = 1500
STOPLOSS_CROSS_BUFFER_TICKS = 1.0
# While in stop-loss cooldown, shrink long target to this fraction of normal baseline.
STOPLOSS_COOLDOWN_TARGET_FRACTION = 0.15


####### MARKET ACCESS FEE (MAF) #######
# New challenge support:
# - If enabled, your desired MAF bid is published via traderData.
MAF_ENABLE = False
MAF_BID = 75


class ProductTrader:
    def __init__(self, name, state, new_trader_data):
        self.orders: List[Order] = []
        self.name = name
        self.state = state
        self.new_trader_data = new_trader_data

        self.last_trader_data = self._get_last_trader_data()
        self.position_limit = POS_LIMITS.get(self.name, 20)
        self.position_limit = LIMITS.get(self.name, 20)
        self.initial_position = self.state.position.get(self.name, 0)

        self.mkt_buy_orders, self.mkt_sell_orders = self._get_order_depth()
        self.best_bid, self.best_ask = self._get_best_bid_ask()
        self.bid_wall, self.wall_mid, self.ask_wall = self._get_walls()
        self.spread, self.microprice, self.micro_shift = self._get_microstructure_features()

        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self._get_max_allowed_volume()
        self.obi = self._get_orderbook_imbalance()

    def _get_last_trader_data(self):
        try:
            return json.loads(self.state.traderData) if self.state.traderData else {}
        except Exception:
            return {}

    def _get_order_depth(self):
        try:
            order_depth: OrderDepth = self.state.order_depths[self.name]
        except Exception:
            return {}, {}

        try:
            buy_orders = {p: abs(v) for p, v in sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)}
        except Exception:
            buy_orders = {}

        try:
            sell_orders = {p: abs(v) for p, v in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])}
        except Exception:
            sell_orders = {}

        return buy_orders, sell_orders

    def _get_best_bid_ask(self):
        best_bid = max(self.mkt_buy_orders.keys()) if self.mkt_buy_orders else None
        best_ask = min(self.mkt_sell_orders.keys()) if self.mkt_sell_orders else None
        return best_bid, best_ask

    def _get_walls(self):
        bid_wall = min(self.mkt_buy_orders.keys()) if self.mkt_buy_orders else None
        ask_wall = max(self.mkt_sell_orders.keys()) if self.mkt_sell_orders else None
        wall_mid = (bid_wall + ask_wall) / 2 if bid_wall is not None and ask_wall is not None else None
        return bid_wall, wall_mid, ask_wall

    def _get_orderbook_imbalance(self):
        bid_vol = sum(self.mkt_buy_orders.values()) if self.mkt_buy_orders else 0
        ask_vol = sum(self.mkt_sell_orders.values()) if self.mkt_sell_orders else 0
        denom = bid_vol + ask_vol
        if denom == 0:
            return 0.0
        return (bid_vol - ask_vol) / denom

    def _get_microstructure_features(self):
        if self.best_bid is None or self.best_ask is None:
            return 0.0, self.wall_mid, 0.0
        spread = float(self.best_ask - self.best_bid)
        bid_v1 = float(self.mkt_buy_orders.get(self.best_bid, 0))
        ask_v1 = float(self.mkt_sell_orders.get(self.best_ask, 0))
        denom = bid_v1 + ask_v1
        if denom > 0:
            microprice = (self.best_ask * bid_v1 + self.best_bid * ask_v1) / denom
        else:
            microprice = self.wall_mid if self.wall_mid is not None else (self.best_bid + self.best_ask) / 2
        wall = self.wall_mid if self.wall_mid is not None else (self.best_bid + self.best_ask) / 2
        micro_shift = float(microprice - wall)
        return spread, float(microprice), micro_shift

    def _get_max_allowed_volume(self):
        return self.position_limit - self.initial_position, self.position_limit + self.initial_position

    def bid(self, price, volume):
        qty = min(abs(int(volume)), int(self.max_allowed_buy_volume))
        if qty > 0:
            self.orders.append(Order(self.name, int(price), int(qty)))
            self.max_allowed_buy_volume -= qty

    def ask(self, price, volume):
        qty = min(abs(int(volume)), int(self.max_allowed_sell_volume))
        if qty > 0:
            self.orders.append(Order(self.name, int(price), -int(qty)))
            self.max_allowed_sell_volume -= qty

    def _reference_price(self):
        if self.wall_mid is not None:
            return float(self.wall_mid)
        if self.best_bid is not None and self.best_ask is not None:
            return float((self.best_bid + self.best_ask) / 2)
        if self.best_bid is not None:
            return float(self.best_bid)
        if self.best_ask is not None:
            return float(self.best_ask)
        return None

    def apply_trailing_stop_loss(
        self,
        enabled: bool,
        drop_ticks: float,
        unwind_fraction: float,
        cooldown_ms: int,
        cross_buffer_ticks: float,
    ) -> bool:
        """
        Returns True if stop-loss was triggered and unwind orders were placed.
        """
        if not enabled:
            return False

        pos = int(self.initial_position)
        if pos == 0:
            # reset stale state when flat
            self.new_trader_data[f'{self.name}_sl_peak'] = None
            self.new_trader_data[f'{self.name}_sl_trough'] = None
            return False

        ref = self._reference_price()
        if ref is None:
            return False

        cooldown_key = f'{self.name}_sl_cooldown_until'
        peak_key = f'{self.name}_sl_peak'
        trough_key = f'{self.name}_sl_trough'
        now = int(self.state.timestamp)

        cooldown_until = int(self.last_trader_data.get(cooldown_key, -1) or -1)
        in_cooldown = now < cooldown_until

        if pos > 0:
            last_peak = self.last_trader_data.get(peak_key, ref)
            try:
                peak = max(float(last_peak), float(ref))
            except Exception:
                peak = float(ref)
            self.new_trader_data[peak_key] = peak
            self.new_trader_data[trough_key] = None

            drawdown = peak - float(ref)
            if (not in_cooldown) and drawdown >= float(drop_ticks):
                need_sell = max(1, int(abs(pos) * float(unwind_fraction)))
                for bp, bv in self.mkt_buy_orders.items():
                    if need_sell <= 0:
                        break
                    if bp >= ref - float(cross_buffer_ticks):
                        qty = min(int(bv), need_sell, int(self.max_allowed_sell_volume))
                        self.ask(bp, qty)
                        need_sell -= qty

                if need_sell > 0 and self.best_bid is not None and self.max_allowed_sell_volume > 0:
                    self.ask(self.best_bid, min(need_sell, int(self.max_allowed_sell_volume)))

                self.new_trader_data[cooldown_key] = now + int(cooldown_ms)
                # reset trailing anchor after stop trigger
                self.new_trader_data[peak_key] = float(ref)
                return len(self.orders) > 0

        else:  # pos < 0
            last_trough = self.last_trader_data.get(trough_key, ref)
            try:
                trough = min(float(last_trough), float(ref))
            except Exception:
                trough = float(ref)
            self.new_trader_data[trough_key] = trough
            self.new_trader_data[peak_key] = None

            adverse = float(ref) - trough
            if (not in_cooldown) and adverse >= float(drop_ticks):
                need_buy = max(1, int(abs(pos) * float(unwind_fraction)))
                for sp, sv in self.mkt_sell_orders.items():
                    if need_buy <= 0:
                        break
                    if sp <= ref + float(cross_buffer_ticks):
                        qty = min(int(sv), need_buy, int(self.max_allowed_buy_volume))
                        self.bid(sp, qty)
                        need_buy -= qty

                if need_buy > 0 and self.best_ask is not None and self.max_allowed_buy_volume > 0:
                    self.bid(self.best_ask, min(need_buy, int(self.max_allowed_buy_volume)))

                self.new_trader_data[cooldown_key] = now + int(cooldown_ms)
                self.new_trader_data[trough_key] = float(ref)
                return len(self.orders) > 0

        self.new_trader_data[cooldown_key] = cooldown_until
        return False

    def stoploss_in_cooldown(self) -> bool:
        cooldown_key = f'{self.name}_sl_cooldown_until'
        now = int(self.state.timestamp)
        cooldown_until = int(self.last_trader_data.get(cooldown_key, -1) or -1)
        return now < cooldown_until


class OsmiumTrader(ProductTrader):
    """
    OPTIMIZED ASH/EMERALDS STRATEGY:
    - Absolute Fair Value Anchoring (10000)
    - Dynamic Pennying (Spread Capture)
    - Strict Inventory Risk Management
    - Zero mathematical lag (No EWMA/Z-Scores)
    """

    def get_orders(self):
        # 0. Stop-loss risk guard
        if self.apply_trailing_stop_loss(
            enabled=STOPLOSS_ENABLE_ACO,
            drop_ticks=STOPLOSS_ACO_DROP_TICKS,
            unwind_fraction=STOPLOSS_UNWIND_FRACTION,
            cooldown_ms=STOPLOSS_COOLDOWN_MS,
            cross_buffer_ticks=STOPLOSS_CROSS_BUFFER_TICKS,
        ):
            return {self.name: self.orders}

        # 1. Fair value selection (fixed by default for live stability)
        fair_key = f'{self.name}_fair_ema'
        base_fair = float(ACO_FAIR_VALUE)
        if ACO_USE_EMA_FAIR_VALUE:
            last_fair = float(self.last_trader_data.get(fair_key, base_fair))

            if self.wall_mid is not None:
                observed_mid = float(self.wall_mid)
            elif self.best_bid is not None and self.best_ask is not None:
                observed_mid = float((self.best_bid + self.best_ask) / 2)
            else:
                observed_mid = base_fair

            fair_value = last_fair + float(ACO_FAIR_EMA_ALPHA) * (observed_mid - last_fair)
            self.new_trader_data[fair_key] = fair_value
        else:
            fair_value = base_fair

        # 1b. ACO microstructure signal stack (OBI + micro-shift + short momentum)
        if self.wall_mid is not None:
            observed_mid = float(self.wall_mid)
        elif self.best_bid is not None and self.best_ask is not None:
            observed_mid = float((self.best_bid + self.best_ask) / 2)
        else:
            observed_mid = float(fair_value)

        last_mid_key = f'{self.name}_aco_last_mid'
        last_mid = float(self.last_trader_data.get(last_mid_key, observed_mid))
        raw_momentum = observed_mid - last_mid
        self.new_trader_data[last_mid_key] = observed_mid

        mom_key = f'{self.name}_aco_mom_ema'
        last_mom = float(self.last_trader_data.get(mom_key, 0.0))
        momentum_ema = (1.0 - ACO_MID_MOM_ALPHA) * last_mom + ACO_MID_MOM_ALPHA * raw_momentum
        self.new_trader_data[mom_key] = momentum_ema

        vol_key = f'{self.name}_aco_vol_ema'
        last_vol = float(self.last_trader_data.get(vol_key, 0.0))
        vol_ema = (1.0 - ACO_VOL_EMA_ALPHA) * last_vol + ACO_VOL_EMA_ALPHA * abs(raw_momentum)
        self.new_trader_data[vol_key] = vol_ema

        raw_signal = (
            ACO_OBI_WEIGHT * self.obi
            + ACO_MICRO_SHIFT_WEIGHT * self.micro_shift
            + ACO_MOMENTUM_WEIGHT * momentum_ema
        )
        clipped_signal = max(-ACO_SIGNAL_CLIP, min(ACO_SIGNAL_CLIP, raw_signal))
        regime_scale = 1.0 / (1.0 + ACO_VOL_PENALTY * vol_ema)
        signal_ticks = regime_scale * clipped_signal * ACO_SIGNAL_TICK_SCALE
        
        # 2. Inventory Skewing
        # Shift target prices based on how much inventory we hold.
        # If holding a lot of stock (>20), drop targets by 1 to encourage 
        # selling and discourage buying.
        spread_widen = ACO_SPREAD_WIDEN_WEIGHT * max(0.0, self.spread - 1.0)
        half_spread = float(ACO_BASE_HALF_SPREAD) + spread_widen
        bid_target = fair_value - half_spread + signal_ticks
        ask_target = fair_value + half_spread + signal_ticks

        if self.initial_position > ACO_INV_SKEW_THRESHOLD_1:
            bid_target -= float(ACO_INV_SKEW_STEP_1)
            ask_target -= float(ACO_INV_SKEW_STEP_1)
        if self.initial_position > ACO_INV_SKEW_THRESHOLD_2:
            bid_target -= float(ACO_INV_SKEW_STEP_2)
            ask_target -= float(ACO_INV_SKEW_STEP_2)
            
        if self.initial_position < -ACO_INV_SKEW_THRESHOLD_1:
            bid_target += float(ACO_INV_SKEW_STEP_1)
            ask_target += float(ACO_INV_SKEW_STEP_1)
        if self.initial_position < -ACO_INV_SKEW_THRESHOLD_2:
            bid_target += float(ACO_INV_SKEW_STEP_2)
            ask_target += float(ACO_INV_SKEW_STEP_2)

        # 3. Aggressive Liquidity Taking
        # If someone is selling below our fair value, buy it instantly.
        take_edge = float(ACO_AGGRESSIVE_TAKE_EDGE)
        for sp, sv in self.mkt_sell_orders.items():
            if sp <= bid_target + take_edge:
                self.bid(sp, sv)

        # If someone is buying above our fair value, sell it instantly.
        for bp, bv in self.mkt_buy_orders.items():
            if bp >= ask_target - take_edge:
                self.ask(bp, bv)

        # 4. Passive Market Making (Dynamic Pennying)
        # Be the best bid/ask, but never pay more than bid_target
        # and never sell for less than ask_target.

        join_ticks = float(ACO_PASSIVE_JOIN_TICKS)
        best_market_bid = self.best_bid if self.best_bid is not None else int(round(bid_target - 1))
        best_market_ask = self.best_ask if self.best_ask is not None else int(round(ask_target + 1))

        # Try to overcut the best bid by 1 tick, capped by our bid_target
        my_bid_price = int(round(min(bid_target, best_market_bid + join_ticks)))
        
        # Try to undercut the best ask by 1 tick, floored by our ask_target
        my_ask_price = int(round(max(ask_target, best_market_ask - join_ticks)))

        # Place the passive orders with our remaining volume capacity
        if self.max_allowed_buy_volume > 0:
            self.bid(my_bid_price, self.max_allowed_buy_volume)
            
        if self.max_allowed_sell_volume > 0:
            self.ask(my_ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


class PepperRootTrader(ProductTrader):
    """INTARIAN IPR-v6: accumulation -> steady-state independent buy/sell checks each tick."""

    @staticmethod
    def _ipr_fair(mid: float, timestamp: int) -> float:
        base = round((mid - timestamp / 1000.0) / 1000.0) * 1000
        return base + timestamp / 1000.0

    def get_orders(self):
        if self.best_bid is None and self.best_ask is None:
            return {self.name: self.orders}

        reached_key = f'{self.name}_reached_80'
        reached_80 = bool(self.last_trader_data.get(reached_key, False))

        position = int(self.initial_position)
        buy_cap = int(self.max_allowed_buy_volume)
        sell_cap = int(self.max_allowed_sell_volume)

        if position >= self.position_limit:
            reached_80 = True
        self.new_trader_data[reached_key] = reached_80

        # Fair value (from provided IPR-v6 logic)
        if self.best_bid is not None and self.best_ask is not None:
            raw_mid = (self.best_bid + self.best_ask) / 2.0
        elif self.best_bid is not None:
            raw_mid = float(self.best_bid)
        else:
            raw_mid = float(self.best_ask)
        fair = self._ipr_fair(raw_mid, self.state.timestamp)

        # ================================================================
        # Accumulation phase (until first time position reaches 80)
        # ================================================================
        if not reached_80:
            take_edge = IPR_WARMUP_TAKE_EDGE if self.state.timestamp < IPR_WARMUP_TICKS else IPR_NORMAL_TAKE_EDGE

            # Aggressive buys within edge gate
            for ask_px in sorted(self.mkt_sell_orders.keys()):
                if buy_cap <= 0 or ask_px > fair + take_edge:
                    break
                qty = min(int(self.mkt_sell_orders[ask_px]), buy_cap)
                if qty > 0:
                    self.bid(ask_px, qty)
                    buy_cap -= qty

            # Passive bid: best_bid + 1 for price priority (cap below best ask)
            if buy_cap > 0 and self.best_bid is not None:
                bid_px = int(self.best_bid + 1)
                if self.best_ask is not None and bid_px >= self.best_ask:
                    bid_px = int(self.best_ask - 1)
                if bid_px > 0:
                    self.bid(bid_px, buy_cap)

            # Sell overlay during accumulation (does not exit accumulation)
            if position >= IPR_SELL_MIN_POS:
                max_overlay_qty = max(0, position - IPR_SELL_MIN_POS)

                # Spike-sell: bids above fair + threshold
                spike_sold = 0
                for bid_px in sorted(self.mkt_buy_orders.keys(), reverse=True):
                    if sell_cap <= 0:
                        break
                    excess = bid_px - fair
                    if excess < IPR_SPIKE_THRESHOLD:  # intentional strict check from v6
                        break

                    qty = min(
                        int(self.mkt_buy_orders[bid_px]),
                        int(IPR_SPIKE_QTY - spike_sold),
                        int(sell_cap),
                        int(max_overlay_qty),
                    )
                    if qty <= 0:
                        break
                    self.ask(bid_px, qty)
                    spike_sold += qty
                    sell_cap -= qty
                    if spike_sold >= IPR_SPIKE_QTY:
                        break

                # Passive ask every tick, independent of spike-sell
                if sell_cap > 0 and self.best_ask is not None:
                    ask_px = int(self.best_ask - 1)
                    ask_px = max(ask_px, int(fair) + 1)
                    qty = min(int(sell_cap), int(IPR_SPIKE_QTY), int(max_overlay_qty))
                    if qty > 0:
                        self.ask(ask_px, qty)

            return {self.name: self.orders}

        # ================================================================
        # Steady-state phase (after first touch of 80): both sides each tick
        # ================================================================

        # Buy side if below cap
        if buy_cap > 0:
            # Aggressive: take asks strictly below fair
            for ask_px in sorted(self.mkt_sell_orders.keys()):
                if buy_cap <= 0 or ask_px >= fair:
                    break
                qty = min(int(self.mkt_sell_orders[ask_px]), buy_cap)
                if qty > 0:
                    self.bid(ask_px, qty)
                    buy_cap -= qty

            # Passive bid: best_bid+1, capped at fair-1 and below best ask
            if buy_cap > 0 and self.best_bid is not None:
                bid_px = int(self.best_bid + 1)
                bid_px = min(bid_px, int(fair) - 1)
                if self.best_ask is not None and bid_px >= self.best_ask:
                    bid_px = int(self.best_ask - 1)
                if bid_px > 0:
                    self.bid(bid_px, buy_cap)

        # Sell side if position high enough
        if position >= IPR_SELL_MIN_POS:
            max_overlay_qty = max(0, position - IPR_SELL_MIN_POS)

            spike_sold = 0
            for bid_px in sorted(self.mkt_buy_orders.keys(), reverse=True):
                if sell_cap <= 0:
                    break
                excess = bid_px - fair
                if excess < IPR_SPIKE_THRESHOLD:  # intentional strict check from v6
                    break

                qty = min(
                    int(self.mkt_buy_orders[bid_px]),
                    int(IPR_SPIKE_QTY - spike_sold),
                    int(sell_cap),
                    int(max_overlay_qty),
                )
                if qty <= 0:
                    break
                self.ask(bid_px, qty)
                spike_sold += qty
                sell_cap -= qty
                if spike_sold >= IPR_SPIKE_QTY:
                    break

            # Passive ask every tick, independent of spike-sell
            if sell_cap > 0 and self.best_ask is not None:
                ask_px = int(self.best_ask - 1)
                ask_px = max(ask_px, int(fair) + 1)
                qty = min(int(sell_cap), int(IPR_SPIKE_QTY), int(max_overlay_qty))
                if qty > 0:
                    self.ask(ask_px, qty)

        return {self.name: self.orders}


class Trader:
    def run(self, state: TradingState) -> Dict[str, List[Order]]:
        result: Dict[str, List[Order]] = {}
        new_trader_data = {}

        product_map = {
            STATIC_SYMBOL: OsmiumTrader,
            DYNAMIC_SYMBOL: PepperRootTrader,
            TUTORIAL_STATIC: OsmiumTrader,
            TUTORIAL_DYNAMIC: PepperRootTrader,
        }

        for symbol in state.order_depths:
            if symbol in product_map:
                try:
                    trader = product_map[symbol](symbol, state, new_trader_data)
                    result.update(trader.get_orders())
                except Exception:
                    pass

        try:
            if MAF_ENABLE:
                new_trader_data['maf_bid'] = int(MAF_BID)
            final_trader_data = json.dumps(new_trader_data)
        except Exception:
            final_trader_data = ''

        conversions = 0
        return result, conversions, final_trader_data
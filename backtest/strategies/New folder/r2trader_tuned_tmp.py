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
ACO_BASE_HALF_SPREAD = 1.5
ACO_SPREAD_WIDEN_WEIGHT = 0.0
ACO_INV_SKEW_THRESHOLD_1 = 15
ACO_INV_SKEW_THRESHOLD_2 = 50.0
ACO_INV_SKEW_STEP_1 = 1.5
ACO_INV_SKEW_STEP_2 = 1.5
ACO_PASSIVE_JOIN_TICKS = 1.0
ACO_AGGRESSIVE_TAKE_EDGE = 0.5
ACO_OBI_WEIGHT = 0.0
ACO_MICRO_SHIFT_WEIGHT = 0.0
ACO_MOMENTUM_WEIGHT = 0.8
ACO_MID_MOM_ALPHA = 0.1
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
IPR_MIN_TARGET = 0
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
IPR_STARTUP_RAMP_WINDOW = 1000
IPR_STARTUP_AGGR_CAP_REDUCTION = 10.0
IPR_STARTUP_RELOAD_FRACTION = 0.82
IPR_STARTUP_SUPPORT_BID_FRACTION = 0.9


####### STOP LOSS #######
# Trailing stop-loss controls to protect against sudden adverse moves / manipulation-like spikes.
# For long positions: trigger when price drops from recent peak by STOPLOSS_DROP_TICKS.
# For short positions: trigger when price rises from recent trough by STOPLOSS_DROP_TICKS.
STOPLOSS_ENABLE_ACO = False
STOPLOSS_ENABLE_IPR = True
STOPLOSS_ACO_DROP_TICKS = 14.0
STOPLOSS_IPR_DROP_TICKS = 35.0
STOPLOSS_UNWIND_FRACTION = 0.65
STOPLOSS_COOLDOWN_MS = 1500
STOPLOSS_CROSS_BUFFER_TICKS = 1.0
# While in stop-loss cooldown, shrink long target to this fraction of normal baseline.
STOPLOSS_COOLDOWN_TARGET_FRACTION = 0.5


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
    """INTARIAN: always-long trend following + aggressive execution."""

    def get_orders(self):
        if self.wall_mid is None:
            return {self.name: self.orders}

        # 0. Stop-loss risk guard (enabled for INTARIAN by default)
        if self.apply_trailing_stop_loss(
            enabled=STOPLOSS_ENABLE_IPR,
            drop_ticks=STOPLOSS_IPR_DROP_TICKS,
            unwind_fraction=STOPLOSS_UNWIND_FRACTION,
            cooldown_ms=STOPLOSS_COOLDOWN_MS,
            cross_buffer_ticks=STOPLOSS_CROSS_BUFFER_TICKS,
        ):
            return {self.name: self.orders}

        sl_cooldown_active = self.stoploss_in_cooldown()

        fast_key = f'{self.name}_fast_ema'
        slow_key = f'{self.name}_slow_ema'
        last_fast = self.last_trader_data.get(fast_key, self.wall_mid)
        last_slow = self.last_trader_data.get(slow_key, self.wall_mid)

        last_obi_key = f'{self.name}_last_obi'
        last_obi = float(self.last_trader_data.get(last_obi_key, self.obi))

        vol_key = f'{self.name}_vol_ema'
        last_vol = float(self.last_trader_data.get(vol_key, 0.0))
        last_mid_key = f'{self.name}_last_mid'
        last_mid = float(self.last_trader_data.get(last_mid_key, self.wall_mid))
        vol_ema = (1.0 - IPR_VOL_ALPHA) * last_vol + IPR_VOL_ALPHA * abs(self.wall_mid - last_mid)
        self.new_trader_data[vol_key] = vol_ema
        self.new_trader_data[last_mid_key] = self.wall_mid

        fast_ema = last_fast + IPR_FAST_EMA_ALPHA * (self.wall_mid - last_fast)
        slow_ema = last_slow + IPR_SLOW_EMA_ALPHA * (self.wall_mid - last_slow)

        self.new_trader_data[fast_key] = fast_ema
        self.new_trader_data[slow_key] = slow_ema
        self.new_trader_data[last_obi_key] = self.obi

        flow_key = f'{self.name}_obi_flow'
        last_flow = float(self.last_trader_data.get(flow_key, 0.0))
        obi_momentum = self.obi - last_obi
        obi_flow = (1.0 - IPR_FLOW_ALPHA) * last_flow + IPR_FLOW_ALPHA * obi_momentum
        self.new_trader_data[flow_key] = obi_flow

        trend_key = f'{self.name}_last_trend'
        raw_trend = fast_ema - slow_ema
        last_trend = float(self.last_trader_data.get(trend_key, raw_trend))
        trend_persist_shift = (raw_trend - last_trend) * IPR_TREND_PERSIST_WEIGHT
        self.new_trader_data[trend_key] = raw_trend

        clipped_trend = max(-IPR_TREND_CLIP, min(IPR_TREND_CLIP, raw_trend))
        clipped_obi = max(-IPR_OBI_CLIP, min(IPR_OBI_CLIP, self.obi))

        trend_shift = clipped_trend * IPR_TREND_AGGRESSION
        obi_shift = clipped_obi * IPR_OBI_WEIGHT
        obi_momentum_shift = obi_momentum * IPR_OBI_MOM_WEIGHT
        flow_shift = obi_flow * IPR_FLOW_WEIGHT
        micro_shift = self.micro_shift * IPR_MICROPRICE_WEIGHT

        regime_scale = 1.0 / (1.0 + IPR_VOL_PENALTY * vol_ema)
        drift_signal = regime_scale * (
            trend_shift + trend_persist_shift + obi_shift + obi_momentum_shift + flow_shift + micro_shift
        )

        # Always-long target with drift-based scaling.
        long_base_target = max(IPR_MIN_TARGET, min(self.position_limit, IPR_BASE_LONG_TARGET))
        if sl_cooldown_active:
            # Risk-off while cooling down after a stop event to avoid immediate re-loading.
            long_base_target = int(round(long_base_target * STOPLOSS_COOLDOWN_TARGET_FRACTION))

        # Smooth startup to reduce early mark-to-market dip from immediate max-long loading.
        if self.state.timestamp < IPR_STARTUP_RAMP_WINDOW:
            ramp_ratio = self.state.timestamp / max(1, IPR_STARTUP_RAMP_WINDOW)
            effective_base_target = max(IPR_MIN_TARGET, int(round(long_base_target * ramp_ratio)))
        else:
            effective_base_target = long_base_target

        effective_drift = min(0.0, drift_signal) if sl_cooldown_active else drift_signal
        scaled_target = effective_base_target + int(max(0.0, effective_drift) * IPR_DRIFT_TO_TARGET)
        current_target = max(effective_base_target, min(self.position_limit, scaled_target))

        predicted_next = self.wall_mid + max(0.0, drift_signal)
        startup_active = self.state.timestamp < IPR_STARTUP_RAMP_WINDOW
        startup_cap_offset = IPR_STARTUP_AGGR_CAP_REDUCTION if startup_active else 0.0
        aggressive_cap = predicted_next + IPR_AGGRESSIVE_EDGE + IPR_VOL_TAKE_WEIGHT * vol_ema - startup_cap_offset

        # Aggressive ask taking to build/maintain long position.
        buy_need = max(0, current_target - self.initial_position)
        for sp, sv in self.mkt_sell_orders.items():
            if buy_need <= 0:
                break
            if sp <= aggressive_cap:
                qty = min(sv, buy_need, int(self.max_allowed_buy_volume))
                self.bid(sp, qty)
                buy_need -= qty

        # Forced reload: if we're below the baseline long inventory, cross best ask immediately.
        baseline_need = max(0, effective_base_target - self.initial_position)
        if startup_active:
            baseline_need = int(baseline_need * IPR_STARTUP_RELOAD_FRACTION)
        if baseline_need > 0:
            for sp, sv in self.mkt_sell_orders.items():
                if baseline_need <= 0:
                    break
                qty = min(sv, baseline_need, int(self.max_allowed_buy_volume))
                self.bid(sp, qty)
                baseline_need -= qty

        # If still below target, keep leaning long with a support bid (not two-sided MM).
        if buy_need > 0 and self.best_bid is not None and self.max_allowed_buy_volume > 0:
            support_bid = int(self.best_bid + 1)
            support_fraction = IPR_STARTUP_SUPPORT_BID_FRACTION if startup_active else IPR_SUPPORT_BID_FRACTION
            support_qty = min(buy_need, int(self.max_allowed_buy_volume * support_fraction))
            self.bid(support_bid, support_qty)

        # Risk trim only when materially above target; avoid market-making style two-sided quoting.
        trim_target = current_target + IPR_OVER_TARGET_TRIM
        excess = max(0, self.initial_position - trim_target)
        if excess > 0:
            for bp, bv in self.mkt_buy_orders.items():
                if excess <= 0:
                    break
                if bp >= self.wall_mid - IPR_TAKE_EDGE:
                    qty = min(bv, excess, int(self.max_allowed_sell_volume))
                    self.ask(bp, qty)
                    excess -= qty

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
            final_trader_data = json.dumps(new_trader_data)
        except Exception:
            final_trader_data = ''

        conversions = 0
        return result, conversions, final_trader_data
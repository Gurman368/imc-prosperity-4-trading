from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order
import json
import math

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
ACO_FAIR_VALUE = 10000
ACO_SKEW_FACTOR = 6.0
ACO_TAKE_EDGE = 1
ACO_VELOCITY_WEIGHT = 0.1
ACO_OBI_WEIGHT = 0.0
ACO_MICROPRICE_WEIGHT = 0.0
ACO_SPREAD_WEIGHT = 0.05
ACO_ACCEL_WEIGHT = 0.0
ACO_VOL_ALPHA = 0.08
ACO_VOL_WEIGHT = 0.2
ACO_EARLY_WINDOW = 200000
ACO_EARLY_EDGE_BONUS = 0.0
ACO_VOL_SIZE_PENALTY = 0.0
ACO_LAYER_FRACTION = 0.45
ACO_LAYER_TICKS = 1.0
ACO_BID_SIZE_FACTOR = 1.0
ACO_ASK_SIZE_FACTOR = 1.0
ACO_MEAN_ALPHA = 0.04
ACO_VAR_ALPHA = 0.08
ACO_ZSCORE_WEIGHT = 0.8
ACO_ZSCORE_TAKE_THRESHOLD = 0.8
ACO_ZSCORE_CLIP = 3.0
ACO_INV_PRICE_SKEW = 2.0

####### TUNING PARAMETERS (INTARIAN / TOMATOES) #######
IPR_FAST_EMA_ALPHA = 0.3
IPR_SLOW_EMA_ALPHA = 0.015
IPR_OBI_WEIGHT = 9.0
IPR_OBI_MOM_WEIGHT = 0.0
IPR_MICROPRICE_WEIGHT = 0.8
IPR_TREND_PERSIST_WEIGHT = 0.8
IPR_LEAN_MULTIPLIER = 1.6
IPR_TARGET_POSITION = 80
IPR_MIN_TARGET = 0
IPR_TIME_DECAY_WINDOW = 150000
IPR_TAKE_EDGE = 1
IPR_TREND_AGGRESSION = 1.8
IPR_VOL_ALPHA = 0.08
IPR_VOL_PENALTY = 0.0
IPR_VOL_TAKE_WEIGHT = 0.06
IPR_SPREAD_EDGE_WEIGHT = 0.0
IPR_EARLY_WINDOW = 200000
IPR_EARLY_EDGE_BONUS = 0.0
IPR_VOL_SIZE_PENALTY = 0.0
IPR_OBI_CLIP = 1.0
IPR_TREND_CLIP = 50.0
IPR_FLOW_ALPHA = 0.2
IPR_FLOW_WEIGHT = 0.0
IPR_TARGET_TREND_WEIGHT = 0.0
IPR_LAYER_FRACTION = 0.45
IPR_LAYER_TICKS = 1.0
IPR_INVENTORY_RELEASE_FRACTION = 0.05
IPR_ASYM_BID_SCALE = 1.0
IPR_ASYM_ASK_SCALE = 0.8
IPR_ALWAYS_ASK_FRACTION = 0.0
IPR_BASE_LONG_TARGET = 80
IPR_DRIFT_TO_TARGET = 20.0
IPR_AGGRESSIVE_EDGE = 3.0
IPR_SUPPORT_BID_FRACTION = 1.0
IPR_OVER_TARGET_TRIM = 20
IPR_STARTUP_RAMP_WINDOW = 1000
IPR_STARTUP_AGGR_CAP_REDUCTION = 10.0
IPR_STARTUP_RELOAD_FRACTION = 0.9
IPR_STARTUP_SUPPORT_BID_FRACTION = 0.9


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


class OsmiumTrader(ProductTrader):
    """ASH: market making + microstructure alpha + z-score mean reversion."""

    def get_orders(self):
        if self.wall_mid is None:
            return {self.name: self.orders}

        last_key = f'{self.name}_last_mid'
        last_mid = self.last_trader_data.get(last_key, self.wall_mid)
        self.new_trader_data[last_key] = self.wall_mid

        last_velocity_key = f'{self.name}_last_velocity'
        last_velocity = float(self.last_trader_data.get(last_velocity_key, 0.0))

        vol_key = f'{self.name}_vol_ema'
        last_vol = float(self.last_trader_data.get(vol_key, 0.0))
        mean_key = f'{self.name}_ewm_mean'
        var_key = f'{self.name}_ewm_var'
        last_mean = float(self.last_trader_data.get(mean_key, self.wall_mid))
        last_var = float(self.last_trader_data.get(var_key, 1.0))

        velocity = self.wall_mid - last_mid
        acceleration = velocity - last_velocity
        self.new_trader_data[last_velocity_key] = velocity
        vol_ema = (1.0 - ACO_VOL_ALPHA) * last_vol + ACO_VOL_ALPHA * abs(velocity)
        self.new_trader_data[vol_key] = vol_ema

        ewm_mean = (1.0 - ACO_MEAN_ALPHA) * last_mean + ACO_MEAN_ALPHA * self.wall_mid
        dev = self.wall_mid - ewm_mean
        ewm_var = (1.0 - ACO_VAR_ALPHA) * last_var + ACO_VAR_ALPHA * (dev ** 2)
        self.new_trader_data[mean_key] = ewm_mean
        self.new_trader_data[var_key] = ewm_var

        sigma = max(1.0, math.sqrt(max(1e-9, ewm_var)))
        z = (self.wall_mid - ewm_mean) / sigma
        z_clipped = max(-ACO_ZSCORE_CLIP, min(ACO_ZSCORE_CLIP, z))

        inventory_lean = -(self.initial_position / max(1, self.position_limit)) * ACO_SKEW_FACTOR
        fair_value = (
            ACO_FAIR_VALUE
            + inventory_lean
            - (velocity * ACO_VELOCITY_WEIGHT)
            - (acceleration * ACO_ACCEL_WEIGHT)
            + self.obi * ACO_OBI_WEIGHT
            + self.micro_shift * ACO_MICROPRICE_WEIGHT
        )

        take_edge = ACO_TAKE_EDGE + ACO_SPREAD_WEIGHT * self.spread + ACO_VOL_WEIGHT * vol_ema
        if self.state.timestamp < ACO_EARLY_WINDOW:
            take_edge += ACO_EARLY_EDGE_BONUS

        # Mean-reversion take logic only when deviation is stretched.
        buy_take_edge = take_edge
        sell_take_edge = take_edge
        if z <= -ACO_ZSCORE_TAKE_THRESHOLD:
            buy_take_edge = max(0.0, take_edge - 0.5)
        if z >= ACO_ZSCORE_TAKE_THRESHOLD:
            sell_take_edge = max(0.0, take_edge - 0.5)

        for sp, sv in self.mkt_sell_orders.items():
            if sp <= fair_value - buy_take_edge and z <= -ACO_ZSCORE_TAKE_THRESHOLD:
                self.bid(sp, sv)
            elif sp <= fair_value and self.initial_position < 0:
                self.bid(sp, min(sv, abs(self.initial_position)))

        for bp, bv in self.mkt_buy_orders.items():
            if bp >= fair_value + sell_take_edge and z >= ACO_ZSCORE_TAKE_THRESHOLD:
                self.ask(bp, bv)
            elif bp >= fair_value and self.initial_position > 0:
                self.ask(bp, min(bv, self.initial_position))

    # Core market-making around stable fair with inventory price skew.
        half_spread = max(1, int(round(max(1.0, self.spread) / 2)))
        inv_price_skew = (self.initial_position / max(1, self.position_limit)) * ACO_INV_PRICE_SKEW
        bid_price = int(round(fair_value - half_spread - max(0.0, inv_price_skew)))
        ask_price = int(round(fair_value + half_spread - min(0.0, inv_price_skew)))

        # restore best.py quote improvement logic
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

        size_scale = 1.0 / (1.0 + ACO_VOL_SIZE_PENALTY * vol_ema)
        bid_qty = int(self.max_allowed_buy_volume * ACO_BID_SIZE_FACTOR * size_scale)
        ask_qty = int(self.max_allowed_sell_volume * ACO_ASK_SIZE_FACTOR * size_scale)

        # Layer passive quotes to improve fill quality in choppy tape
        bid_l1 = int(bid_qty * (1.0 - ACO_LAYER_FRACTION))
        bid_l2 = bid_qty - bid_l1
        ask_l1 = int(ask_qty * (1.0 - ACO_LAYER_FRACTION))
        ask_l2 = ask_qty - ask_l1

        self.bid(bid_price, bid_l1)
        self.ask(ask_price, ask_l1)

        layer_ticks = int(ACO_LAYER_TICKS)
        if self.spread > 1 and layer_ticks > 0:
            self.bid(bid_price - layer_ticks, bid_l2)
            self.ask(ask_price + layer_ticks, ask_l2)
        else:
            self.bid(bid_price, bid_l2)
            self.ask(ask_price, ask_l2)
        return {self.name: self.orders}


class PepperRootTrader(ProductTrader):
    """INTARIAN: always-long trend following + aggressive execution."""

    def get_orders(self):
        if self.wall_mid is None:
            return {self.name: self.orders}

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
        # Smooth startup to reduce early mark-to-market dip from immediate max-long loading.
        if self.state.timestamp < IPR_STARTUP_RAMP_WINDOW:
            ramp_ratio = self.state.timestamp / max(1, IPR_STARTUP_RAMP_WINDOW)
            effective_base_target = max(IPR_MIN_TARGET, int(round(long_base_target * ramp_ratio)))
        else:
            effective_base_target = long_base_target

        scaled_target = effective_base_target + int(max(0.0, drift_signal) * IPR_DRIFT_TO_TARGET)
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

from datamodel import OrderDepth, TradingState, Order
import json
import math
from statistics import NormalDist, median

_N = NormalDist()

# =========================
# SYMBOLS
# =========================
STATIC_SYMBOL            = "HYDROGEL_PACK"
DYNAMIC_SYMBOL           = "VELVETFRUIT_EXTRACT"
OPTION_UNDERLYING_SYMBOL = "VELVETFRUIT_EXTRACT"

OPTION_SYMBOLS = [
    "VEV_4000", "VEV_4500", "VEV_5000", "VEV_5100",
    "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500",
    "VEV_6000", "VEV_6500"
]

# ❌ Disable bad strikes
DISABLED_OPTIONS = {}

# =========================
# COUNTERPARTY INTELLIGENCE  (from doc7)
# =========================
SMART_TRADERS   = {"Mark 14", "Mark 01"}   # informed → fade them
DUMB_TRADERS    = {"Mark 38", "Mark 55"}   # uninformed → trade with them
NEUTRAL_TRADERS = {"Mark 22", "Mark 49"}

def get_recent_trades(state, symbol):
    return state.market_trades.get(symbol, [])

# =========================
# LIMITS
# =========================
POS_LIMITS = {
    STATIC_SYMBOL: 200,
    DYNAMIC_SYMBOL: 200,
    OPTION_UNDERLYING_SYMBOL: 300,
    **{os: 300 for os in OPTION_SYMBOLS},
}

try:
    import prosperity4bt.runner as _p4_runner
    for product, limit in POS_LIMITS.items():
        _p4_runner.LIMITS[product] = limit
except Exception:
    pass

LIMITS = POS_LIMITS

# =========================
# MARKET HELPERS  (from doc6)
# =========================
def sorted_bids(buy_orders):
    return sorted(buy_orders.items(), reverse=True)

def sorted_asks(sell_orders):
    return sorted(sell_orders.items())

def vwap_mid(buy_orders, sell_orders):
    """Volume-weighted average of both sides (doc6 logic)."""
    bid_vwap = None
    ask_vwap = None
    if buy_orders:
        total = sum(buy_orders.values())
        if total > 0:
            bid_vwap = sum(p * v for p, v in buy_orders.items()) / total
    if sell_orders:
        total = sum(-v for v in sell_orders.values())
        if total > 0:
            ask_vwap = sum(p * (-v) for p, v in sell_orders.items()) / total
    if bid_vwap is not None and ask_vwap is not None:
        return (bid_vwap + ask_vwap) / 2
    return bid_vwap if bid_vwap is not None else ask_vwap

def popular_mid(buy_orders, sell_orders):
    """Most-volume level on each side (doc6 logic)."""
    bid = None
    ask = None
    if buy_orders:
        bid = max(buy_orders.items(), key=lambda x: (x[1], x[0]))[0]
    if sell_orders:
        ask = min(sell_orders.items(), key=lambda x: (x[1], x[0]))[0]
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2

def top_level_imbalance(buy_orders, sell_orders):
    """Signed imbalance at best bid/ask (doc6 logic)."""
    if not buy_orders or not sell_orders:
        return 0.0
    best_b = max(buy_orders)
    best_a = min(sell_orders)
    bv = buy_orders.get(best_b, 0)
    av = -sell_orders.get(best_a, 0)
    denom = bv + av
    if denom <= 0:
        return 0.0
    return (bv - av) / denom

def book_imbalance(buy_orders, sell_orders, levels=3):
    bv = sum(v for _, v in sorted_bids(buy_orders)[:levels])
    av = sum(-v for _, v in sorted_asks(sell_orders)[:levels])
    denom = bv + av
    if denom <= 0:
        return 0.0
    return (bv - av) / denom

def observed_fair(buy_orders, sell_orders,
                  anchor, anchor_weight,
                  popular_weight=0.65, imbalance_weight=0.35):
    """
    Blend anchor + popular_mid + VWAP + imbalance  (doc6 StationaryDeltaOne logic).
    anchor_weight  : how strongly we pin to a known anchor
    popular_weight : weight of popular_mid vs VWAP inside market_fair
    imbalance_weight: how much top+book imbalance shifts fair
    """
    if not buy_orders or not sell_orders:
        return anchor

    best_b = max(buy_orders)
    best_a = min(sell_orders)
    mid    = (best_b + best_a) / 2
    pop    = popular_mid(buy_orders, sell_orders) or mid
    vwap   = vwap_mid(buy_orders, sell_orders)    or mid
    spread = best_a - best_b or 1.0

    market_fair = popular_weight * pop + (1.0 - popular_weight) * vwap
    imbalance   = 0.6 * top_level_imbalance(buy_orders, sell_orders) \
                + 0.4 * book_imbalance(buy_orders, sell_orders)

    anchored = anchor_weight * anchor + (1.0 - anchor_weight) * market_fair
    return anchored + imbalance_weight * spread * imbalance

# =========================
# BASE CLASS (UNCHANGED)
# =========================
class ProductTrader:

    def __init__(self, name, state, new_trader_data):

        self.orders = []
        self.name = name
        self.state = state
        self.new_trader_data = new_trader_data

        try:
            self.last_traderData = json.loads(state.traderData) if state.traderData else {}
        except:
            self.last_traderData = {}

        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0)

        depth = self.state.order_depths.get(self.name)
        if depth:
            self.mkt_buy_orders  = depth.buy_orders  or {}
            self.mkt_sell_orders = depth.sell_orders or {}
        else:
            self.mkt_buy_orders, self.mkt_sell_orders = {}, {}

        self.best_bid = max(self.mkt_buy_orders)  if self.mkt_buy_orders  else None
        self.best_ask = min(self.mkt_sell_orders) if self.mkt_sell_orders else None

        self.mid = None
        if self.best_bid and self.best_ask:
            self.mid = (self.best_bid + self.best_ask) / 2

    def buy(self, price, volume):
        self.orders.append(Order(self.name, int(price), int(volume)))

    def sell(self, price, volume):
        self.orders.append(Order(self.name, int(price), -int(volume)))


# =========================
# HYDRO
# Improvements applied:
#   • observed_fair() blends anchor + popular_mid + VWAP + imbalance  (doc6)
#   • Informed-trader signal: fade SMART buys, tighten on DUMB sells   (doc6/7)
#   • Symmetric stop-loss (long + short)                               (audit fix)
#   • Passive quoting uses skewed center (inventory-aware)             (doc6)
# =========================
class HydroTrader(ProductTrader):

    EMA_ALPHA      = 0.04
    MAD_ALPHA      = 0.02
    K              = 3
    BASE_THRESHOLD = 20

    STOP_LOSS_DEV  = 30
    COOLDOWN_PERIOD = 50

    # doc6 StationaryDeltaOne params for Hydro
    ANCHOR         = 10000.0   # long-run anchor from doc6
    ANCHOR_WEIGHT  = 0.0       # fully market-driven (doc6 uses 0.0 for HYDRO)
    POPULAR_WEIGHT = 0.70
    IMBALANCE_WEIGHT = 0.45
    SKEW_K         = 18.0      # inventory skew (doc6)

    def get_orders(self):

        if self.mid is None:
            return {self.name: self.orders}

        mid = self.mid
        pos = self.initial_position
        limit = self.position_limit

        max_sell = limit + pos
        max_buy  = limit - pos

        # ── Cooldown ──────────────────────────────────────────────────
        cooldown = self.last_traderData.get("hp_cooldown", 0)
        cooldown = max(0, cooldown - 1)

        # ── Observed fair (doc6 blend) ────────────────────────────────
        ema_prev = self.last_traderData.get("hp_ema", mid)
        raw_fair = observed_fair(
            self.mkt_buy_orders, self.mkt_sell_orders,
            self.ANCHOR, self.ANCHOR_WEIGHT,
            self.POPULAR_WEIGHT, self.IMBALANCE_WEIGHT
        )
        ema = ema_prev + self.EMA_ALPHA * (raw_fair - ema_prev)
        dev = mid - ema

        # ── MAD adaptive threshold ────────────────────────────────────
        stats = self.last_traderData.get("hp_stats", {"mean": 0, "mad": 1})
        mean = stats["mean"] + self.MAD_ALPHA * (dev - stats["mean"])
        mad  = stats["mad"]  + self.MAD_ALPHA * (abs(dev - mean) - stats["mad"])
        threshold = max(self.BASE_THRESHOLD, self.K * mad)

        # ── Flow bias from counterparty intelligence (doc7) ───────────
        # DUMB sellers → market is cheap → lower threshold to sell
        # SMART buyers → informed up-move → widen threshold (don't fight)
        bias = 0
        for t in get_recent_trades(self.state, self.name):
            if t.seller in DUMB_TRADERS:
                bias += 2     # dumb selling → we should also sell → easier threshold
            if t.buyer  in DUMB_TRADERS:
                bias -= 2
            if t.buyer  in SMART_TRADERS:
                bias -= 3     # smart buying → don't short into them
            if t.seller in SMART_TRADERS:
                bias += 3
        threshold = max(5, threshold - bias * 2)

        # ── Save state ────────────────────────────────────────────────
        self.new_trader_data["hp_ema"]   = ema
        self.new_trader_data["hp_stats"] = {"mean": mean, "mad": mad}

        # ── 1. Stop-loss: BOTH directions (audit fix) ─────────────────
        if pos < 0 and dev > self.STOP_LOSS_DEV:
            cover = abs(pos)
            for ask_p in sorted(self.mkt_sell_orders.keys()):
                vol = min(abs(self.mkt_sell_orders[ask_p]), cover)
                if vol > 0:
                    self.buy(ask_p, vol)
                    cover -= vol
                if cover <= 0:
                    break
            cooldown = self.COOLDOWN_PERIOD

        elif pos > 0 and dev < -self.STOP_LOSS_DEV:
            cover = abs(pos)
            for bid_p in sorted(self.mkt_buy_orders.keys(), reverse=True):
                vol = min(abs(self.mkt_buy_orders[bid_p]), cover)
                if vol > 0:
                    self.sell(bid_p, vol)
                    cover -= vol
                if cover <= 0:
                    break
            cooldown = self.COOLDOWN_PERIOD

        # ── 2. Aggressive entry ───────────────────────────────────────
        elif cooldown == 0:

            if dev > threshold and max_sell > 0:
                for bid_p in sorted(self.mkt_buy_orders.keys(), reverse=True):
                    vol = min(abs(self.mkt_buy_orders[bid_p]), max_sell)
                    if vol > 0:
                        self.sell(bid_p, vol)
                        max_sell -= vol
                    if max_sell <= 0:
                        break

            elif dev < -threshold and max_buy > 0:     # ← aggressive long (audit fix)
                for ask_p in sorted(self.mkt_sell_orders.keys()):
                    vol = min(abs(self.mkt_sell_orders[ask_p]), max_buy)
                    if vol > 0:
                        self.buy(ask_p, vol)
                        max_buy -= vol
                    if max_buy <= 0:
                        break

        # ── 3. Passive market-making with inventory skew (doc6) ───────
        if cooldown == 0 and self.best_bid and self.best_ask:
            # inventory-skewed center (doc6 quote_prices logic)
            center = ema - self.SKEW_K * pos / limit

            if max_sell > 0:
                ask = max(math.ceil(center + 1), self.best_ask - 1)
                if ask > self.best_bid:
                    self.sell(ask, min(15, max_sell))

            if max_buy > 0:
                bid = min(math.floor(center - 1), self.best_bid + 1)
                if bid < self.best_ask:
                    self.buy(bid, min(15, max_buy))

        self.new_trader_data["hp_cooldown"] = cooldown
        return {self.name: self.orders}


# =========================
# FRUIT
# Improvements applied:
#   • observed_fair() replaces plain mid            (doc6)
#   • Inventory-skewed fair price for quotes        (doc7)
#   • Flow bias from counterparty intelligence      (doc7)
#   • Active MR exit layer                          (doc7)
#   • Symmetric stop-loss + cooldown                (existing + audit)
# =========================
class FruitTrader(ProductTrader):

    EMA_ALPHA    = 0.04
    MAD_ALPHA    = 0.03
    K            = 3
    BASE_THRESHOLD = 13

    # doc6 fair-value blend params for VEF
    ANCHOR         = 5250.0
    ANCHOR_WEIGHT  = 0.15
    POPULAR_WEIGHT = 0.65
    IMBALANCE_WEIGHT = 0.35
    SKEW_K         = 10.0      # inventory skew (doc6)

    STOP_LOSS_DEV  = 30
    COOLDOWN_PERIOD = 40

    def get_orders(self):

        if self.mid is None:
            return {self.name: self.orders}

        mid   = self.mid
        pos   = self.initial_position
        limit = self.position_limit

        max_sell = limit + pos
        max_buy  = limit - pos

        # ── Cooldown ──────────────────────────────────────────────────
        cooldown = self.last_traderData.get("fruit_cooldown", 0)
        cooldown = max(0, cooldown - 1)

        # ── Observed fair (doc6 blend) ────────────────────────────────
        ema_prev = self.last_traderData.get("fruit_ema", mid)
        raw_fair = observed_fair(
            self.mkt_buy_orders, self.mkt_sell_orders,
            self.ANCHOR, self.ANCHOR_WEIGHT,
            self.POPULAR_WEIGHT, self.IMBALANCE_WEIGHT
        )
        ema = ema_prev + self.EMA_ALPHA * (raw_fair - ema_prev)
        dev = mid - ema

        # ── MAD adaptive threshold ────────────────────────────────────
        stats = self.last_traderData.get("fruit_stats", {"mean": 0, "mad": 1})
        mean  = stats["mean"] + self.MAD_ALPHA * (dev - stats["mean"])
        mad   = stats["mad"]  + self.MAD_ALPHA * (abs(dev - mean) - stats["mad"])
        threshold = max(self.BASE_THRESHOLD, self.K * mad)

        # ── Flow bias (doc7) ──────────────────────────────────────────
        signal = 0
        for t in get_recent_trades(self.state, self.name):
            if t.seller in DUMB_TRADERS:
                signal += 1
            if t.buyer  in DUMB_TRADERS:
                signal -= 1
            if t.buyer  in SMART_TRADERS:
                signal -= 2
            if t.seller in SMART_TRADERS:
                signal += 2
        signal = max(-3, min(3, signal))

        # ── Save state ────────────────────────────────────────────────
        self.new_trader_data["fruit_ema"]   = ema
        self.new_trader_data["fruit_stats"] = {"mean": mean, "mad": mad}

        # ── 1. Stop-loss: both sides ──────────────────────────────────
        if pos < 0 and dev > self.STOP_LOSS_DEV:
            cover = abs(pos)
            for ask_p in sorted(self.mkt_sell_orders.keys()):
                vol = min(abs(self.mkt_sell_orders[ask_p]), cover)
                if vol > 0:
                    self.buy(ask_p, vol)
                    cover -= vol
                if cover <= 0:
                    break
            cooldown = self.COOLDOWN_PERIOD

        elif pos > 0 and dev < -self.STOP_LOSS_DEV:
            cover = abs(pos)
            for bid_p in sorted(self.mkt_buy_orders.keys(), reverse=True):
                vol = min(abs(self.mkt_buy_orders[bid_p]), cover)
                if vol > 0:
                    self.sell(bid_p, vol)
                    cover -= vol
                if cover <= 0:
                    break
            cooldown = self.COOLDOWN_PERIOD

        # ── 2. Aggressive mean-reversion (blocked in cooldown) ────────
        elif cooldown == 0:

            if dev > threshold and max_sell > 0:
                for bid_p in sorted(self.mkt_buy_orders.keys(), reverse=True):
                    vol = min(abs(self.mkt_buy_orders[bid_p]), max_sell)
                    if vol > 0:
                        self.sell(bid_p, vol)
                        max_sell -= vol
                    if max_sell <= 0:
                        break

            elif dev < -threshold and max_buy > 0:
                for ask_p in sorted(self.mkt_sell_orders.keys()):
                    vol = min(abs(self.mkt_sell_orders[ask_p]), max_buy)
                    if vol > 0:
                        self.buy(ask_p, vol)
                        max_buy -= vol
                    if max_buy <= 0:
                        break

        # ── 3. Passive market-making with inventory + signal skew (doc6/7) ──
        if cooldown == 0 and self.best_bid and self.best_ask:
            # Inventory-skewed center (doc7) + flow signal nudge
            fair_price = ema - self.SKEW_K * pos / limit + signal

            if max_sell > 0:
                ask = max(math.ceil(fair_price + 1), self.best_ask - 1)
                if ask > self.best_bid:
                    self.sell(ask, min(10, max_sell))

            if max_buy > 0:
                bid = min(math.floor(fair_price - 1), self.best_bid + 1)
                if bid < self.best_ask:
                    self.buy(bid, min(10, max_buy))

        # ── 4. Active MR exit layer (doc7) ────────────────────────────
        # If we're long and price is above fair → unwind
        # If we're short and price is below fair → unwind
        if pos > 0 and mid > ema and self.best_bid:
            self.sell(self.best_bid, min(pos, 20))
        elif pos < 0 and mid < ema and self.best_ask:
            self.buy(self.best_ask, min(-pos, 20))

        self.new_trader_data["fruit_cooldown"] = cooldown
        return {self.name: self.orders}


# =========================
# OPTIONS
# Improvements applied:
#   • Adaptive EMA anchor (existing, kept)
#   • Implied vol calibration from smile fit         (doc6 VelvetfruitVoucherStrategy)
#   • Dynamic threshold EMA (noisy market → wider)  (doc6)
#   • Bot signal detection for VEV_4000/4500         (doc6 _update_bot_signal)
#   • Execution gate uses int(anchor)                (audit fix)
#   • EMA_ALPHA bumped to 0.02                       (audit fix)
#   • K bumped to 0.3                                (audit fix)
# =========================
class OptionTrader:

    # Initial priors (warm-start only; EMA adapts after first tick)
    ANCHORS = {
        "VEV_4000": 1250,
        "VEV_4500": 747,
        "VEV_5000": 255,
        "VEV_5100": 167,
        "VEV_5200": 96,
        "VEV_5300": 47,
        "VEV_5400": 16,
        "VEV_5500": 7,
        "VEV_6000": 1,
        "VEV_6500": 1,
    }

    DEV_FULL_MAP = {
        "VEV_4000": 30,
        "VEV_4500": 30,
        "VEV_5000": 25,
        "VEV_5100": 20,
        "VEV_5200": 10,
        "VEV_5300": 10,
        "VEV_5400": 5,
        "VEV_5500": 1,
        "VEV_6000": 1,
        "VEV_6500": 1,
    }

    # Calibration strikes for smile fitting (doc6)
    SMILE_CALIBRATION = ["VEV_5000","VEV_5100","VEV_5200","VEV_5300","VEV_5400","VEV_5500"]
    DEFAULT_TOTAL_VOL = 0.031
    SMILE_IV_MIN = 0.005
    SMILE_IV_MAX = 0.50

    EMA_ALPHA   = 0.02    # fixed from 0.00005 (audit)
    K           = 0.30    # fixed from 0.001   (audit)
    LIMIT       = 300
    MAX_STEP    = 25

    # Dynamic threshold EMA (doc6 THRESHOLD_EMA_ALPHA)
    THRESH_EMA_ALPHA = 0.04
    THRESH_MULT      = 1.15
    THRESH_CAP       = 5.0

    def __init__(self, state, new_trader_data):
        self.options    = [ProductTrader(s, state, new_trader_data) for s in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, new_trader_data)
        self.state = state
        self.new_trader_data = new_trader_data
        try:
            self.last_traderData = json.loads(state.traderData) if state.traderData else {}
        except:
            self.last_traderData = {}

    # ── Black-Scholes (total-vol form, doc6) ──────────────────────────
    def bs_call_total_vol(self, S, K, total_vol):
        intrinsic = max(S - K, 0.0)
        if total_vol <= 0.0:
            return intrinsic
        S = max(float(S), 1e-9)
        K = max(float(K), 1e-9)
        d1 = (math.log(S / K) + 0.5 * total_vol * total_vol) / total_vol
        d2 = d1 - total_vol
        return S * _N.cdf(d1) - K * _N.cdf(d2)

    # ── Implied total-vol solver (doc6) ───────────────────────────────
    def implied_total_vol(self, price, S, K):
        intrinsic = max(S - K, 0.0)
        if price <= intrinsic + 1e-9:
            return 0.0
        lo, hi = 1e-6, 2.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if self.bs_call_total_vol(S, K, mid) < price:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    # ── Smile polynomial fit (doc6) ───────────────────────────────────
    def fit_smile_poly(self, strikes, total_vols, spot):
        if len(strikes) < 3:
            return []
        ms = [math.log(k / max(spot, 1e-9)) for k in strikes]
        n = len(ms)
        mat = [[m*m, m, 1.0] for m in ms]
        ata = [[sum(mat[i][r]*mat[i][c] for i in range(n)) for c in range(3)] for r in range(3)]
        atb = [sum(mat[i][r]*total_vols[i] for i in range(n)) for r in range(3)]
        aug = [ata[r]+[atb[r]] for r in range(3)]
        for col in range(3):
            pivot = max(range(col,3), key=lambda r: abs(aug[r][col]))
            aug[col], aug[pivot] = aug[pivot], aug[col]
            if abs(aug[col][col]) < 1e-12:
                return []
            for row in range(3):
                if row == col:
                    continue
                f = aug[row][col] / aug[col][col]
                for c in range(4):
                    aug[row][c] -= f * aug[col][c]
        return [aug[r][3]/aug[r][r] for r in range(3)]

    # ── Smile fair price for a given strike (doc6) ───────────────────
    def smile_fair(self, spot, strike, coeffs):
        m = math.log(max(strike, 1e-9) / max(spot, 1e-9))
        total_vol = coeffs[0]*m*m + coeffs[1]*m + coeffs[2]
        total_vol = min(max(total_vol, self.SMILE_IV_MIN), self.SMILE_IV_MAX)
        return self.bs_call_total_vol(spot, strike, total_vol)

    # ── Calibrate smile from live option mids (doc6) ──────────────────
    def calibrate_smile(self, spot):
        implied = []
        for sym in self.SMILE_CALIBRATION:
            depth = self.state.order_depths.get(sym)
            if depth is None:
                continue
            b = max(depth.buy_orders) if depth.buy_orders else None
            a = min(depth.sell_orders) if depth.sell_orders else None
            if b is None or a is None:
                continue
            option_mid = (b + a) / 2
            K = int(sym.split("_")[1])
            tv = self.implied_total_vol(option_mid, spot, K)
            if self.SMILE_IV_MIN <= tv <= self.SMILE_IV_MAX:
                implied.append((K, tv))
        if len(implied) < 3:
            return None
        strikes = [x[0] for x in implied]
        vols    = [x[1] for x in implied]
        return self.fit_smile_poly(strikes, vols, spot)

    # ── Dynamic threshold: widen when market is noisy (doc6) ──────────
    def dynamic_threshold(self, base_edge, abs_dev_ema):
        if abs_dev_ema <= 0.0:
            return base_edge
        return min(max(base_edge, self.THRESH_MULT * abs_dev_ema), self.THRESH_CAP)

    # ── Bot signal for deep-ITM strikes (doc6 _update_bot_signal) ─────
    def bot_signal(self, symbol, state, last_ts):
        score = 0
        newest_ts = last_ts
        for trade in get_recent_trades(state, symbol):
            if trade.timestamp <= last_ts:
                continue
            contrib = 0
            if getattr(trade, "buyer",  None) == "Mark 14":
                contrib += trade.quantity
            if getattr(trade, "seller", None) == "Mark 14":
                contrib -= trade.quantity
            if getattr(trade, "buyer",  None) == "Mark 38":
                contrib -= trade.quantity
            if getattr(trade, "seller", None) == "Mark 38":
                contrib += trade.quantity
            if contrib:
                score += contrib
                newest_ts = max(newest_ts, trade.timestamp)
        direction = 1 if score > 0 else (-1 if score < 0 else 0)
        return direction, newest_ts

    def get_orders(self):

        if self.underlying.mid is None:
            return {}

        S = self.underlying.mid

        # ── Calibrate smile once per tick ─────────────────────────────
        smile_coeffs = self.calibrate_smile(S)

        result = {}

        for opt in self.options:

            if opt.name in DISABLED_OPTIONS:
                continue
            if opt.mid is None or opt.best_bid is None or opt.best_ask is None:
                continue

            name  = opt.name
            mid   = opt.mid
            pos   = opt.initial_position
            K_val = float(name.split("_")[1])

            # =========================================================
            # DEEP ITM: VEV_4000, VEV_4500
            # Use smile fair if available, else BS; + bot signal gate
            # =========================================================
            if name in ["VEV_4000", "VEV_4500"]:

                # fair price
                if smile_coeffs:
                    theo = self.smile_fair(S, K_val, smile_coeffs)
                else:
                    # fallback: use adaptive anchor as fair
                    theo = self.last_traderData.get(
                        f"opt_anchor_{name}", self.ANCHORS.get(name, mid)
                    )

                edge = mid - theo

                # bot signal gate (doc6): only trade against the bot's direction
                bot_ts_key = f"bot_ts_{name}"
                last_bot_ts = self.last_traderData.get(bot_ts_key, -1)
                bot_dir, new_bot_ts = self.bot_signal(name, self.state, last_bot_ts)
                self.new_trader_data[bot_ts_key] = new_bot_ts

                if edge > 3 and bot_dir <= 0:   # don't sell into smart buying
                    opt.sell(opt.best_bid, 5)
                elif edge < -3 and bot_dir >= 0:
                    opt.buy(opt.best_ask, 5)

                result[name] = opt.orders
                continue

            # =========================================================
            # ALL OTHER STRIKES: adaptive anchor + smile-adjusted fair
            # =========================================================

            # ── Adaptive anchor (EMA, warm-started from priors) ───────
            anchor_prev = self.last_traderData.get(
                f"opt_anchor_{name}", self.ANCHORS.get(name, mid)
            )
            anchor = anchor_prev + self.EMA_ALPHA * (mid - anchor_prev)
            self.new_trader_data[f"opt_anchor_{name}"] = anchor

            # ── Smile-blended fair (doc6 iv_weight logic) ─────────────
            iv_weight = 0.3 if name in ["VEV_5200","VEV_5300","VEV_5500"] else 0.0
            if smile_coeffs and iv_weight > 0:
                smile_price = self.smile_fair(S, K_val, smile_coeffs)
                fair = (1.0 - iv_weight) * anchor + iv_weight * smile_price
            else:
                fair = anchor

            dev      = mid - fair
            dev_full = self.DEV_FULL_MAP.get(name, 40)

            # ── Dynamic threshold: widen when mkt noisy (doc6) ────────
            abs_dev_ema_key = f"abs_dev_ema_{name}"
            abs_dev_ema = self.last_traderData.get(abs_dev_ema_key, 0.0)
            abs_dev_ema = self.THRESH_EMA_ALPHA * abs(dev) + (1 - self.THRESH_EMA_ALPHA) * abs_dev_ema
            self.new_trader_data[abs_dev_ema_key] = abs_dev_ema

            base_edge = self.K * dev_full
            threshold = self.dynamic_threshold(base_edge, abs_dev_ema)

            # ── Position target ───────────────────────────────────────
            if abs(dev) <= threshold:
                target = 0
            else:
                effective_dev = abs(dev) - threshold
                scaled = int(self.LIMIT * effective_dev / dev_full)
                scaled = min(self.LIMIT, scaled)
                target = -scaled if dev > 0 else scaled

            delta = target - pos
            delta = max(-self.MAX_STEP, min(self.MAX_STEP, delta))

            # ── Execution: good price only (int anchor fix) ───────────
            anchor_int = int(anchor)

            if delta > 0:
                for ask_p in sorted(opt.mkt_sell_orders.keys()):
                    if ask_p >= anchor_int:
                        break
                    vol = min(abs(opt.mkt_sell_orders[ask_p]), delta)
                    if vol > 0:
                        opt.buy(ask_p, vol)
                        delta -= vol
                    if delta <= 0:
                        break

            elif delta < 0:
                for bid_p in sorted(opt.mkt_buy_orders.keys(), reverse=True):
                    if bid_p <= anchor_int:
                        break
                    vol = min(abs(opt.mkt_buy_orders[bid_p]), -delta)
                    if vol > 0:
                        opt.sell(bid_p, vol)
                        delta += vol
                    if delta >= 0:
                        break

            result[name] = opt.orders

        return result


# =========================
# MAIN
# =========================
class Trader:

    def run(self, state: TradingState):

        new_trader_data = {}
        result = {}

        if STATIC_SYMBOL in state.order_depths:
            result.update(HydroTrader(STATIC_SYMBOL, state, new_trader_data).get_orders())

        if DYNAMIC_SYMBOL in state.order_depths:
            result.update(FruitTrader(DYNAMIC_SYMBOL, state, new_trader_data).get_orders())

        result.update(OptionTrader(state, new_trader_data).get_orders())

        return result, 0, json.dumps(new_trader_data)
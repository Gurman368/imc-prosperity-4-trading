from datamodel import OrderDepth, TradingState, Order
import math
from statistics import NormalDist

N = NormalDist()

# =========================
# PRODUCTS
# =========================
UNDERLYING = "VELVETFRUIT_EXTRACT"
STATIC = "HYDROGEL_PACK"

OPTIONS = [
    "VEV_4000","VEV_4500","VEV_5000","VEV_5100","VEV_5200",
    "VEV_5300","VEV_5400","VEV_5500","VEV_6000","VEV_6500"
]

STRIKES = {s: int(s.split("_")[1]) for s in OPTIONS}

# =========================
# LIMITS (MAX)
# =========================
LIMITS = {
    STATIC: 200,
    UNDERLYING: 200,
    **{o: 300 for o in OPTIONS}
}

# =========================
# PARAMETERS (OPTIMIZABLE)
# =========================
MM_SPREAD = 2
INVENTORY_SKEW = 0.2
VOL = 0.3
TTE = 5 / 365  # Round 3

# =========================
# BLACK SCHOLES
# =========================
def bs_call(S, K, T, sigma):
    if S <= 0 or T <= 0:
        return 0
    d1 = (math.log(S/K) + 0.5*sigma**2*T)/(sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return S*N.cdf(d1) - K*N.cdf(d2)

# =========================
# HELPER
# =========================
def get_mid(depth):
    if not depth.buy_orders or not depth.sell_orders:
        return None
    return (max(depth.buy_orders) + min(depth.sell_orders)) / 2

# =========================
# TRADER
# =========================
class Trader:

    def run(self, state: TradingState):
        result = {}

        # =========================
        # HYDROGEL (MEAN REVERSION)
        # =========================
        if STATIC in state.order_depths:
            depth = state.order_depths[STATIC]
            orders = []

            mid = get_mid(depth)
            if mid:
                fair = 10000

                if mid < fair - 2:
                    orders.append(Order(STATIC, int(mid+1), 20))
                elif mid > fair + 2:
                    orders.append(Order(STATIC, int(mid-1), -20))

            result[STATIC] = orders

        # =========================
        # UNDERLYING (LIGHT MM)
        # =========================
        if UNDERLYING in state.order_depths:
            depth = state.order_depths[UNDERLYING]
            orders = []

            mid = get_mid(depth)
            if mid:
                bid = int(mid - MM_SPREAD)
                ask = int(mid + MM_SPREAD)

                orders.append(Order(UNDERLYING, bid, 10))
                orders.append(Order(UNDERLYING, ask, -10))

            result[UNDERLYING] = orders

        # =========================
        # OPTIONS (ARBITRAGE)
        # =========================
        if UNDERLYING in state.order_depths:
            S = get_mid(state.order_depths[UNDERLYING])
            if S:
                for opt in OPTIONS:
                    if opt not in state.order_depths:
                        continue

                    depth = state.order_depths[opt]
                    orders = []

                    mid = get_mid(depth)
                    if mid is None:
                        continue

                    K = STRIKES[opt]
                    fair = bs_call(S, K, TTE, VOL)

                    # Mispricing threshold
                    if mid < fair - 1:
                        orders.append(Order(opt, int(mid+1), 30))
                    elif mid > fair + 1:
                        orders.append(Order(opt, int(mid-1), -30))

                    result[opt] = orders

        return result, 0, ""
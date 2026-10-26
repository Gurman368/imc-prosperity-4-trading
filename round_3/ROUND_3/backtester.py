import pandas as pd
import json
from pathlib import Path
from datamodel import OrderDepth, TradingState, Order
from trader import Trader  # your strategy file

# =========================
# LOAD DATA
# =========================
def load_data():
    base_path = Path(__file__).resolve().parent
    prices = []
    trades = []

    for d in range(3):
        price_file = base_path / f"prices_round_3_day_{d}.csv"
        trade_file = base_path / f"trades_round_3_day_{d}.csv"
        prices.append(pd.read_csv(price_file, sep=';'))
        trades.append(pd.read_csv(trade_file, sep=';'))

    prices = pd.concat(prices).reset_index(drop=True)
    trades = pd.concat(trades).reset_index(drop=True)

    return prices, trades


# =========================
# BUILD ORDER BOOK
# =========================
def build_order_depth(row_group):
    order_depths = {}

    for _, row in row_group.iterrows():
        product = row['product']

        depth = OrderDepth()

        # bids
        if not pd.isna(row['bid_price_1']):
            depth.buy_orders[int(row['bid_price_1'])] = int(row['bid_volume_1'])

        if not pd.isna(row['bid_price_2']):
            depth.buy_orders[int(row['bid_price_2'])] = int(row['bid_volume_2'])

        if not pd.isna(row['bid_price_3']):
            depth.buy_orders[int(row['bid_price_3'])] = int(row['bid_volume_3'])

        # asks
        if not pd.isna(row['ask_price_1']):
            depth.sell_orders[int(row['ask_price_1'])] = int(row['ask_volume_1'])

        if not pd.isna(row['ask_price_2']):
            depth.sell_orders[int(row['ask_price_2'])] = int(row['ask_volume_2'])

        if not pd.isna(row['ask_price_3']):
            depth.sell_orders[int(row['ask_price_3'])] = int(row['ask_volume_3'])

        order_depths[product] = depth

    return order_depths


# =========================
# BACKTEST LOOP
# =========================
def run_backtest():

    prices, _ = load_data()

    trader = Trader()

    position = {}
    cash = 0
    traderData = ""

    pnl_series = []

    grouped = prices.groupby(['day', 'timestamp'])

    for (day, ts), group in grouped:

        order_depths = build_order_depth(group)

        state = TradingState(
            timestamp=ts,
            traderData=traderData,
            listings={},
            order_depths=order_depths,
            own_trades={},
            market_trades={},
            position=position,
            observations={}
        )

        orders, _, traderData = trader.run(state)

        # =========================
        # EXECUTION (simplified fill)
        # =========================
        for product, order_list in orders.items():

            depth = order_depths.get(product)
            if depth is None:
                continue

            for order in order_list:

                if order.quantity > 0:
                    # BUY → match against asks
                    for ask_price in sorted(depth.sell_orders):
                        vol = depth.sell_orders[ask_price]

                        trade_qty = min(order.quantity, vol)

                        cash -= trade_qty * ask_price
                        position[product] = position.get(product, 0) + trade_qty

                        order.quantity -= trade_qty

                        if order.quantity <= 0:
                            break

                else:
                    # SELL → match against bids
                    for bid_price in sorted(depth.buy_orders, reverse=True):
                        vol = depth.buy_orders[bid_price]

                        trade_qty = min(abs(order.quantity), vol)

                        cash += trade_qty * bid_price
                        position[product] = position.get(product, 0) - trade_qty

                        order.quantity += trade_qty

                        if order.quantity >= 0:
                            break

        # =========================
        # MARK TO MARKET
        # =========================
        mtm = cash

        for product, pos in position.items():
            depth = order_depths.get(product)

            if depth and depth.buy_orders and depth.sell_orders:
                mid = (max(depth.buy_orders) + min(depth.sell_orders)) / 2
                mtm += pos * mid

        pnl_series.append(mtm)

    return pnl_series


# =========================
# RUN
# =========================
if __name__ == "__main__":
    pnl = run_backtest()

    import matplotlib.pyplot as plt
    plt.plot(pnl)
    plt.title("PnL")
    plt.show()
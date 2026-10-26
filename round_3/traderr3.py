import json
import math
from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order

HYDROGEL_PACK = "HYDROGEL_PACK"
VELVETFRUIT_EXTRACT = "VELVETFRUIT_EXTRACT"

POS_LIMIT = 50

# Strategy parameters
BETA = 0.1976
WINDOW = 500

ENTRY_Z = 2.0
EXIT_Z = 0.5
STOP_Z = 3.0

MAX_HOLD = 300


class Trader:

    def run(self, state: TradingState) -> Dict[str, List[Order]]:
        
        # --- Load memory ---
        try:
            data = json.loads(state.traderData) if state.traderData else {}
        except:
            data = {}
        
        spread_hist = data.get("spread_hist", [])
        position = data.get("position", 0)  # +1 long spread, -1 short
        entry_time = data.get("entry_time", 0)
        
        result = {HYDROGEL_PACK: [], VELVETFRUIT_EXTRACT: []}
        
        # --- Get order books ---
        depth_h = state.order_depths.get(HYDROGEL_PACK)
        depth_f = state.order_depths.get(VELVETFRUIT_EXTRACT)
        
        if not depth_h or not depth_f:
            return result, 0, json.dumps(data)
        
        if not depth_h.buy_orders or not depth_h.sell_orders:
            return result, 0, json.dumps(data)
        
        if not depth_f.buy_orders or not depth_f.sell_orders:
            return result, 0, json.dumps(data)
        
        # --- Mid prices ---
        h_bid = max(depth_h.buy_orders.keys())
        h_ask = min(depth_h.sell_orders.keys())
        f_bid = max(depth_f.buy_orders.keys())
        f_ask = min(depth_f.sell_orders.keys())
        
        h_mid = (h_bid + h_ask) / 2
        f_mid = (f_bid + f_ask) / 2
        
        # --- Spread ---
        spread = h_mid - BETA * f_mid
        spread_hist.append(spread)
        
        if len(spread_hist) > WINDOW:
            spread_hist = spread_hist[-WINDOW:]
        
        if len(spread_hist) < WINDOW:
            data["spread_hist"] = spread_hist
            return result, 0, json.dumps(data)
        
        # --- Z-score ---
        mean = sum(spread_hist) / len(spread_hist)
        std = (sum((x - mean) ** 2 for x in spread_hist) / len(spread_hist)) ** 0.5
        
        if std == 0:
            return result, 0, json.dumps(data)
        
        z = (spread - mean) / std
        
        # --- Current positions ---
        pos_h = state.position.get(HYDROGEL_PACK, 0)
        pos_f = state.position.get(VELVETFRUIT_EXTRACT, 0)
        
        t = state.timestamp
        
        # =========================
        # EXIT LOGIC
        # =========================
        if position != 0:
            if abs(z) < EXIT_Z or abs(z) > STOP_Z or (t - entry_time > MAX_HOLD):
                
                # Close HYDROGEL
                if pos_h > 0:
                    result[HYDROGEL_PACK].append(Order(HYDROGEL_PACK, h_bid, -pos_h))
                elif pos_h < 0:
                    result[HYDROGEL_PACK].append(Order(HYDROGEL_PACK, h_ask, -pos_h))
                
                # Close FRUIT
                if pos_f > 0:
                    result[VELVETFRUIT_EXTRACT].append(Order(VELVETFRUIT_EXTRACT, f_bid, -pos_f))
                elif pos_f < 0:
                    result[VELVETFRUIT_EXTRACT].append(Order(VELVETFRUIT_EXTRACT, f_ask, -pos_f))
                
                position = 0
        
        # =========================
        # ENTRY LOGIC
        # =========================
        if position == 0:
            
            size_h = 10
            size_f = int(round(BETA * size_h))
            
            # SHORT spread
            if z > ENTRY_Z:
                
                # Sell HYDROGEL
                result[HYDROGEL_PACK].append(Order(HYDROGEL_PACK, h_bid, -size_h))
                
                # Buy FRUIT
                result[VELVETFRUIT_EXTRACT].append(Order(VELVETFRUIT_EXTRACT, f_ask, size_f))
                
                position = -1
                entry_time = t
            
            # LONG spread
            elif z < -ENTRY_Z:
                
                # Buy HYDROGEL
                result[HYDROGEL_PACK].append(Order(HYDROGEL_PACK, h_ask, size_h))
                
                # Sell FRUIT
                result[VELVETFRUIT_EXTRACT].append(Order(VELVETFRUIT_EXTRACT, f_bid, -size_f))
                
                position = 1
                entry_time = t
        
        # --- Save state ---
        data["spread_hist"] = spread_hist
        data["position"] = position
        data["entry_time"] = entry_time
        
        return result, 0, json.dumps(data)
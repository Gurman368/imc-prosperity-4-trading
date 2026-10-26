import itertools
import subprocess
import json
import re
from pathlib import Path

# =========================
# PATH SETUP
# =========================
BASE = Path(__file__).resolve().parent
PROSPERITY_BIN = str(BASE / "venv" / "Scripts" / "prosperity4bt.exe")
STRATEGY_PATH = str(BASE / "strategies" / "376684.py")
DATA_PATH = str(BASE / "data")

# =========================
# PARAMETER GRID
# =========================
# Added more parameters and wider ranges to explore more aggressive strategies
GRID = {
    "h_make_size": [5, 15, 30],         # Wider maker sizes for Hydrogel
    "h_make_edge": [1, 2],              # Testing spread widening
    "f_z_entry": [1.5, 2.0, 3.0],       # Testing more frequent vs extreme entries
    "f_trade_size": [5, 10],            # Increased trade size for Velvetfruit
    "f_max_pos": [20, 40],              # Testing higher inventory limits
    "o_single_edge": [1, 3, 6],         # Testing tighter vs wider option edges
    "o_hedge_thr": [10, 20, 40],        # Delta hedging sensitivity
}

def run_backtest(params):
    # 1. Write params to file
    # FIXED: Write to CWD so 376684.py can find it when running prosperity4bt
    params_path = Path.cwd() / "params.json"
    with open(params_path, "w") as f:
        json.dump(params, f)

    # 2. Construct command
    cmd = [
        PROSPERITY_BIN,
        STRATEGY_PATH,
        "3",
        "--data", DATA_PATH,
        "--merge-pnl",
        "--no-out"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stdout
        
        # 3. Parse Total profit
        # Looking for line: "Total profit: -511,697"
        match = re.search(r"Total profit:\s*([-,\d]+)", output)
        if match:
            profit_str = match.group(1).replace(",", "")
            return int(profit_str)
    except Exception as e:
        print(f"Error running backtest: {e}")
    
    return -999999999

def main():
    keys = list(GRID.keys())
    combinations = list(itertools.product(*GRID.values()))
    
    print(f"Starting Grid Search: {len(combinations)} total runs.")
    
    best_pnl = -float('inf')
    best_params = None

    for i, values in enumerate(combinations):
        current_params = dict(zip(keys, values))
        
        # Exhaustive list of all parameters found in 376684.py
        full_params = {
            "h_take_size": 10, 
            "h_make_edge": 1, 
            "h_make_size": 5,
            "f_hist_len": 100, 
            "f_min_hist": 30, 
            "f_min_std": 2,
            "f_max_pos": 20, 
            "f_reduce_size": 5, 
            "f_trade_size": 2, 
            "f_z_entry": 2.5,
            "o_t": 0.1, 
            "o_atm_filter": 150, 
            "o_cross_edge": 2, 
            "o_inv_adj": 0.1,
            "o_single_edge": 3, 
            "o_single_size": 2, 
            "o_hedge_mult": -0.5,
            "o_hedge_thr": 20, 
            "o_hedge_max": 15
        }
        full_params.update(current_params)

        pnl = run_backtest(full_params)
        print(f"Run {i+1}/{len(combinations)} | PnL: {pnl:10} | Params: {current_params}")

        if pnl > best_pnl:
            best_pnl = pnl
            best_params = current_params
            print(f">>> NEW BEST: {best_pnl}")

    print("\n" + "="*30)
    print(f"FINAL BEST PNL: {best_pnl}")
    print(f"BEST PARAMETERS: {best_params}")

if __name__ == "__main__":
    main()
import itertools
import subprocess
import json
import re
from pathlib import Path
import random

# =========================
# PATH SETUP
# =========================
BASE = Path(__file__).resolve().parent
PROSPERITY_BIN = str(BASE / "venv" / "Scripts" / "prosperity4bt.exe")
STRATEGY_PATH = str(BASE / "strategies" / "pairtraderr3.py")
DATA_PATH = str(BASE / "data")

# =========================
# CONFIGURATION
# =========================
MAX_RUNS = 100  # Number of random combinations to test (Full grid search is too large)

# =========================
# PARAMETER GRID
# =========================
# Reduced to 9 key parameters for Velvetfruit and Options to improve search efficiency
GRID = {
    # Velvetfruit (Solo and Pairs logic)
    "f_trade_size": [2, 5, 8],
    "f_z_entry": [0.8, 1.0, 1.2],
    "p_window": [50, 100, 150],
    "p_z_entry": [0.8, 1.0, 1.2],
    "p_adf_threshold": [0.01, 0.02, 0.03],
    "p_trade_size": [1, 2, 3],
    # Options on Velvetfruit
    "o_atm_filter": [60, 90, 110],
    "o_single_edge": [0.2, 0.5, 0.8],
    "o_hedge_thr": [20, 40, 50]
}

def run_backtest(params):
    params_path = Path.cwd() / "params.json"
    with open(params_path, "w") as f:
        json.dump(params, f)

    cmd = [
        PROSPERITY_BIN,
        STRATEGY_PATH,
        "3", # Backtest Round 3
        "--data", DATA_PATH,
        "--merge-pnl",
        "--no-out"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stdout
        
        if result.returncode != 0:
            print(f"\n[BACKTEST ERROR] Command failed with code {result.returncode}")
            print(result.stderr)
            return -999999999

        match = re.search(r"Total profit:\s*([-,\d]+)", output)
        if match:
            profit_str = match.group(1).replace(",", "")
            return int(profit_str)
        else:
            print("\n[PARSING ERROR] 'Total profit:' not found in output.")
            print("Last 500 chars of output:")
            print(output[-500:])
            
    except Exception as e:
        print(f"Error running backtest for params {params}: {e}")
    
    return -999999999

def main():
    # 0. Check Environment
    if not Path(PROSPERITY_BIN).exists():
        print(f"CRITICAL ERROR: Binary not found at {PROSPERITY_BIN}")
        print("Ensure you are running the script with the venv python.")
        return

    keys = list(GRID.keys())
    combinations = list(itertools.product(*GRID.values()))
    
    # Shuffle and limit to avoid 1.5M runs
    random.shuffle(combinations)
    combinations = combinations[:MAX_RUNS]
    
    print(f"Starting Grid Search: {len(combinations)} total runs.")
    
    best_pnl = -float('inf')
    best_params = None

    for i, values in enumerate(combinations):
        current_params = dict(zip(keys, values))
        
        pnl = run_backtest(current_params)
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
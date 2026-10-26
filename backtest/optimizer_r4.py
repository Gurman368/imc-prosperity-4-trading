import subprocess
import json
import re
from pathlib import Path
import copy

# =========================
# PATH SETUP
# =========================
BASE = Path(__file__).resolve().parent
PROSPERITY_BIN = str(BASE / "venv" / "Scripts" / "prosperity4bt.exe")
STRATEGY_PATH = str(BASE / "pairtraderr3.py")
DATA_PATH = str(BASE / "data")

# =========================
# INITIAL DEV MAP
# =========================
DEV_MAP = {
    "VEV_4000": 50,
    "VEV_4500": 50,
    "VEV_5000": 25,
    "VEV_5100": 35,
    "VEV_5200": 50,
    "VEV_5300": 30,
    "VEV_5400": 15,
    "VEV_5500": 15,
    "VEV_6000": 5,
    "VEV_6500": 5,
}

# 10 values: 10 → 55
DEV_CANDIDATES = [5 * i for i in range(2, 12)]

# =========================
# BACKTEST
# =========================
def run_backtest(dev_map):

    params = {
        "dev_map": dev_map
    }

    with open("params.json", "w") as f:
        json.dump(params, f)

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

        match = re.search(r"Total profit:\s*([-,\d]+)", output)
        if match:
            return int(match.group(1).replace(",", ""))
    except Exception as e:
        print(f"Error: {e}")

    return -999999999


# =========================
# OPTIMIZER
# =========================
def optimize_dev_map():

    best_map = copy.deepcopy(DEV_MAP)

    print("🚀 Optimizing DEV_FULL_MAP...\n")

    for option in best_map.keys():

        print(f"\n🔍 {option}")

        # baseline with current map
        best_pnl = run_backtest(best_map)
        best_val = best_map[option]

        print(f"Start → dev={best_val}, pnl={best_pnl}")

        for dev in DEV_CANDIDATES:

            test_map = copy.deepcopy(best_map)
            test_map[option] = dev

            pnl = run_backtest(test_map)

            print(f"  dev={dev:2} → pnl={pnl}")

            if pnl > best_pnl:
                best_pnl = pnl
                best_val = dev
                print("   ✅ improved")

        best_map[option] = best_val

        print(f"🏁 Locked {option} = {best_val} (pnl={best_pnl})")

    print("\n" + "="*40)
    print("🎯 FINAL DEV MAP:")
    print(json.dumps(best_map, indent=2))


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    optimize_dev_map()
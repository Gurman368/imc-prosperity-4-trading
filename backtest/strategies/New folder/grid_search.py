import itertools
import subprocess
import json
import time

# =========================
# PARAMETER GRID
# =========================
PARAM_GRID = {
    "mm_spread": [1, 2, 3],
    "inventory_skew": [0.1, 0.2, 0.3],

    "iv_threshold": [0.3, 0.5, 0.7],
    "mr_threshold": [3, 5, 8],

    "ema_window_u": [5, 10],
    "ema_window_o": [10, 20],

    "position_cap": [200],   # max allowed (as per round)
}

# =========================
# CONFIG
# =========================
TRADER_PATH = r"C:\Users\rajy7\OneDrive\Documents\GitHub\Imc_prosperity4_ISI_BSDS\backtest\strategies\trader3v3.py"
DATA_PATH = r"c:/Users/rajy7/OneDrive/Documents/GitHub/Imc_prosperity4_ISI_BSDS/backtest/data"

ROUND = "3"

# =========================
# GENERATE COMBINATIONS
# =========================
keys = list(PARAM_GRID.keys())
values = list(PARAM_GRID.values())

all_combos = list(itertools.product(*values))

print(f"Total runs: {len(all_combos)}")

results = []

# =========================
# GRID SEARCH LOOP
# =========================
for i, combo in enumerate(all_combos):

    params = dict(zip(keys, combo))

    # Save params to file
    with open("params.json", "w") as f:
        json.dump(params, f)

    print(f"\nRunning {i+1}/{len(all_combos)}: {params}")

    # Run backtest
    cmd = [
        "prosperity4bt",
        TRADER_PATH,
        ROUND,
        "--data",
        DATA_PATH,
        "--merge-pnl",
        "--no-out"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stdout

        total_pnl = 0
        daily_pnls = []

        for line in output.split("\n"):
            if "Total profit:" in line:
                val = int(line.split(":")[-1].replace(",", "").strip())
                daily_pnls.append(val)

        if len(daily_pnls) > 0:
            total_pnl = sum(daily_pnls)
            worst_day = min(daily_pnls)

            # robust score (VERY IMPORTANT)
            score = total_pnl + worst_day * 0.5

        else:
            total_pnl = -999999
            score = -999999
            worst_day = -999999

    except Exception as e:
        print("Error:", e)
        total_pnl = -999999
        score = -999999
        worst_day = -999999

    results.append({
        "params": params,
        "total_pnl": total_pnl,
        "worst_day": worst_day,
        "score": score
    })

    print(f"Result → Total: {total_pnl}, Worst: {worst_day}, Score: {score}")

    time.sleep(0.2)  # prevent overload

# =========================
# SORT RESULTS
# =========================
results.sort(key=lambda x: x["score"], reverse=True)

# =========================
# PRINT BEST
# =========================
print("\n================ BEST CONFIGS ================\n")

for r in results[:10]:
    print(r)

# =========================
# SAVE RESULTS
# =========================
with open("grid_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("\nSaved to grid_results.json")
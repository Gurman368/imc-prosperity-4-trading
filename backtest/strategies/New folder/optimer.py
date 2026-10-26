import itertools
import subprocess
import json
import time

PARAM_GRID = {
    "hydro_ema": [0.005, 0.01, 0.02],
    "hydro_dev": [10, 13, 16],
    "fruit_ema": [0.005, 0.01, 0.02],
    "fruit_dev": [8, 11, 14],
}

TRADER_PATH = r"C:\Users\rajy7\OneDrive\Documents\GitHub\Imc_prosperity4_ISI_BSDS\backtest\strategies\traderr3v4.py"
DATA_PATH   = r"c:/Users/rajy7/OneDrive/Documents/GitHub/Imc_prosperity4_ISI_BSDS/backtest/data"

keys = list(PARAM_GRID.keys())
values = list(PARAM_GRID.values())
combos = list(itertools.product(*values))

print(f"Total runs: {len(combos)}")

results = []

for i, combo in enumerate(combos):

    params = dict(zip(keys, combo))

    with open("params.json", "w") as f:
        json.dump(params, f)

    print(f"\nRun {i+1}/{len(combos)} → {params}")

    cmd = [
        "prosperity4bt",
        TRADER_PATH,
        "3",
        "--data",
        DATA_PATH,
        "--merge-pnl",
        "--no-out"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        output = result.stdout

        daily = []
        for line in output.split("\n"):
            if "Total profit:" in line:
                val = int(line.split(":")[-1].replace(",", "").strip())
                daily.append(val)

        if daily:
            total = sum(daily)
            worst = min(daily)
            score = total + 0.5 * worst
        else:
            total, worst, score = -999999, -999999, -999999

    except:
        total, worst, score = -999999, -999999, -999999

    results.append({
        "params": params,
        "total": total,
        "worst": worst,
        "score": score
    })

    print(f"→ Total: {total}, Worst: {worst}, Score: {score}")

    time.sleep(0.2)

results.sort(key=lambda x: x["score"], reverse=True)

print("\n🔥 BEST CONFIGS:\n")
for r in results[:10]:
    print(r)

with open("results.json", "w") as f:
    json.dump(results, f, indent=2)
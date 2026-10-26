import subprocess
import re
import json
from itertools import product
from pathlib import Path

# =========================
# PATH SETUP (FIXED)
# =========================
BASE = Path(__file__).resolve().parent

STRATEGY = BASE / "trader_final.py"   # <-- IMPORTANT
TEMP = BASE / "temp_strategy.py"

DATA = BASE.parent / "data"
ROUNDS = ["3"]

# =========================
# PARAM GRID
# =========================
GRID = {
    "MM_SPREAD": [1,2,3],
    "INVENTORY_SKEW": [0.1,0.2],
    "VOL": [0.2,0.25,0.3],
}

# =========================
# PARSER
# =========================
def parse_profit(output):
    matches = re.findall(r"Total profit:\s*([-\d,]+)", output)
    if not matches:
        return -1e9
    return float(matches[-1].replace(",", ""))

# =========================
# PATCH STRATEGY
# =========================
def write_params(params):
    text = STRATEGY.read_text()

    for k,v in params.items():
        text = re.sub(rf"{k}\s*=\s*.*", f"{k} = {v}", text)

    TEMP.write_text(text)

# =========================
# RUN BACKTEST
# =========================
def run(params):
    write_params(params)

    cmd = [
        "prosperity4bt",
        str(TEMP),
        *ROUNDS,
        "--data", str(DATA),
        "--merge-pnl",
        "--no-out"
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=40,
            cwd=BASE.parent  # <-- VERY IMPORTANT
        )

        return parse_profit(res.stdout)

    except Exception as e:
        print("Error:", e)
        return -1e9

# =========================
# SEARCH
# =========================
best = None
best_score = -1e9

all_runs = list(product(*GRID.values()))

print("Total runs:", len(all_runs))

for i,vals in enumerate(all_runs):
    params = dict(zip(GRID.keys(), vals))

    score = run(params)

    print(f"{i+1}/{len(all_runs)} | {params} → {score}")

    if score > best_score:
        best_score = score
        best = params

        with open(BASE / "best.json","w") as f:
            json.dump({"score": score, "params": params}, f, indent=2)

print("\nBEST:", best)
print("SCORE:", best_score)
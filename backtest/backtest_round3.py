import subprocess
from pathlib import Path

# =============================================================================
# Backtest runner for Round 3 (Pairs Trading: Hydrogel vs Velvetfruit)
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent
STRATEGY_PATH = BASE_DIR / "strategies" / "traderr3.py"

# Point this to the directory containing Round 3 price CSVs
# Based on your folder structure, they are in 'round_3/ROUND_3/'
DATA_DIR = BASE_DIR.parent / "round_3" / "ROUND_3"

# Round 3 typically uses Day 0, 1, and 2
DAYS = ["0", "1", "2"]

def run_backtest():
    """Runs the prosperity4bt backtest command."""
    
    # Construct the command similar to your optimize scripts
    cmd = [
        "prosperity4bt",
        "run",
        str(STRATEGY_PATH),
        *DAYS,
        "--data", str(DATA_DIR),
        "--merge-pnl"
    ]
    
    print(f"--- Round 3 Backtest ---")
    print(f"Strategy: {STRATEGY_PATH.name}")
    print(f"Data Dir: {DATA_DIR}")
    print(f"Days:     {', '.join(DAYS)}\n")
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n[SUCCESS] Backtest completed.")
    else:
        print(f"\n[ERROR] Backtest failed with exit code {result.returncode}.")

if __name__ == "__main__":
    run_backtest()
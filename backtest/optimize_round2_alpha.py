import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path


BASE = Path(__file__).resolve().parent
STRATEGY = BASE / "strategies" / "r2trader.py"
TMP_STRATEGY = BASE / "strategies" / "r2trader_alpha_tuned_tmp.py"
BEST_LOG = BASE / "logs" / "opt_round2_alpha_best_params.json"

DATA_DIR = BASE / "data"
DAYS = ["2"]
PASSES = 2


PARAM_GRID = {
    # Keep this focused on alpha/execution knobs (excluding stoploss).
    "ACO_BASE_HALF_SPREAD": [1.0, 1.5, 2.0],
    "ACO_AGGRESSIVE_TAKE_EDGE": [0.0, 0.5, 1.0],
    "ACO_MOMENTUM_WEIGHT": [0.3, 0.8, 1.2],
    "IPR_OBI_WEIGHT": [7.0, 9.0, 12.0],
    "IPR_MICROPRICE_WEIGHT": [0.4, 0.8, 1.2],
    "IPR_TREND_AGGRESSION": [1.2, 1.8, 2.5],
    "IPR_DRIFT_TO_TARGET": [12.0, 20.0, 30.0],
    "IPR_AGGRESSIVE_EDGE": [2.0, 3.0, 5.0],
    "IPR_OVER_TARGET_TRIM": [10.0, 20.0, 35.0],
}


def set_params_in_text(text: str, params: dict) -> str:
    out = text
    for key, value in params.items():
        pattern = rf"(^\s*{re.escape(key)}\s*=\s*)([-+]?\d*\.?\d+)"
        repl = rf"\g<1>{value}"
        out, n = re.subn(pattern, repl, out, flags=re.MULTILINE)
        if n == 0:
            raise ValueError(f"Could not find constant {key} in {STRATEGY}")
    return out


def parse_total_profit(output: str) -> float:
    matches = re.findall(r"Total profit:\s*([-,\d]+)", output)
    if not matches:
        return float("-inf")
    return float(matches[-1].replace(",", ""))


def parse_symbol_profit(output: str, symbol: str) -> float:
    matches = re.findall(rf"{re.escape(symbol)}:\s*([-,\d]+)", output)
    if not matches:
        return float("-inf")
    return float(sum(int(m.replace(",", "")) for m in matches))


def run_backtest_on_file(path: Path) -> tuple[float, float, str]:
    cmd = [
        "prosperity4bt",
        str(path),
        *DAYS,
        "--data",
        str(DATA_DIR),
        "--merge-pnl",
        "--no-out",
    ]
    p = subprocess.run(cmd, cwd=BASE.parent, capture_output=True, text=True)
    if p.returncode != 0:
        return float("-inf"), float("-inf"), p.stderr
    total = parse_total_profit(p.stdout)
    ipr = parse_symbol_profit(p.stdout, "INTARIAN_PEPPER_ROOT")
    return total, ipr, p.stdout


def run_backtest_on_params(params: dict) -> tuple[float, float, str]:
    original = STRATEGY.read_text(encoding="utf-8")
    tuned = set_params_in_text(original, params)
    TMP_STRATEGY.write_text(tuned, encoding="utf-8")
    return run_backtest_on_file(TMP_STRATEGY)


def extract_current_params() -> dict:
    src = STRATEGY.read_text(encoding="utf-8")
    out = {}
    for key in PARAM_GRID.keys():
        m = re.search(rf"^\s*{re.escape(key)}\s*=\s*([-+]?\d*\.?\d+)", src, flags=re.MULTILINE)
        if not m:
            raise ValueError(f"Could not read {key} from strategy")
        out[key] = float(m.group(1))
    return out


def apply_best_to_strategy(params: dict) -> None:
    src = STRATEGY.read_text(encoding="utf-8")
    tuned = set_params_in_text(src, params)
    STRATEGY.write_text(tuned, encoding="utf-8")


def coordinate_search(initial: dict) -> tuple[dict, float, float]:
    best_params = deepcopy(initial)
    best_total, best_ipr, _ = run_backtest_on_params(best_params)
    print(f"[baseline] total={best_total:.0f}, IPR={best_ipr:.0f}, params={best_params}")

    eval_budget = PASSES * sum(len(v) for v in PARAM_GRID.values())
    eval_no = 0

    for p in range(1, PASSES + 1):
        improved_any = False
        print(f"\n=== pass {p}/{PASSES} ===")

        for key, values in PARAM_GRID.items():
            local_best_val = best_params[key]
            local_best_total = best_total
            local_best_ipr = best_ipr
            print(f"optimizing {key}")

            for v in values:
                eval_no += 1
                trial = deepcopy(best_params)
                trial[key] = float(v)
                total, ipr, _ = run_backtest_on_params(trial)
                print(f"  [{eval_no}/{eval_budget}] {key}={v} -> total={total:.0f}, IPR={ipr:.0f}")

                if total > local_best_total:
                    local_best_total = total
                    local_best_ipr = ipr
                    local_best_val = float(v)

            if local_best_total > best_total:
                best_params[key] = local_best_val
                best_total = local_best_total
                best_ipr = local_best_ipr
                improved_any = True
                print(f"  [improved] keep {key}={local_best_val}; best total={best_total:.0f}, IPR={best_ipr:.0f}")
            else:
                print(f"  [no change] keep {key}={best_params[key]}")

        if not improved_any:
            print("No improvement this pass; stopping early.")
            break

    return best_params, best_total, best_ipr


def main() -> None:
    initial = extract_current_params()
    best_params, best_total, best_ipr = coordinate_search(initial)

    payload = {
        "strategy": str(STRATEGY),
        "data_dir": str(DATA_DIR),
        "days": DAYS,
        "best_total_profit": best_total,
        "best_ipr_profit": best_ipr,
        "best_params": best_params,
    }
    BEST_LOG.parent.mkdir(parents=True, exist_ok=True)
    BEST_LOG.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[saved] {BEST_LOG}")

    apply_best_to_strategy(best_params)
    print("[applied] Best params written to strategy")

    final_total, final_ipr, _ = run_backtest_on_file(STRATEGY)
    print(f"[final strategy] total={final_total:.0f}, IPR={final_ipr:.0f}")


if __name__ == "__main__":
    main()

import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path


BASE = Path(__file__).resolve().parent
STRATEGY = BASE / "strategies" / "r2trader.py"
TMP_STRATEGY = BASE / "strategies" / "r2trader_allparams_tmp.py"
BEST_LOG = BASE / "logs" / "opt_round2_all_params_wide_best.json"
CHECKPOINT = BASE / "logs" / "opt_round2_all_params_wide_checkpoint.json"

DATA_DIR = BASE / "data"
DAYS = ["2"]
PASSES = 1  # increase to 2+ if you want deeper coordinate refinement

PREFIXES = ("ACO_", "IPR_", "STOPLOSS_", "MAF_")
EXCLUDE_EXACT = {
    "MAF_ENABLE",
    "ACO_USE_EMA_FAIR_VALUE",
    "STOPLOSS_ENABLE_ACO",
    "STOPLOSS_ENABLE_IPR",
}


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


def set_params_in_text(text: str, params: dict) -> str:
    out = text
    for key, value in params.items():
        pattern = rf"(^\s*{re.escape(key)}\s*=\s*)([-+]?\d*\.?\d+)"
        repl = rf"\g<1>{value}"
        out, n = re.subn(pattern, repl, out, flags=re.MULTILINE)
        if n == 0:
            raise ValueError(f"Could not find constant {key} in strategy text")
    return out


def run_backtest_on_params(params: dict) -> tuple[float, float, str]:
    original = STRATEGY.read_text(encoding="utf-8")
    tuned = set_params_in_text(original, params)
    TMP_STRATEGY.write_text(tuned, encoding="utf-8")
    return run_backtest_on_file(TMP_STRATEGY)


def detect_numeric_params() -> dict:
    src = STRATEGY.read_text(encoding="utf-8")
    params = {}
    pattern = re.compile(r"^\s*([A-Z0-9_]+)\s*=\s*([-+]?\d*\.?\d+)\s*$", re.MULTILINE)

    for m in pattern.finditer(src):
        name = m.group(1)
        value_s = m.group(2)

        if not name.startswith(PREFIXES):
            continue
        if name in EXCLUDE_EXACT:
            continue

        # Keep integer-like parameters as ints where appropriate.
        if "." in value_s:
            val = float(value_s)
            is_int = False
        else:
            val = int(value_s)
            is_int = True

        # Avoid non-tunable constants that should not explode.
        if "LIMIT" in name and not name.startswith("STOPLOSS"):
            continue

        params[name] = {"value": val, "is_int": is_int}

    if not params:
        raise ValueError("No numeric ACO/IPR/STOPLOSS/MAF parameters detected")
    return params


def make_wide_doubling_values(base: float, is_int: bool) -> list:
    """
    10 values where each next is ~2x previous.
    Sequence centered around base: base/16 ... base*32
    """
    if base > 0:
        start = base / 16.0
    else:
        # For zero defaults, start from a small positive seed.
        start = 0.03125 if not is_int else 1.0

    vals = [start * (2.0 ** i) for i in range(10)]

    cleaned = []
    seen = set()
    for v in vals:
        if is_int:
            x = max(0, int(round(v)))
        else:
            x = max(0.0, float(v))

        if x not in seen:
            seen.add(x)
            cleaned.append(x)

    # If integer rounding collapsed too much, pad progressively.
    if is_int:
        cur = cleaned[-1] if cleaned else 0
        while len(cleaned) < 10:
            cur += max(1, cur)
            if cur not in seen:
                seen.add(cur)
                cleaned.append(cur)

    return cleaned[:10]


def build_param_grid(detected: dict) -> dict:
    grid = {}
    for name, meta in detected.items():
        grid[name] = make_wide_doubling_values(float(meta["value"]), bool(meta["is_int"]))
    return grid


def extract_current_params(detected: dict) -> dict:
    return {k: v["value"] for k, v in detected.items()}


def save_checkpoint(payload: dict) -> None:
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def coordinate_search(initial: dict, param_grid: dict) -> tuple[dict, float, float]:
    best_params = deepcopy(initial)
    best_total, best_ipr, _ = run_backtest_on_params(best_params)
    print(f"[baseline] total={best_total:.0f}, IPR={best_ipr:.0f}")

    total_evals = PASSES * sum(len(v) for v in param_grid.values())
    eval_no = 0

    for p in range(1, PASSES + 1):
        improved_any = False
        print(f"\n=== pass {p}/{PASSES} ===")

        for key, values in param_grid.items():
            local_best_total = best_total
            local_best_ipr = best_ipr
            local_best_val = best_params[key]

            print(f"optimizing {key} (10 values)")
            for v in values:
                eval_no += 1
                trial = deepcopy(best_params)
                trial[key] = v
                total, ipr, _ = run_backtest_on_params(trial)
                print(f"  [{eval_no}/{total_evals}] {key}={v} -> total={total:.0f}, IPR={ipr:.0f}")

                if total > local_best_total:
                    local_best_total = total
                    local_best_ipr = ipr
                    local_best_val = v

                save_checkpoint(
                    {
                        "pass": p,
                        "eval_no": eval_no,
                        "total_evals": total_evals,
                        "current_param": key,
                        "current_value": v,
                        "best_total": best_total,
                        "best_ipr": best_ipr,
                        "best_params": best_params,
                    }
                )

            if local_best_total > best_total:
                best_total = local_best_total
                best_ipr = local_best_ipr
                best_params[key] = local_best_val
                improved_any = True
                print(f"  [improved] keep {key}={local_best_val}; best total={best_total:.0f}, IPR={best_ipr:.0f}")
            else:
                print(f"  [no change] keep {key}={best_params[key]}")

        if not improved_any:
            print("No improvement this pass; stopping early.")
            break

    return best_params, best_total, best_ipr


def apply_best_to_strategy(params: dict) -> None:
    src = STRATEGY.read_text(encoding="utf-8")
    tuned = set_params_in_text(src, params)
    STRATEGY.write_text(tuned, encoding="utf-8")


def main() -> None:
    detected = detect_numeric_params()
    param_grid = build_param_grid(detected)
    initial = extract_current_params(detected)

    print(f"[detected params] {len(initial)}")
    print("[mode] CPU coordinate grid search with 10 doubling-spaced values per parameter")

    best_params, best_total, best_ipr = coordinate_search(initial, param_grid)

    payload = {
        "strategy": str(STRATEGY),
        "data_dir": str(DATA_DIR),
        "days": DAYS,
        "passes": PASSES,
        "detected_param_count": len(initial),
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

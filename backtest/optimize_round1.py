import json
import re
import subprocess
import ast
from itertools import product
from copy import deepcopy
from pathlib import Path

BASE = Path(__file__).resolve().parent
STRATEGY = BASE / "strategies" / "191194.py"
TMP_STRATEGY = BASE / "strategies" / "191194_tuned_tmp.py"

PARAM_GRID = {
    # ACO-only tuning grid (ASH/EMERALDS execution)
    "ACO_FAIR_VALUE": [9999, 10000, 10001],
    "ACO_BASE_HALF_SPREAD": [1.0, 1.5, 2.0],
    "ACO_SPREAD_WIDEN_WEIGHT": [0.0, 0.2, 0.4],
    "ACO_INV_SKEW_THRESHOLD_1": [15, 20, 25],
    "ACO_INV_SKEW_THRESHOLD_2": [50, 60, 70],
    "ACO_INV_SKEW_STEP_1": [0.5, 1.0, 1.5],
    "ACO_INV_SKEW_STEP_2": [0.5, 1.0, 1.5],
    "ACO_PASSIVE_JOIN_TICKS": [1.0, 1.5, 2.0],
    "ACO_AGGRESSIVE_TAKE_EDGE": [0.0, 0.5, 1.0],
    "ACO_OBI_WEIGHT": [0.0, 0.8, 1.6],
    "ACO_MICRO_SHIFT_WEIGHT": [0.0, 0.3, 0.7],
    "ACO_MOMENTUM_WEIGHT": [0.0, 0.4, 0.8],
    "ACO_MID_MOM_ALPHA": [0.1, 0.2, 0.35],
    "ACO_VOL_EMA_ALPHA": [0.08, 0.12, 0.2],
    "ACO_VOL_PENALTY": [0.0, 0.4, 0.8],
    "ACO_SIGNAL_CLIP": [2.0, 3.0, 4.0],
    "ACO_SIGNAL_TICK_SCALE": [0.5, 1.0, 1.5],
    "ACO_MODE_OVERRIDE": [-1, 0, 1, 2, 3],
    "ACO_REGIME_WIDE_SPREAD": [1.5, 2.0],
    "ACO_REGIME_HIGH_VOL": [0.8, 1.2],
    "ACO_REGIME_MOM_TRIGGER": [0.25, 0.35],
    "ACO_MOMENTUM_SIGNAL_MULT": [1.1, 1.35],
    "ACO_DEFENSIVE_SIGNAL_MULT": [0.6, 0.8],
}

# Focused interaction search (joint cartesian product) after coordinate ascent.
JOINT_PARAM_GRID = {
    "ACO_BASE_HALF_SPREAD": [1.0, 1.5, 2.0],
    "ACO_SPREAD_WIDEN_WEIGHT": [0.0, 0.2, 0.4],
    "ACO_OBI_WEIGHT": [0.0, 0.8, 1.6],
    "ACO_MOMENTUM_WEIGHT": [0.0, 0.4, 0.8],
    "ACO_PASSIVE_JOIN_TICKS": [1.0, 1.5, 2.0],
    "ACO_AGGRESSIVE_TAKE_EDGE": [0.0, 0.5, 1.0],
}

ENABLE_JOINT_GRID = False
OBJECTIVE_SYMBOL = "ASH_COATED_OSMIUM"

PASSES = 2
APPLY_BEST_TO_STRATEGY = True


def set_params_in_text(text: str, params: dict) -> str:
    out = text
    for key, value in params.items():
        pattern = rf"(^\s*{re.escape(key)}\s*=\s*)([-+]?\d*\.?\d+)"
        repl = rf"\g<1>{value}"
        out, n = re.subn(pattern, repl, out, flags=re.MULTILINE)
        if n == 0:
            print(f"[WARN] Could not find constant {key} in {STRATEGY.name}")
    return out


def extract_live_param_names(source_text: str) -> set[str]:
    """Return ACO_/IPR_ constants that are declared and loaded at least once."""
    tree = ast.parse(source_text)
    assigned = set()
    loaded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and (
                    target.id.startswith("ACO_") or target.id.startswith("IPR_")
                ):
                    assigned.add(target.id)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loaded.add(node.id)
    return assigned & loaded


def parse_total_profit(output: str) -> float:
    # parse all 'Total profit:' occurrences, final one is summary
    matches = re.findall(r"Total profit:\s*([-,\d]+)", output)
    if not matches:
        return float("-inf")
    return float(matches[-1].replace(",", ""))


def parse_symbol_profit(output: str, symbol: str) -> float:
    matches = re.findall(rf"{re.escape(symbol)}:\s*([-,\d]+)", output)
    if not matches:
        return float("-inf")
    return float(sum(int(m.replace(",", "")) for m in matches))


def run_backtest_on_temp(params: dict) -> tuple[float, float]:
    original = STRATEGY.read_text(encoding="utf-8")
    modified = set_params_in_text(original, params)
    TMP_STRATEGY.write_text(modified, encoding="utf-8")

    cmd = ["prosperity4bt", str(TMP_STRATEGY), "1", "--merge-pnl", "--no-out"]
    p = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
    if p.returncode != 0:
        print("--- backtest failed ---")
        print(p.stderr)
        return float("-inf"), float("-inf")
    return parse_symbol_profit(p.stdout, OBJECTIVE_SYMBOL), parse_total_profit(p.stdout)


def run_backtest_on_strategy(path: Path) -> tuple[float, float]:
    cmd = ["prosperity4bt", str(path), "1", "--merge-pnl", "--no-out"]
    p = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
    if p.returncode != 0:
        print("--- baseline/final backtest failed ---")
        print(p.stderr)
        return float("-inf"), float("-inf")
    return parse_symbol_profit(p.stdout, OBJECTIVE_SYMBOL), parse_total_profit(p.stdout)


def coordinate_ascent(initial_params: dict) -> tuple[dict, float]:
    best_params = deepcopy(initial_params)
    best_obj_pnl, best_total_pnl = run_backtest_on_temp(best_params)
    print(f"[baseline] {OBJECTIVE_SYMBOL}={best_obj_pnl:.0f}, total={best_total_pnl:.0f}")
    print(f"[baseline params] {best_params}")

    for p_i in range(1, PASSES + 1):
        print(f"\n=== pass {p_i}/{PASSES} ===")
        improved_any = False
        for param_name, values in PARAM_GRID.items():
            local_best_val = best_params[param_name]
            local_best_obj = best_obj_pnl
            local_best_total = best_total_pnl
            print(f"\noptimizing {param_name}")
            for v in values:
                trial = deepcopy(best_params)
                trial[param_name] = v
                obj_pnl, total_pnl = run_backtest_on_temp(trial)
                print(f"  {param_name}={v} -> {OBJECTIVE_SYMBOL}={obj_pnl:.0f}, total={total_pnl:.0f}")
                if obj_pnl > local_best_obj:
                    local_best_obj = obj_pnl
                    local_best_total = total_pnl
                    local_best_val = v
            if local_best_obj > best_obj_pnl:
                best_obj_pnl = local_best_obj
                best_total_pnl = local_best_total
                best_params[param_name] = local_best_val
                improved_any = True
                print(
                    f"  [improved] {param_name}={local_best_val}, "
                    f"best {OBJECTIVE_SYMBOL}={best_obj_pnl:.0f}, total={best_total_pnl:.0f}"
                )
            else:
                print(f"  [no change] keep {param_name}={best_params[param_name]}")

        if not improved_any:
            print("No further improvement in this pass, stopping early.")
            break

    return best_params, best_obj_pnl


def joint_grid_refine(initial_params: dict, initial_pnl: float) -> tuple[dict, float]:
    if not JOINT_PARAM_GRID:
        return initial_params, initial_pnl

    keys = list(JOINT_PARAM_GRID.keys())
    value_lists = [JOINT_PARAM_GRID[k] for k in keys]
    total_combos = 1
    for vals in value_lists:
        total_combos *= len(vals)

    best_params = deepcopy(initial_params)
    best_pnl = initial_pnl

    print(f"\n=== joint grid refine ({total_combos} combos) ===")
    for idx, combo in enumerate(product(*value_lists), start=1):
        trial = deepcopy(initial_params)
        for k, v in zip(keys, combo):
            trial[k] = v

        pnl, _ = run_backtest_on_temp(trial)
        if idx % 25 == 0 or idx == 1 or idx == total_combos:
            print(f"  combo {idx}/{total_combos} -> pnl={pnl:.0f}")

        if pnl > best_pnl:
            best_pnl = pnl
            best_params = trial
            print(f"  [joint improved] combo {idx}/{total_combos}, best_pnl={best_pnl:.0f}")

    return best_params, best_pnl


def main():
    baseline_obj, baseline_total = run_backtest_on_strategy(STRATEGY)
    print(f"[strategy baseline] {OBJECTIVE_SYMBOL}={baseline_obj:.0f}, total={baseline_total:.0f}")

    # Read current defaults from source quickly by regex
    src = STRATEGY.read_text(encoding="utf-8")
    live_params = extract_live_param_names(src)

    grid_keys = set(PARAM_GRID.keys()) | set(JOINT_PARAM_GRID.keys())
    stale_grid_keys = sorted(grid_keys - live_params)
    if stale_grid_keys:
        raise ValueError(
            f"Optimizer grid has non-live params in {STRATEGY.name}: {stale_grid_keys}. "
            "Please remove them from PARAM_GRID/JOINT_PARAM_GRID."
        )

    all_param_keys = list(dict.fromkeys(list(PARAM_GRID.keys()) + list(JOINT_PARAM_GRID.keys())))
    initial = {}
    for k in all_param_keys:
        m = re.search(rf"^\s*{re.escape(k)}\s*=\s*([-+]?\d*\.?\d+)", src, flags=re.MULTILINE)
        if not m:
            raise ValueError(f"Could not find {k} in {STRATEGY}")
        initial[k] = float(m.group(1))

    best_params, best_pnl = coordinate_ascent(initial)

    if ENABLE_JOINT_GRID:
        best_params, best_pnl = joint_grid_refine(best_params, best_pnl)

    final_summary = {
        "objective_symbol": OBJECTIVE_SYMBOL,
        "best_objective_pnl": best_pnl,
        "best_params": best_params,
    }

    print("\n=== FINAL BEST ===")
    print(json.dumps(final_summary, indent=2))

    # write artifact for easy copy/apply
    out_path = BASE / "logs" / "opt_round1_best_params.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(final_summary, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")

    if APPLY_BEST_TO_STRATEGY:
        src = STRATEGY.read_text(encoding="utf-8")
        updated = set_params_in_text(src, best_params)
        STRATEGY.write_text(updated, encoding="utf-8")
        print(f"Applied best params to: {STRATEGY}")

    final_obj, final_total = run_backtest_on_strategy(STRATEGY)
    print(f"[strategy final] {OBJECTIVE_SYMBOL}={final_obj:.0f}, total={final_total:.0f}")
    print(f"[objective delta] {final_obj - baseline_obj:.0f}")
    print(f"[total delta] {final_total - baseline_total:.0f}")

    if TMP_STRATEGY.exists():
        TMP_STRATEGY.unlink()


if __name__ == "__main__":
    main()

import json
import re
import subprocess
from pathlib import Path


BASE = Path(__file__).resolve().parent
STRATEGY = BASE / "strategies" / "r2trader.py"
TMP_STRATEGY = BASE / "strategies" / "r2trader_maf_tmp.py"
OUT_LOG = BASE / "logs" / "opt_round2_maf_sweep.json"

DATA_DIR = BASE / "data"
DAYS = ["2"]

# Candidate bids for challenge submission tuning.
MAF_CANDIDATES = [0, 25, 50, 75, 100, 150, 200, 300, 500]


def set_constant(text: str, key: str, value: str) -> str:
    pattern = rf"(^\s*{re.escape(key)}\s*=\s*)(.+)$"
    out, n = re.subn(pattern, rf"\g<1>{value}", text, flags=re.MULTILINE)
    if n == 0:
        raise ValueError(f"Could not set {key} in strategy")
    return out


def parse_total_profit(output: str) -> float:
    matches = re.findall(r"Total profit:\s*([-,\d]+)", output)
    if not matches:
        return float("-inf")
    return float(matches[-1].replace(",", ""))


def run_backtest(path: Path) -> tuple[float, str]:
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
        return float("-inf"), p.stderr
    return parse_total_profit(p.stdout), p.stdout


def build_variant(maf_bid: int) -> Path:
    src = STRATEGY.read_text(encoding="utf-8")
    src = set_constant(src, "MAF_ENABLE", "True")
    src = set_constant(src, "MAF_BID", str(int(maf_bid)))
    TMP_STRATEGY.write_text(src, encoding="utf-8")
    return TMP_STRATEGY


def main() -> None:
    base_total, _ = run_backtest(STRATEGY)
    print(f"[baseline strategy] total={base_total:.0f}")

    results = []
    for i, maf in enumerate(MAF_CANDIDATES, start=1):
        variant = build_variant(maf)
        total, _ = run_backtest(variant)

        # Backtester doesn't model MAF market access winner logic.
        # We include one simple 'net_if_paid_once' metric for ranking conservatively.
        net_if_paid_once = total - maf if total != float("-inf") else float("-inf")
        row = {
            "maf_bid": int(maf),
            "backtest_total_profit": total,
            "net_if_paid_once": net_if_paid_once,
        }
        results.append(row)
        print(f"  [{i}/{len(MAF_CANDIDATES)}] maf={maf} -> total={total:.0f}, net_if_paid_once={net_if_paid_once:.0f}")

    valid = [r for r in results if r["backtest_total_profit"] != float("-inf")]
    best_backtest = max(valid, key=lambda x: x["backtest_total_profit"]) if valid else None
    best_conservative = max(valid, key=lambda x: x["net_if_paid_once"]) if valid else None

    summary = {
        "strategy": str(STRATEGY),
        "data_dir": str(DATA_DIR),
        "days": DAYS,
        "baseline_total_profit": base_total,
        "results": results,
        "best_by_backtest_total": best_backtest,
        "best_by_conservative_net_if_paid_once": best_conservative,
        "note": "Prosperity backtester does not simulate MAF contract win logic or extra 25% quotes.",
    }

    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_LOG.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[saved] {OUT_LOG}")


if __name__ == "__main__":
    main()

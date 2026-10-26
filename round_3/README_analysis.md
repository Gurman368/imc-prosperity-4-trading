# Round 3 Continuous 3-Day Analysis

This analysis script stitches Round 3 price data (`day 0,1,2`) into one continuous timeline and produces graphs for:

- `HYDROGEL_PACK`
- `VELVETFRUIT_EXTRACT`
- all `VEV_*` vouchers

## Script

- `round_3/analysis_round3.py`

## Outputs

Written to `round_3/analysis_outputs/`:

- `continuous_underlyings.png`
- `continuous_vev_all.png`
- `vev_valuation_stats.csv`
- `vev_valuation_sample.csv`

## Run

```powershell
c:/Users/rajy7/OneDrive/Documents/GitHub/Imc_prosperity4_ISI_BSDS/backtest/venv/Scripts/python.exe round_3/analysis_round3.py
```

## Notes for strategy design

- Use `continuous_underlyings.png` to inspect 3-day drift/regime shifts.
- Use `continuous_vev_all.png` to inspect strike-wise voucher dynamics.
- Use `vev_valuation_stats.csv` to identify persistent rich/cheap time-value behavior by strike.

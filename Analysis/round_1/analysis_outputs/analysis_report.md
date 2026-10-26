# Advanced Round 1 Analysis Report

## Expected Function (Trend) by Product

- **ASH_COATED_OSMIUM [OLS]**: `mid_price(t) = 9980.170019 + (0.00000740) * t + noise`  
  - R² = 0.000028, slope stderr = 0.000008
- **ASH_COATED_OSMIUM [Theil-Sen]**: `mid_price(t) = 10000.500000 + (0.00000000) * t + robust_noise`  
  - R² = -0.001695, slope stderr = 403.858624
- **INTARIAN_PEPPER_ROOT [OLS]**: `mid_price(t) = 10972.164168 + (0.00101415) * t + noise`  
  - R² = 0.086892, slope stderr = 0.000019
- **INTARIAN_PEPPER_ROOT [Theil-Sen]**: `mid_price(t) = 10997.550000 + (0.00100000) * t + robust_noise`  
  - R² = 0.086535, slope stderr = 949.047663

## Microstructure Regression (next return ~ OBI + spread + depth + signed flow)

- **ASH_COATED_OSMIUM** samples=27643, R²=0.000107, β_obi=0.000002, β_spread=0.000031, β_depth=-0.000022, β_signed_flow=-0.000097
- **INTARIAN_PEPPER_ROOT** samples=27687, R²=0.000228, β_obi=0.001192, β_spread=0.000104, β_depth=0.000007, β_signed_flow=-0.000287
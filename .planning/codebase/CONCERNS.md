# Concerns

## Critical Issues

### Backtester Position Limit Mismatch
- **File:** `backtest.py` line 221
- **Issue:** Hardcoded `limit = 20` (Round 0 limit). Round 1 products have `limit = 80`.
- **Impact:** Backtesting `round1.py` strategies against Round 1 data will produce incorrect results — fills get rejected at 20 instead of 80.
- **Fix:** Read limit from `Trader.LIMITS` dict dynamically.

### Data Path Hardcoding
- **File:** `backtest.py` lines 359-360, `analyze.py` lines 23, 111, 120, 160-161
- **Issue:** Hardcoded paths to `Data/prices_round_0_day_*.csv` — won't work for Round 1 data in `historical_data/`.
- **Impact:** Cannot backtest Round 1 without editing file paths manually.
- **Fix:** Parameterize data directory and round number.

## Technical Debt

### No Strategy Versioning
- Strategies are edited in-place (`trader.py`). Previous versions only preserved by submission snapshots (e.g., `187824/`).
- Version comments in docstrings ("v9", "from v8 log analysis") but no git tagging or branching per version.

### Duplicate Code Patterns
- `_aco()` and `_emeralds()` are nearly identical (same mean-reversion strategy, different product names and limits).
- Phase 1/2/3 taking + market making + backstop pattern repeated across all 4 strategy methods.
- Opportunity: Extract common market-making framework, parameterize per product.

### traderData Size Management
- Manual truncation check (`if len(traderData) > 45000`) with hardcoded key whitelist.
- Fragile — adding new state keys requires updating the truncation logic.

## Performance Concerns

### EMA Warmup Period
- Both `_ipr()` and `_tomatoes()` use fast warmup (`alpha = 0.5`) for first 5 iterations, then switch to slow tracking.
- During warmup, fair value estimates are noisy, which could cause suboptimal trades in the first few hundred timestamps.

### Emergency Flatten Threshold
- `_tomatoes()` triggers emergency flatten at `abs_pos >= 10` (50% of limit), which is quite aggressive.
- May cause unnecessary selling in trending markets.

## Security

- No secrets or credentials in codebase (competition platform handles auth via web upload)
- No network calls or external data access in submitted code
- `traderData` is visible to the competition platform — don't store anything sensitive

## Missing Features

- No multi-product correlation analysis (e.g., pairs trading, statistical arbitrage)
- No conversion request logic (the `conversions` return value is always `0`)
- No order flow / market trades analysis in live strategy (only used in offline analysis)
- No adaptive parameter tuning (all parameters are static constants)

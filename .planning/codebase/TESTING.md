# Testing

## Framework

- **No formal test framework** — no pytest, unittest, or test directory
- Testing is done via backtesting against historical data

## Backtesting Infrastructure (`backtest.py`)

### Approach
- Loads historical price CSV snapshots
- Creates mock `datamodel` classes (`Order`, `OrderDepth`, `TradingState`) via `sys.modules` injection
- Dynamically imports `trader.py` via `importlib`
- Simulates order fills with two models:
  - **Aggressive fills:** Orders that cross the spread (deterministic)
  - **Passive fills:** Probability-based fill rates by distance from best price

### Fill Rate Model
| Distance from best | Fill rate |
|---------------------|-----------|
| ≤ 1 tick | 35% |
| ≤ 3 ticks | 18% |
| ≤ 5 ticks | 10% |
| > 5 ticks | 4% |

### Metrics Tracked
- Mark-to-market PnL per iteration
- Max drawdown
- Position ranges (min/max per product)
- Aggressive vs passive fill counts
- PnL progression at 25/50/75/100% quartiles

### Output
- Console summary
- JSON log files in `logs/` directory with detailed iteration data (every 100th + first 10)

## Analysis Tools

### `analyze.py`
- Standalone market data analysis for price/trade CSV files
- Computes: mid prices, spreads, volatility (tick returns), order book depth, PnL
- Price distribution analysis (rounded frequency counts)
- Buyer/seller participant analysis from trade data

### `log_analyzer.py`
- Reads backtest JSON logs from `logs/` directory
- Aggregates: fill type analysis, PnL statistics, combined summary
- Saves `summary_report.json`

## Testing Gaps

- ⚠ No unit tests for individual strategy components
- ⚠ Backtester hardcodes `limit = 20` (Round 0) — won't work for Round 1 (`limit = 80`)
- ⚠ No automated regression testing between strategy versions
- ⚠ Fill simulation is approximate — real exchange behavior may differ
- ⚠ No CI/CD pipeline

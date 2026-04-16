# Integrations

## External Services

### IMC Prosperity 4 Exchange Platform
- **Type:** Competition trading platform
- **Interaction:** Upload Python `Trader` class → runs in AWS Lambda sandbox
- **Data flow:** Platform calls `Trader.run(TradingState)` → returns `(orders_dict, conversions, traderData)`
- **Constraints:**
  - `traderData` max 50,000 characters
  - Stateless Lambda — no global/class variable persistence between calls
  - Position limits enforced by exchange (orders rejected if aggregate would exceed limits)
  - 1,000 iterations during testing, 10,000 for final simulation

### AWS Lambda
- **Type:** Execution runtime (managed by IMC)
- **Impact:** No file I/O, no network calls, no external libraries in submitted code
- **State:** Must serialize all persistent state to `traderData` string

## Data Sources

### Historical Market Data
- Location: `historical_data/` directory
- Content: Round 1 price snapshots and trade records (days -2, -1, 0)
- Format: Semicolon-delimited CSV
- Products: ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT (Round 1)

### Round 0 Data
- Location: `Data/` directory (referenced in code, may not be in repo)
- Products: EMERALDS, TOMATOES (Round 0)

### Submission Logs
- Location: `187824/` directory
- Content: JSON result data + plain text logs from previous submissions
- Used for: Post-hoc analysis and strategy tuning

## APIs

- No external APIs — all interaction is through the competition's `datamodel` interface
- `OrderDepth.buy_orders` / `OrderDepth.sell_orders` — order book access
- `TradingState.position` — current position tracking
- `TradingState.own_trades` / `TradingState.market_trades` — trade history

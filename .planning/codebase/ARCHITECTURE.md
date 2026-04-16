# Architecture

## Pattern

**Single-class algorithmic trader** — one `Trader` class per round with product-specific strategy methods dispatched from a central `run()` entry point.

## Layers

1. **Entry Point** (`run()` method) — Deserializes `traderData`, dispatches to product-specific strategy methods, serializes state back
2. **Strategy Methods** (e.g., `_aco()`, `_ipr()`, `_emeralds()`, `_tomatoes()`) — Self-contained per-product trading logic
3. **Order Generation** — Each strategy follows a consistent 3-5 phase pattern:
   - Phase 1: Aggressive taking (cross the spread to fill immediately)
   - Phase 2: Passive market making (post resting orders at calculated prices)
   - Phase 3: Deep layer (wider backstop quotes)
   - Phase 4: Emergency flatten (position management when over threshold)
   - Phase 5: Backstop (catch-all remaining capacity)

## Data Flow

```
TradingState → run() → per-product dispatch → strategy method → Order[]
                ↓                                     ↑
          deserialize traderData              serialize traderData
```

- `traderData` carries EMA values, base estimates, iteration counters between calls
- Each product method receives: `order_depth`, `position`, `limit`, `saved_state`, optionally `timestamp`
- Output: list of `Order` objects per product

## Key Abstractions

### Fair Value Estimation
- **ACO/EMERALDS:** Fixed fair value (10000) — mean-reverting product
- **IPR:** Linear trend model `fair = base_ema + 0.001 * timestamp` — trend-following
- **TOMATOES:** Blended signal: `0.45 * microprice + 0.30 * book_vwap + 0.25 * mid` with dual EMA

### Inventory Management
- Position-dependent skew: `skew = pos / limit`
- Inventory shift adjusts quote prices toward unwinding direction
- Sizing multipliers reduce exposure on the side closer to position limits
- Emergency flatten logic triggers at configurable inventory thresholds

### Edge Calculation
- Buy/sell edge thresholds vary by current position level
- Long-biased products (IPR) have asymmetric edges (aggressive buying, conservative selling)
- Market-neutral products (ACO/EMERALDS) have symmetric edges

## Entry Points

- `trader.py` → Round 0 (EMERALDS, TOMATOES) — **primary submission file**
- `round1.py` → Round 1 (ASH_COATED_OSMIUM, INTARIAN_PEPPER_ROOT)
- `backtest.py` → Local backtesting harness
- `analyze.py` → Market data analysis (standalone script)
- `log_analyzer.py` → Backtest log analysis

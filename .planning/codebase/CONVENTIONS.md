# Conventions

## Code Style

- **Python 3** with type hints on method signatures (e.g., `-> List[Order]`)
- No linter/formatter config files present (no `.flake8`, `pyproject.toml`, `ruff.toml`)
- `.ruff_cache/` in `.gitignore` suggests Ruff may be used occasionally
- Standard PEP 8 loosely followed
- Lines typically under 100 characters
- No docstring convention enforced, but strategy methods have detailed block comments

## Naming

- **Classes:** PascalCase (`Trader`, `OrderDepth`, `TradingState`)
- **Methods:** snake_case with leading underscore for private strategy methods (`_aco()`, `_ipr()`)
- **Variables:** snake_case (`buy_cap`, `sell_cap`, `best_bid`, `best_ask`)
- **Constants:** UPPER_CASE (`LIMITS`, `F = 10000`)
- **Products:** ALL_CAPS_SNAKE_CASE strings (`"ASH_COATED_OSMIUM"`)
- **Single-letter aliases:** `P` for product name, `F` for fair value, `od` for order depth — used within strategy methods for brevity

## Patterns

### Strategy Method Structure
Every product strategy follows the same multi-phase pattern:
```python
def _product(self, od, pos, lim, saved, ...) -> List[Order]:
    orders = []
    # Phase 1: Aggressive take (cross spread)
    # Phase 2: Passive market making (resting orders)
    # Phase 3: Deep layer / backstop
    # Phase 4: Emergency flatten (optional)
    return orders
```

### State Management
```python
# Deserialize at start of run()
saved = json.loads(state.traderData) if state.traderData else {}
# Each strategy reads/writes to saved dict
saved["key"] = value
# Serialize at end of run()
traderData = json.dumps(saved)
# Truncation safety check
if len(traderData) > 45000:
    traderData = json.dumps({...minimal keys...})
```

### Position Capacity Tracking
```python
buy_cap = lim - pos   # remaining buy capacity
sell_cap = lim + pos   # remaining sell capacity
# Decrement as orders placed
buy_cap -= vol
```

## Error Handling

- Minimal — bare `except: pass` blocks for JSON parsing and float conversion
- No logging framework — ad-hoc `print()` statements (visible in Lambda logs)
- No exception classes or custom error types
- Defensive coding via `if not od.buy_orders and not od.sell_orders: return orders`

## Comments

- Extensive inline comments explaining strategy rationale
- Multi-line docstrings on strategy methods with mathematical models
- Section headers using `# ======= PHASE N: DESCRIPTION =======` pattern
- Parameters documented with tuning history (e.g., "was 2 in v8")

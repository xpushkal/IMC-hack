# Stack

## Language & Runtime

- **Python 3.14** (via Homebrew, `.venv` virtualenv)
- System Python 3.9.6 also available but not used for project

## Framework

- **IMC Prosperity 4 Exchange Simulator** — proprietary competition platform
- Execution runtime: AWS Lambda (stateless, string-based state persistence via `traderData`)
- `datamodel` module provided by competition (not pip-installable) — contains `OrderDepth`, `TradingState`, `Order`, `Trade`, `Listing`, `Observation`

## Dependencies

- **Standard library only** — `json`, `math`, `csv`, `collections`, `importlib`, `os`, `datetime`
- No third-party packages in trader code (competition constraint — Lambda sandbox)
- Analysis scripts use only stdlib

## Configuration

- No config files — all parameters are hardcoded constants in trader classes
- Position limits defined per product as class-level dictionaries
- Fair values and strategy parameters embedded inline
- `traderData` string (max 50,000 chars) used for inter-iteration state persistence via JSON serialization

## Data Format

- Market data: semicolon-delimited CSV files with order book snapshots (3 levels of depth)
- Trade data: semicolon-delimited CSV with buyer/seller/price/quantity
- Files organized as `prices_round_{N}_day_{D}.csv` and `trades_round_{N}_day_{D}.csv`
- Submission logs: JSON + plain text log files (e.g., `187824/`)

## Build & Run

- No build step — pure Python scripts
- `backtest.py` loads `trader.py` via `importlib` and mocks the `datamodel` module
- `analyze.py` runs standalone for market data analysis
- Submission: upload single `.py` file to IMC Prosperity platform

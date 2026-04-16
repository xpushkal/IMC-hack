# Structure

## Directory Layout

```
IMC-hack/
├── trader.py              # Round 0 submission (EMERALDS, TOMATOES)
├── round1.py              # Round 1 submission (ACO, IPR)
├── backtest.py            # Local backtesting harness
├── analyze.py             # Market data analysis script
├── log_analyzer.py        # Backtest log analyzer
├── README.md              # Project readme (minimal)
├── .gitignore             # Git ignore rules
├── .venv/                 # Python 3.14 virtualenv
├── Docs/
│   ├── do.txt             # IMC Prosperity competition documentation
│   ├── new.txt            # Additional notes
│   └── *.pdf              # OOP reference material
├── historical_data/       # Round 1 market data
│   ├── prices_round_1_day_-2.csv
│   ├── prices_round_1_day_-1.csv
│   ├── prices_round_1_day_0.csv
│   ├── trades_round_1_day_-2.csv
│   ├── trades_round_1_day_-1.csv
│   └── trades_round_1_day_0.csv
├── DATA CAPSUEL/          # Additional data (Round 1 copy)
├── 187824/                # Submission logs
│   ├── 187824.py          # Submitted code snapshot
│   ├── 187824.json        # Submission result data
│   └── 187824.log         # Submission execution log
├── .planning/             # GSD planning directory
│   └── codebase/          # This mapping
├── wiki/                  # Wiki-brain knowledge base
├── raw/                   # Wiki-brain source files
├── graphify-out/          # Graphify knowledge graph output
└── log.md                 # Wiki-brain session log
```

## Key Locations

| What | Where |
|------|-------|
| Active Round 0 strategy | `trader.py` |
| Active Round 1 strategy | `round1.py` |
| Backtester | `backtest.py` |
| Market data analyzer | `analyze.py` |
| Competition documentation | `Docs/do.txt` |
| Round 1 historical data | `historical_data/` |
| Previous submission | `187824/` |

## Naming Conventions

- **Trader files:** `trader.py` (generic), `round1.py` (round-specific)
- **Products:** ALL_CAPS_SNAKE_CASE (e.g., `ASH_COATED_OSMIUM`, `INTARIAN_PEPPER_ROOT`)
- **Strategy methods:** `_product_abbreviation()` (e.g., `_aco()`, `_ipr()`, `_emeralds()`, `_tomatoes()`)
- **Data files:** `{type}_round_{N}_day_{D}.csv` (semicolon-delimited)
- **Submission dirs:** numeric ID (e.g., `187824/`)

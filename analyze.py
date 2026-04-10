import csv
import json
from collections import defaultdict


def load_prices(filename):
    with open(filename, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        return list(reader)


def load_trades(filename):
    with open(filename, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        return list(reader)


# === PRICE DATA ANALYSIS ===
print("=" * 80)
print("PRICE DATA ANALYSIS")
print("=" * 80)

for day_file in ["Data/prices_round_0_day_-2.csv", "Data/prices_round_0_day_-1.csv"]:
    rows = load_prices(day_file)
    print(f"\n--- {day_file} ---")
    print(f"Columns: {list(rows[0].keys())}")
    print(f"Total rows: {len(rows)}")

    products = set(r.get("product", "") for r in rows)
    print(f"Products: {products}")

    for product in sorted(products):
        prod_rows = [r for r in rows if r.get("product") == product]
        print(f"\n  Product: {product}")
        print(f"  Rows: {len(prod_rows)}")

        # Extract mid prices
        mid_prices = []
        bid_prices = []
        ask_prices = []
        spreads = []
        timestamps = []

        for r in prod_rows:
            try:
                bid_1 = float(r.get("bid_price_1", "0") or "0")
                ask_1 = float(r.get("ask_price_1", "0") or "0")
                if bid_1 > 0 and ask_1 > 0:
                    mid = (bid_1 + ask_1) / 2
                    mid_prices.append(mid)
                    bid_prices.append(bid_1)
                    ask_prices.append(ask_1)
                    spreads.append(ask_1 - bid_1)
                    timestamps.append(int(r.get("timestamp", 0)))
            except:
                pass

        if mid_prices:
            print(
                f"  Mid Price - Min: {min(mid_prices):.2f}, Max: {max(mid_prices):.2f}, "
                f"Mean: {sum(mid_prices) / len(mid_prices):.2f}"
            )
            print(
                f"  Best Bid - Min: {min(bid_prices):.2f}, Max: {max(bid_prices):.2f}, "
                f"Mean: {sum(bid_prices) / len(bid_prices):.2f}"
            )
            print(
                f"  Best Ask - Min: {min(ask_prices):.2f}, Max: {max(ask_prices):.2f}, "
                f"Mean: {sum(ask_prices) / len(ask_prices):.2f}"
            )
            print(
                f"  Spread   - Min: {min(spreads):.2f}, Max: {max(spreads):.2f}, "
                f"Mean: {sum(spreads) / len(spreads):.2f}"
            )

            # Volatility
            returns = [
                (mid_prices[i] - mid_prices[i - 1]) for i in range(1, len(mid_prices))
            ]
            if returns:
                mean_ret = sum(returns) / len(returns)
                var_ret = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                std_ret = var_ret**0.5
                print(f"  Tick Returns - Mean: {mean_ret:.4f}, Std: {std_ret:.4f}")

            # Look at order book depth
            try:
                bid_vol_1 = [
                    abs(float(r.get("bid_volume_1", "0") or "0")) for r in prod_rows
                ]
                ask_vol_1 = [
                    abs(float(r.get("ask_volume_1", "0") or "0")) for r in prod_rows
                ]
                print(f"  Bid Vol L1 - Mean: {sum(bid_vol_1) / len(bid_vol_1):.2f}")
                print(f"  Ask Vol L1 - Mean: {sum(ask_vol_1) / len(ask_vol_1):.2f}")
            except:
                pass

            # Profit and loss column
            try:
                pnls = [float(r.get("profit_and_loss", "0") or "0") for r in prod_rows]
                if any(p != 0 for p in pnls):
                    print(
                        f"  PnL - Min: {min(pnls):.2f}, Max: {max(pnls):.2f}, Final: {pnls[-1]:.2f}"
                    )
            except:
                pass

# Print sample row to see all columns
print(f"\n\nSample row (first price entry):")
sample_rows = load_prices("Data/prices_round_0_day_-1.csv")
for k, v in sample_rows[0].items():
    print(f"  {k}: {v}")

# === TRADE DATA ANALYSIS ===
print("\n" + "=" * 80)
print("TRADE DATA ANALYSIS")
print("=" * 80)

for day_file in ["Data/trades_round_0_day_-2.csv", "Data/trades_round_0_day_-1.csv"]:
    trades = load_trades(day_file)
    print(f"\n--- {day_file} ---")
    print(f"Total trades: {len(trades)}")
    print(f"Columns: {list(trades[0].keys())}")

    products = set(t.get("symbol", "") for t in trades)
    for product in sorted(products):
        prod_trades = [t for t in trades if t.get("symbol") == product]
        prices = [float(t.get("price", 0)) for t in prod_trades]
        quantities = [float(t.get("quantity", 0)) for t in prod_trades]

        # Who is buying/selling
        buyers = defaultdict(int)
        sellers = defaultdict(int)
        for t in prod_trades:
            buyers[t.get("buyer", "unknown")] += 1
            sellers[t.get("seller", "unknown")] += 1

        print(f"\n  Product: {product}")
        print(f"  Trades: {len(prod_trades)}")
        print(
            f"  Price - Min: {min(prices):.2f}, Max: {max(prices):.2f}, Mean: {sum(prices) / len(prices):.2f}"
        )
        print(
            f"  Qty - Min: {min(quantities):.2f}, Max: {max(quantities):.2f}, Mean: {sum(quantities) / len(quantities):.2f}"
        )
        print(f"  Buyers: {dict(buyers)}")
        print(f"  Sellers: {dict(sellers)}")

    # Print sample trade
    print(f"\n  Sample trade:")
    for k, v in trades[0].items():
        print(f"    {k}: {v}")

# === EMERALD PRICE STABILITY ANALYSIS ===
print("\n" + "=" * 80)
print("EMERALD DETAILED ANALYSIS")
print("=" * 80)

rows = load_prices("Data/prices_round_0_day_-1.csv")
emerald_rows = [r for r in rows if r.get("product") == "RAINFOREST_RESIN"]
if not emerald_rows:
    emerald_rows = [
        r
        for r in rows
        if "EMERALD" in r.get("product", "").upper()
        or "RESIN" in r.get("product", "").upper()
    ]

# Try all products
all_products = set(r.get("product", "") for r in rows)
print(f"All available products: {all_products}")

for product in all_products:
    prod_rows = [r for r in rows if r.get("product") == product]

    # Check price distribution around round numbers
    mid_prices = []
    for r in prod_rows:
        try:
            bid = float(r.get("bid_price_1", "0") or "0")
            ask = float(r.get("ask_price_1", "0") or "0")
            if bid > 0 and ask > 0:
                mid_prices.append((bid + ask) / 2)
        except:
            pass

    if mid_prices:
        from collections import Counter

        rounded = Counter(round(p) for p in mid_prices)
        print(f"\n  {product} - Price distribution (top 10 rounded values):")
        for price, count in sorted(rounded.items(), key=lambda x: -x[1])[:10]:
            print(
                f"    {price}: {count} occurrences ({count / len(mid_prices) * 100:.1f}%)"
            )

import json
import csv
from io import StringIO
from collections import defaultdict

print("=" * 70)
print("COMPARING ALL SUBMISSIONS - PRODUCT-LEVEL PNL")
print("=" * 70)

for sub_id in ["48270", "48341", "60069", "65145", "65175"]:
    with open(f"logs/extracted/{sub_id}/{sub_id}.json", "r") as f:
        data = json.load(f)

    activities = data["activitiesLog"]
    reader = csv.DictReader(StringIO(activities), delimiter=";")
    rows = list(reader)

    # Get final PnL per product
    last_by_product = {}
    for r in rows:
        product = r["product"]
        last_by_product[product] = r

    total_pnl = data["profit"]
    print(f"\n{sub_id} (Total PnL={total_pnl:.2f}):")
    for product, r in sorted(last_by_product.items()):
        pnl = float(r.get("profit_and_loss", 0))
        print(f"  {product}: final PnL = {pnl:.2f}")

    # Graph log analysis - PnL curve
    graph = data["graphLog"]
    graph_reader = csv.DictReader(StringIO(graph), delimiter=";")
    graph_rows = list(graph_reader)

    if graph_rows:
        max_pnl = 0
        min_pnl = float("inf")
        max_dd = 0
        peak = 0

        for r in graph_rows:
            val = float(r["value"])
            max_pnl = max(max_pnl, val)
            min_pnl = min(min_pnl, val)
            peak = max(peak, val)
            dd = peak - val
            max_dd = max(max_dd, dd)

        print(f"  Max PnL: {max_pnl:.1f}, Min PnL: {min_pnl:.1f}, Max DD: {max_dd:.1f}")

# Analyze the trader code from the BEST submission
print("\n\n" + "=" * 70)
print("BEST SUBMISSION (48341) - TRADER CODE (first 120 lines)")
print("=" * 70)

with open("logs/extracted/48341/48341.py", "r") as f:
    code = f.read()
lines = code.split("\n")
for i, line in enumerate(lines[:120]):
    print(f"  {i+1}: {line}")

print(f"\n... ({len(lines)} total lines)")

# Also show latest submission code
print("\n\n" + "=" * 70)
print("LATEST SUBMISSION (65175) - TRADER CODE (first 120 lines)")
print("=" * 70)

with open("logs/extracted/65175/65175.py", "r") as f:
    code = f.read()
lines = code.split("\n")
for i, line in enumerate(lines[:120]):
    print(f"  {i+1}: {line}")

print(f"\n... ({len(lines)} total lines)")

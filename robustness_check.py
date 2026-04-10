"""
Robustness check: verify the v11 trader handles edge cases correctly.
Also compare with real submission PnL ratios.
"""
import json
import csv
from io import StringIO

print("=" * 60)
print("REAL SUBMISSION PNL vs BACKTEST PNL CALIBRATION")
print("=" * 60)

# Real PnL from submissions
real_pnl = {
    "48270": 817.58,
    "48341": 1474.86,  # best
    "60069": 540.29,
    "65145": 540.29,
    "65175": 802.14,
}

# Backtest PnL (from compare_versions.py)
backtest_pnl = {
    "48341_v5": 2217586,
    "65175_v9": 1109601,
    "v11": 2678755,
}

print(f"\nCalibration ratios (real/backtest):")
print(f"  v5  (48341): real={real_pnl['48341']:.0f}, bt={backtest_pnl['48341_v5']:.0f}")
ratio_v5 = real_pnl["48341"] / backtest_pnl["48341_v5"]
print(f"    ratio = {ratio_v5:.6f}")

print(f"  v9  (65175): real={real_pnl['65175']:.0f}, bt={backtest_pnl['65175_v9']:.0f}")
ratio_v9 = real_pnl["65175"] / backtest_pnl["65175_v9"]
print(f"    ratio = {ratio_v9:.6f}")

avg_ratio = (ratio_v5 + ratio_v9) / 2
print(f"\n  Average calibration ratio: {avg_ratio:.6f}")
print(f"\n  V11 backtest: {backtest_pnl['v11']:.0f}")
print(f"  V11 estimated real PnL: {backtest_pnl['v11'] * avg_ratio:.0f}")
print(f"  V11 vs V5 real improvement: {(backtest_pnl['v11'] * avg_ratio - real_pnl['48341']) / real_pnl['48341'] * 100:+.1f}%")

# Check PnL breakdown by product for best submission
print("\n\n" + "=" * 60)
print("V5 PRODUCT BREAKDOWN (from real submission)")
print("=" * 60)

with open("logs/extracted/48341/48341.json", "r") as f:
    data = json.load(f)

activities = data["activitiesLog"]
reader = csv.DictReader(StringIO(activities), delimiter=";")
rows = list(reader)

last_by_product = {}
for r in rows:
    last_by_product[r["product"]] = float(r.get("profit_and_loss", 0))

for prod, pnl in sorted(last_by_product.items()):
    print(f"  {prod}: {pnl:.2f}")

total_product_pnl = sum(last_by_product.values())
print(f"  Sum: {total_product_pnl:.2f} (reported: {data['profit']:.2f})")

print("\n\n" + "=" * 60)
print("STRATEGY SUMMARY FOR SUBMISSION")
print("=" * 60)
print("""
V11 Key Parameters:
  EMERALDS:
    - Fair value: 10000 (fixed)
    - Aggressive take: sweep all asks < 10000, bids > 10000
    - At-fair take: if short (buy), if long (sell), up to |pos|+5
    - Passive levels: 6 bid + 6 ask, spaced 2 ticks apart
      Bids: 9999, 9997, 9995, 9993, 9991, 9989
      Asks: 10001, 10003, 10005, 10007, 10009, 10011
    - Inventory shift: skew * 3 ticks
    - Backstop: F-13 / F+13

  TOMATOES:
    - Fair value: EMA(alpha=0.12) + imbalance * 1.5
    - No trend following (data shows negative edge)
    - Aggressive take: edge >= 0.5 from fair
    - Passive levels: 5 bid + 5 ask
      Offsets from fair: 1, 3, 5, 8, 11 ticks
    - Inventory offset: skew * 2.0 ticks
    - Emergency flatten at |pos| >= 16 (hit BBO to reduce)
    - Backstop: fair-15 / fair+15
""")

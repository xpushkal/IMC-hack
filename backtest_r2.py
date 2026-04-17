"""
Round 2 Backtester — adapted from backtest_r1.py
- Imports round1.py (same products: ACO + IPR)
- Position limit = 80
- Uses ROUND_2/ CSVs
"""

import csv
import json
import math
import os
import sys
from collections import defaultdict


# ---- Minimal datamodel stubs ----
class Order:
    def __init__(self, symbol, price, quantity):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

    def __repr__(self):
        return f"Order({self.symbol}, p={self.price}, q={self.quantity})"


class OrderDepth:
    def __init__(self):
        self.buy_orders = {}
        self.sell_orders = {}


class TradingState:
    def __init__(self):
        self.traderData = ""
        self.timestamp = 0
        self.order_depths = {}
        self.position = {}
        self.own_trades = {}
        self.market_trades = {}
        self.observations = {}
        self.listings = {}


# ---- Import trader module ----
import importlib.util

sys.modules["datamodel"] = type(sys)("datamodel")
sys.modules["datamodel"].OrderDepth = OrderDepth
sys.modules["datamodel"].TradingState = TradingState
sys.modules["datamodel"].Order = Order
sys.modules["datamodel"].UserId = str

# Use round1.py as the trader (same products ACO + IPR)
trader_file = sys.argv[1] if len(sys.argv) > 1 else "round1.py"
spec = importlib.util.spec_from_file_location("trader_module", trader_file)
trader_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trader_mod)
Trader = trader_mod.Trader


def load_snapshots(filename):
    with open(filename, "r") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)

    timestamps = defaultdict(dict)
    for r in rows:
        ts = int(r["timestamp"])
        product = r["product"]
        od = OrderDepth()

        for level in [1, 2, 3]:
            bp = r.get(f"bid_price_{level}", "")
            bv = r.get(f"bid_volume_{level}", "")
            ap = r.get(f"ask_price_{level}", "")
            av = r.get(f"ask_volume_{level}", "")
            if bp and bv:
                od.buy_orders[int(float(bp))] = int(float(bv))
            if ap and av:
                od.sell_orders[int(float(ap))] = -abs(int(float(av)))

        timestamps[ts][product] = od

    return dict(sorted(timestamps.items()))


def simulate_fills(orders, order_depth, position, limit):
    fills = []
    aggressive_count = 0
    passive_count = 0

    for order in orders:
        if order.quantity > 0:
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price <= order.price and order.quantity > 0:
                    available = -order_depth.sell_orders[ask_price]
                    fill_qty = min(order.quantity, available)
                    fills.append((order.symbol, ask_price, fill_qty, "aggressive"))
                    aggressive_count += fill_qty
                    order.quantity -= fill_qty
                else:
                    break

            if order.quantity > 0:
                best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
                if best_ask is not None:
                    distance = best_ask - order.price
                    if distance <= 1:
                        fill_rate = 0.35
                    elif distance <= 3:
                        fill_rate = 0.18
                    elif distance <= 5:
                        fill_rate = 0.10
                    else:
                        fill_rate = 0.04
                    passive_fill = max(1, int(order.quantity * fill_rate))
                    fills.append((order.symbol, order.price, passive_fill, "passive"))
                    passive_count += passive_fill

        elif order.quantity < 0:
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price >= order.price and order.quantity < 0:
                    available = order_depth.buy_orders[bid_price]
                    fill_qty = min(-order.quantity, available)
                    fills.append((order.symbol, bid_price, -fill_qty, "aggressive"))
                    aggressive_count += fill_qty
                    order.quantity += fill_qty
                else:
                    break

            if order.quantity < 0:
                best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
                if best_bid is not None:
                    distance = order.price - best_bid
                    if distance <= 1:
                        fill_rate = 0.35
                    elif distance <= 3:
                        fill_rate = 0.18
                    elif distance <= 5:
                        fill_rate = 0.10
                    else:
                        fill_rate = 0.04
                    passive_fill = max(1, int(-order.quantity * fill_rate))
                    fills.append((order.symbol, order.price, -passive_fill, "passive"))
                    passive_count += passive_fill

    return fills, aggressive_count, passive_count


def run_backtest(price_file, log_file=None):
    print(f"\n{'='*70}")
    print(f"BACKTESTING: {price_file}")
    print(f"{'='*70}")

    snapshots = load_snapshots(price_file)
    trader = Trader()
    trader_data = ""

    products = set()
    for ts_data in snapshots.values():
        products.update(ts_data.keys())

    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    positions = defaultdict(int)
    cash = 0
    total_trades = 0
    pnl_series = []
    trade_count = defaultdict(int)
    aggressive_fills = defaultdict(int)
    passive_fills = defaultdict(int)
    max_pos = defaultdict(int)
    min_pos = defaultdict(int)
    product_cash = defaultdict(float)

    iteration_count = 0

    for ts in sorted(snapshots.keys()):
        iteration_count += 1

        state = TradingState()
        state.traderData = trader_data
        state.timestamp = ts
        state.order_depths = snapshots[ts]
        state.position = dict(positions)

        result_orders, conversions, trader_data = trader.run(state)

        for product, prod_orders in result_orders.items():
            if product not in snapshots[ts]:
                continue

            od = snapshots[ts][product]
            limit = LIMITS.get(product, 80)

            total_buy_qty = sum(o.quantity for o in prod_orders if o.quantity > 0)
            total_sell_qty = sum(-o.quantity for o in prod_orders if o.quantity < 0)

            if positions[product] + total_buy_qty > limit:
                continue
            if positions[product] - total_sell_qty < -limit:
                continue

            fills, agg_count, pas_count = simulate_fills(
                prod_orders, od, positions[product], limit
            )

            for symbol, price, qty, fill_type in fills:
                new_pos = positions[symbol] + qty
                if abs(new_pos) > limit:
                    if qty > 0:
                        qty = max(0, limit - positions[symbol])
                    else:
                        qty = min(0, -limit - positions[symbol])
                    if qty == 0:
                        continue
                    new_pos = positions[symbol] + qty

                cash -= price * qty
                product_cash[symbol] -= price * qty
                positions[symbol] = new_pos
                total_trades += 1
                trade_count[symbol] += 1

                if fill_type == "aggressive":
                    aggressive_fills[symbol] += abs(qty)
                else:
                    passive_fills[symbol] += abs(qty)

                max_pos[symbol] = max(max_pos[symbol], positions[symbol])
                min_pos[symbol] = min(min_pos[symbol], positions[symbol])

        # Track running PnL (mark-to-market)
        running_pnl = cash
        product_pnl = {}
        for product, pos in positions.items():
            if product in snapshots[ts]:
                od = snapshots[ts][product]
                if od.buy_orders and od.sell_orders:
                    mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
                    running_pnl += pos * mid
                    product_pnl[product] = product_cash[product] + pos * mid
        pnl_series.append((ts, running_pnl))

        if iteration_count % 200 == 0 or iteration_count <= 3:
            pos_str = ", ".join(f"{p}={v}" for p, v in sorted(positions.items()))
            ppnl = ", ".join(f"{p}={v:.0f}" for p, v in sorted(product_pnl.items()))
            print(f"  t={ts:6d} | PnL={running_pnl:10.1f} | {pos_str} | {ppnl}")

    # ---- Final summary ----
    total_pnl = pnl_series[-1][1] if pnl_series else 0
    max_dd = 0
    peak = float("-inf")
    for ts, pnl in pnl_series:
        peak = max(peak, pnl)
        dd = peak - pnl
        max_dd = max(max_dd, dd)

    n = len(pnl_series)
    q25 = pnl_series[n // 4][1] if n > 4 else 0
    q50 = pnl_series[n // 2][1] if n > 2 else 0
    q75 = pnl_series[3 * n // 4][1] if n > 4 else 0

    print(f"\n{'─'*70}")
    print(f"  RESULTS: {os.path.basename(price_file)}")
    print(f"{'─'*70}")
    print(f"  Total PnL:      {total_pnl:,.1f}")
    print(f"  Max Drawdown:   {max_dd:,.1f}")
    print(f"  Total Trades:   {total_trades}")
    print(f"  Iterations:     {iteration_count}")
    print(f"  PnL @25%: {q25:,.1f} | @50%: {q50:,.1f} | @75%: {q75:,.1f} | @100%: {total_pnl:,.1f}")
    print()

    for p in sorted(products):
        ppnl = product_cash.get(p, 0) + positions[p] * (
            (max(snapshots[max(snapshots.keys())].get(p, OrderDepth()).buy_orders.keys(), default=0) +
             min(snapshots[max(snapshots.keys())].get(p, OrderDepth()).sell_orders.keys(), default=0)) / 2
            if snapshots[max(snapshots.keys())].get(p) and
               snapshots[max(snapshots.keys())][p].buy_orders and
               snapshots[max(snapshots.keys())][p].sell_orders else 0
        )
        print(f"  {p}:")
        print(f"    PnL:      {ppnl:,.1f}")
        print(f"    Trades: {trade_count[p]}, Aggressive: {aggressive_fills[p]}, Passive: {passive_fills[p]}")
        print(f"    Position range: [{min_pos[p]}, {max_pos[p]}]")
        print(f"    Final position: {positions[p]}")

    return total_pnl


# ---- Run on all Round 2 data ----
total = 0
data_dir = "ROUND_2"

files = sorted([
    os.path.join(data_dir, f) for f in os.listdir(data_dir)
    if f.startswith("prices_round_2") and f.endswith(".csv")
])

if not files:
    print("ERROR: No Round 2 price files found in ROUND_2/")
    sys.exit(1)

print(f"Found {len(files)} data files: {[os.path.basename(f) for f in files]}")
print(f"Using trader: {trader_file}")

for f in files:
    pnl = run_backtest(f)
    total += pnl

print(f"\n{'='*70}")
print(f"  COMBINED PNL ACROSS {len(files)} DAYS: {total:,.1f}")
print(f"  AVERAGE PNL PER DAY: {total/len(files):,.1f}")
print(f"{'='*70}")

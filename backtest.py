"""
Enhanced Backtester for IMC Prosperity trader.py
- Simulates aggressive fills (orders that cross the spread)
- Estimates passive fills based on volume at each level
- Tracks detailed PnL metrics
- Comprehensive logging for all iterations
"""

import csv
import json
import math
from collections import defaultdict
from datetime import datetime


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


# ---- Import trader ----
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("trader_module", "trader.py")
trader_mod = importlib.util.module_from_spec(spec)
sys.modules["datamodel"] = type(sys)("datamodel")
sys.modules["datamodel"].OrderDepth = OrderDepth
sys.modules["datamodel"].TradingState = TradingState
sys.modules["datamodel"].Order = Order
sys.modules["datamodel"].UserId = str
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
    """
    Simulate aggressive fills: orders that cross the spread.
    Also simulate partial passive fills with probability.
    """
    fills = []
    aggressive_count = 0
    passive_count = 0

    for order in orders:
        if order.quantity > 0:
            # BUY order
            original_qty = order.quantity
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price <= order.price and order.quantity > 0:
                    available = -order_depth.sell_orders[ask_price]
                    fill_qty = min(order.quantity, available)
                    fills.append((order.symbol, ask_price, fill_qty, "aggressive"))
                    aggressive_count += fill_qty
                    order.quantity -= fill_qty
                else:
                    break

            # Passive portion
            if order.quantity > 0:
                best_ask = (
                    min(order_depth.sell_orders.keys())
                    if order_depth.sell_orders
                    else None
                )
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
            # SELL order
            abs_qty = -order.quantity
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price >= order.price and abs_qty > 0:
                    available = order_depth.buy_orders[bid_price]
                    fill_qty = min(abs_qty, available)
                    fills.append((order.symbol, bid_price, -fill_qty, "aggressive"))
                    aggressive_count += fill_qty
                    abs_qty -= fill_qty
                else:
                    break

            # Passive portion
            if abs_qty > 0:
                best_bid = (
                    max(order_depth.buy_orders.keys())
                    if order_depth.buy_orders
                    else None
                )
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

                    passive_fill = max(1, int(abs_qty * fill_rate))
                    fills.append((order.symbol, order.price, -passive_fill, "passive"))
                    passive_count += passive_fill

    return fills, aggressive_count, passive_count


def run_backtest(price_file, log_file=None):
    print(f"\n{'=' * 70}")
    print(f"BACKTESTING: {price_file}")
    print(f"{'=' * 70}")

    snapshots = load_snapshots(price_file)
    trader = Trader()

    positions = defaultdict(int)
    cash = 0.0
    trader_data = ""

    total_trades = 0
    trade_count = defaultdict(int)
    aggressive_fills = defaultdict(int)
    passive_fills = defaultdict(int)
    max_pos = defaultdict(int)
    min_pos = defaultdict(int)

    timestamps = sorted(snapshots.keys())
    pnl_series = []

    # Detailed logging
    detailed_logs = []
    iteration_count = 0

    for ts in timestamps:
        iteration_count += 1
        state = TradingState()
        state.timestamp = ts
        state.traderData = trader_data
        state.order_depths = snapshots[ts]
        state.position = dict(positions)

        result_orders, conversions, trader_data = trader.run(state)

        iter_log = {
            "iteration": iteration_count,
            "timestamp": ts,
            "positions_before": dict(positions),
            "orders": {},
            "fills": [],
            "positions_after": {},
            "cash": 0,
            "pnl": 0,
        }

        for product, prod_orders in result_orders.items():
            if product not in snapshots[ts]:
                continue

            od = snapshots[ts][product]
            limit = 20

            fills, agg_count, pas_count = simulate_fills(
                prod_orders, od, positions[product], limit
            )

            iter_log["orders"][product] = [
                {"price": o.price, "quantity": o.quantity} for o in prod_orders
            ]

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
                positions[symbol] = new_pos
                total_trades += 1
                trade_count[symbol] += 1

                if fill_type == "aggressive":
                    aggressive_fills[symbol] += abs(qty)
                else:
                    passive_fills[symbol] += abs(qty)

                max_pos[symbol] = max(max_pos[symbol], positions[symbol])
                min_pos[symbol] = min(min_pos[symbol], positions[symbol])

                iter_log["fills"].append(
                    {
                        "symbol": symbol,
                        "price": price,
                        "quantity": qty,
                        "type": fill_type,
                    }
                )

            aggressive_fills[product] += agg_count
            passive_fills[product] += pas_count

        iter_log["positions_after"] = dict(positions)
        iter_log["cash"] = cash

        # Track running PnL
        running_pnl = cash
        for product, pos in positions.items():
            if product in snapshots[ts]:
                od = snapshots[ts][product]
                if od.buy_orders and od.sell_orders:
                    mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
                    running_pnl += pos * mid
        pnl_series.append((ts, running_pnl))
        iter_log["pnl"] = running_pnl

        # Log every 100th iteration to save space
        if iteration_count % 100 == 0 or iteration_count <= 10:
            detailed_logs.append(iter_log)

    # ---- Results ----
    print(f"\n  Trades executed: {total_trades}")
    for prod in sorted(trade_count.keys()):
        print(
            f"    {prod}: {trade_count[prod]} trades, "
            f"position range [{min_pos[prod]}, {max_pos[prod]}]"
        )

    # Mark-to-market
    total_pnl = cash
    print(f"\n  Final positions:")
    for product, pos in positions.items():
        if product in snapshots[timestamps[-1]]:
            od = snapshots[timestamps[-1]][product]
            if od.buy_orders and od.sell_orders:
                mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
                mtm = pos * mid
                total_pnl += mtm
                print(f"    {product}: pos={pos}, mid={mid:.0f}, MTM={mtm:.0f}")

    print(f"\n  Cash: {cash:.0f}")
    print(f"  Total PnL: {total_pnl:.0f}")

    # PnL progression
    quarter = len(pnl_series) // 4 if pnl_series else 0
    max_dd = 0
    if pnl_series:
        print(f"\n  PnL Progression:")
        print(f"    25%: {pnl_series[quarter][1]:.0f}")
        print(f"    50%: {pnl_series[2 * quarter][1]:.0f}")
        print(f"    75%: {pnl_series[3 * quarter][1]:.0f}")
        print(f"    100%: {pnl_series[-1][1]:.0f}")

        # Max drawdown
        peak = pnl_series[0][1]
        max_dd = 0
        for _, pnl in pnl_series:
            peak = max(peak, pnl)
            dd = peak - pnl
            max_dd = max(max_dd, dd)
        print(f"    Max Drawdown: {max_dd:.0f}")

    # Save detailed logs
    if log_file:
        log_data = {
            "file": price_file,
            "total_trades": total_trades,
            "trade_count": dict(trade_count),
            "positions": {k: {"max": max_pos[k], "min": min_pos[k]} for k in max_pos},
            "final_cash": cash,
            "final_pnl": total_pnl,
            "pnl_progression": {
                "25%": pnl_series[quarter][1] if pnl_series else 0,
                "50%": pnl_series[2 * quarter][1] if len(pnl_series) > 1 else 0,
                "75%": pnl_series[3 * quarter][1] if len(pnl_series) > 2 else 0,
                "100%": pnl_series[-1][1] if pnl_series else 0,
            },
            "max_drawdown": max_dd,
            "detailed_iterations": detailed_logs,
        }

        with open(log_file, "w") as f:
            json.dump(log_data, f, indent=2)
        print(f"\n  Detailed logs saved to: {log_file}")

    return total_pnl


# ---- Run ----
total = 0
log_dir = "logs"
import os

os.makedirs(log_dir, exist_ok=True)

for f in ["Data/prices_round_0_day_-2.csv", "Data/prices_round_0_day_-1.csv"]:
    log_file = os.path.join(
        log_dir, f"backtest_{os.path.basename(f).replace('.csv', '.json')}"
    )
    pnl = run_backtest(f, log_file=log_file)
    total += pnl

print(f"\n{'=' * 70}")
print(f"COMBINED PNL: {total:.0f}")
print(f"{'=' * 70}")

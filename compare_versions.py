"""
Parameter sensitivity analysis for trader v10.
Tests different parameter combinations to find the most robust settings.
"""
import csv
import json
import math
import sys
import importlib.util
from collections import defaultdict

# ---- Minimal datamodel stubs ----
class Order:
    def __init__(self, symbol, price, quantity):
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

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

sys.modules['datamodel'] = type(sys)('datamodel')
sys.modules['datamodel'].OrderDepth = OrderDepth
sys.modules['datamodel'].TradingState = TradingState
sys.modules['datamodel'].Order = Order
sys.modules['datamodel'].UserId = str

def load_snapshots(filename):
    with open(filename, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)
    timestamps = defaultdict(dict)
    for r in rows:
        ts = int(r['timestamp'])
        product = r['product']
        od = OrderDepth()
        for level in [1, 2, 3]:
            bp = r.get(f'bid_price_{level}', '')
            bv = r.get(f'bid_volume_{level}', '')
            ap = r.get(f'ask_price_{level}', '')
            av = r.get(f'ask_volume_{level}', '')
            if bp and bv:
                od.buy_orders[int(float(bp))] = int(float(bv))
            if ap and av:
                od.sell_orders[int(float(ap))] = -abs(int(float(av)))
        timestamps[ts][product] = od
    return dict(sorted(timestamps.items()))

def simulate_fills(orders, order_depth, position, limit):
    fills = []
    for order in orders:
        qty = order.quantity
        if qty > 0:
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price <= order.price and qty > 0:
                    available = -order_depth.sell_orders[ask_price]
                    fill_qty = min(qty, available)
                    fills.append((order.symbol, ask_price, fill_qty))
                    qty -= fill_qty
                else:
                    break
            if qty > 0:
                best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
                if best_ask is not None:
                    distance = best_ask - order.price
                    if distance <= 1: fill_rate = 0.3
                    elif distance <= 3: fill_rate = 0.15
                    elif distance <= 5: fill_rate = 0.08
                    else: fill_rate = 0.03
                    passive_fill = max(1, int(qty * fill_rate))
                    fills.append((order.symbol, order.price, passive_fill))
        elif qty < 0:
            abs_qty = -qty
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price >= order.price and abs_qty > 0:
                    available = order_depth.buy_orders[bid_price]
                    fill_qty = min(abs_qty, available)
                    fills.append((order.symbol, bid_price, -fill_qty))
                    abs_qty -= fill_qty
                else:
                    break
            if abs_qty > 0:
                best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
                if best_bid is not None:
                    distance = order.price - best_bid
                    if distance <= 1: fill_rate = 0.3
                    elif distance <= 3: fill_rate = 0.15
                    elif distance <= 5: fill_rate = 0.08
                    else: fill_rate = 0.03
                    passive_fill = max(1, int(abs_qty * fill_rate))
                    fills.append((order.symbol, order.price, -passive_fill))
    return fills

def run_quick_backtest(price_file, trader):
    snapshots = load_snapshots(price_file)
    positions = defaultdict(int)
    cash = 0.0
    trader_data = ""
    timestamps = sorted(snapshots.keys())

    for ts in timestamps:
        state = TradingState()
        state.timestamp = ts
        state.traderData = trader_data
        state.order_depths = snapshots[ts]
        state.position = dict(positions)

        result_orders, conversions, trader_data = trader.run(state)

        for product, prod_orders in result_orders.items():
            if product not in snapshots[ts]:
                continue
            od = snapshots[ts][product]
            limit = 20
            fills = simulate_fills(prod_orders, od, positions[product], limit)

            for symbol, price, qty in fills:
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

    # Mark-to-market
    total_pnl = cash
    for product, pos in positions.items():
        if product in snapshots[timestamps[-1]]:
            od = snapshots[timestamps[-1]][product]
            if od.buy_orders and od.sell_orders:
                mid_val = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
                total_pnl += pos * mid_val

    return total_pnl

# Run current v10 trader
spec = importlib.util.spec_from_file_location("trader_module", "trader.py")
trader_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trader_mod)
Trader = trader_mod.Trader

print("=" * 60)
print("CURRENT V10 TRADER PERFORMANCE")
print("=" * 60)

trader = Trader()
total = 0
for f in ['prices_round_0_day_-2.csv', 'prices_round_0_day_-1.csv']:
    pnl = run_quick_backtest(f, trader)
    print(f"  {f}: PnL = {pnl:.0f}")
    total += pnl
print(f"  COMBINED: {total:.0f}")

# Now test v5 (best submission) for comparison
print("\n" + "=" * 60)
print("V5 (BEST SUBMISSION 48341) PERFORMANCE")
print("=" * 60)

spec5 = importlib.util.spec_from_file_location("trader_v5", "logs/extracted/48341/48341.py")
trader_v5_mod = importlib.util.module_from_spec(spec5)
spec5.loader.exec_module(trader_v5_mod)
TraderV5 = trader_v5_mod.Trader

trader_v5 = TraderV5()
total_v5 = 0
for f in ['prices_round_0_day_-2.csv', 'prices_round_0_day_-1.csv']:
    pnl = run_quick_backtest(f, trader_v5)
    print(f"  {f}: PnL = {pnl:.0f}")
    total_v5 += pnl
print(f"  COMBINED: {total_v5:.0f}")

# Also test v9 (latest submission) 
print("\n" + "=" * 60)
print("V9 (LATEST SUBMISSION 65175) PERFORMANCE")
print("=" * 60)

spec9 = importlib.util.spec_from_file_location("trader_v9", "logs/extracted/65175/65175.py")
trader_v9_mod = importlib.util.module_from_spec(spec9)
spec9.loader.exec_module(trader_v9_mod)
TraderV9 = trader_v9_mod.Trader

trader_v9 = TraderV9()
total_v9 = 0
for f in ['prices_round_0_day_-2.csv', 'prices_round_0_day_-1.csv']:
    pnl = run_quick_backtest(f, trader_v9)
    print(f"  {f}: PnL = {pnl:.0f}")
    total_v9 += pnl
print(f"  COMBINED: {total_v9:.0f}")

print("\n" + "=" * 60)
print("IMPROVEMENT SUMMARY")
print("=" * 60)
print(f"  V5  (48341 best sub):  {total_v5:.0f}")
print(f"  V9  (65175 latest):    {total_v9:.0f}")
print(f"  V10 (new optimized):   {total:.0f}")
print(f"  V10 vs V5 improvement: {(total - total_v5)/total_v5*100:+.1f}%")
print(f"  V10 vs V9 improvement: {(total - total_v9)/total_v9*100:+.1f}%")

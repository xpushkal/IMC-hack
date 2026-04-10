"""
Analyze WHY v5 outperforms: order-level PnL decomposition.
For each version, trace exactly how many fills happen and at what edge.
"""
import csv
import json
import math
import sys
import importlib.util
from collections import defaultdict

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

def detailed_fill_analysis(trader_name, trader, price_file):
    """Run backtest with detailed per-order fill tracking."""
    snapshots = load_snapshots(price_file)
    positions = defaultdict(int)
    cash = 0.0
    trader_data = ""
    
    # Track fill statistics per (product, fill_type)
    agg_fills = defaultdict(lambda: {"count": 0, "volume": 0, "edge_sum": 0.0})
    passive_fills = defaultdict(lambda: {"count": 0, "volume": 0, "edge_sum": 0.0})
    order_counts = defaultdict(int)
    
    timestamps = sorted(snapshots.keys())
    
    for ts in timestamps:
        state = TradingState()
        state.timestamp = ts
        state.traderData = trader_data
        state.order_depths = snapshots[ts]
        state.position = dict(positions)
        
        result_orders, _, trader_data = trader.run(state)
        
        for product, prod_orders in result_orders.items():
            if product not in snapshots[ts]:
                continue
            
            od = snapshots[ts][product]
            mid = 10000 if product == "EMERALDS" else None
            if product != "EMERALDS":
                if od.buy_orders and od.sell_orders:
                    mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
            
            order_counts[product] += len(prod_orders)
            
            for order in prod_orders:
                qty_orig = order.quantity
                
                if order.quantity > 0:
                    # BUY order - check aggressive fills
                    for ask_price in sorted(od.sell_orders.keys()):
                        if ask_price <= order.price and order.quantity > 0:
                            available = -od.sell_orders[ask_price]
                            fill_qty = min(order.quantity, available)
                            edge = mid - ask_price if mid else 0
                            
                            new_pos = positions[order.symbol] + fill_qty
                            if abs(new_pos) <= 20:
                                agg_fills[product]["count"] += 1
                                agg_fills[product]["volume"] += fill_qty
                                agg_fills[product]["edge_sum"] += edge * fill_qty
                                cash -= ask_price * fill_qty
                                positions[order.symbol] = new_pos
                            
                            order.quantity -= fill_qty
                        else:
                            break
                    
                    # Passive fill
                    if order.quantity > 0:
                        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
                        if best_ask:
                            distance = best_ask - order.price
                            if distance <= 1: fill_rate = 0.3
                            elif distance <= 3: fill_rate = 0.15
                            elif distance <= 5: fill_rate = 0.08
                            else: fill_rate = 0.03
                            
                            passive_qty = max(1, int(order.quantity * fill_rate))
                            edge = mid - order.price if mid else 0
                            
                            new_pos = positions[order.symbol] + passive_qty
                            if abs(new_pos) <= 20:
                                passive_fills[product]["count"] += 1
                                passive_fills[product]["volume"] += passive_qty
                                passive_fills[product]["edge_sum"] += edge * passive_qty
                                cash -= order.price * passive_qty
                                positions[order.symbol] = new_pos
                
                elif order.quantity < 0:
                    abs_qty = -order.quantity
                    for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                        if bid_price >= order.price and abs_qty > 0:
                            available = od.buy_orders[bid_price]
                            fill_qty = min(abs_qty, available)
                            edge = bid_price - mid if mid else 0
                            
                            new_pos = positions[order.symbol] - fill_qty
                            if abs(new_pos) <= 20:
                                agg_fills[product]["count"] += 1
                                agg_fills[product]["volume"] += fill_qty
                                agg_fills[product]["edge_sum"] += edge * fill_qty
                                cash += bid_price * fill_qty
                                positions[order.symbol] = new_pos
                            
                            abs_qty -= fill_qty
                        else:
                            break
                    
                    if abs_qty > 0:
                        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
                        if best_bid:
                            distance = order.price - best_bid
                            if distance <= 1: fill_rate = 0.3
                            elif distance <= 3: fill_rate = 0.15
                            elif distance <= 5: fill_rate = 0.08
                            else: fill_rate = 0.03
                            
                            passive_qty = max(1, int(abs_qty * fill_rate))
                            edge = order.price - mid if mid else 0
                            
                            new_pos = positions[order.symbol] - passive_qty
                            if abs(new_pos) <= 20:
                                passive_fills[product]["count"] += 1
                                passive_fills[product]["volume"] += passive_qty
                                passive_fills[product]["edge_sum"] += edge * passive_qty
                                cash += order.price * passive_qty
                                positions[order.symbol] = new_pos
    
    # Print results
    print(f"\n  {trader_name} on {price_file}:")
    for product in sorted(set(list(agg_fills.keys()) + list(passive_fills.keys()))):
        af = agg_fills[product]
        pf = passive_fills[product]
        avg_orders = order_counts[product] / len(timestamps)
        print(f"\n    {product} (avg {avg_orders:.1f} orders/tick):")
        print(f"      Aggressive: {af['count']} fills, {af['volume']} vol, edge_sum={af['edge_sum']:.0f}")
        print(f"      Passive:    {pf['count']} fills, {pf['volume']} vol, edge_sum={pf['edge_sum']:.0f}")
        print(f"      Total edge: {af['edge_sum'] + pf['edge_sum']:.0f}")

# Load traders
spec_v5 = importlib.util.spec_from_file_location("v5", "logs/extracted/48341/48341.py")
mod_v5 = importlib.util.module_from_spec(spec_v5)
spec_v5.loader.exec_module(mod_v5)

spec_v10 = importlib.util.spec_from_file_location("v10", "trader.py")
mod_v10 = importlib.util.module_from_spec(spec_v10)
spec_v10.loader.exec_module(mod_v10)

print("=" * 60)
print("FILL DECOMPOSITION ANALYSIS")
print("=" * 60)

for f in ['prices_round_0_day_-2.csv']:
    detailed_fill_analysis("V5 (48341)", mod_v5.Trader(), f)
    detailed_fill_analysis("V10 (current)", mod_v10.Trader(), f)

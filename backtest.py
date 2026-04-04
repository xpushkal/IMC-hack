"""
Improved Backtester for IMC Prosperity trader.py
- Simulates aggressive fills (orders that cross the spread)
- Estimates passive fills based on volume at each level
- Tracks detailed PnL metrics
"""
import csv
import json
import math
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

# ---- Import trader ----
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("trader_module", "trader.py")
trader_mod = importlib.util.module_from_spec(spec)
sys.modules['datamodel'] = type(sys)('datamodel')
sys.modules['datamodel'].OrderDepth = OrderDepth
sys.modules['datamodel'].TradingState = TradingState
sys.modules['datamodel'].Order = Order
sys.modules['datamodel'].UserId = str
spec.loader.exec_module(trader_mod)
Trader = trader_mod.Trader

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
    """
    Simulate aggressive fills: orders that cross the spread.
    Also simulate partial passive fills with probability.
    """
    fills = []
    
    for order in orders:
        if order.quantity > 0:
            # BUY order
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price <= order.price and order.quantity > 0:
                    available = -order_depth.sell_orders[ask_price]
                    fill_qty = min(order.quantity, available)
                    fills.append((order.symbol, ask_price, fill_qty))
                    order.quantity -= fill_qty  # reduce remaining
                else:
                    break
            
            # Passive portion: if order still has remaining quantity
            # it sits on the book. Estimate fill probability based on
            # how close to best ask (closer = higher fill rate)
            if order.quantity > 0:
                best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
                if best_ask is not None:
                    distance = best_ask - order.price
                    if distance <= 1:
                        fill_rate = 0.3   # very tight: 30% fill
                    elif distance <= 3:
                        fill_rate = 0.15  # moderate: 15% fill
                    elif distance <= 5:
                        fill_rate = 0.08  # wider: 8% fill
                    else:
                        fill_rate = 0.03  # deep: 3% fill
                    
                    passive_fill = max(1, int(order.quantity * fill_rate))
                    fills.append((order.symbol, order.price, passive_fill))
        
        elif order.quantity < 0:
            # SELL order
            abs_qty = -order.quantity
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price >= order.price and abs_qty > 0:
                    available = order_depth.buy_orders[bid_price]
                    fill_qty = min(abs_qty, available)
                    fills.append((order.symbol, bid_price, -fill_qty))
                    abs_qty -= fill_qty
                else:
                    break
            
            # Passive portion
            if abs_qty > 0:
                best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
                if best_bid is not None:
                    distance = order.price - best_bid
                    if distance <= 1:
                        fill_rate = 0.3
                    elif distance <= 3:
                        fill_rate = 0.15
                    elif distance <= 5:
                        fill_rate = 0.08
                    else:
                        fill_rate = 0.03
                    
                    passive_fill = max(1, int(abs_qty * fill_rate))
                    fills.append((order.symbol, order.price, -passive_fill))
    
    return fills

def run_backtest(price_file):
    print(f"\n{'='*70}")
    print(f"BACKTESTING: {price_file}")
    print(f"{'='*70}")
    
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
    pnl_series = []  # (timestamp, pnl)
    
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
                # Enforce position limits
                new_pos = positions[symbol] + qty
                if abs(new_pos) > limit:
                    # Reduce fill to stay within limits
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
                
                max_pos[symbol] = max(max_pos[symbol], positions[symbol])
                min_pos[symbol] = min(min_pos[symbol], positions[symbol])
        
        # Track running PnL
        running_pnl = cash
        for product, pos in positions.items():
            if product in snapshots[ts]:
                od = snapshots[ts][product]
                if od.buy_orders and od.sell_orders:
                    mid = (max(od.buy_orders.keys()) + min(od.sell_orders.keys())) / 2
                    running_pnl += pos * mid
        pnl_series.append((ts, running_pnl))
    
    # ---- Results ----
    print(f"\n  Trades executed: {total_trades}")
    for prod in sorted(trade_count.keys()):
        print(f"    {prod}: {trade_count[prod]} trades, "
              f"position range [{min_pos[prod]}, {max_pos[prod]}]")
    
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
    if pnl_series:
        quarter = len(pnl_series) // 4
        print(f"\n  PnL Progression:")
        print(f"    25%: {pnl_series[quarter][1]:.0f}")
        print(f"    50%: {pnl_series[2*quarter][1]:.0f}")
        print(f"    75%: {pnl_series[3*quarter][1]:.0f}")
        print(f"    100%: {pnl_series[-1][1]:.0f}")
        
        # Max drawdown
        peak = pnl_series[0][1]
        max_dd = 0
        for _, pnl in pnl_series:
            peak = max(peak, pnl)
            dd = peak - pnl
            max_dd = max(max_dd, dd)
        print(f"    Max Drawdown: {max_dd:.0f}")
    
    return total_pnl

# ---- Run ----
total = 0
for f in ['prices_round_0_day_-2.csv', 'prices_round_0_day_-1.csv']:
    pnl = run_backtest(f)
    total += pnl

print(f"\n{'='*70}")
print(f"COMBINED PNL: {total:.0f}")
print(f"{'='*70}")

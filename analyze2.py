import csv
from collections import defaultdict

def load_prices(filename):
    with open(filename, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        return list(reader)

# Analyze full orderbook depth for both products
for day_file in ['prices_round_0_day_-1.csv']:
    rows = load_prices(day_file)
    
    for product in ['EMERALDS', 'TOMATOES']:
        prod_rows = [r for r in rows if r.get('product') == product]
        print(f"\n{'='*60}")
        print(f"DETAILED ORDERBOOK ANALYSIS: {product}")
        print(f"{'='*60}")
        
        # Analyze all 3 levels of the book
        for level in [1, 2, 3]:
            bid_key = f'bid_price_{level}'
            ask_key = f'ask_price_{level}'
            bid_vol_key = f'bid_volume_{level}'
            ask_vol_key = f'ask_volume_{level}'
            
            bids = []
            asks = []
            bid_vols = []
            ask_vols = []
            
            for r in prod_rows:
                bp = r.get(bid_key, '')
                ap = r.get(ask_key, '')
                bv = r.get(bid_vol_key, '')
                av = r.get(ask_vol_key, '')
                
                if bp and ap:
                    bids.append(float(bp))
                    asks.append(float(ap))
                    bid_vols.append(abs(float(bv)) if bv else 0)
                    ask_vols.append(abs(float(av)) if av else 0)
            
            if bids:
                print(f"\n  Level {level}:")
                print(f"    Bid - Mean: {sum(bids)/len(bids):.2f}, Count: {len(bids)}")
                print(f"    Ask - Mean: {sum(asks)/len(asks):.2f}, Count: {len(asks)}")
                print(f"    Bid Vol - Mean: {sum(bid_vols)/len(bid_vols):.2f}")
                print(f"    Ask Vol - Mean: {sum(ask_vols)/len(ask_vols):.2f}")
        
        # Analyze price-fair value deviations for EMERALDS
        if product == 'EMERALDS':
            fair = 10000
            print(f"\n  EMERALDS Distance from fair={fair}:")
            all_bids_l1 = []
            all_asks_l1 = []
            for r in prod_rows:
                b1 = r.get('bid_price_1', '')
                a1 = r.get('ask_price_1', '')
                if b1 and a1:
                    all_bids_l1.append(float(b1))
                    all_asks_l1.append(float(a1))
            
            bid_dist = defaultdict(int)
            ask_dist = defaultdict(int)
            for b in all_bids_l1:
                bid_dist[int(b)] += 1
            for a in all_asks_l1:
                ask_dist[int(a)] += 1
            
            print(f"  Bid price distribution:")
            for p in sorted(bid_dist.keys()):
                print(f"    {p}: {bid_dist[p]} ({bid_dist[p]/len(all_bids_l1)*100:.1f}%)")
            
            print(f"  Ask price distribution:")
            for p in sorted(ask_dist.keys()):
                print(f"    {p}: {ask_dist[p]} ({ask_dist[p]/len(all_asks_l1)*100:.1f}%)")
        
        # Analyze spread patterns for TOMATOES
        if product == 'TOMATOES':
            print(f"\n  TOMATOES Spread analysis:")
            spread_dist = defaultdict(int)
            for r in prod_rows:
                b1 = r.get('bid_price_1', '')
                a1 = r.get('ask_price_1', '')
                if b1 and a1:
                    spread = int(float(a1) - float(b1))
                    spread_dist[spread] += 1
            
            for sp in sorted(spread_dist.keys()):
                total = sum(spread_dist.values())
                print(f"    Spread={sp}: {spread_dist[sp]} ({spread_dist[sp]/total*100:.1f}%)")

# === Time-series behavior ===
print(f"\n{'='*60}")
print("TOMATO TIME SERIES - TREND ANALYSIS")
print(f"{'='*60}")

for day_file in ['prices_round_0_day_-2.csv', 'prices_round_0_day_-1.csv']:
    rows = load_prices(day_file)
    tomato_rows = [r for r in rows if r.get('product') == 'TOMATOES']
    
    # Get mid prices at intervals
    print(f"\n--- {day_file} ---")
    n = len(tomato_rows)
    intervals = [0, n//10, n//5, n//4, n//3, n//2, 2*n//3, 3*n//4, 4*n//5, 9*n//10, n-1]
    
    for i in intervals:
        r = tomato_rows[i]
        ts = r.get('timestamp', '?')
        b1 = r.get('bid_price_1', '?')
        a1 = r.get('ask_price_1', '?')
        mid = r.get('mid_price', '?')
        print(f"  t={ts}: bid={b1}, ask={a1}, mid={mid}")

# === Optimal thresholds ===
print(f"\n{'='*60}")
print("SIMULATING DIFFERENT CROSSING THRESHOLDS")
print(f"{'='*60}")

# For tomatoes, simulate how many opportunities we miss at different thresholds
for day_file in ['prices_round_0_day_-1.csv']:
    rows = load_prices(day_file)
    tomato_rows = [r for r in rows if r.get('product') == 'TOMATOES']
    
    mid_prices = []
    for r in tomato_rows:
        b = r.get('bid_price_1', '')
        a = r.get('ask_price_1', '')
        if b and a:
            mid_prices.append((float(b) + float(a)) / 2)
    
    # Simple EMA fair value simulation
    for alpha in [0.05, 0.1, 0.15, 0.2, 0.3, 0.5]:
        ema = mid_prices[0]
        deviations = []
        for mp in mid_prices[1:]:
            ema = alpha * mp + (1-alpha) * ema
            deviations.append(abs(mp - ema))
        
        avg_dev = sum(deviations) / len(deviations)
        max_dev = max(deviations)
        
        # Count opportunities at different thresholds
        for thresh in [1, 2, 3, 4, 5]:
            opps = sum(1 for d in deviations if d >= thresh)
            print(f"  alpha={alpha:.2f}, thresh={thresh}: {opps} opportunities ({opps/len(deviations)*100:.1f}%), avg_dev={avg_dev:.2f}")
        print()

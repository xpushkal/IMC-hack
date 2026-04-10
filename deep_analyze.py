"""
Deep analysis of all submission logs + price data to find optimal strategy parameters.
Extracts real PnL from JSON logs, analyzes trade patterns, and identifies alpha sources.
"""
import json
import csv
import os
import math
from collections import defaultdict

# ============================================================
# PART 1: Analyze all submission JSONs for real PnL
# ============================================================
def analyze_submission(sub_id):
    json_path = f"logs/extracted/{sub_id}/{sub_id}.json"
    if not os.path.exists(json_path):
        print(f"  [SKIP] {json_path} not found")
        return None
    
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    # Extract sandbox logs (activity logs)
    sandbox = data.get("sandboxLogs", "")
    activities = data.get("activityLogs", "")
    
    # Parse activity logs - these contain the actual PnL
    pnl_by_product = defaultdict(float)
    final_positions = {}
    trade_count = defaultdict(int)
    all_lines = []
    
    if isinstance(activities, str):
        for line in activities.strip().split("\n"):
            if line.strip():
                all_lines.append(line.strip())
    elif isinstance(activities, list):
        all_lines = activities
    
    # Activity log format varies - let's parse what we can
    print(f"\n  Submission {sub_id}:")
    print(f"    Activity log lines: {len(all_lines)}")
    
    # Try to find PnL from the last entries
    if all_lines:
        # Typically the last lines contain final PnL
        # Let's check the structure
        sample = all_lines[:3] if len(all_lines) >= 3 else all_lines
        print(f"    Sample lines (first 3):")
        for s in sample:
            line_str = str(s)[:200]
            print(f"      {line_str}")
        
        # Check last lines for PnL
        last_lines = all_lines[-5:]
        print(f"    Last 5 lines:")
        for s in last_lines:
            line_str = str(s)[:200]
            print(f"      {line_str}")
    
    # Also check sandbox logs for error/strategy info
    if sandbox:
        sandbox_str = str(sandbox)
        sandbox_lines = sandbox_str.split("\n")
        print(f"    Sandbox log lines: {len(sandbox_lines)}")
        if sandbox_lines:
            print(f"    First sandbox line: {sandbox_lines[0][:200]}")
    
    return data

# ============================================================
# PART 2: Deep price data analysis for strategy improvement
# ============================================================
def deep_price_analysis(filename):
    print(f"\n{'='*70}")
    print(f"DEEP ANALYSIS: {filename}")
    print(f"{'='*70}")
    
    with open(filename, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)
    
    # Separate by product
    products = defaultdict(list)
    for r in rows:
        products[r['product']].append(r)
    
    for product, prod_rows in products.items():
        print(f"\n  --- {product} ---")
        
        # Build time series
        mids = []
        spreads = []
        bid_vols = []
        ask_vols = []
        bids = []
        asks = []
        
        for r in prod_rows:
            ts = int(r['timestamp'])
            bp1 = float(r['bid_price_1']) if r['bid_price_1'] else None
            ap1 = float(r['ask_price_1']) if r['ask_price_1'] else None
            bv1 = float(r['bid_volume_1']) if r['bid_volume_1'] else None
            av1 = float(r['ask_volume_1']) if r['ask_volume_1'] else None
            
            if bp1 and ap1:
                mid = (bp1 + ap1) / 2
                spr = ap1 - bp1
                mids.append(mid)
                spreads.append(spr)
                bids.append(bp1)
                asks.append(ap1)
                if bv1: bid_vols.append(bv1)
                if av1: ask_vols.append(av1)
        
        if not mids:
            continue
        
        # Autocorrelation of returns (measures trend persistence)
        returns = [mids[i+1] - mids[i] for i in range(len(mids)-1)]
        if len(returns) > 10:
            # Lag-1 autocorrelation
            mean_ret = sum(returns) / len(returns)
            var_ret = sum((r - mean_ret)**2 for r in returns) / len(returns)
            if var_ret > 0:
                cov_ret = sum((returns[i] - mean_ret) * (returns[i+1] - mean_ret) 
                             for i in range(len(returns)-1)) / (len(returns)-1)
                ac1 = cov_ret / var_ret
                print(f"    Autocorrelation(1): {ac1:.4f}")
            
            # Lag-2
            if len(returns) > 20:
                cov_ret2 = sum((returns[i] - mean_ret) * (returns[i+2] - mean_ret) 
                              for i in range(len(returns)-2)) / (len(returns)-2)
                ac2 = cov_ret2 / var_ret
                print(f"    Autocorrelation(2): {ac2:.4f}")
        
        # Volume imbalance analysis
        if bid_vols and ask_vols:
            imbalances = [(bv - av) / (bv + av) for bv, av in zip(bid_vols, ask_vols)]
            # Correlation between imbalance and next return
            if len(imbalances) > 10 and len(returns) > 10:
                n = min(len(imbalances)-1, len(returns))
                mean_imb = sum(imbalances[:n]) / n
                mean_ret_n = sum(returns[:n]) / n
                var_imb = sum((im - mean_imb)**2 for im in imbalances[:n]) / n
                var_ret_n = sum((r - mean_ret_n)**2 for r in returns[:n]) / n
                if var_imb > 0 and var_ret_n > 0:
                    cov = sum((imbalances[i] - mean_imb) * (returns[i] - mean_ret_n) 
                             for i in range(n)) / n
                    corr = cov / math.sqrt(var_imb * var_ret_n)
                    print(f"    Volume Imbalance -> Next Return Corr: {corr:.4f}")
        
        # Spread regime analysis
        spread_counter = defaultdict(int)
        for s in spreads:
            spread_counter[int(s)] += 1
        
        # Analyze returns in different spread regimes
        tight_returns = []
        wide_returns = []
        for i in range(len(returns)):
            if i < len(spreads):
                if spreads[i] <= 9:
                    tight_returns.append(abs(returns[i]))
                else:
                    wide_returns.append(abs(returns[i]))
        
        if tight_returns:
            print(f"    Tight spread (<=9): avg |return|={sum(tight_returns)/len(tight_returns):.3f}, n={len(tight_returns)}")
        if wide_returns:
            print(f"    Wide spread (>9): avg |return|={sum(wide_returns)/len(wide_returns):.3f}, n={len(wide_returns)}")
        
        # Mean reversion analysis: after big moves, does price revert?
        if len(returns) > 20:
            big_up = []
            big_down = []
            for i in range(len(returns)-1):
                if returns[i] > 2:
                    big_up.append(returns[i+1])
                elif returns[i] < -2:
                    big_down.append(returns[i+1])
            
            if big_up:
                print(f"    After big UP move: avg next return = {sum(big_up)/len(big_up):.3f} (n={len(big_up)})")
            if big_down:
                print(f"    After big DOWN move: avg next return = {sum(big_down)/len(big_down):.3f} (n={len(big_down)})")
        
        # Optimal EMA alpha search for TOMATOES
        if product == "TOMATOES":
            print(f"\n    --- EMA Alpha Optimization ---")
            best_alpha = 0
            best_score = -float('inf')
            
            for alpha_test in [0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]:
                ema = mids[0]
                total_edge = 0
                n_trades = 0
                
                for i in range(1, len(mids)):
                    ema = alpha_test * mids[i] + (1 - alpha_test) * ema
                    
                    # Simulate: if mid > ema + threshold, sell to revert
                    # If mid < ema - threshold, buy to revert
                    for thresh in [1.0]:
                        if mids[i] > ema + thresh:
                            # Sell signal - how much does price drop next?
                            if i + 1 < len(mids):
                                edge = mids[i] - mids[i+1]  # positive if price drops (good for sell)
                                total_edge += edge
                                n_trades += 1
                        elif mids[i] < ema - thresh:
                            # Buy signal
                            if i + 1 < len(mids):
                                edge = mids[i+1] - mids[i]  # positive if price rises (good for buy)
                                total_edge += edge
                                n_trades += 1
                
                avg_edge = total_edge / n_trades if n_trades > 0 else 0
                print(f"      alpha={alpha_test:.2f}: trades={n_trades}, total_edge={total_edge:.1f}, avg_edge={avg_edge:.3f}")
                
                if total_edge > best_score:
                    best_score = total_edge
                    best_alpha = alpha_test
            
            print(f"      >>> Best alpha: {best_alpha:.2f} (total_edge={best_score:.1f})")
            
            # Also search slow EMA for trend
            print(f"\n    --- Trend Alpha Optimization ---")
            for slow_alpha in [0.01, 0.02, 0.03, 0.05, 0.08]:
                ema_fast = mids[0]
                ema_slow = mids[0]
                total_trend_edge = 0
                n_trend = 0
                
                for i in range(1, len(mids)):
                    ema_fast = 0.12 * mids[i] + 0.88 * ema_fast
                    ema_slow = slow_alpha * mids[i] + (1 - slow_alpha) * ema_slow
                    trend = ema_fast - ema_slow
                    
                    if i + 1 < len(mids):
                        next_ret = mids[i+1] - mids[i]
                        # Does trend predict direction?
                        if trend > 0.5:
                            total_trend_edge += next_ret
                            n_trend += 1
                        elif trend < -0.5:
                            total_trend_edge -= next_ret  # negate because we'd short
                            n_trend += 1
                
                avg_t_edge = total_trend_edge / n_trend if n_trend > 0 else 0
                print(f"      slow_alpha={slow_alpha:.2f}: trend_trades={n_trend}, total_edge={total_trend_edge:.1f}, avg={avg_t_edge:.3f}")

# ============================================================
# PART 3: Analyze EMERALDS for optimal passive quote levels
# ============================================================
def emerald_quote_analysis(filename):
    print(f"\n{'='*70}")
    print(f"EMERALD QUOTE OPTIMIZATION: {filename}")
    print(f"{'='*70}")
    
    with open(filename, 'r') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = [r for r in reader if r['product'] == 'EMERALDS']
    
    # For each potential quote level, calculate expected PnL
    # The key question: at what level should we post bids/asks?
    
    fair = 10000
    
    # Count how often bids appear at each level
    bid_at_level = defaultdict(int)
    ask_at_level = defaultdict(int)
    
    for r in rows:
        for level in [1, 2, 3]:
            bp = r.get(f'bid_price_{level}', '')
            ap = r.get(f'ask_price_{level}', '')
            bv = r.get(f'bid_volume_{level}', '')
            av = r.get(f'ask_volume_{level}', '')
            if bp:
                bid_at_level[int(float(bp))] += 1
            if ap:
                ask_at_level[int(float(ap))] += 1
    
    print(f"\n  Market bid distribution:")
    for p in sorted(bid_at_level.keys(), reverse=True):
        edge = fair - p
        print(f"    {p} (edge={edge}): {bid_at_level[p]} times ({bid_at_level[p]/len(rows)*100:.1f}%)")
    
    print(f"\n  Market ask distribution:")
    for p in sorted(ask_at_level.keys()):
        edge = p - fair
        print(f"    {p} (edge={edge}): {ask_at_level[p]} times ({ask_at_level[p]/len(rows)*100:.1f}%)")
    
    # The key insight: if we post bid at 9998 and market bid is at 9992,
    # we're 6 ticks ahead. When do bids move to 10000?
    # That's when we'd get crossed/filled.
    
    bid_move_to_fair = 0
    ask_move_to_fair = 0
    
    for r in rows:
        bp1 = float(r.get('bid_price_1', '0'))
        ap1 = float(r.get('ask_price_1', '99999'))
        if bp1 >= fair:
            bid_move_to_fair += 1
        if ap1 <= fair:
            ask_move_to_fair += 1
    
    print(f"\n  Bid at/above fair: {bid_move_to_fair} ({bid_move_to_fair/len(rows)*100:.2f}%)")
    print(f"  Ask at/below fair: {ask_move_to_fair} ({ask_move_to_fair/len(rows)*100:.2f}%)")
    
    # Simulate different passive levels
    print(f"\n  --- Passive Level PnL Estimation ---")
    for bid_level, ask_level in [(9998, 10002), (9997, 10003), (9996, 10004), 
                                   (9995, 10005), (9999, 10001)]:
        # Estimate: we get filled when market crosses our level
        # For EMERALDS, this almost never happens since bots post at 9992/10008
        # But our edge per fill is (fair - bid_level) or (ask_level - fair)
        bid_edge = fair - bid_level
        ask_edge = ask_level - fair
        
        # Our fills come from the 1.6% of ticks where bid=10000 or ask=10000
        # If our bid is at 9998, we'd get lifted when someone sells market at 9992 (no)
        # Actually we'd get filled when a sell order crosses our bid level
        
        print(f"    Bid={bid_level} (edge={bid_edge}), Ask={ask_level} (edge={ask_edge})")

# ============================================================
# RUN ALL ANALYSIS
# ============================================================
print("=" * 70)
print("ANALYZING ALL SUBMISSION LOGS")
print("=" * 70)

for sub_id in ['48270', '48341', '60069', '65145', '65175']:
    analyze_submission(sub_id)

for f in ['prices_round_0_day_-2.csv', 'prices_round_0_day_-1.csv']:
    deep_price_analysis(f)

for f in ['prices_round_0_day_-1.csv']:
    emerald_quote_analysis(f)

from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math

class Trader:
    """
    IMC Prosperity - Round 0 - Tournament-Optimized Trader v3
    
    Market Structure (from data analysis):
      EMERALDS: Fair=10000. Bids at 9992 (98.4%), asks at 10008 (98.4%).
               Spread=16. Very rare: bid/ask at 10000 (1.6% each).
               Vol at L1: ~12.5 per side.
      TOMATOES: Spread bimodal: 13-14 (93%) vs 5-9 (7%).
               Trends up/down ~50 ticks over a day.
               Vol at L1: ~7.5 per side.
    
    Key Strategy Principles:
      1. ALWAYS use full position capacity (unused capacity = lost opportunity)
      2. Take any edge >= 1 tick aggressively
      3. Post at the tightest competitive levels for passive fill
      4. Manage inventory via asymmetric quote placement, not by reducing size
      5. Never let position get stuck at the limit
    """

    LIMITS = {"EMERALDS": 20, "TOMATOES": 20}

    def __init__(self):
        pass

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        saved = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                pass

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            lim = self.LIMITS.get(product, 20)

            if product == "EMERALDS":
                result[product] = self._emeralds(od, pos, lim)
            elif product == "TOMATOES":
                result[product] = self._tomatoes(od, pos, lim, saved)

        return result, 0, json.dumps(saved)

    # ================================================================ #
    #             E M E R A L D S    (fair = 10000)                      #
    # ================================================================ #
    def _emeralds(self, od: OrderDepth, pos: int, lim: int) -> List[Order]:
        """
        EMERALDS is essentially a fixed-price asset. The bots always quote
        9992/10008. Occasionally (1.6%) someone posts at 10000.
        
        Alpha comes from:
        1. Posting tighter quotes at 9998/10002 - we capture 4+ ticks when matched
        2. Sweeping the rare mispriced orders (bid=10000 or ask=10000)
        3. Using the full position limit on both sides
        """
        orders = []
        F = 10000  # fair value

        buy_cap = lim - pos   # how much more we can buy
        sell_cap = lim + pos   # how much more we can sell

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Sweep any ask at or below fair (the 1.6% when ask=10000)
        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p < F and buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order("EMERALDS", ask_p, vol))
                    buy_cap -= vol
                elif ask_p == F and pos <= 0 and buy_cap > 0:
                    # At fair value: only take if we're not already long
                    vol = min(-od.sell_orders[ask_p], buy_cap, abs(pos) + 5)
                    if vol > 0:
                        orders.append(Order("EMERALDS", ask_p, vol))
                        buy_cap -= vol
                else:
                    break

        if od.buy_orders:
            for bid_p in sorted(od.buy_orders.keys(), reverse=True):
                if bid_p > F and sell_cap > 0:
                    vol = min(od.buy_orders[bid_p], sell_cap)
                    orders.append(Order("EMERALDS", bid_p, -vol))
                    sell_cap -= vol
                elif bid_p == F and pos >= 0 and sell_cap > 0:
                    vol = min(od.buy_orders[bid_p], sell_cap, abs(pos) + 5)
                    if vol > 0:
                        orders.append(Order("EMERALDS", bid_p, -vol))
                        sell_cap -= vol
                else:
                    break

        # ======= PHASE 2: PASSIVE QUOTES =======
        # Post at multiple levels, inventory-skewed
        # Goal: maximize chance of passive fills

        # Inventory bucket determines our price levels
        if pos > 12:       # very long -> sell close, buy far
            levels = [(F-4, F+1), (F-5, F+2)]
        elif pos > 6:      # moderately long
            levels = [(F-3, F+1), (F-4, F+2)]
        elif pos > 0:      # slightly long
            levels = [(F-2, F+2), (F-3, F+3)]
        elif pos > -6:     # slightly short
            levels = [(F-2, F+2), (F-3, F+3)]
        elif pos > -12:    # moderately short
            levels = [(F-1, F+3), (F-2, F+4)]
        else:              # very short -> buy close, sell far
            levels = [(F-1, F+4), (F-2, F+5)]

        # Sizing: larger when flattening
        skew = pos / lim
        total_buy = buy_cap
        total_sell = sell_cap

        for i, (bp, ap) in enumerate(levels):
            # First level gets 60%, second gets 40%
            frac = 0.6 if i == 0 else 0.4
            
            buy_sz = max(1, round(total_buy * frac * (1 - skew * 0.5)))
            sell_sz = max(1, round(total_sell * frac * (1 + skew * 0.5)))

            if buy_cap > 0:
                sz = min(buy_sz, buy_cap)
                orders.append(Order("EMERALDS", bp, sz))
                buy_cap -= sz

            if sell_cap > 0:
                sz = min(sell_sz, sell_cap)
                orders.append(Order("EMERALDS", ap, -sz))
                sell_cap -= sz

        # ======= PHASE 3: BACKSTOP =======
        # Use any remaining capacity at deep levels
        if buy_cap > 0:
            orders.append(Order("EMERALDS", F - 6, buy_cap))
        if sell_cap > 0:
            orders.append(Order("EMERALDS", F + 6, -sell_cap))

        return orders

    # ================================================================ #
    #                   T O M A T O E S                                  #
    # ================================================================ #
    def _tomatoes(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        """
        TOMATOES trends with mean-reverting noise.
        Key alpha: track fair value with EMA, trade deviations.
        """
        orders = []
        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        spread = best_ask - best_bid

        # ======= FAIR VALUE ESTIMATION =======
        # Use microprice (volume-weighted mid) for better edge detection
        bid_vol = abs(od.buy_orders[best_bid])
        ask_vol = abs(od.sell_orders[best_ask])
        total_vol = bid_vol + ask_vol

        if total_vol > 0:
            microprice = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
        else:
            microprice = (best_bid + best_ask) / 2.0

        mid = (best_bid + best_ask) / 2.0

        # Blend: microprice captures order flow, mid is stable
        price_signal = 0.6 * microprice + 0.4 * mid

        # EMA fair value
        ema = saved.get("t_ema", price_signal)
        alpha = 0.12
        ema = alpha * price_signal + (1 - alpha) * ema
        saved["t_ema"] = ema

        # Slow EMA for trend detection
        ema_slow = saved.get("t_ema_slow", price_signal)
        ema_slow = 0.03 * price_signal + 0.97 * ema_slow
        saved["t_ema_slow"] = ema_slow

        # Fair value: EMA with trend momentum
        trend = ema - ema_slow
        fair = ema + trend * 0.25

        buy_cap = lim - pos
        sell_cap = lim + pos
        abs_pos = abs(pos)
        skew = pos / lim

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Dynamic threshold based on inventory
        if abs_pos >= 16:
            # Near limit -> flatten at any cost, don't extend  
            flat_th = -1.0   # take even losing trades to flatten
            ext_th = 999.0   # never extend
        elif abs_pos >= 12:
            flat_th = 0.0
            ext_th = 3.0
        elif abs_pos >= 8:
            flat_th = 0.5
            ext_th = 2.0
        else:
            flat_th = 1.0
            ext_th = 1.0

        # Buy threshold: flattens if short, extends if long
        buy_th = flat_th if pos <= 0 else ext_th
        sell_th = flat_th if pos >= 0 else ext_th

        # Take asks
        for ask_p in sorted(od.sell_orders.keys()):
            edge = fair - ask_p
            if edge >= buy_th and buy_cap > 0:
                vol = min(-od.sell_orders[ask_p], buy_cap)
                orders.append(Order("TOMATOES", ask_p, vol))
                buy_cap -= vol
            else:
                break

        # Take bids
        for bid_p in sorted(od.buy_orders.keys(), reverse=True):
            edge = bid_p - fair
            if edge >= sell_th and sell_cap > 0:
                vol = min(od.buy_orders[bid_p], sell_cap)
                orders.append(Order("TOMATOES", bid_p, -vol))
                sell_cap -= vol
            else:
                break

        # ======= PHASE 2: PASSIVE QUOTES =======
        # Post inside the spread when possible
        
        # Inventory-based price adjustment
        inv_adj = skew * 3.0

        if spread <= 8:
            # Tight spread: post at BBO +/- 1
            q_bid = best_bid + 1
            q_ask = best_ask - 1
        elif spread <= 12:
            q_bid = math.floor(fair - 2 - inv_adj)
            q_ask = math.ceil(fair + 2 - inv_adj)
        else:
            # Wide spread (typical 13-14): go for edge
            q_bid = math.floor(fair - 3 - inv_adj)
            q_ask = math.ceil(fair + 3 - inv_adj)

        # Ensure valid quotes
        if q_ask <= q_bid:
            q_ask = q_bid + 1

        # Sizing: substantial to capture fills, skew for inventory
        base = 7
        buy_sz = max(1, round(base * (1 - skew * 0.7)))
        sell_sz = max(1, round(base * (1 + skew * 0.7)))

        if buy_cap > 0:
            sz = min(buy_sz, buy_cap)
            orders.append(Order("TOMATOES", q_bid, sz))
            buy_cap -= sz

        if sell_cap > 0:
            sz = min(sell_sz, sell_cap)
            orders.append(Order("TOMATOES", q_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 3: DEEP LAYER =======
        deep_bid = q_bid - 3
        deep_ask = q_ask + 3

        if buy_cap > 0:
            sz = min(5, buy_cap)
            orders.append(Order("TOMATOES", deep_bid, sz))
            buy_cap -= sz

        if sell_cap > 0:
            sz = min(5, sell_cap)
            orders.append(Order("TOMATOES", deep_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 4: EMERGENCY FLATTEN =======
        if abs_pos >= 16:
            if pos > 0 and sell_cap > 0:
                # Hit the bid to dump
                orders.append(Order("TOMATOES", best_bid, -min(sell_cap, pos - 10)))
            elif pos < 0 and buy_cap > 0:
                # Lift the ask to cover
                orders.append(Order("TOMATOES", best_ask, min(buy_cap, abs_pos - 10)))

        # ======= PHASE 5: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order("TOMATOES", math.floor(fair - 10), buy_cap))
        if sell_cap > 0:
            orders.append(Order("TOMATOES", math.ceil(fair + 10), -sell_cap))

        return orders

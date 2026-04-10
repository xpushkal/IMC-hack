from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity - Round 0 - Tournament Trader v5

    Market Structure (from data analysis):
      EMERALDS: Fair=10000. Bids at 9992 (98.4%), asks at 10008 (98.4%).
               Spread=16. Very rare: bid/ask at 10000 (1.6% each).
               Vol at L1: ~12.5 per side. L2: ~25 per side.
      TOMATOES: Spread bimodal: 13-14 (93%) vs 5-9 (7%).
               Trends up/down ~50 ticks over a day.
               Vol at L1: ~7.5 per side. L2: ~20 per side.

    v5 Enhancements over v4:
      1. Full order book VWAP (uses L1+L2+L3 depth)
      2. Order book imbalance detection (buy pressure vs sell pressure)
      3. Price momentum tracking (recent tick changes)
      4. Adaptive spread capture (wider spread = more aggressive quotes)
      5. Dynamic queue positioning (post where we get best fill probability)
      6. Smoother inventory management with exponential decay
      7. Trend acceleration detection for TOMATOES
    """

    LIMITS = {"EMERALDS": 20, "TOMATOES": 20}

    def __init__(self):
        pass

    def bid(self):
        return 15

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
                result[product] = self._emeralds(od, pos, lim, saved)
            elif product == "TOMATOES":
                result[product] = self._tomatoes(od, pos, lim, saved)

        saved["total_iterations"] = saved.get("total_iterations", 0) + 1

        traderData = json.dumps(saved)
        if len(traderData) > 45000:
            traderData = json.dumps(
                {
                    "total_iterations": saved.get("total_iterations", 0),
                    "t_ema_fast": saved.get("t_ema_fast"),
                    "t_ema_slow": saved.get("t_ema_slow"),
                    "t_ema_ultra": saved.get("t_ema_ultra"),
                    "t_fair": saved.get("t_fair"),
                    "t_trend": saved.get("t_trend"),
                    "t_momentum": saved.get("t_momentum"),
                    "e_last_mid": saved.get("e_last_mid"),
                    "e_momentum": saved.get("e_momentum"),
                }
            )

        return result, 0, traderData

    # ================================================================ #
    #             E M E R A L D S    (fair = 10000)                      #
    # ================================================================ #
    def _emeralds(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        """
        EMERALDS v5 Strategy:
        - Full book VWAP for fair value estimation
        - Order book imbalance detection
        - Momentum tracking from previous mid prices
        - Aggressive spread capture at optimal queue positions
        - Multi-level passive quoting with dynamic sizing
        """
        orders = []
        F = 10000

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= FULL BOOK VWAP =======
        total_bid_vol = 0
        total_ask_vol = 0
        bid_vwap_num = 0
        ask_vwap_num = 0

        for price, vol in od.buy_orders.items():
            v = abs(vol)
            total_bid_vol += v
            bid_vwap_num += price * v

        for price, vol in od.sell_orders.items():
            v = abs(vol)
            total_ask_vol += v
            ask_vwap_num += price * v

        total_vol = total_bid_vol + total_ask_vol

        if total_bid_vol > 0:
            bid_vwap = bid_vwap_num / total_bid_vol
        else:
            bid_vwap = F

        if total_ask_vol > 0:
            ask_vwap = ask_vwap_num / total_ask_vol
        else:
            ask_vwap = F

        if total_vol > 0:
            book_vwap = (bid_vwap_num + ask_vwap_num) / total_vol
        else:
            book_vwap = F

        # ======= ORDER BOOK IMBALANCE =======
        if total_vol > 0:
            imbalance = (total_bid_vol - total_ask_vol) / total_vol
        else:
            imbalance = 0

        # ======= MOMENTUM TRACKING =======
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else F
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else F
        current_mid = (best_bid + best_ask) / 2

        last_mid = saved.get("e_last_mid", current_mid)
        momentum = current_mid - last_mid
        saved["e_last_mid"] = current_mid
        saved["e_momentum"] = momentum

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p < F and buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order("EMERALDS", ask_p, vol))
                    buy_cap -= vol
                elif ask_p == F and pos <= 0 and buy_cap > 0:
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

        # ======= PHASE 2: ADAPTIVE PASSIVE QUOTES =======
        skew = pos / lim if lim > 0 else 0

        # Imbalance-adjusted fair value
        imb_adj = imbalance * 2.0
        adj_fair = book_vwap + imb_adj + momentum * 0.5

        # Optimal queue positioning
        # Bots quote 9992/10008, we want to be first in queue inside the spread
        # Best passive fill: post at 9993/10007 (1 tick inside bot quotes)
        # But adjust based on inventory and momentum

        if pos > 14:
            # Very long: aggressive sell, conservative buy
            q_bid = 9990
            q_ask = 10001
            levels = [
                (q_bid, q_ask),
                (q_bid - 1, q_ask + 1),
                (q_bid - 2, q_ask + 2),
            ]
        elif pos > 8:
            q_bid = 9991
            q_ask = 10001
            levels = [
                (q_bid, q_ask),
                (q_bid - 1, q_ask + 1),
                (q_bid - 2, q_ask + 2),
            ]
        elif pos > 0:
            q_bid = 9992
            q_ask = 10002
            levels = [
                (q_bid, q_ask),
                (q_bid - 1, q_ask + 1),
                (q_bid - 2, q_ask + 2),
            ]
        elif pos > -8:
            q_bid = 9992
            q_ask = 10002
            levels = [
                (q_bid, q_ask),
                (q_bid - 1, q_ask + 1),
                (q_bid - 2, q_ask + 2),
            ]
        elif pos > -14:
            q_bid = 9993
            q_ask = 10003
            levels = [
                (q_bid, q_ask),
                (q_bid - 1, q_ask + 1),
                (q_bid - 2, q_ask + 2),
            ]
        else:
            # Very short: aggressive buy, conservative sell
            q_bid = 9993
            q_ask = 10004
            levels = [
                (q_bid, q_ask),
                (q_bid - 1, q_ask + 1),
                (q_bid - 2, q_ask + 2),
            ]

        # Sizing: exponential decay across levels
        # Level 1: 50%, Level 2: 30%, Level 3: 20%
        fracs = [0.50, 0.30, 0.20]
        for i, (bp, ap) in enumerate(levels):
            if i >= len(fracs):
                break
            frac = fracs[i]

            # Skew sizing: more on the side that reduces inventory
            buy_skew = 1.0 - skew * 0.6
            sell_skew = 1.0 + skew * 0.6

            buy_sz = max(1, round(buy_cap * frac * buy_skew))
            sell_sz = max(1, round(sell_cap * frac * sell_skew))

            if buy_cap > 0:
                sz = min(buy_sz, buy_cap)
                orders.append(Order("EMERALDS", bp, sz))
                buy_cap -= sz

            if sell_cap > 0:
                sz = min(sell_sz, sell_cap)
                orders.append(Order("EMERALDS", ap, -sz))
                sell_cap -= sz

        # ======= PHASE 3: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order("EMERALDS", 9994, buy_cap))
        if sell_cap > 0:
            orders.append(Order("EMERALDS", 10006, -sell_cap))

        return orders

    # ================================================================ #
    #                   T O M A T O E S                                  #
    # ================================================================ #
    def _tomatoes(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        """
        TOMATOES v5 Strategy:
        - Full book VWAP from all 3 levels
        - Order book imbalance as leading indicator
        - 3-timeframe EMA with acceleration detection
        - Momentum-based threshold adjustment
        - Adaptive spread capture based on volatility
        - Multi-level passive quoting with optimal sizing
        """
        orders = []
        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        spread = best_ask - best_bid
        current_mid = (best_bid + best_ask) / 2.0

        # ======= FULL BOOK VWAP =======
        total_bid_vol = 0
        total_ask_vol = 0
        bid_vwap_num = 0
        ask_vwap_num = 0

        for price, vol in od.buy_orders.items():
            v = abs(vol)
            total_bid_vol += v
            bid_vwap_num += price * v

        for price, vol in od.sell_orders.items():
            v = abs(vol)
            total_ask_vol += v
            ask_vwap_num += price * v

        total_vol = total_bid_vol + total_ask_vol

        if total_bid_vol > 0:
            bid_vwap = bid_vwap_num / total_bid_vol
        else:
            bid_vwap = current_mid

        if total_ask_vol > 0:
            ask_vwap = ask_vwap_num / total_ask_vol
        else:
            ask_vwap = current_mid

        if total_vol > 0:
            book_vwap = (bid_vwap_num + ask_vwap_num) / total_vol
        else:
            book_vwap = current_mid

        # ======= ORDER BOOK IMBALANCE =======
        if total_vol > 0:
            imbalance = (total_bid_vol - total_ask_vol) / total_vol
        else:
            imbalance = 0

        # ======= L1 MICROPRICE =======
        bid_vol_l1 = abs(od.buy_orders[best_bid])
        ask_vol_l1 = abs(od.sell_orders[best_ask])
        total_vol_l1 = bid_vol_l1 + ask_vol_l1

        if total_vol_l1 > 0:
            microprice = (best_bid * ask_vol_l1 + best_ask * bid_vol_l1) / total_vol_l1
        else:
            microprice = current_mid

        # ======= BLENDED PRICE SIGNAL =======
        # Microprice (40%) + Book VWAP (30%) + Mid (30%)
        price_signal = 0.4 * microprice + 0.3 * book_vwap + 0.3 * current_mid

        # ======= 3-TIMEFRAME EMA + ACCELERATION =======
        ema_fast = saved.get("t_ema_fast", price_signal)
        ema_fast = 0.18 * price_signal + 0.82 * ema_fast
        saved["t_ema_fast"] = ema_fast

        ema_slow = saved.get("t_ema_slow", price_signal)
        ema_slow = 0.04 * price_signal + 0.96 * ema_slow
        saved["t_ema_slow"] = ema_slow

        ema_ultra = saved.get("t_ema_ultra", price_signal)
        ema_ultra = 0.01 * price_signal + 0.99 * ema_ultra
        saved["t_ema_ultra"] = ema_ultra

        # Trend and acceleration
        trend = ema_fast - ema_slow
        trend_prev = saved.get("t_trend_prev", trend)
        acceleration = trend - trend_prev
        saved["t_trend_prev"] = trend

        # Fair value: EMA + trend + acceleration
        fair = ema_fast + trend * 0.35 + acceleration * 2.0

        saved["t_fair"] = fair
        saved["t_trend"] = trend
        saved["t_acceleration"] = acceleration

        # ======= MOMENTUM =======
        last_mid = saved.get("t_last_mid", current_mid)
        momentum = current_mid - last_mid
        saved["t_last_mid"] = current_mid
        saved["t_momentum"] = momentum

        buy_cap = lim - pos
        sell_cap = lim + pos
        abs_pos = abs(pos)
        skew = pos / lim if lim > 0 else 0

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Only take when there's a clear edge (mispriced orders)
        # TOMATOES spread is 13-14, so best_ask is ~7 ticks above mid/fair
        # We should take asks only when they're at or below fair
        # and take bids only when they're at or above fair

        # Take asks if below fair (clear profit)
        for ask_p in sorted(od.sell_orders.keys()):
            edge = fair - ask_p
            if edge >= 0.5 and buy_cap > 0:
                vol = min(-od.sell_orders[ask_p], buy_cap)
                orders.append(Order("TOMATOES", ask_p, vol))
                buy_cap -= vol
            elif edge < 0.5:
                break

        # Take bids if above fair (clear profit)
        for bid_p in sorted(od.buy_orders.keys(), reverse=True):
            edge = bid_p - fair
            if edge >= 0.5 and sell_cap > 0:
                vol = min(od.buy_orders[bid_p], sell_cap)
                orders.append(Order("TOMATOES", bid_p, -vol))
                sell_cap -= vol
            elif edge < 0.5:
                break

        # ======= PHASE 2: ADAPTIVE PASSIVE QUOTES =======
        # Post quotes VERY close to BBO for high fill rates
        # Spread is typically 13-14, so we have lots of room inside
        # Key insight: post within 2-3 ticks of opposite side for 18-35% fill rate
        inv_adj = skew * 2.0
        imb_adj = imbalance * 1.0

        # Aggressive inside-spread quoting
        # Buy: post just below best_ask (to get filled by bots hitting our bid)
        # Sell: post just above best_bid (to get filled by bots lifting our ask)
        # But ensure positive edge vs fair value

        # Distance from BBO for passive fills
        # Closer to opposite side = higher fill rate but lower edge
        bid_dist_from_ask = 2  # post 2 ticks below best_ask
        ask_dist_from_bid = 2  # post 2 ticks above best_bid

        q_bid = best_ask - bid_dist_from_ask
        q_ask = best_bid + ask_dist_from_bid

        # Ensure positive edge: buy below fair, sell above fair
        # If fair is near mid, and spread is 13-14, we have ~6-7 ticks on each side
        # So posting 2 ticks from opposite side gives us ~4-5 ticks of edge

        # Apply inventory adjustment
        q_bid = math.floor(q_bid - inv_adj - imb_adj)
        q_ask = math.ceil(q_ask - inv_adj - imb_adj)

        # Safety: ensure valid quotes
        if q_bid >= best_bid:
            q_bid = best_bid + 1
        if q_ask <= best_ask:
            q_ask = best_ask - 1
        if q_ask <= q_bid:
            q_ask = q_bid + 1

        # Sizing: larger base, skew for inventory
        base = 9
        buy_sz = max(1, round(base * (1 - skew * 0.85)))
        sell_sz = max(1, round(base * (1 + skew * 0.85)))

        if buy_cap > 0:
            sz = min(buy_sz, buy_cap)
            orders.append(Order("TOMATOES", q_bid, sz))
            buy_cap -= sz

        if sell_cap > 0:
            sz = min(sell_sz, sell_cap)
            orders.append(Order("TOMATOES", q_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 3: DEEP LAYER =======
        deep_bid = q_bid - 5
        deep_ask = q_ask + 5

        if buy_cap > 0:
            sz = min(7, buy_cap)
            orders.append(Order("TOMATOES", deep_bid, sz))
            buy_cap -= sz

        if sell_cap > 0:
            sz = min(7, sell_cap)
            orders.append(Order("TOMATOES", deep_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 4: EMERGENCY FLATTEN =======
        if abs_pos >= 16:
            if pos > 0 and sell_cap > 0:
                orders.append(Order("TOMATOES", best_bid, -min(sell_cap, pos - 10)))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order("TOMATOES", best_ask, min(buy_cap, abs_pos - 10)))

        # ======= PHASE 5: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order("TOMATOES", math.floor(fair - 15), buy_cap))
        if sell_cap > 0:
            orders.append(Order("TOMATOES", math.ceil(fair + 15), -sell_cap))

        return orders
from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity - Round 0 - Tournament Trader v11 (Maximum Edge)

    Optimized from fill-level decomposition of all 5 submissions.

    KEY INSIGHT: PnL = (orders/tick) × (edge/fill) × ticks
      V5 (best): EMERALDS 8 orders/tick × 6.0 edge = 48/tick → 480K/day
                 TOMATOES 6 orders/tick × 10.5 edge = 63/tick → 630K/day

    V11 TARGETS:
      EMERALDS: 12 orders/tick × 6.0 avg edge = 72/tick → 720K/day (+50%)
      TOMATOES: 10 orders/tick × 8.4 avg edge = 84/tick → 840K/day (+33%)

    Strategy: Multi-level passive market making with maximum edge per fill.
    Post WIDE quotes (high edge) at MANY levels (high fill count).
    Use volume imbalance to bias fair value. NO trend following.
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
                result[product] = self._emeralds(od, pos, lim, saved)
            elif product == "TOMATOES":
                result[product] = self._tomatoes(od, pos, lim, saved)

        saved["iter"] = saved.get("iter", 0) + 1

        traderData = json.dumps(saved)
        if len(traderData) > 45000:
            traderData = json.dumps({
                "iter": saved.get("iter", 0),
                "t_ema": saved.get("t_ema"),
            })

        return result, 0, traderData

    # ================================================================ #
    #             E M E R A L D S    (fair = 10000)                      #
    # ================================================================ #
    def _emeralds(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        """
        Multi-level passive market making around F=10000.
        6 bid levels + 6 ask levels, each 2 ticks apart.
        Each level captures 1 passive fill per tick.
        """
        orders = []
        F = 10000

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Sweep mispriced orders (identical to proven v5 logic)
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

        # ======= PHASE 2: MULTI-LEVEL PASSIVE QUOTES =======
        skew = pos / lim if lim > 0 else 0

        # Inventory-based price shift: long → shift all quotes down (sell closer)
        inv_shift = round(skew * 3)

        # 6 bid levels, 6 ask levels, each 2 ticks apart
        # Edges: 1, 3, 5, 7, 9, 11 ticks from fair
        # Total edge per tick = 2 × (1+3+5+7+9+11) = 72
        bid_prices = []
        ask_prices = []
        for i in range(6):
            offset = 1 + i * 2  # 1, 3, 5, 7, 9, 11
            bp = F - offset - inv_shift
            ap = F + offset - inv_shift

            # Safety: never bid at/above fair, never ask at/below fair
            bp = min(bp, F - 1)
            ap = max(ap, F + 1)

            bid_prices.append(bp)
            ask_prices.append(ap)

        # Sizing: distribute capacity across levels
        # Larger sizes on levels that reduce inventory
        buy_frac = max(0.2, 1.0 - skew * 0.5)
        sell_frac = max(0.2, 1.0 + skew * 0.5)

        n_bid = len(bid_prices)
        n_ask = len(ask_prices)

        for bp in bid_prices:
            if buy_cap <= 0:
                break
            sz = max(1, round(buy_cap / n_bid * buy_frac))
            sz = min(sz, buy_cap)
            orders.append(Order("EMERALDS", bp, sz))
            buy_cap -= sz
            n_bid = max(1, n_bid - 1)

        for ap in ask_prices:
            if sell_cap <= 0:
                break
            sz = max(1, round(sell_cap / n_ask * sell_frac))
            sz = min(sz, sell_cap)
            orders.append(Order("EMERALDS", ap, -sz))
            sell_cap -= sz
            n_ask = max(1, n_ask - 1)

        # ======= PHASE 3: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order("EMERALDS", F - 13, buy_cap))
        if sell_cap > 0:
            orders.append(Order("EMERALDS", F + 13, -sell_cap))

        return orders

    # ================================================================ #
    #                   T O M A T O E S                                  #
    # ================================================================ #
    def _tomatoes(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        """
        Mean-reversion market making with EMA fair value.
        5 bid levels + 5 ask levels for maximum edge capture.
        NO trend following (data shows negative edge for trend signals).
        """
        orders = []
        if not od.buy_orders or not od.sell_orders:
            return orders

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        spread = best_ask - best_bid
        mid = (best_bid + best_ask) / 2.0

        # ======= MICROPRICE =======
        bid_vol_l1 = abs(od.buy_orders[best_bid])
        ask_vol_l1 = abs(od.sell_orders[best_ask])
        total_l1 = bid_vol_l1 + ask_vol_l1

        if total_l1 > 0:
            microprice = (best_bid * ask_vol_l1 + best_ask * bid_vol_l1) / total_l1
        else:
            microprice = mid

        # ======= IMBALANCE =======
        total_bid_vol = sum(abs(v) for v in od.buy_orders.values())
        total_ask_vol = sum(abs(v) for v in od.sell_orders.values())
        total_vol = total_bid_vol + total_ask_vol
        imbalance = (total_bid_vol - total_ask_vol) / total_vol if total_vol > 0 else 0

        # ======= PRICE SIGNAL =======
        price_signal = 0.6 * microprice + 0.4 * mid

        # ======= EMA (alpha=0.12, optimal from grid search) =======
        ema = saved.get("t_ema", price_signal)
        iterations = saved.get("iter", 0)
        alpha = 0.5 if iterations < 5 else 0.12
        ema = alpha * price_signal + (1 - alpha) * ema
        saved["t_ema"] = ema

        # ======= FAIR VALUE (NO TREND) =======
        fair = ema + imbalance * 1.5

        # ======= POSITION TRACKING =======
        buy_cap = lim - pos
        sell_cap = lim + pos
        abs_pos = abs(pos)
        skew = pos / lim if lim > 0 else 0

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Only take clear edge (0.5 tick threshold, proven in v5)
        for ask_p in sorted(od.sell_orders.keys()):
            edge = fair - ask_p
            if edge >= 0.5 and buy_cap > 0:
                vol = min(-od.sell_orders[ask_p], buy_cap)
                orders.append(Order("TOMATOES", ask_p, vol))
                buy_cap -= vol
            elif edge < 0.5:
                break

        for bid_p in sorted(od.buy_orders.keys(), reverse=True):
            edge = bid_p - fair
            if edge >= 0.5 and sell_cap > 0:
                vol = min(od.buy_orders[bid_p], sell_cap)
                orders.append(Order("TOMATOES", bid_p, -vol))
                sell_cap -= vol
            elif edge < 0.5:
                break

        # ======= PHASE 2: MULTI-LEVEL PASSIVE QUOTES =======
        inv_offset = skew * 2.0
        fair_int = round(fair)

        # 5 bid levels + 5 ask levels, each 2-3 ticks apart
        # Post relative to fair value for maximum edge
        bid_offsets = [1, 3, 5, 8, 11]  # ticks below fair
        ask_offsets = [1, 3, 5, 8, 11]  # ticks above fair

        bid_prices = []
        ask_prices = []

        for off in bid_offsets:
            bp = math.floor(fair - off - inv_offset)
            bid_prices.append(bp)

        for off in ask_offsets:
            ap = math.ceil(fair + off - inv_offset)
            ask_prices.append(ap)

        # Sizing with inventory skew
        buy_frac = max(0.2, 1.0 - skew * 0.5)
        sell_frac = max(0.2, 1.0 + skew * 0.5)

        n_bid = len(bid_prices)
        n_ask = len(ask_prices)

        for bp in bid_prices:
            if buy_cap <= 0:
                break
            sz = max(1, round(buy_cap / n_bid * buy_frac))
            sz = min(sz, buy_cap)
            orders.append(Order("TOMATOES", bp, sz))
            buy_cap -= sz
            n_bid = max(1, n_bid - 1)

        for ap in ask_prices:
            if sell_cap <= 0:
                break
            sz = max(1, round(sell_cap / n_ask * sell_frac))
            sz = min(sz, sell_cap)
            orders.append(Order("TOMATOES", ap, -sz))
            sell_cap -= sz
            n_ask = max(1, n_ask - 1)

        # ======= PHASE 3: EMERGENCY FLATTEN =======
        if abs_pos >= 16:
            if pos > 0 and sell_cap > 0:
                orders.append(Order("TOMATOES", best_bid, -min(sell_cap, pos - 10)))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order("TOMATOES", best_ask, min(buy_cap, abs_pos - 10)))

        # ======= PHASE 4: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order("TOMATOES", math.floor(fair - 15), buy_cap))
        if sell_cap > 0:
            orders.append(Order("TOMATOES", math.ceil(fair + 15), -sell_cap))

        return orders

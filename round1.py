from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity 4 - Round 1 (v13 — quotes moved to actual fill zone)

    ASH_COATED_OSMIUM (ACO) - limit 80:
      Bot spread: 16 ticks. Bid at F-7..F-8, Ask at F+9..F+10.
      Old quotes at F±2 were in dead zone (3.6% fill rate).
      v13: L1 at F-5/F+7 (inside bot), L2 at F-7/F+9 (at bot), asymmetric.
      v9: 1289, v10: 1019, v11: 1083, v12: pending. Target: 4000+

    INTARIAN_PEPPER_ROOT (IPR) - limit 80:
      After t=10K runs at 100% efficiency (800/10K ticks = theoretical max).
      v13: buy_edge=-20 at start to fill 80 units in first few ticks.
      v10/v11: 7370. Target: 8000+
    """

    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

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
            lim = self.LIMITS.get(product, 80)

            if product == "ASH_COATED_OSMIUM":
                result[product] = self._aco(od, pos, lim, saved)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product] = self._ipr(od, pos, lim, saved, state.timestamp)

        saved["iter"] = saved.get("iter", 0) + 1

        traderData = json.dumps(saved)
        if len(traderData) > 45000:
            traderData = json.dumps({
                "iter": saved.get("iter", 0),
                "aco_ema": saved.get("aco_ema"),
                "ipr_base_ema": saved.get("ipr_base_ema"),
            })

        return result, 0, traderData

    # ================================================================ #
    #   ASH_COATED_OSMIUM — mean-reverting market making (fair=10000)   #
    # ================================================================ #
    def _aco(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        orders = []
        P = "ASH_COATED_OSMIUM"
        F = 10000  # HARDCODED — mean-reversion anchor

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Buy everything below fair, sell everything above fair
        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p < F and buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order(P, ask_p, vol))
                    buy_cap -= vol
                elif ask_p == F and buy_cap > 0:
                    # At fair: unwind opposing position, or nibble if near flat
                    if pos < 0:
                        vol = min(-od.sell_orders[ask_p], buy_cap, abs(pos))
                    elif abs(pos) <= 40:
                        vol = min(-od.sell_orders[ask_p], buy_cap, 20)
                    else:
                        vol = 0
                    if vol > 0:
                        orders.append(Order(P, ask_p, vol))
                        buy_cap -= vol
                else:
                    break

        if od.buy_orders:
            for bid_p in sorted(od.buy_orders.keys(), reverse=True):
                if bid_p > F and sell_cap > 0:
                    vol = min(od.buy_orders[bid_p], sell_cap)
                    orders.append(Order(P, bid_p, -vol))
                    sell_cap -= vol
                elif bid_p == F and sell_cap > 0:
                    if pos > 0:
                        vol = min(od.buy_orders[bid_p], sell_cap, abs(pos))
                    elif abs(pos) <= 40:
                        vol = min(od.buy_orders[bid_p], sell_cap, 20)
                    else:
                        vol = 0
                    if vol > 0:
                        orders.append(Order(P, bid_p, -vol))
                        sell_cap -= vol
                else:
                    break

        # ======= PHASE 2: PASSIVE MARKET MAKING =======
        # Bot spread: bid at F-7..F-8, ask at F+9..F+10 (asymmetric, 16 wide)
        # OLD: L1 at F±2 → 3.6% fill. DEAD ZONE.
        # NEW: L1 at F-5/F+7, L2 at F-7/F+9. Inside bot spread where fills happen.
        skew = pos / lim if lim > 0 else 0
        inv_shift = round(skew * 2)  # reduced from 3/4 to prevent displacement

        # Layer 1: inside bot spread (pennying bots by 2-3 ticks)
        l1_bid = F - 5 - inv_shift   # inside bot bid at F-7
        l1_ask = F + 7 - inv_shift   # inside bot ask at F+9
        # Layer 2: at bot level (competitive)
        l2_bid = F - 7 - inv_shift   # matching bot bid
        l2_ask = F + 9 - inv_shift   # matching bot ask

        # Safety: never post bids above fair or asks below fair
        l1_bid = min(l1_bid, F - 1)
        l2_bid = min(l2_bid, F - 1)
        l1_ask = max(l1_ask, F + 1)
        l2_ask = max(l2_ask, F + 1)

        if l1_ask <= l1_bid:
            l1_ask = l1_bid + 1
        if l2_ask <= l2_bid:
            l2_ask = l2_bid + 1

        # Inventory-skewed sizing
        buy_mult = max(0.1, 1.0 - skew * 0.8)
        sell_mult = max(0.1, 1.0 + skew * 0.8)

        levels = [
            (l1_bid, l1_ask, 0.55),   # primary: inside bot spread
            (l2_bid, l2_ask, 0.35),   # secondary: at bot level
        ]

        for bp, ap, frac in levels:
            buy_sz = max(1, round(buy_cap * frac * buy_mult))
            sell_sz = max(1, round(sell_cap * frac * sell_mult))

            if buy_cap > 0:
                sz = min(buy_sz, buy_cap)
                orders.append(Order(P, int(bp), sz))
                buy_cap -= sz

            if sell_cap > 0:
                sz = min(sell_sz, sell_cap)
                orders.append(Order(P, int(ap), -sz))
                sell_cap -= sz

        # ======= PHASE 3: BACKSTOP =======
        # Deep backstop at bot edges
        if buy_cap > 0:
            orders.append(Order(P, F - 9, buy_cap))   # just outside bot bid
        if sell_cap > 0:
            orders.append(Order(P, F + 10, -sell_cap)) # matching bot ask

        return orders

    # ================================================================ #
    #   INTARIAN_PEPPER_ROOT — trend-following long bias                #
    # ================================================================ #
    def _ipr(self, od: OrderDepth, pos: int, lim: int, saved: dict, ts: int) -> List[Order]:
        """
        Price model: price(ts) = base + 0.001 * ts
        After t=10K runs at 100% efficiency (800 XiRECs per 10K ticks).
        v13: Market-buy all 80 units in first few ticks.
        Every 100-tick delay costs 8 XiRECs. Paying 20 ticks premium
        is recovered in 250 timestamps.
        """
        orders = []
        P = "INTARIAN_PEPPER_ROOT"

        if not od.buy_orders and not od.sell_orders:
            return orders

        # Current book state
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            mid = float(best_bid)
        elif best_ask is not None:
            mid = float(best_ask)
        else:
            return orders

        # Estimate base price using detrended EMA
        detrended = mid - 0.001 * ts

        base_ema = saved.get("ipr_base_ema", detrended)
        itr = saved.get("iter", 0)

        # Fast warmup then slow tracking
        alpha = 0.8 if itr < 10 else 0.01
        base_ema = alpha * detrended + (1 - alpha) * base_ema
        saved["ipr_base_ema"] = base_ema

        # Fair value = trend-adjusted base
        fair = base_ema + 0.001 * ts

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE (long-biased) =======
        # Every timestamp at 80 units earns 0.08 XiRECs.
        # Paying 20 ticks premium = breakeven in 250 timestamps.
        # Be MAXIMALLY aggressive in first iterations.

        if itr < 5:
            # FIRST 5 TICKS: market buy everything, pay any price
            buy_edge = -20.0
        elif pos < 20:
            buy_edge = -12.0  # still extremely aggressive
        elif pos < 40:
            buy_edge = -8.0
        elif pos < 60:
            buy_edge = -4.0
        elif pos < 75:
            buy_edge = -1.0
        else:
            buy_edge = 0.5

        # Sell edge: NEVER sell below position 70
        if pos < 70:
            sell_edge = 999.0
        elif pos < 78:
            sell_edge = 8.0
        else:
            sell_edge = 6.0

        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                edge = fair - ask_p
                if edge >= buy_edge and buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order(P, ask_p, vol))
                    buy_cap -= vol
                elif edge < buy_edge:
                    break

        if od.buy_orders:
            for bid_p in sorted(od.buy_orders.keys(), reverse=True):
                edge = bid_p - fair
                if edge >= sell_edge and sell_cap > 0:
                    vol = min(od.buy_orders[bid_p], sell_cap)
                    orders.append(Order(P, bid_p, -vol))
                    sell_cap -= vol
                elif edge < sell_edge:
                    break

        # ======= PHASE 2: PASSIVE QUOTES (long-biased) =======
        fair_int = round(fair)

        if itr < 5:
            # First 5 ticks: bid at fair+5 to guarantee fills
            bid_offset = -5   # negative = above fair (guaranteed fill)
            ask_offset = 20   # never sell
            bid_size = 80     # max size
            ask_size = 0
        elif pos < 40:
            bid_offset = 1
            ask_offset = 12
            bid_size = 40
            ask_size = 3
        elif pos < 60:
            bid_offset = 2
            ask_offset = 10
            bid_size = 30
            ask_size = 3
        elif pos < 70:
            bid_offset = 2
            ask_offset = 10
            bid_size = 20
            ask_size = 3
        elif pos < 78:
            bid_offset = 3
            ask_offset = 8
            bid_size = 10
            ask_size = 5
        else:
            bid_offset = 5
            ask_offset = 6
            bid_size = 5
            ask_size = 10

        q_bid = fair_int - bid_offset
        q_ask = fair_int + ask_offset

        # Don't cross the book
        if best_ask is not None and q_bid >= best_ask:
            q_bid = best_ask - 1
        if best_bid is not None and q_ask <= best_bid:
            q_ask = best_bid + 1
        if q_ask <= q_bid:
            q_ask = q_bid + 1

        if buy_cap > 0 and bid_size > 0:
            sz = min(bid_size, buy_cap)
            orders.append(Order(P, q_bid, sz))
            buy_cap -= sz

        # Only post sell orders at high position
        if pos >= 70 and sell_cap > 0 and ask_size > 0:
            sz = min(ask_size, sell_cap)
            orders.append(Order(P, q_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 3: DEEP LAYER =======
        deep_bid = q_bid - 4

        if buy_cap > 0:
            sz = min(30, buy_cap)
            orders.append(Order(P, deep_bid, sz))
            buy_cap -= sz

        if pos >= 75 and sell_cap > 0:
            deep_ask = q_ask + 5
            sz = min(5, sell_cap)
            orders.append(Order(P, deep_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 4: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order(P, fair_int - 10, buy_cap))

        if pos >= 75 and sell_cap > 0:
            orders.append(Order(P, fair_int + 15, -sell_cap))

        return orders

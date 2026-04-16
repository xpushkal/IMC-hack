from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity 4 - Round 1 (v16 — v13 base + safe wider taking at F+3)

    ASH_COATED_OSMIUM (ACO) - limit 80:
      v15 LESSON: taking at F+5..F+7 causes catastrophic inventory losses.
      Thin edge (+1..+3) gets destroyed by mean-reversion when passive sell doesn't fill.
      SAFE ZONE: buy up to F+3 max (edge vs F+8 sell = +5 min, survives reversion).
      v13: 2179 (best ACO). v15: -677 (too aggressive). Target: 3000+

    INTARIAN_PEPPER_ROOT (IPR) - limit 80:
      After t=10K: 100% efficiency (800/10K = theoretical max).
      v13: 7354. Near perfect.
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
        # SAFE ZONE: buy up to F+3 max (edge vs F+8 sell = +5, survives reversion)
        # v15 proved F+5..F+7 is DISASTER (mean reversion kills thin edge)
        # Position-dependent thresholds for inventory management

        if pos < -40:
            buy_up_to = F + 3    # aggressive to flatten short
            sell_down_to = F + 1 # don't sell when very short
        elif pos < -10:
            buy_up_to = F + 3    # still aggressive
            sell_down_to = F - 2
        elif pos < 10:
            buy_up_to = F + 3    # near flat: take best available
            sell_down_to = F - 3
        elif pos < 40:
            buy_up_to = F + 2    # moderate long
            sell_down_to = F - 3
        elif pos < 60:
            buy_up_to = F + 1    # getting full
            sell_down_to = F - 4 # aggressive flatten
        else:
            buy_up_to = F        # near limit: only below fair
            sell_down_to = F - 5 # max flatten

        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p <= buy_up_to and buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order(P, ask_p, vol))
                    buy_cap -= vol
                else:
                    break

        if od.buy_orders:
            for bid_p in sorted(od.buy_orders.keys(), reverse=True):
                if bid_p >= sell_down_to and sell_cap > 0:
                    vol = min(od.buy_orders[bid_p], sell_cap)
                    orders.append(Order(P, bid_p, -vol))
                    sell_cap -= vol
                else:
                    break

        # ======= PHASE 2: PASSIVE MARKET MAKING =======
        # v13 proven levels: L1 at F-6/F+8, L2 at F-8/F+9
        skew = pos / lim if lim > 0 else 0
        inv_shift = round(skew * 2)

        # Layer 1: inside bot spread
        l1_bid = F - 6 - inv_shift
        l1_ask = F + 8 - inv_shift
        # Layer 2: at bot level
        l2_bid = F - 8 - inv_shift
        l2_ask = F + 9 - inv_shift

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
            (l1_bid, l1_ask, 0.55),
            (l2_bid, l2_ask, 0.35),
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
        if buy_cap > 0:
            orders.append(Order(P, F - 10, buy_cap))
        if sell_cap > 0:
            orders.append(Order(P, F + 11, -sell_cap))

        return orders

    # ================================================================ #
    #   INTARIAN_PEPPER_ROOT — trend-following long bias                #
    # ================================================================ #
    def _ipr(self, od: OrderDepth, pos: int, lim: int, saved: dict, ts: int) -> List[Order]:
        """
        After t=10K: 100% efficiency (800/10K = theoretical max).
        v13: 7354. Near perfect.
        """
        orders = []
        P = "INTARIAN_PEPPER_ROOT"

        if not od.buy_orders and not od.sell_orders:
            return orders

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

        detrended = mid - 0.001 * ts
        base_ema = saved.get("ipr_base_ema", detrended)
        itr = saved.get("iter", 0)

        alpha = 0.8 if itr < 10 else 0.01
        base_ema = alpha * detrended + (1 - alpha) * base_ema
        saved["ipr_base_ema"] = base_ema

        fair = base_ema + 0.001 * ts

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        if itr < 5:
            buy_edge = -20.0
        elif pos < 20:
            buy_edge = -12.0
        elif pos < 40:
            buy_edge = -8.0
        elif pos < 60:
            buy_edge = -4.0
        elif pos < 75:
            buy_edge = -1.0
        else:
            buy_edge = 0.5

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

        # ======= PHASE 2: PASSIVE QUOTES =======
        fair_int = round(fair)

        if itr < 5:
            bid_offset = -5
            ask_offset = 20
            bid_size = 80
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

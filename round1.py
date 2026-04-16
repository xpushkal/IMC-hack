from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity 4 - Round 1 (v11 — tuned from 188461 results)

    ASH_COATED_OSMIUM (ACO) - limit 80:
      Mean-reverting around 10000 but mid deviates >2 ticks 32% of time.
      Strategy: dynamic fair from book, F±2 quotes, moderate skew=3.
      v9: 1289, v10: 1019 (regressed from F±1), target: 1500+

    INTARIAN_PEPPER_ROOT (IPR) - limit 80:
      Deterministic linear uptrend: price(ts) = base + 0.001 * timestamp.
      Strategy: ultra-aggressive buy to 80 ASAP, never sell below pos=70.
      v10: 7370 (+25% vs v9), keep as-is.
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

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ---- Dynamic fair value from book ----
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            mid = (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            spread = 16
            mid = float(best_bid + 8)
        elif best_ask is not None:
            spread = 16
            mid = float(best_ask - 8)
        else:
            return orders

        # Anchor fair toward 10000 but track the book
        # 70% book mid, 30% anchor — prevents adverse selection when mid drifts
        F_raw = 0.7 * mid + 0.3 * 10000
        F = round(F_raw)

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Buy everything below fair, sell everything above fair
        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p < F and buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order(P, ask_p, vol))
                    buy_cap -= vol
                elif ask_p == F and buy_cap > 0:
                    # At fair value: take to unwind or nibble conservatively
                    if pos < 0:
                        vol = min(-od.sell_orders[ask_p], buy_cap, abs(pos))
                    else:
                        vol = min(-od.sell_orders[ask_p], buy_cap, 20)
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
                    else:
                        vol = min(od.buy_orders[bid_p], sell_cap, 20)
                    if vol > 0:
                        orders.append(Order(P, bid_p, -vol))
                        sell_cap -= vol
                else:
                    break

        # ======= PHASE 2: PASSIVE MARKET MAKING =======
        skew = pos / lim if lim > 0 else 0
        inv_shift = round(skew * 3)  # v9=5 (too wide), v10=2 (too tight), v11=3

        # Adaptive spread based on current book conditions
        if spread <= 8:
            # Tight spread: penny the market at F±1
            l1_bid = F - 1 - inv_shift
            l1_ask = F + 1 - inv_shift
            l2_bid = F - 2 - inv_shift
            l2_ask = F + 2 - inv_shift
        elif spread <= 16:
            # Normal spread (62% of time): F±2 with L2 at F±4
            l1_bid = F - 2 - inv_shift
            l1_ask = F + 2 - inv_shift
            l2_bid = F - 4 - inv_shift
            l2_ask = F + 4 - inv_shift
        else:
            # Wide spread: wider quotes
            l1_bid = F - 3 - inv_shift
            l1_ask = F + 3 - inv_shift
            l2_bid = F - 5 - inv_shift
            l2_ask = F + 5 - inv_shift

        # Safety: never post bids above fair or asks below fair
        l1_bid = min(l1_bid, F - 1)
        l2_bid = min(l2_bid, F - 1)
        l1_ask = max(l1_ask, F + 1)
        l2_ask = max(l2_ask, F + 1)

        if l1_ask <= l1_bid:
            l1_ask = l1_bid + 1
        if l2_ask <= l2_bid:
            l2_ask = l2_bid + 1

        # Inventory-skewed sizing (moderate)
        buy_mult = max(0.15, 1.0 - skew * 0.7)
        sell_mult = max(0.15, 1.0 + skew * 0.7)

        levels = [
            (l1_bid, l1_ask, 0.50),  # tight layer: most volume here
            (l2_bid, l2_ask, 0.35),  # mid layer
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
        # Catch remaining capacity at wider levels
        if buy_cap > 0:
            orders.append(Order(P, F - 7 - inv_shift, buy_cap))
        if sell_cap > 0:
            orders.append(Order(P, F + 7 - inv_shift, -sell_cap))

        return orders

    # ================================================================ #
    #   INTARIAN_PEPPER_ROOT — trend-following long bias                #
    # ================================================================ #
    def _ipr(self, od: OrderDepth, pos: int, lim: int, saved: dict, ts: int) -> List[Order]:
        """
        Price model: price(ts) = base + 0.001 * ts
        Slope confirmed at exactly 0.001 per timestamp across all 3 days.
        v10: Ultra-aggressive buying, no selling below pos=70.
        Expected: 80 units held for ~99K timestamps = ~7,920 XiRECs from trend alone.
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
        alpha = 0.8 if itr < 10 else 0.01  # was 0.5/5/0.02 — faster warmup, slower track
        base_ema = alpha * detrended + (1 - alpha) * base_ema
        saved["ipr_base_ema"] = base_ema

        # Fair value = trend-adjusted base
        fair = base_ema + 0.001 * ts

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE (long-biased) =======
        # Key insight: every timestamp held at full position earns 0.08 XiRECs.
        # So paying 8 ticks premium to buy 500 timestamps earlier = breakeven.
        # Be EXTREMELY aggressive buying, especially early.

        if pos < 20:
            buy_edge = -8.0   # pay up to fair+8 — get long IMMEDIATELY
        elif pos < 40:
            buy_edge = -6.0   # still very aggressive
        elif pos < 60:
            buy_edge = -3.0   # moderate but willing to pay up
        elif pos < 75:
            buy_edge = -1.0   # near fair
        else:
            buy_edge = 0.5    # slight discount only when near limit

        # Sell edge: NEVER sell below position 70
        # Every unit sold costs ~13 ticks to rebuy (spread) = 1300 timestamps of trend holding
        if pos < 70:
            sell_edge = 999.0   # effectively never sell
        elif pos < 78:
            sell_edge = 8.0     # only at huge premium
        else:
            sell_edge = 6.0     # large premium when at max

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

        if pos < 40:
            # Ultra-aggressive: bid near fair, ask far above
            bid_offset = 1
            ask_offset = 12   # was 8 — push asks way out to prevent fills
            bid_size = 40     # was 30 — maximize buy volume
            ask_size = 3      # was 5 — minimize sell exposure
        elif pos < 60:
            bid_offset = 2
            ask_offset = 10   # was 7
            bid_size = 30     # was 25
            ask_size = 3      # was 8
        elif pos < 70:
            bid_offset = 2
            ask_offset = 10   # was 5 — keep asks far even here
            bid_size = 20     # was 15
            ask_size = 3      # was 12
        elif pos < 78:
            bid_offset = 3
            ask_offset = 8
            bid_size = 10
            ask_size = 5
        else:
            # At max: wide bids, moderate asks
            bid_offset = 5
            ask_offset = 6    # was 4 — still not too tight
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

        if buy_cap > 0:
            sz = min(bid_size, buy_cap)
            orders.append(Order(P, q_bid, sz))
            buy_cap -= sz

        # Only post sell orders at high position
        if pos >= 70 and sell_cap > 0:
            sz = min(ask_size, sell_cap)
            orders.append(Order(P, q_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 3: DEEP LAYER =======
        deep_bid = q_bid - 4   # was -3

        if buy_cap > 0:
            sz = min(30, buy_cap)  # was 25 — more aggressive backstop buying
            orders.append(Order(P, deep_bid, sz))
            buy_cap -= sz

        # Only post deep sells near max position
        if pos >= 75 and sell_cap > 0:
            deep_ask = q_ask + 5  # was +4
            sz = min(5, sell_cap)
            orders.append(Order(P, deep_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 4: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order(P, fair_int - 10, buy_cap))  # was -8, wider to catch crashes

        # Only backstop sells at very high position
        if pos >= 75 and sell_cap > 0:
            orders.append(Order(P, fair_int + 15, -sell_cap))  # was +12

        return orders

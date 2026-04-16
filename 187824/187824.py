from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity 4 - Round 1

    ASH_COATED_OSMIUM (ACO) - limit 80:
      Stable mean-reverting fair value = 10000. Bot spread ~16 (9992/10008).
      Strategy: aggressive taking + tight market making around 10000.
      Autocorrelation = -0.5 (strong mean reversion).

    INTARIAN_PEPPER_ROOT (IPR) - limit 80:
      Deterministic linear uptrend: price(ts) = base + 0.001 * timestamp.
      Gains ~1000 per day (10000 iterations). Trend P&L dominates (~80K).
      Strategy: accumulate max long position ASAP, hold, only sell at premium.
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
        F = 10000  # rock-stable fair value across all 3 historical days

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Buy anything priced below fair
        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p < F and buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order(P, ask_p, vol))
                    buy_cap -= vol
                elif ask_p == F and buy_cap > 0:
                    # At fair: buy to unwind short, or nibble if near flat
                    if pos < 0:
                        vol = min(-od.sell_orders[ask_p], buy_cap, abs(pos))
                    elif abs(pos) <= 40:
                        vol = min(-od.sell_orders[ask_p], buy_cap, 15)
                    else:
                        vol = 0
                    if vol > 0:
                        orders.append(Order(P, ask_p, vol))
                        buy_cap -= vol
                else:
                    break

        # Sell anything priced above fair
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
                        vol = min(od.buy_orders[bid_p], sell_cap, 15)
                    else:
                        vol = 0
                    if vol > 0:
                        orders.append(Order(P, bid_p, -vol))
                        sell_cap -= vol
                else:
                    break

        # ======= PHASE 2: PASSIVE MARKET MAKING =======
        skew = pos / lim if lim > 0 else 0
        inv_shift = round(skew * 5)

        # Layer 1: tight (penny ahead of bots at 9992/10008)
        l1_bid = F - 2 - inv_shift
        l1_ask = F + 2 - inv_shift
        # Layer 2: mid
        l2_bid = F - 4 - inv_shift
        l2_ask = F + 4 - inv_shift
        # Layer 3: wide backstop
        l3_bid = F - 7 - inv_shift
        l3_ask = F + 7 - inv_shift

        # Safety: never post bids above fair or asks below fair
        for lvl in [(l1_bid, l1_ask), (l2_bid, l2_ask), (l3_bid, l3_ask)]:
            pass  # clamp below
        l1_bid = min(l1_bid, F - 1)
        l2_bid = min(l2_bid, F - 1)
        l3_bid = min(l3_bid, F - 1)
        l1_ask = max(l1_ask, F + 1)
        l2_ask = max(l2_ask, F + 1)
        l3_ask = max(l3_ask, F + 1)

        if l1_ask <= l1_bid:
            l1_ask = l1_bid + 1
        if l2_ask <= l2_bid:
            l2_ask = l2_bid + 1

        # Inventory-skewed sizing: reduce side toward limit
        buy_mult = max(0.1, 1.0 - skew * 0.8)
        sell_mult = max(0.1, 1.0 + skew * 0.8)

        levels = [
            (l1_bid, l1_ask, 0.50),
            (l2_bid, l2_ask, 0.30),
            (l3_bid, l3_ask, 1.00),
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
            orders.append(Order(P, F + 10, -sell_cap))

        return orders

    # ================================================================ #
    #   INTARIAN_PEPPER_ROOT — trend-following long bias                #
    # ================================================================ #
    def _ipr(self, od: OrderDepth, pos: int, lim: int, saved: dict, ts: int) -> List[Order]:
        """
        Price model: price(ts) = base + 0.001 * ts
        Slope confirmed at exactly 0.001 per timestamp across all 3 days.
        Expected profit from holding 80 units full day: ~80,000 XiRECs.
        Strategy: get to +80 ASAP, hold, only sell at large premium.
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
        # true_price = base + 0.001 * ts  =>  base = price - 0.001 * ts
        detrended = mid - 0.001 * ts

        base_ema = saved.get("ipr_base_ema", detrended)
        itr = saved.get("iter", 0)

        # Fast warmup, then slow tracking
        alpha = 0.5 if itr < 5 else 0.02
        base_ema = alpha * detrended + (1 - alpha) * base_ema
        saved["ipr_base_ema"] = base_ema

        # Fair value = trend-adjusted base
        fair = base_ema + 0.001 * ts

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE (long-biased) =======
        # Since price goes UP, buying is almost always profitable.
        # Be very aggressive buying, very conservative selling.

        # Buy edge: how far below fair we require the ask to be
        # Negative = willing to pay ABOVE fair (because trend gains ~0.1/tick)
        if pos < 20:
            buy_edge = -3.0   # pay up to fair+3 to build position fast
        elif pos < 40:
            buy_edge = -2.0   # still aggressive
        elif pos < 60:
            buy_edge = -1.0   # moderate
        elif pos < 75:
            buy_edge = 0.0    # at fair
        else:
            buy_edge = 1.0    # only below fair when near limit

        # Sell edge: only sell at significant premium above fair
        if pos < 40:
            sell_edge = 100.0   # never sell when building position
        elif pos < 60:
            sell_edge = 8.0     # only at huge premium
        elif pos < 75:
            sell_edge = 5.0     # at premium
        else:
            sell_edge = 3.0     # more willing to trade at high position

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
            # Very aggressive: bid near fair, ask far above
            bid_offset = 1
            ask_offset = 8
            bid_size = 30
            ask_size = 5
        elif pos < 60:
            bid_offset = 2
            ask_offset = 7
            bid_size = 25
            ask_size = 8
        elif pos < 75:
            bid_offset = 3
            ask_offset = 5
            bid_size = 15
            ask_size = 12
        else:
            # Near limit: wider bids, tighter asks
            bid_offset = 5
            ask_offset = 4
            bid_size = 8
            ask_size = 20

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

        if sell_cap > 0:
            sz = min(ask_size, sell_cap)
            orders.append(Order(P, q_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 3: DEEP LAYER =======
        deep_bid = q_bid - 3
        deep_ask = q_ask + 4

        if buy_cap > 0:
            sz = min(25, buy_cap)
            orders.append(Order(P, deep_bid, sz))
            buy_cap -= sz

        if sell_cap > 0:
            sz = min(5, sell_cap)
            orders.append(Order(P, deep_ask, -sz))
            sell_cap -= sz

        # ======= PHASE 4: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order(P, fair_int - 8, buy_cap))
        if sell_cap > 0:
            orders.append(Order(P, fair_int + 12, -sell_cap))

        return orders
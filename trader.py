from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity 4 — Round 2 Strategy v2 (tuned from live results)

    Live R2 run #1 analysis (8167 PnL):
    - ACO: 593 PnL — passive quotes at F-6/F+8 sat AT bot levels, zero fills
    - IPR: 7574 PnL — 94.7% of theoretical max, near optimal

    v2 changes:
    - ACO: dynamic fair value via EMA of mid, tighter 3-layer quotes
      inside the 16-tick bot spread for price priority
    - ACO: penny-ahead logic to beat bot queue priority
    - IPR: reduce early aggression to get better entry prices
    """

    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    def __init__(self):
        pass

    def bid(self):
        """
        Market Access Fee bid — one-time cost deducted from R2 profit if accepted.
        Top 50% of bids get 25% more quotes in the order book.
        250 is safely in top 50% while being a negligible cost vs expected benefit.
        """
        return 250

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
        """
        ACO mean-reverts around F=10000.

        Live R2 analysis:
        - Bot spread is 16 ticks wide (best bid ~9994-10001, best ask ~10008-10017)
        - Bot best bid distribution: 9994(14%), 9998(11%), 9999(11%), 9995(10%)
        - Bot best ask distribution: 10010(13%), 10015(10%), 10014(10%), 10013(10%)
        - Our old passive quotes at 9994/10008 sat AT bot levels = zero priority

        v2: Use dynamic fair, penny-ahead bots, tighter spread for more fills.
        """
        orders = []
        P = "ASH_COATED_OSMIUM"
        F_ANCHOR = 10000  # long-term mean anchor

        # Dynamic fair value from order book mid
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is not None and best_ask is not None:
            mid = (best_bid + best_ask) / 2.0
        elif best_bid is not None:
            mid = float(best_bid)
        elif best_ask is not None:
            mid = float(best_ask)
        else:
            mid = float(F_ANCHOR)

        # EMA of mid for fair value, anchored toward 10000
        aco_ema = saved.get("aco_ema", mid)
        itr = saved.get("iter", 0)
        alpha = 0.3 if itr < 5 else 0.05
        aco_ema = alpha * mid + (1 - alpha) * aco_ema
        # Anchor toward 10000 to prevent drift
        aco_ema = 0.95 * aco_ema + 0.05 * F_ANCHOR
        saved["aco_ema"] = aco_ema

        F = round(aco_ema)

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Take any orders that are clearly mispriced vs our fair value.
        # KEY FIX: Never sell below F+1 when flat — selling below fair = loss.
        # Volume cap: max 15 units per tick to prevent position blowout.
        if pos < -40:
            buy_up_to = F + 5    # aggressive to flatten short
            sell_down_to = F + 3 # don't sell when deeply short
        elif pos < -10:
            buy_up_to = F + 4
            sell_down_to = F + 1 # only sell ABOVE fair when short
        elif pos < 10:
            buy_up_to = F + 4    # near flat: grab good prices
            sell_down_to = F + 1 # NEVER sell below fair when flat
        elif pos < 30:
            buy_up_to = F + 3
            sell_down_to = F     # sell at fair OK when slightly long
        elif pos < 50:
            buy_up_to = F + 2
            sell_down_to = F - 1 # moderate flatten
        elif pos < 65:
            buy_up_to = F + 1
            sell_down_to = F - 2 # aggressive flatten
        else:
            buy_up_to = F
            sell_down_to = F - 3 # max flatten near limit

        max_take = 15  # volume cap per tick — prevent instant blowout

        if od.sell_orders:
            taken = 0
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p <= buy_up_to and buy_cap > 0 and taken < max_take:
                    vol = min(-od.sell_orders[ask_p], buy_cap, max_take - taken)
                    orders.append(Order(P, ask_p, vol))
                    buy_cap -= vol
                    taken += vol
                else:
                    break

        if od.buy_orders:
            taken = 0
            for bid_p in sorted(od.buy_orders.keys(), reverse=True):
                if bid_p >= sell_down_to and sell_cap > 0 and taken < max_take:
                    vol = min(od.buy_orders[bid_p], sell_cap, max_take - taken)
                    orders.append(Order(P, bid_p, -vol))
                    sell_cap -= vol
                    taken += vol
                else:
                    break

        # ======= PHASE 2: TIGHT PASSIVE MARKET MAKING =======
        # KEY CHANGE: quote INSIDE the bot spread to get price priority.
        # Bot bids cluster at 9992-9999, bot asks at 10008-10017.
        # We post 1 tick better than bots to get filled first.
        skew = pos / lim if lim > 0 else 0
        inv_shift = round(skew * 3)  # More aggressive inventory shift

        # Penny-ahead logic: if we see bot best bid/ask, post 1 tick inside
        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            if spread >= 6:
                # Wide spread — penny ahead of bots
                l1_bid = best_bid + 1 - inv_shift
                l1_ask = best_ask - 1 - inv_shift
            else:
                # Tight spread — use fair ± small offset
                l1_bid = F - 2 - inv_shift
                l1_ask = F + 3 - inv_shift
        else:
            l1_bid = F - 2 - inv_shift
            l1_ask = F + 3 - inv_shift

        # Layer 2: slightly wider
        l2_bid = F - 4 - inv_shift
        l2_ask = F + 6 - inv_shift

        # Layer 3: at bot level for deeper fills
        l3_bid = F - 7 - inv_shift
        l3_ask = F + 9 - inv_shift

        # Safety: never post bids above fair or asks below fair
        for i, (bid, ask) in enumerate([(l1_bid, l1_ask), (l2_bid, l2_ask), (l3_bid, l3_ask)]):
            bid = min(bid, F)
            ask = max(ask, F + 1)
            if ask <= bid:
                ask = bid + 1
            if i == 0:
                l1_bid, l1_ask = bid, ask
            elif i == 1:
                l2_bid, l2_ask = bid, ask
            else:
                l3_bid, l3_ask = bid, ask

        # Inventory-skewed sizing — lean harder into rebalancing
        buy_mult = max(0.1, 1.0 - skew)
        sell_mult = max(0.1, 1.0 + skew)

        levels = [
            (l1_bid, l1_ask, 0.40),  # tight layer: most volume
            (l2_bid, l2_ask, 0.30),  # medium layer
            (l3_bid, l3_ask, 0.20),  # wide layer: backstop
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
            orders.append(Order(P, F + 12, -sell_cap))

        return orders

    # ================================================================ #
    #   INTARIAN_PEPPER_ROOT — trend-following long bias                #
    # ================================================================ #
    def _ipr(self, od: OrderDepth, pos: int, lim: int, saved: dict, ts: int) -> List[Order]:
        """
        IPR has a perfect linear uptrend: +0.001 per timestamp (+1 per 1000ts).

        Live R2 result: 7574 PnL = 94.7% of theoretical max (8000).
        Already near-optimal. v2 tweaks: slightly less aggressive early entry
        to avoid overpaying in the first few ticks when spread is wide.
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

        # Detrend mid-price to get baseline, then reconstruct fair value
        detrended = mid - 0.001 * ts
        base_ema = saved.get("ipr_base_ema", detrended)
        itr = saved.get("iter", 0)

        alpha = 0.5 if itr < 5 else 0.01
        base_ema = alpha * detrended + (1 - alpha) * base_ema
        saved["ipr_base_ema"] = base_ema

        fair = base_ema + 0.001 * ts

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # v2: less aggressive in first 3 ticks — spread is wide (14 ticks),
        # don't pay up 20 ticks just to get early position.
        # But still aggressive enough to accumulate quickly.
        if itr < 3:
            buy_edge = -10.0    # was -20, reduce overpay on initial fills
        elif itr < 8:
            buy_edge = -8.0     # still aggressive early
        elif pos < 20:
            buy_edge = -6.0
        elif pos < 40:
            buy_edge = -4.0
        elif pos < 60:
            buy_edge = -2.0
        elif pos < 75:
            buy_edge = -0.5
        else:
            buy_edge = 1.0

        # Almost never sell — only when near position cap
        if pos < 70:
            sell_edge = 999.0   # effectively never sell
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
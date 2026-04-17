from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity 4 – Round 2 (Refined from Round 1 v16 + Round 2 data analysis)

    TARGET: 200,000+ XIRECs net PnL

    === DATA-DRIVEN INSIGHTS (Round 2 analysis) ===

    ASH_COATED_OSMIUM (ACO) – limit 80:
      - Mean-reverts around EXACTLY 10000 (confirmed across all 3 days of R2 data)
      - Spread: 16 ticks (59% of time), occasionally 5-13 (tight) or 18-21 (wide)
      - L1 ask typically at 10008-10010, L1 bid at 9992-9994
      - Autocorrelation: 0.66 at lag-1, slowly decaying (mean reversion is SLOW)
      - Theoretical PnL: ~3500/day from buy<10000/sell>10000
      - Strategy: proven v16 approach — position-dependent take thresholds + 2-layer MM

    INTARIAN_PEPPER_ROOT (IPR) – limit 80:
      - PERFECT linear trend: price = day_start + 0.001 * timestamp
      - Each day: +1000 price move (day-1: 11000→12000, day0: 12000→13000, day1: 13000→14000)
      - Residuals: stdev 2.2-2.5, range ±11 (tiny vs 1000 daily move)
      - L1 ask/bid typically ±6-7 from fair
      - Fill speed: 80 units filled within ts=500-700 (first 0.07% of day)
      - Theoretical PnL: ~79,300/day (buy 80 ASAP, hold to end)
      - Strategy: buy everything immediately, hold forever, only sell at extreme premium

    === MAF BID ===
      - Extra 25% volume is worth ~1000-2000/day extra (faster IPR fills + more ACO flow)
      - Bid 15 XIRECs: conservative, should clear median in game-theory equilibrium
      - Cost is one-time, paid only if accepted

    === MANUAL ALLOCATION (50,000 XIRECs) ===
      RECOMMENDED: Research=23%, Scale=77%, Speed=0%
      - Research(23) = 137,724 (logarithmic, diminishing returns above ~25%)
      - Scale(77) = 5.39 (linear, scales best with budget)
      - Speed(0) = game-theory: if many bid 0, everyone ties at rank 1 → 0.9 multiplier
      - Expected PnL at speed 0.5: ~321,000 XIRECs (after 50k budget deduction)
    """

    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # IPR trend slope (confirmed: exactly 0.001 per timestamp unit across all days)
    IPR_SLOPE = 0.001

    def __init__(self):
        pass

    def bid(self):
        """
        Market Access Fee bid for extra 25% order book volume.
        Game theory: need to be in top 50% of all bids.
        15 XIRECs is moderate — should beat the many conservative/zero bidders
        while not overpaying. Extra volume is worth ~3000-6000 over the round.
        """
        return 15

    # ------------------------------------------------------------------
    #  Main entry point
    # ------------------------------------------------------------------
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
                "ipr_base": saved.get("ipr_base"),
            })

        return result, 0, traderData

    # ==================================================================
    #   ASH_COATED_OSMIUM — mean-reverting market making (fair = 10000)
    # ==================================================================
    def _aco(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        """
        Proven v16 strategy with minor tightening based on R2 data:
        - Fair value = 10000 (rock-solid across all R2 days)
        - Position-dependent take thresholds (buy_up_to, sell_down_to)
        - 2-layer passive market making with inventory skew
        - Backstop layer to catch extreme dislocations

        R2 data confirms:
        - Spread mostly 16 (L1 ask ~10008, L1 bid ~9993)
        - Profitable edge exists buying at 10003 or below, selling at 9997 or above
        - Risk: taking at F+5..F+7 causes inventory losses (v15 lesson)
        """
        orders = []
        P = "ASH_COATED_OSMIUM"
        F = 10000  # Hardcoded fair — mean-reversion anchor

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # Position-dependent thresholds (proven in v16)
        # SAFE ZONE: buy up to F+3 max to survive mean reversion
        if pos < -40:
            buy_up_to = F + 3     # aggressive to flatten short
            sell_down_to = F + 1  # don't sell when very short
        elif pos < -10:
            buy_up_to = F + 3
            sell_down_to = F - 2
        elif pos < 10:
            buy_up_to = F + 3    # near flat: take best available
            sell_down_to = F - 3
        elif pos < 40:
            buy_up_to = F + 2    # moderate long: tighten buys
            sell_down_to = F - 3
        elif pos < 60:
            buy_up_to = F + 1    # getting full
            sell_down_to = F - 4  # aggressive flatten
        else:
            buy_up_to = F        # near limit: only below fair
            sell_down_to = F - 5  # max flatten

        # Mirror for short positions (symmetric sell thresholds)
        if pos > 40:
            sell_down_to = min(sell_down_to, F - 3)
        if pos > 60:
            sell_down_to = min(sell_down_to, F - 4)

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
        # R2 data shows L1 ask at ~10008-10010, L1 bid at ~9992-9994
        # Our passive quotes should sit INSIDE the bot spread to get priority fills
        skew = pos / lim if lim > 0 else 0
        inv_shift = round(skew * 2)

        # Layer 1: inside bot spread (proven v13/v16 levels)
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

    # ==================================================================
    #   INTARIAN_PEPPER_ROOT — trend-following long bias
    # ==================================================================
    def _ipr(self, od: OrderDepth, pos: int, lim: int, saved: dict, ts: int) -> List[Order]:
        """
        R2 data confirms:
        - EXACT linear trend: price = base + 0.001 * timestamp
        - Each day moves +1000 (day-1: 11k→12k, day0: 12k→13k, day1: 13k→14k)
        - Residual stdev ≈ 2.3 (trivial vs 1000/day move)
        - 80 units can be filled within first 500-700 ticks

        Strategy: Buy 80 units ASAP, hold to end of day.
        - PnL ≈ 79,000/day from pure trend capture
        - Only sell at extreme premium (bid >> fair) to manage risk at position limit
        - Bootstrap fair value from first observed mid price
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

        # Bootstrap base price from first observation
        # fair(t) = base + 0.001 * t
        # At t=0, fair = base ≈ first mid
        itr = saved.get("iter", 0)

        # Use detrended EMA to track the base (intercept) robustly
        detrended = mid - self.IPR_SLOPE * ts
        base_ema = saved.get("ipr_base", detrended)

        # Fast warmup, then slow tracking
        alpha = 0.8 if itr < 10 else 0.01
        base_ema = alpha * detrended + (1 - alpha) * base_ema
        saved["ipr_base"] = base_ema

        fair = base_ema + self.IPR_SLOPE * ts

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE BUY (buy everything available) =======
        # Since price rises ~1000/day and residuals are tiny (~2.3 stdev),
        # buying at ANY price in the first half of the day is massively profitable.
        # Even buying at fair+10 at t=0 yields 1000-10 = 990 profit by end of day.

        # Early game (first 20% of day): buy everything regardless of edge
        # Mid game: buy below fair + generous threshold
        # Late game: buy only below fair (trend upside shrinking)
        remaining_move = self.IPR_SLOPE * (999900 - ts)  # expected remaining price appreciation

        if itr < 5:
            # Startup: buy everything aggressively
            buy_edge = -20.0
        elif remaining_move > 800:
            # Early day (>80% of move remaining): buy aggressively
            if pos < 20:
                buy_edge = -15.0
            elif pos < 40:
                buy_edge = -12.0
            elif pos < 60:
                buy_edge = -8.0
            elif pos < 75:
                buy_edge = -4.0
            else:
                buy_edge = -1.0
        elif remaining_move > 500:
            # Mid day
            if pos < 20:
                buy_edge = -10.0
            elif pos < 50:
                buy_edge = -6.0
            elif pos < 70:
                buy_edge = -3.0
            else:
                buy_edge = 0.0
        elif remaining_move > 200:
            # Late mid day
            if pos < 40:
                buy_edge = -5.0
            elif pos < 60:
                buy_edge = -2.0
            else:
                buy_edge = 1.0
        else:
            # End of day: only buy at discount
            if pos < 20:
                buy_edge = -3.0
            else:
                buy_edge = 2.0

        # Sell edge: almost never sell (trend is up)
        # Only sell if position is at limit AND bid is way above fair
        if pos < 70:
            sell_edge = 999.0  # never sell
        elif pos < 78:
            sell_edge = 8.0    # sell only at extreme premium
        else:
            sell_edge = 6.0    # sell at good premium when maxed out

        # Execute takes
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

        # Bid close to fair to maximize fill probability
        # Ask far from fair to avoid being sold out of profitable position
        if itr < 5:
            # Startup: maximum buying aggression
            bid_offset = -5    # bid ABOVE fair to guarantee fills
            ask_offset = 20    # don't sell
            bid_size = 80
            ask_size = 0
        elif remaining_move > 800:
            # Early day: aggressive accumulation
            if pos < 40:
                bid_offset = 1
                ask_offset = 14
                bid_size = min(40, buy_cap)
                ask_size = 0
            elif pos < 60:
                bid_offset = 2
                ask_offset = 12
                bid_size = min(30, buy_cap)
                ask_size = 0
            elif pos < 70:
                bid_offset = 2
                ask_offset = 10
                bid_size = min(20, buy_cap)
                ask_size = 3
            elif pos < 78:
                bid_offset = 3
                ask_offset = 8
                bid_size = min(10, buy_cap)
                ask_size = 5
            else:
                bid_offset = 5
                ask_offset = 6
                bid_size = min(5, buy_cap)
                ask_size = 10
        elif remaining_move > 300:
            # Mid day
            if pos < 50:
                bid_offset = 2
                ask_offset = 12
                bid_size = min(30, buy_cap)
                ask_size = 0
            elif pos < 70:
                bid_offset = 3
                ask_offset = 10
                bid_size = min(15, buy_cap)
                ask_size = 3
            else:
                bid_offset = 4
                ask_offset = 8
                bid_size = min(8, buy_cap)
                ask_size = 5
        else:
            # Late day: winding down, start selling if we're full
            if pos < 30:
                bid_offset = 3
                ask_offset = 10
                bid_size = min(15, buy_cap)
                ask_size = 0
            elif pos > 60:
                bid_offset = 5
                ask_offset = 5
                bid_size = min(5, buy_cap)
                ask_size = min(10, sell_cap)
            else:
                bid_offset = 4
                ask_offset = 8
                bid_size = min(10, buy_cap)
                ask_size = 3

        q_bid = fair_int - bid_offset
        q_ask = fair_int + ask_offset

        # Prevent crossing
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

        if sell_cap > 0 and ask_size > 0 and pos >= 70:
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

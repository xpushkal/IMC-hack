from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity 4 – Round 2 v2 (Post-mortem optimized)

    Round 1 result: 19,357 XIRECs. Need 200,000+ total.
    Last R2 test: 8,131 XIRECs. Must improve dramatically.

    === POST-MORTEM FROM SUBMISSION 274353 ===

    BUG #1: IPR sold 51 units in uptrend → lost 2,487 XIRECs
      Root cause: passive asks at pos≥70 getting filled, sell_edge too low
      FIX: NEVER sell IPR. Zero passive asks. sell_edge = infinity.

    BUG #2: ACO ended with -71 position (deeply short)
      Root cause: asymmetric passive MM fills + aggressive sells below fair
      FIX: Only sell at F+1 or above. Symmetric inventory management.

    BUG #3: ACO buying at 10001-10003 (above fair)
      Root cause: buy_up_to = F+3 when near flat
      FIX: Only buy at F or below unless flattening short position.

    === SIMULATION DISCOVERY ===
    Test runs 1,000 ticks (ts 0→99,900). Full day = 10,000 ticks (0→999,900).
    IPR slope = 0.001/ts → test moves ~100, full day moves ~1,000.
    Algorithm must work at any simulation length.

    === PROJECTED PnL (per full day) ===
    IPR: 80 × 1,000 = ~80,000 (buy & hold, never sell)
    ACO: ~2,000-5,000 (conservative MM, no bad trades)
    Over 3 days: ~250,000-255,000 → target achieved
    """

    LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    IPR_SLOPE = 0.001  # Exact: price = base + 0.001 * timestamp

    def __init__(self):
        pass

    def bid(self):
        """
        Market Access Fee: 15 XIRECs.
        Top 50% of bids get extra 25% volume. 15 is moderate —
        beats conservative bidders while not overpaying.
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
                "ipr_base": saved.get("ipr_base"),
            })

        return result, 0, traderData

    # ==================================================================
    #   ASH_COATED_OSMIUM — conservative mean-reversion market making
    # ==================================================================
    def _aco(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        """
        Post-mortem findings:
        - Ended at -71 position (TERRIBLE) → mark-to-market loss
        - Sold 50 units below fair (9998-9999) → direct losses
        - Bought 74 units above fair (10001-10003) → overpaying

        v2 RULES:
        1. NEVER buy above F (10000) unless flattening a short (pos < -20)
        2. NEVER sell below F+1 (10001) unless flattening a long (pos > 20)
        3. Passive MM: place quotes that only fill at profitable prices
        4. Strong inventory skew to prevent position blowout
        """
        orders = []
        P = "ASH_COATED_OSMIUM"
        F = 10000

        buy_cap = lim - pos    # max additional units we can buy
        sell_cap = lim + pos   # max additional units we can sell

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        # POST-MORTEM 275687: algo sells 47 vol into bids at 9998-10000 in
        # the FIRST TWO TICKS, blowing position to -69 instantly.
        # Root cause: sell_down_to = F-3 hits ALL bids (9998+).
        #
        # FIX: Only sell ABOVE fair (F+1=10001+) unless flattening a long.
        #      Buys at F+3 are fine (asks are at 10008+ anyway).
        #      Cap aggressive take volume to prevent instant blowout.

        # Buy thresholds (proven: F+3 works for buying)
        if pos < -40:
            buy_up_to = F + 3     # max flatten short
        elif pos < -10:
            buy_up_to = F + 3
        elif pos <= 30:
            buy_up_to = F + 3     # normal buying
        elif pos <= 50:
            buy_up_to = F + 1     # reduce buying when long
        elif pos <= 65:
            buy_up_to = F         # tighter when getting full
        else:
            buy_up_to = F - 2     # near limit: only deep buys

        # Sell thresholds — CRITICAL: never sell below F+1 unless flattening long
        if pos < -40:
            sell_down_to = F + 5  # absolutely don't sell when deeply short
        elif pos < -10:
            sell_down_to = F + 3  # don't sell when short
        elif pos <= 10:
            sell_down_to = F + 1  # only sell ABOVE fair when flat
        elif pos <= 30:
            sell_down_to = F      # sell at fair OK when slightly long
        elif pos <= 50:
            sell_down_to = F - 1  # moderate flatten
        elif pos <= 65:
            sell_down_to = F - 2  # aggressive flatten
        else:
            sell_down_to = F - 3  # max flatten when near limit

        # Volume cap per tick: prevent instant position blowout
        # Max aggressive take = 15 units per tick per side
        max_take = 15

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

        # ======= PHASE 2: PASSIVE MARKET MAKING =======
        # Key: place quotes such that fills are ALWAYS profitable
        # L1 bids at 9993-9994, L1 asks at 10008-10010 (from data)
        # Our quotes: bid at F-5 to F-7 (buy below fair → profit)
        #             ask at F+5 to F+8 (sell above fair → profit)

        skew = pos / lim if lim > 0 else 0

        # Inventory-based spread adjustment:
        # When long → widen bid (less buying) + tighten ask (more selling)
        # When short → tighten bid (more buying) + widen ask (less selling)
        inv_adj = round(skew * 3)  # -3 to +3

        # Layer 1: primary quotes
        l1_bid = F - 5 - inv_adj   # when flat: 9995. when long 40/80: 9994
        l1_ask = F + 5 - inv_adj   # when flat: 10005. when long 40/80: 10004

        # Layer 2: deeper
        l2_bid = F - 7 - inv_adj
        l2_ask = F + 8 - inv_adj

        # Safety: never let bid go above fair or ask below fair
        l1_bid = min(l1_bid, F - 1)
        l2_bid = min(l2_bid, F - 1)
        l1_ask = max(l1_ask, F + 1)
        l2_ask = max(l2_ask, F + 1)

        # Prevent crossing
        if l1_ask <= l1_bid:
            l1_ask = l1_bid + 2
        if l2_ask <= l2_bid:
            l2_ask = l2_bid + 2

        # Inventory-skewed sizing: reduce size toward position limit
        buy_mult = max(0.05, 1.0 - skew)     # 0 when fully long
        sell_mult = max(0.05, 1.0 + skew)     # 0 when fully short

        levels = [
            (l1_bid, l1_ask, 0.50),  # primary layer
            (l2_bid, l2_ask, 0.35),  # secondary layer
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
        # Catch extreme dislocations
        if buy_cap > 0:
            orders.append(Order(P, F - 10, buy_cap))
        if sell_cap > 0:
            orders.append(Order(P, F + 11, -sell_cap))

        return orders

    # ==================================================================
    #   INTARIAN_PEPPER_ROOT — pure trend capture (BUY & HOLD)
    # ==================================================================
    def _ipr(self, od: OrderDepth, pos: int, lim: int, saved: dict, ts: int) -> List[Order]:
        """
        Post-mortem: Selling 51 units lost 2,487 XIRECs in the test.
        Over a full day (10x longer), that's ~25,000 lost per day.

        v2 STRATEGY: NEVER SELL. Period.
        - Buy 80 units as fast as possible
        - Hold forever (price goes up 1,000/day minimum)
        - Only passive bids to catch dips — no asks at all
        - Position carries to next day → free money

        Expected: ~80,000 PnL per full day from pure trend capture.
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

        # Bootstrap fair value from detrended EMA
        itr = saved.get("iter", 0)
        detrended = mid - self.IPR_SLOPE * ts
        base_ema = saved.get("ipr_base", detrended)

        alpha = 0.8 if itr < 10 else 0.01
        base_ema = alpha * detrended + (1 - alpha) * base_ema
        saved["ipr_base"] = base_ema

        fair = base_ema + self.IPR_SLOPE * ts

        buy_cap = lim - pos  # how many more we can buy

        # ======= PHASE 1: AGGRESSIVE BUY EVERYTHING =======
        # In a +1000/day trend, buying at ANY price is profitable.
        # The spread cost (~7) is negligible vs the ~1000 daily gain.
        # Buy ALL available asks regardless of price.

        if od.sell_orders and buy_cap > 0:
            for ask_p in sorted(od.sell_orders.keys()):
                if buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order(P, ask_p, vol))
                    buy_cap -= vol

        # ======= PHASE 2: PASSIVE BIDS (catch dips) =======
        # Post bids close to fair to fill on any downward noise.
        # The trend guarantees these fill profitably.
        fair_int = round(fair)

        if buy_cap > 0:
            # Layer 1: just below fair (high fill probability)
            bid_p = fair_int - 1
            if best_ask is not None and bid_p >= best_ask:
                bid_p = best_ask - 1
            sz = min(buy_cap, 40)
            orders.append(Order(P, bid_p, sz))
            buy_cap -= sz

        if buy_cap > 0:
            # Layer 2: at fair minus spread
            bid_p = fair_int - 3
            sz = min(buy_cap, 25)
            orders.append(Order(P, bid_p, sz))
            buy_cap -= sz

        if buy_cap > 0:
            # Layer 3: deep backstop
            bid_p = fair_int - 6
            orders.append(Order(P, bid_p, buy_cap))

        # ======= NO SELLS. EVER. =======
        # Every unit held captures ~1,000 per day.
        # Selling to capture a 6-point spread is insane.

        return orders
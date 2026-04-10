from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity - Round 0 - Tournament Trader v9

    EMERALDS: Log analysis showed PnL didn't start until ts=6000 (60 ticks dead).
    Bot spread is always 9992/10008 (16 wide). Tightened to 1-tick offset from
    fair and more aggressive fair-value taking to fill earlier and faster.

    Key parameters (tuned from v8 log analysis):
      - Base offset: 1 tick from fair (was 2)
      - Inventory shift: skew * 4
      - Sizing: 0.8 skew factor
      - Front-loaded 75/50/100% of remaining capacity (was 60/50/100)
      - More aggressive at-fair taking: up to 8 units (was 4)

    TOMATOES: Log showed 94% of spreads are 13-14 ticks, so the spread<=9
    penny-ahead logic was firing only 6% of the time. Fixed threshold to 14.
    Also: tighter backstop (8 vs 12), earlier flatten (10 vs 12), stronger
    inventory shift (5.0 vs 3.5), closer deep layers (2 vs 4).
    Max drawdown was 139.66 — addressed with more aggressive position mgmt.
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

        saved["iter"] = saved.get("iter", 0) + 1

        traderData = json.dumps(saved)
        if len(traderData) > 45000:
            traderData = json.dumps({
                "iter": saved.get("iter", 0),
                "t_ema_fast": saved.get("t_ema_fast"),
                "t_ema_slow": saved.get("t_ema_slow"),
                "t_fair": saved.get("t_fair"),
                "t_vol": saved.get("t_vol"),
                "t_last_mid": saved.get("t_last_mid"),
            })

        return result, 0, traderData

    # ================================================================ #
    #             E M E R A L D S    (fair = 10000)                      #
    # ================================================================ #
    def _emeralds(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
        orders = []
        F = 10000

        buy_cap = lim - pos
        sell_cap = lim + pos

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        if od.sell_orders:
            for ask_p in sorted(od.sell_orders.keys()):
                if ask_p < F and buy_cap > 0:
                    vol = min(-od.sell_orders[ask_p], buy_cap)
                    orders.append(Order("EMERALDS", ask_p, vol))
                    buy_cap -= vol
                elif ask_p == F and buy_cap > 0:
                    if pos < 0:
                        vol = min(-od.sell_orders[ask_p], buy_cap, abs(pos))
                    elif pos <= 10:
                        vol = min(-od.sell_orders[ask_p], buy_cap, 8)
                    else:
                        vol = 0
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
                elif bid_p == F and sell_cap > 0:
                    if pos > 0:
                        vol = min(od.buy_orders[bid_p], sell_cap, abs(pos))
                    elif pos >= -10:
                        vol = min(od.buy_orders[bid_p], sell_cap, 8)
                    else:
                        vol = 0
                    if vol > 0:
                        orders.append(Order("EMERALDS", bid_p, -vol))
                        sell_cap -= vol
                else:
                    break

        # ======= PHASE 2: PASSIVE MARKET MAKING =======
        skew = pos / lim if lim > 0 else 0

        # Continuous inventory shift
        inv_shift = round(skew * 4)

        # Tightest base: 1 tick from fair (was 2 in v8)
        l1_bid = F - 1 - inv_shift
        l1_ask = F + 1 - inv_shift
        l2_bid = F - 3 - inv_shift
        l2_ask = F + 3 - inv_shift
        l3_bid = F - 6 - inv_shift
        l3_ask = F + 6 - inv_shift

        # Safety clamps
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

        # Inventory-skewed sizing
        buy_mult = max(0.1, 1.0 - skew * 0.8)
        sell_mult = max(0.1, 1.0 + skew * 0.8)

        levels = [
            (l1_bid, l1_ask, 0.75),
            (l2_bid, l2_ask, 0.50),
            (l3_bid, l3_ask, 1.00),
        ]

        for bp, ap, frac in levels:
            buy_sz = max(1, round(buy_cap * frac * buy_mult))
            sell_sz = max(1, round(sell_cap * frac * sell_mult))

            if buy_cap > 0:
                sz = min(buy_sz, buy_cap)
                orders.append(Order("EMERALDS", int(bp), sz))
                buy_cap -= sz

            if sell_cap > 0:
                sz = min(sell_sz, sell_cap)
                orders.append(Order("EMERALDS", int(ap), -sz))
                sell_cap -= sz

        # ======= PHASE 3: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order("EMERALDS", F - 10, buy_cap))
        if sell_cap > 0:
            orders.append(Order("EMERALDS", F + 10, -sell_cap))

        return orders

    # ================================================================ #
    #                   T O M A T O E S                                  #
    # ================================================================ #
    def _tomatoes(self, od: OrderDepth, pos: int, lim: int, saved: dict) -> List[Order]:
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

        # ======= FULL BOOK VWAP =======
        bid_vwap_num, bid_vwap_den = 0, 0
        for p, v in od.buy_orders.items():
            vol = abs(v)
            bid_vwap_num += p * vol
            bid_vwap_den += vol

        ask_vwap_num, ask_vwap_den = 0, 0
        for p, v in od.sell_orders.items():
            vol = abs(v)
            ask_vwap_num += p * vol
            ask_vwap_den += vol

        total_book = bid_vwap_den + ask_vwap_den
        if total_book > 0:
            book_vwap = (bid_vwap_num + ask_vwap_num) / total_book
            imbalance = (bid_vwap_den - ask_vwap_den) / total_book
        else:
            book_vwap = mid
            imbalance = 0

        # ======= BLENDED PRICE SIGNAL =======
        price_signal = 0.45 * microprice + 0.30 * book_vwap + 0.25 * mid

        # ======= DUAL EMA WITH WARMUP =======
        iterations = saved.get("iter", 0)

        ema_fast = saved.get("t_ema_fast", price_signal)
        ema_slow = saved.get("t_ema_slow", price_signal)

        if iterations < 5:
            alpha_f, alpha_s = 0.5, 0.3
        else:
            alpha_f, alpha_s = 0.15, 0.05

        ema_fast = alpha_f * price_signal + (1 - alpha_f) * ema_fast
        ema_slow = alpha_s * price_signal + (1 - alpha_s) * ema_slow
        saved["t_ema_fast"] = ema_fast
        saved["t_ema_slow"] = ema_slow

        # ======= TREND & VOLATILITY =======
        trend = ema_fast - ema_slow

        last_mid = saved.get("t_last_mid", mid)
        tick_return = abs(mid - last_mid)
        vol_ema = saved.get("t_vol", 2.0)
        vol_ema = 0.1 * tick_return + 0.9 * vol_ema
        saved["t_last_mid"] = mid
        saved["t_vol"] = vol_ema

        # ======= FAIR VALUE =======
        fair = ema_fast + trend * 0.25 + imbalance * 1.5
        saved["t_fair"] = fair

        # ======= POSITION TRACKING =======
        buy_cap = lim - pos
        sell_cap = lim + pos
        abs_pos = abs(pos)
        skew = pos / lim if lim > 0 else 0

        # ======= PHASE 1: AGGRESSIVE TAKE =======
        if abs_pos >= 10:
            buy_edge = 0.2 if pos <= 0 else 2.5
            sell_edge = 0.2 if pos >= 0 else 2.5
        elif abs_pos >= 5:
            buy_edge = 0.5 if pos <= 0 else 1.5
            sell_edge = 0.5 if pos >= 0 else 1.5
        else:
            buy_edge = 0.5
            sell_edge = 0.5

        for ask_p in sorted(od.sell_orders.keys()):
            edge = fair - ask_p
            if edge >= buy_edge and buy_cap > 0:
                vol = min(-od.sell_orders[ask_p], buy_cap)
                orders.append(Order("TOMATOES", ask_p, vol))
                buy_cap -= vol
            elif edge < buy_edge:
                break

        for bid_p in sorted(od.buy_orders.keys(), reverse=True):
            edge = bid_p - fair
            if edge >= sell_edge and sell_cap > 0:
                vol = min(od.buy_orders[bid_p], sell_cap)
                orders.append(Order("TOMATOES", bid_p, -vol))
                sell_cap -= vol
            elif edge < sell_edge:
                break

        # ======= PHASE 2: PASSIVE QUOTES =======
        inv_offset = skew * 5.0

        base_hs = 3.0 + vol_ema * 0.4
        base_hs = max(2.5, min(base_hs, 6.0))

        if spread <= 14:
            q_bid = best_bid + 1
            q_ask = best_ask - 1
        else:
            q_bid = math.floor(fair - base_hs - inv_offset)
            q_ask = math.ceil(fair + base_hs - inv_offset)

        if q_ask <= q_bid:
            q_ask = q_bid + 1
        if q_bid >= best_ask:
            q_bid = best_ask - 1
        if q_ask <= best_bid:
            q_ask = best_bid + 1

        base_sz = 9
        buy_sz = max(1, round(base_sz * max(0.1, 1.0 - skew * 0.85)))
        sell_sz = max(1, round(base_sz * max(0.1, 1.0 + skew * 0.85)))

        for off in bid_offsets:
            bp = math.floor(fair - off - inv_offset)
            bid_prices.append(bp)

        for off in ask_offsets:
            ap = math.ceil(fair + off - inv_offset)
            ask_prices.append(ap)

        # ======= PHASE 3: DEEP LAYER =======
        deep_bid = q_bid - 2
        deep_ask = q_ask + 2

        deep_buy_sz = max(1, round(7 * max(0.1, 1.0 - skew * 0.85)))
        deep_sell_sz = max(1, round(7 * max(0.1, 1.0 + skew * 0.85)))

        if buy_cap > 0:
            sz = min(deep_buy_sz, buy_cap)
            orders.append(Order("TOMATOES", deep_bid, sz))
            buy_cap -= sz
            n_bid = max(1, n_bid - 1)

        if sell_cap > 0:
            sz = min(deep_sell_sz, sell_cap)
            orders.append(Order("TOMATOES", deep_ask, -sz))
            sell_cap -= sz
            n_ask = max(1, n_ask - 1)

        # ======= PHASE 4: EMERGENCY FLATTEN =======
        if abs_pos >= 10:
            if pos > 0 and sell_cap > 0:
                flatten = min(sell_cap, pos - 3)
                if flatten > 0:
                    orders.append(Order("TOMATOES", best_bid, -flatten))
                    sell_cap -= flatten
            elif pos < 0 and buy_cap > 0:
                flatten = min(buy_cap, abs_pos - 3)
                if flatten > 0:
                    orders.append(Order("TOMATOES", best_ask, flatten))
                    buy_cap -= flatten

        # ======= PHASE 4: BACKSTOP =======
        if buy_cap > 0:
            orders.append(Order("TOMATOES", math.floor(fair - 8), buy_cap))
        if sell_cap > 0:
            orders.append(Order("TOMATOES", math.ceil(fair + 8), -sell_cap))

        return orders

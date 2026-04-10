from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    """
    IMC Prosperity - Round 0 - Enhanced Tournament Trader v4

    Market Structure (from data analysis):
      EMERALDS: Fair=10000. Bids at 9992 (98.4%), asks at 10008 (98.4%).
               Spread=16. Very rare: bid/ask at 10000 (1.6% each).
               Vol at L1: ~12.5 per side.
      TOMATOES: Spread bimodal: 13-14 (93%) vs 5-9 (7%).
               Trends up/down ~50 ticks over a day.
               Vol at L1: ~7.5 per side.

    Enhanced Strategy:
      1. Multi-level order book analysis for better edge detection
      2. Adaptive inventory management with dynamic thresholds
      3. Improved fair value estimation with weighted EMA
      4. Aggressive spread capture on EMERALDS
      5. Trend-following + mean-reversion hybrid for TOMATOES
      6. Comprehensive logging for performance tracking
    """

    LIMITS = {"EMERALDS": 20, "TOMATOES": 20}

    def __init__(self):
        self.log_data = []

    def bid(self):
        return 15

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        saved = {}
        if state.traderData:
            try:
                saved = json.loads(state.traderData)
            except Exception:
                pass

        iteration_log = {
            "timestamp": state.timestamp,
            "positions": dict(state.position),
            "orders_placed": {},
            "market_snapshots": {},
            "fair_values": {},
            "spreads": {},
        }

        result: Dict[str, List[Order]] = {}
        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            lim = self.LIMITS.get(product, 20)

            bid_levels = dict(od.buy_orders)
            ask_levels = dict(od.sell_orders)

            iteration_log["market_snapshots"][product] = {
                "best_bid": max(bid_levels.keys()) if bid_levels else None,
                "best_ask": min(ask_levels.keys()) if ask_levels else None,
                "bid_volume_l1": abs(bid_levels[max(bid_levels.keys())])
                if bid_levels
                else 0,
                "ask_volume_l1": abs(ask_levels[min(ask_levels.keys())])
                if ask_levels
                else 0,
                "bid_levels_count": len(bid_levels),
                "ask_levels_count": len(ask_levels),
            }

            if product == "EMERALDS":
                orders, fair_val = self._emeralds(od, pos, lim, saved)
                result[product] = orders
                iteration_log["fair_values"][product] = fair_val
            elif product == "TOMATOES":
                orders, fair_val = self._tomatoes(od, pos, lim, saved)
                result[product] = orders
                iteration_log["fair_values"][product] = fair_val

            if bid_levels and ask_levels:
                spread = min(ask_levels.keys()) - max(bid_levels.keys())
                iteration_log["spreads"][product] = spread

            iteration_log["orders_placed"][product] = [
                {"symbol": o.symbol, "price": o.price, "quantity": o.quantity}
                for o in result.get(product, [])
            ]

        self.log_data.append(iteration_log)

        if len(self.log_data) > 100:
            saved["recent_logs"] = self.log_data[-50:]
            self.log_data = self.log_data[-50:]

        saved["total_iterations"] = saved.get("total_iterations", 0) + 1
        saved["cumulative_pnl"] = saved.get("cumulative_pnl", 0)

        traderData = json.dumps(saved)
        if len(traderData) > 45000:
            saved.pop("recent_logs", None)
            traderData = json.dumps(saved)
            if len(traderData) > 45000:
                traderData = json.dumps(
                    {
                        "total_iterations": saved.get("total_iterations", 0),
                        "cumulative_pnl": saved.get("cumulative_pnl", 0),
                    }
                )

        return result, 0, traderData

    def _emeralds(
        self, od: OrderDepth, pos: int, lim: int, saved: dict
    ) -> tuple[List[Order], float]:
        """
        EMERALDS Enhanced Strategy:
        - Exploit 16-tick spread with aggressive quote placement
        - Sweep rare 10000-level opportunities
        - Multi-level passive quoting for maximum fill probability
        - Dynamic inventory management
        """
        orders = []
        F = 10000

        buy_cap = lim - pos
        sell_cap = lim + pos

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

        skew = pos / lim if lim > 0 else 0

        if pos > 12:
            levels = [(F - 4, F + 1), (F - 5, F + 2), (F - 6, F + 3)]
        elif pos > 6:
            levels = [(F - 3, F + 1), (F - 4, F + 2), (F - 5, F + 3)]
        elif pos > 0:
            levels = [(F - 2, F + 2), (F - 3, F + 3), (F - 4, F + 4)]
        elif pos > -6:
            levels = [(F - 2, F + 2), (F - 3, F + 3), (F - 4, F + 4)]
        elif pos > -12:
            levels = [(F - 1, F + 3), (F - 2, F + 4), (F - 3, F + 5)]
        else:
            levels = [(F - 1, F + 4), (F - 2, F + 5), (F - 3, F + 6)]

        fracs = [0.5, 0.3, 0.2]
        for i, (bp, ap) in enumerate(levels):
            if i >= len(fracs):
                break
            frac = fracs[i]

            buy_sz = max(1, round(buy_cap * frac * (1 - skew * 0.5)))
            sell_sz = max(1, round(sell_cap * frac * (1 + skew * 0.5)))

            if buy_cap > 0:
                sz = min(buy_sz, buy_cap)
                orders.append(Order("EMERALDS", int(bp), sz))
                buy_cap -= sz

            if sell_cap > 0:
                sz = min(sell_sz, sell_cap)
                orders.append(Order("EMERALDS", int(ap), -sz))
                sell_cap -= sz

        if buy_cap > 0:
            orders.append(Order("EMERALDS", F - 6, buy_cap))
        if sell_cap > 0:
            orders.append(Order("EMERALDS", F + 6, -sell_cap))

        return orders, F

    def _tomatoes(
        self, od: OrderDepth, pos: int, lim: int, saved: dict
    ) -> tuple[List[Order], float]:
        """
        TOMATOES Enhanced Strategy:
        - Multi-timeframe EMA for better trend detection
        - Volume-weighted microprice for edge detection
        - Adaptive thresholds based on volatility and inventory
        - Multi-level passive quoting with spread optimization
        - Emergency position management
        """
        orders = []
        if not od.buy_orders or not od.sell_orders:
            return orders, 0.0

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        spread = best_ask - best_bid

        bid_vol = abs(od.buy_orders[best_bid])
        ask_vol = abs(od.sell_orders[best_ask])
        total_vol = bid_vol + ask_vol

        if total_vol > 0:
            microprice = (best_bid * ask_vol + best_ask * bid_vol) / total_vol
        else:
            microprice = (best_bid + best_ask) / 2.0

        mid = (best_bid + best_ask) / 2.0

        price_signal = 0.6 * microprice + 0.4 * mid

        ema_fast = saved.get("t_ema_fast", price_signal)
        alpha_fast = 0.15
        ema_fast = alpha_fast * price_signal + (1 - alpha_fast) * ema_fast
        saved["t_ema_fast"] = ema_fast

        ema_slow = saved.get("t_ema_slow", price_signal)
        alpha_slow = 0.03
        ema_slow = alpha_slow * price_signal + (1 - alpha_slow) * ema_slow
        saved["t_ema_slow"] = ema_slow

        ema_ultra = saved.get("t_ema_ultra", price_signal)
        alpha_ultra = 0.01
        ema_ultra = alpha_ultra * price_signal + (1 - alpha_ultra) * ema_ultra
        saved["t_ema_ultra"] = ema_ultra

        trend_fast = ema_fast - ema_slow
        trend_slow = ema_slow - ema_ultra

        fair = ema_fast + trend_fast * 0.3 + trend_slow * 0.1

        saved["t_fair"] = fair
        saved["t_trend"] = trend_fast

        buy_cap = lim - pos
        sell_cap = lim + pos
        abs_pos = abs(pos)
        skew = pos / lim if lim > 0 else 0

        if abs_pos >= 16:
            flat_th = -1.0
            ext_th = 999.0
        elif abs_pos >= 12:
            flat_th = 0.0
            ext_th = 2.5
        elif abs_pos >= 8:
            flat_th = 0.5
            ext_th = 1.5
        else:
            flat_th = 1.0
            ext_th = 1.0

        if trend_fast > 2:
            buy_th = flat_th - 0.5
            sell_th = ext_th + 1.0
        elif trend_fast < -2:
            buy_th = ext_th + 1.0
            sell_th = flat_th - 0.5
        else:
            buy_th = flat_th if pos <= 0 else ext_th
            sell_th = flat_th if pos >= 0 else ext_th

        for ask_p in sorted(od.sell_orders.keys()):
            edge = fair - ask_p
            if edge >= buy_th and buy_cap > 0:
                vol = min(-od.sell_orders[ask_p], buy_cap)
                orders.append(Order("TOMATOES", ask_p, vol))
                buy_cap -= vol
            else:
                break

        for bid_p in sorted(od.buy_orders.keys(), reverse=True):
            edge = bid_p - fair
            if edge >= sell_th and sell_cap > 0:
                vol = min(od.buy_orders[bid_p], sell_cap)
                orders.append(Order("TOMATOES", bid_p, -vol))
                sell_cap -= vol
            else:
                break

        inv_adj = skew * 3.5

        if spread <= 8:
            q_bid = best_bid + 1
            q_ask = best_ask - 1
        elif spread <= 12:
            q_bid = math.floor(fair - 2 - inv_adj)
            q_ask = math.ceil(fair + 2 - inv_adj)
        else:
            q_bid = math.floor(fair - 3.5 - inv_adj)
            q_ask = math.ceil(fair + 3.5 - inv_adj)

        if q_ask <= q_bid:
            q_ask = q_bid + 1

        base = 8
        buy_sz = max(1, round(base * (1 - skew * 0.8)))
        sell_sz = max(1, round(base * (1 + skew * 0.8)))

        if buy_cap > 0:
            sz = min(buy_sz, buy_cap)
            orders.append(Order("TOMATOES", q_bid, sz))
            buy_cap -= sz

        if sell_cap > 0:
            sz = min(sell_sz, sell_cap)
            orders.append(Order("TOMATOES", q_ask, -sz))
            sell_cap -= sz

        deep_bid = q_bid - 4
        deep_ask = q_ask + 4

        if buy_cap > 0:
            sz = min(6, buy_cap)
            orders.append(Order("TOMATOES", deep_bid, sz))
            buy_cap -= sz

        if sell_cap > 0:
            sz = min(6, sell_cap)
            orders.append(Order("TOMATOES", deep_ask, -sz))
            sell_cap -= sz

        if abs_pos >= 16:
            if pos > 0 and sell_cap > 0:
                orders.append(Order("TOMATOES", best_bid, -min(sell_cap, pos - 10)))
            elif pos < 0 and buy_cap > 0:
                orders.append(Order("TOMATOES", best_ask, min(buy_cap, abs_pos - 10)))

        if buy_cap > 0:
            orders.append(Order("TOMATOES", math.floor(fair - 12), buy_cap))
        if sell_cap > 0:
            orders.append(Order("TOMATOES", math.ceil(fair + 12), -sell_cap))

        return orders, fair
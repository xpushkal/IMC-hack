"""
Comprehensive Logging and Analysis Script for IMC Prosperity
- Analyzes backtest logs
- Provides detailed performance metrics
- Generates summary reports
"""

import json
import os
from collections import defaultdict


def analyze_log_file(log_path):
    """Analyze a single backtest log file"""
    with open(log_path, "r") as f:
        data = json.load(f)

    print(f"\n{'=' * 70}")
    print(f"ANALYZING: {log_path}")
    print(f"{'=' * 70}")

    print(f"\n  File: {data['file']}")
    print(f"  Total Trades: {data['total_trades']}")
    print(f"  Trade Count by Product: {data['trade_count']}")
    print(f"  Position Ranges:")
    for prod, range_data in data["positions"].items():
        print(f"    {prod}: [{range_data['min']}, {range_data['max']}]")

    print(f"\n  Final Cash: {data['final_cash']:,.0f}")
    print(f"  Final PnL: {data['final_pnl']:,.0f}")
    print(f"  Max Drawdown: {data['max_drawdown']:,.0f}")

    print(f"\n  PnL Progression:")
    for pct, val in data["pnl_progression"].items():
        print(f"    {pct}: {val:,.0f}")

    # Analyze iteration details
    iterations = data.get("detailed_iterations", [])
    if iterations:
        print(f"\n  Detailed Iterations Analyzed: {len(iterations)}")

        # Fill type analysis
        agg_fills = 0
        pas_fills = 0
        product_fills = defaultdict(lambda: {"aggressive": 0, "passive": 0})

        for iter_data in iterations:
            for fill in iter_data.get("fills", []):
                if fill["type"] == "aggressive":
                    agg_fills += 1
                    product_fills[fill["symbol"]]["aggressive"] += 1
                else:
                    pas_fills += 1
                    product_fills[fill["symbol"]]["passive"] += 1

        print(f"\n  Fill Analysis:")
        print(f"    Aggressive Fills: {agg_fills}")
        print(f"    Passive Fills: {pas_fills}")
        print(
            f"    Aggressive %: {agg_fills / (agg_fills + pas_fills) * 100:.1f}%"
            if (agg_fills + pas_fills) > 0
            else ""
        )

        print(f"\n  Fill Analysis by Product:")
        for prod, counts in product_fills.items():
            total = counts["aggressive"] + counts["passive"]
            print(
                f"    {prod}: {total} fills (Agg: {counts['aggressive']}, Pas: {counts['passive']})"
            )

        # PnL per iteration stats
        pnls = [it["pnl"] for it in iterations if "pnl" in it]
        if pnls:
            print(f"\n  PnL Statistics (sampled iterations):")
            print(f"    Mean PnL: {sum(pnls) / len(pnls):,.0f}")
            print(f"    Min PnL: {min(pnls):,.0f}")
            print(f"    Max PnL: {max(pnls):,.0f}")

    return data


def generate_summary_report(log_dir="logs"):
    """Generate a summary report from all log files"""
    print(f"\n{'=' * 70}")
    print("COMPREHENSIVE PERFORMANCE SUMMARY")
    print(f"{'=' * 70}")

    log_files = [f for f in os.listdir(log_dir) if f.endswith(".json")]

    if not log_files:
        print("No log files found. Run backtest.py first.")
        return

    all_data = []
    for log_file in sorted(log_files):
        log_path = os.path.join(log_dir, log_file)
        data = analyze_log_file(log_path)
        all_data.append(data)

    # Combined summary
    print(f"\n{'=' * 70}")
    print("COMBINED SUMMARY")
    print(f"{'=' * 70}")

    total_pnl = sum(d["final_pnl"] for d in all_data)
    total_trades = sum(d["total_trades"] for d in all_data)
    avg_drawdown = sum(d["max_drawdown"] for d in all_data) / len(all_data)

    print(f"\n  Total Files Analyzed: {len(all_data)}")
    print(f"  Combined PnL: {total_pnl:,.0f}")
    print(f"  Average PnL per Day: {total_pnl / len(all_data):,.0f}")
    print(f"  Total Trades: {total_trades:,}")
    print(f"  Average Max Drawdown: {avg_drawdown:,.0f}")

    # Save summary
    summary = {
        "files_analyzed": len(all_data),
        "combined_pnl": total_pnl,
        "avg_pnl_per_day": total_pnl / len(all_data),
        "total_trades": total_trades,
        "avg_max_drawdown": avg_drawdown,
        "daily_results": [
            {
                "file": d["file"],
                "pnl": d["final_pnl"],
                "trades": d["total_trades"],
                "max_drawdown": d["max_drawdown"],
            }
            for d in all_data
        ],
    }

    summary_path = os.path.join(log_dir, "summary_report.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n  Summary report saved to: {summary_path}")


if __name__ == "__main__":
    generate_summary_report()

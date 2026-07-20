"""
validate_strategy.py
────────────────────
The referee: runs a strategy and a buy-and-hold benchmark over the same
period and prints full-period plus per-year out-of-sample comparisons.

No model or sizing change should ship without beating or matching both
the benchmark and the previous baseline here — on the bull period AND
the crisis period.

Usage:
    python3 validate_strategy.py                # bull period (data/)
    python3 validate_strategy.py --crisis       # 2006-2012 (data/crisis/)
"""

import os
import sys
import logging

from src.engine import BacktestEngine
from src.execution.sim_broker import SimulatedBroker
from src.strategy.buy_and_hold import BuyAndHold
from src.strategy.rolling_ridge import RollingRidgeDirectionalPredictor
from src.validation import comparison_table, alpha_beta, edge_decay

logging.basicConfig(level=logging.WARNING, format="%(message)s")

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INITIAL_CASH = 100_000.0
COMMISSION = 0.001
SLIPPAGE = 0.0005

if "--crisis" in sys.argv:
    DATA_DIR = os.path.join(BASE_DIR, "data", "crisis")
    SYMBOLS = ["SPY", "GLD", "JPM"]
    PERIOD_LABEL = "CRISIS 2006-2012"
else:
    DATA_DIR = os.path.join(BASE_DIR, "data")
    SYMBOLS = ["SPY", "BTC-USD"]
    PERIOD_LABEL = "BULL 2020-2026"

START_DATE = None   # e.g. "2020-01-01" to restrict the window
END_DATE = None


def make_strategy():
    """The strategy under evaluation. Edit params here when tuning."""
    # Shipped defaults (vol_threshold_k=0.15 was tuned on the 2020-2023
    # train window only; see doc/validation_baseline.md for the record).
    return RollingRidgeDirectionalPredictor()


def run(strategy, name):
    engine = BacktestEngine(
        data_dir=DATA_DIR,
        symbols=SYMBOLS,
        initial_cash=INITIAL_CASH,
        strategy=strategy,
        execution_handler=SimulatedBroker(commission_rate=COMMISSION,
                                          slippage_rate=SLIPPAGE),
        start_date=START_DATE,
        end_date=END_DATE,
    )
    return engine.run(name)


def main():
    strategy = make_strategy()
    result = run(strategy, "Strategy")
    benchmark = run(BuyAndHold(strength=1.0 / len(SYMBOLS)), "Buy & Hold")

    print(f"\n=== Validation: {PERIOD_LABEL} | {', '.join(SYMBOLS)} ===\n")
    for line in comparison_table(result.equity_df, benchmark.equity_df):
        print(line)

    print(f"\nStrategy trades: {result.metrics['num_trades']} "
          f"(round trips: {result.metrics.get('num_round_trips', 0)}, "
          f"win rate: {result.metrics.get('win_rate_pct', 0.0):.1f}%)")
    print(f"Benchmark trades: {benchmark.metrics['num_trades']}")

    # ── Independence / crowding analysis ──────────────────────────────
    # beta ≈ 1 with high R² = repackaged market exposure (the crowd).
    # Positive alpha with low beta = return the benchmark can't explain.
    stats = alpha_beta(result.equity_df, benchmark.equity_df)
    print(f"\nIndependence vs benchmark ({stats['n_days']} common days):")
    print(f"  beta:        {stats['beta']:>7.3f}   (1.0 = fully market-driven)")
    print(f"  ann. alpha:  {stats['alpha_ann_pct']:>+7.2f}%  (residual edge)")
    print(f"  correlation: {stats['correlation']:>7.3f}   (R² = {stats['r_squared']:.3f})")
    for half in edge_decay(result.equity_df, benchmark.equity_df):
        print(f"  {half['label']} ({half['start']} → {half['end']}): "
              f"alpha {half['alpha_ann_pct']:+.2f}%, beta {half['beta']:.3f}")

    # Directional hit rate, if the strategy tracks prediction diagnostics
    if hasattr(strategy, "get_hit_rate"):
        for sym in SYMBOLS:
            hit_rate = strategy.get_hit_rate(sym)
            if hit_rate is not None:
                print(f"Hit rate {sym}: {hit_rate * 100:.1f}%")


if __name__ == "__main__":
    main()

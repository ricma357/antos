"""
Validation helpers — the referee for strategy changes.

Computes performance metrics from equity-curve slices so a single full
backtest can be broken into out-of-sample time windows (per-year folds)
and compared against a passive benchmark. No strategy change should ship
without beating or matching both the benchmark and the previous baseline
here.
"""

from typing import Dict, List

import pandas as pd

TRADING_DAYS = 252


def slice_metrics(equity_df: pd.DataFrame) -> Dict[str, float]:
    """
    Computes return, max drawdown, and annualized Sharpe for a slice of an
    equity curve (DataFrame with an 'Equity' column indexed by date).

    Drawdown is computed within the slice (peak resets at the slice start)
    so each fold is judged on its own risk, not inherited highs.
    """
    if len(equity_df) < 2:
        return {'return_pct': 0.0, 'max_drawdown_pct': 0.0, 'sharpe': 0.0}

    equity = equity_df['Equity']
    total_return = (equity.iloc[-1] / equity.iloc[0] - 1) * 100

    peak = equity.cummax()
    max_drawdown = ((equity - peak) / peak).min() * 100

    daily_returns = equity.pct_change().dropna()
    std = daily_returns.std()
    sharpe = (daily_returns.mean() / std * (TRADING_DAYS ** 0.5)) if std > 0 else 0.0

    return {
        'return_pct': total_return,
        'max_drawdown_pct': max_drawdown,
        'sharpe': sharpe,
    }


def yearly_breakdown(equity_df: pd.DataFrame) -> Dict[int, Dict[str, float]]:
    """
    Splits an equity curve into calendar years and computes slice_metrics
    for each. Returns {year: metrics} in chronological order.
    """
    breakdown: Dict[int, Dict[str, float]] = {}
    if equity_df.empty:
        return breakdown

    for year in sorted(equity_df.index.year.unique()):
        year_slice = equity_df[equity_df.index.year == year]
        if len(year_slice) >= 2:
            breakdown[int(year)] = slice_metrics(year_slice)
    return breakdown


def comparison_table(strategy_df: pd.DataFrame, benchmark_df: pd.DataFrame,
                     strategy_name: str = "Strategy",
                     benchmark_name: str = "Buy & Hold") -> List[str]:
    """
    Renders full-period and per-year strategy-vs-benchmark metrics as
    aligned text lines ready for printing or logging.
    """
    lines: List[str] = []
    header = (f"{'Period':<10} "
              f"{strategy_name + ' Ret%':>16} {benchmark_name + ' Ret%':>16} "
              f"{'Strat DD%':>10} {'Bench DD%':>10} "
              f"{'Strat Sharpe':>13} {'Bench Sharpe':>13}")
    lines.append(header)
    lines.append("-" * len(header))

    def row(label: str, s: Dict[str, float], b: Dict[str, float]) -> str:
        return (f"{label:<10} "
                f"{s['return_pct']:>+16.2f} {b['return_pct']:>+16.2f} "
                f"{s['max_drawdown_pct']:>10.2f} {b['max_drawdown_pct']:>10.2f} "
                f"{s['sharpe']:>13.3f} {b['sharpe']:>13.3f}")

    lines.append(row("FULL", slice_metrics(strategy_df), slice_metrics(benchmark_df)))

    strat_years = yearly_breakdown(strategy_df)
    bench_years = yearly_breakdown(benchmark_df)
    for year in sorted(set(strat_years) & set(bench_years)):
        lines.append(row(str(year), strat_years[year], bench_years[year]))

    return lines

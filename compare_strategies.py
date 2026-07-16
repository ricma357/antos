"""
compare_strategies.py
─────────────────────
Runs multiple strategies on the same dataset and produces a rich
multi-panel visualization for side-by-side performance comparison.

Usage:
    python3 compare_strategies.py

Output (saved to /data/):
    strategy_comparison.png   — 4-panel chart (equity, drawdown, rolling Sharpe, metrics table)
"""

import os
import logging
from typing import List
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.colors as mcolors

# Show engine output on the console. Use level=logging.DEBUG to also
# see every individual fill.
logging.basicConfig(level=logging.INFO, format="%(message)s")

from src.engine import BacktestEngine, BacktestResult
from src.strategy.sma_crossover import SMACrossover
from src.strategy.rsi_mean_reversion import RSIMeanReversion
from src.strategy.peak_breakout_pullback import PeakBreakoutPullback
from src.strategy.volatility_squeeze import VolatilitySqueezeMomentum
from src.strategy.rolling_ridge import RollingRidgeDirectionalPredictor
from src.execution.sim_broker import SimulatedBroker

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
DATA_DIR    = "/Users/flipis/dev/antos/data"
OUTPUT_DIR  = "/Users/flipis/dev/antos/data"
SYMBOLS     = ["SPY", "BTC-USD"]
INITIAL_CASH = 100_000.0
COMMISSION  = 0.001
SLIPPAGE    = 0.0005

# Strategy definitions: (name, strategy_instance)
STRATEGIES = [
    ("SMA Crossover (50/200)",  SMACrossover(short_window=50,  long_window=200)),
    ("SMA Crossover (20/100)",  SMACrossover(short_window=20,  long_window=100)),
    ("RSI Mean Reversion (14)", RSIMeanReversion(period=14, oversold=30, overbought=70)),
    ("RSI Mean Reversion (21)", RSIMeanReversion(period=21, oversold=25, overbought=75)),
    ("Peak Breakout Pullback", PeakBreakoutPullback(lookback_window=5, atr_period=14, vol_sma_period=20, atr_multiplier=3.0)),
    ("Volatility Squeeze Momentum", VolatilitySqueezeMomentum(bb_period=20, bb_std=2.0, squeeze_lookback=120, squeeze_percentile=20.0, roc_period=10, atr_period=14, atr_trail_mult=2.5, patience=5, strength=0.50)),
    ("Rolling Ridge ML Predictor", RollingRidgeDirectionalPredictor(lookback_window=90, l2_lambda=1.0, prediction_threshold=0.001, strength=0.50)),
]

# Distinct color palette for each strategy line
PALETTE = [
    "#1f77b4",  # blue
    "#ff7f0e",  # orange
    "#2ca02c",  # green
    "#d62728",  # red
    "#9467bd",  # purple
    "#8c564b",  # brown
]


def run_all_strategies() -> List[BacktestResult]:
    """Runs each strategy definition and collects BacktestResults."""
    results = []
    for name, strategy in STRATEGIES:
        engine = BacktestEngine(
            data_dir=DATA_DIR,
            symbols=SYMBOLS,
            initial_cash=INITIAL_CASH,
            strategy=strategy,
            execution_handler=SimulatedBroker(
                commission_rate=COMMISSION,
                slippage_rate=SLIPPAGE,
            ),
        )
        result = engine.run(strategy_name=name)
        results.append(result)
    return results


def plot_comparison(results: List[BacktestResult], output_dir: str) -> None:
    """
    Generates a rich 4-panel comparison figure:
      Panel 1 (large): Overlaid equity curves
      Panel 2 (medium): Overlaid drawdown curves
      Panel 3 (medium): 60-day rolling Sharpe ratio per strategy
      Panel 4 (table):  Side-by-side metrics table
    """
    fig = plt.figure(figsize=(18, 14))
    fig.suptitle(
        "Strategy Comparison Dashboard",
        fontsize=18, fontweight='bold', y=0.98
    )

    gs = gridspec.GridSpec(
        3, 2,
        figure=fig,
        height_ratios=[3, 2, 2],
        hspace=0.45,
        wspace=0.35,
    )

    ax_equity   = fig.add_subplot(gs[0, :])   # Full-width top panel
    ax_drawdown = fig.add_subplot(gs[1, 0])
    ax_rolling  = fig.add_subplot(gs[1, 1])
    ax_table    = fig.add_subplot(gs[2, :])

    # ── Panel 1: Equity Curves ────────────────────────────────────────────
    ax_equity.set_title("Equity Curves (Normalized to $100k Start)", fontsize=13, fontweight='bold')
    for i, result in enumerate(results):
        color = PALETTE[i % len(PALETTE)]
        df = result.equity_df
        label = f"{result.strategy_name}  (+{result.metrics['total_return_pct']:.1f}%)"
        ax_equity.plot(df['Equity'], label=label, color=color, linewidth=2.0)
        ax_equity.fill_between(df.index, df['Equity'], INITIAL_CASH, alpha=0.05, color=color)

    ax_equity.axhline(INITIAL_CASH, color='gray', linestyle='--', linewidth=0.8, alpha=0.6)
    ax_equity.set_ylabel("Portfolio Value ($)", fontsize=11)
    ax_equity.legend(loc='upper left', fontsize=9.5)
    ax_equity.grid(True, linestyle='--', alpha=0.35)
    ax_equity.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"${x:,.0f}")
    )

    # ── Panel 2: Drawdown ─────────────────────────────────────────────────
    ax_drawdown.set_title("Drawdown (%)", fontsize=12, fontweight='bold')
    for i, result in enumerate(results):
        color = PALETTE[i % len(PALETTE)]
        df = result.equity_df
        ax_drawdown.fill_between(
            df.index, df['Drawdown'] * 100, 0,
            alpha=0.25, color=color
        )
        ax_drawdown.plot(
            df.index, df['Drawdown'] * 100,
            color=color, linewidth=1.2, label=result.strategy_name
        )
    ax_drawdown.set_ylabel("Drawdown %", fontsize=10)
    ax_drawdown.legend(fontsize=8)
    ax_drawdown.grid(True, linestyle='--', alpha=0.35)

    # ── Panel 3: Rolling 60-day Sharpe ───────────────────────────────────
    ax_rolling.set_title("Rolling 60-Day Sharpe Ratio", fontsize=12, fontweight='bold')
    for i, result in enumerate(results):
        color = PALETTE[i % len(PALETTE)]
        df = result.equity_df.copy()
        df['DailyReturn'] = df['Equity'].pct_change()
        rolling_sharpe = (
            df['DailyReturn'].rolling(60).mean()
            / df['DailyReturn'].rolling(60).std()
        ) * (252 ** 0.5)
        ax_rolling.plot(
            rolling_sharpe.index, rolling_sharpe,
            color=color, linewidth=1.5, label=result.strategy_name
        )
    ax_rolling.axhline(0, color='gray', linestyle='--', linewidth=0.8)
    ax_rolling.axhline(1, color='green', linestyle=':', linewidth=0.8, alpha=0.6)
    ax_rolling.set_ylabel("Sharpe Ratio", fontsize=10)
    ax_rolling.legend(fontsize=8)
    ax_rolling.grid(True, linestyle='--', alpha=0.35)

    # ── Panel 4: Metrics Table ────────────────────────────────────────────
    ax_table.axis('off')
    ax_table.set_title("Performance Metrics Summary", fontsize=12, fontweight='bold', pad=12)

    col_labels = [
        "Strategy",
        "Total Return",
        "Ann. Return",
        "Max Drawdown",
        "Sharpe",
        "Sortino",
        "Calmar",
        "# Trades",
    ]

    table_data = []
    for result in results:
        m = result.metrics
        table_data.append([
            result.strategy_name,
            f"{m['total_return_pct']:+.2f}%",
            f"{m['ann_return_pct']:+.2f}%",
            f"{m['max_drawdown_pct']:.2f}%",
            f"{m['sharpe']:.3f}",
            f"{m['sortino']:.3f}",
            f"{m['calmar']:.3f}",
            str(m['num_trades']),
        ])

    table = ax_table.table(
        cellText=table_data,
        colLabels=col_labels,
        loc='center',
        cellLoc='center',
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    table.scale(1.0, 1.8)

    # Color-code the header row
    for j in range(len(col_labels)):
        table[0, j].set_facecolor('#2c3e50')
        table[0, j].set_text_props(color='white', fontweight='bold')

    # Alternate row shading for readability
    for i in range(1, len(table_data) + 1):
        bg = '#f0f4f8' if i % 2 == 0 else 'white'
        for j in range(len(col_labels)):
            table[i, j].set_facecolor(bg)

    # Save
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "strategy_comparison.png")
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nSaved comparison chart: {path}")


if __name__ == "__main__":
    results = run_all_strategies()
    plot_comparison(results, OUTPUT_DIR)

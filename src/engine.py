import os
import logging
from dataclasses import dataclass
from typing import List, Dict, Any
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend — prevents crashes on headless servers
import matplotlib.pyplot as plt
from src.data_provider import HistoricalCSVDataProvider
from src.strategy.base import BaseStrategy
from src.execution.base import BaseExecutionHandler
from src.portfolio import Portfolio
from src.events import MarketEvent

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """
    Structured container for all outputs of a single backtest run.
    Passed to the comparison runner for multi-strategy visualization.
    """
    strategy_name: str
    equity_df: pd.DataFrame      # Indexed by Date; columns: Cash, Holdings, Equity, Drawdown
    trade_log: List[dict]
    metrics: Dict[str, Any]      # Sharpe, Sortino, Calmar, Return, Drawdown …


class BacktestEngine:
    """
    Core Event-Driven Simulation Engine.

    Critical execution order per bar:
    1. Process pending fills at this bar's Open price.   ← eliminates lookahead bias
    2. Update portfolio mark-to-market at this bar's Close price.
    3. Run strategy signal calculations.
    4. Queue any new orders for the next bar.
    """

    def __init__(
        self,
        data_dir: str,
        symbols: List[str],
        initial_cash: float,
        strategy: BaseStrategy,
        execution_handler: BaseExecutionHandler,
        risk_free_rate: float = 0.0,
    ):
        self.data_provider    = HistoricalCSVDataProvider(data_dir, symbols)
        self.strategy         = strategy
        self.execution_handler = execution_handler
        self.portfolio        = Portfolio(initial_cash)
        self.risk_free_rate   = risk_free_rate

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, strategy_name: str = "Strategy") -> BacktestResult:
        """
        Runs the event loop and returns a structured BacktestResult.
        """
        print(f"\nRunning: {strategy_name}")
        print("-" * 50)

        for market_bar in self.data_provider.stream_events():
            # 1. Fill yesterday's pending orders at today's Open
            for fill in self.execution_handler.process_market_event(market_bar):
                self.portfolio.update_fill(fill)

            # 2. Mark portfolio to today's Close
            self.portfolio.update_market_price(market_bar)

            # 3. Run strategy on today's data
            current_qty = self.portfolio.positions.get(market_bar.symbol, 0)
            signals = self.strategy.calculate_signals(market_bar, current_qty)

            # 4. Convert signals → orders, queue for tomorrow's Open
            for signal in signals:
                order = self.portfolio.generate_order(signal)
                if order:
                    self.execution_handler.queue_order(order)

        print(f"  {len(self.portfolio.trade_log)} trades executed.")
        return self._build_result(strategy_name)

    # ------------------------------------------------------------------
    # Internal: metrics and packaging
    # ------------------------------------------------------------------

    def _build_result(self, strategy_name: str) -> BacktestResult:
        """
        Computes all performance metrics and packages them into a BacktestResult.
        """
        if not self.portfolio.equity_curve:
            logger.warning(f"No equity data for '{strategy_name}'. Returning empty result.")
            empty_df = pd.DataFrame(columns=['Cash', 'Holdings', 'Equity', 'Drawdown', 'Peak', 'DailyReturn'])
            return BacktestResult(
                strategy_name=strategy_name,
                equity_df=empty_df,
                trade_log=[],
                metrics={k: 0.0 for k in [
                    'initial_balance', 'final_balance', 'total_return_pct',
                    'ann_return_pct', 'max_drawdown_pct', 'sharpe', 'sortino',
                    'calmar', 'num_trades'
                ]},
            )

        df = pd.DataFrame(
            self.portfolio.equity_curve,
            columns=['Date', 'Cash', 'Holdings', 'Equity']
        ).set_index('Date')

        # Drop duplicate timestamps (multiple assets sharing same daily date)
        df = df[~df.index.duplicated(keep='last')]

        initial_val = self.portfolio.initial_cash
        final_val   = df['Equity'].iloc[-1]

        # Drawdown
        df['Peak']     = df['Equity'].cummax()
        df['Drawdown'] = (df['Equity'] - df['Peak']) / df['Peak']
        max_drawdown   = df['Drawdown'].min() * 100

        # Returns
        df['DailyReturn'] = df['Equity'].pct_change()

        # Calculate dynamic annualization factor
        if len(df) > 1:
            days_diff = (df.index[-1] - df.index[0]).days
            years = days_diff / 365.25
            ann_factor = len(df) / years if years > 0 else 252.0
        else:
            ann_factor = 252.0
            years = 0.0

        # Daily risk-free rate
        daily_rf = (1 + self.risk_free_rate) ** (1 / ann_factor) - 1 if ann_factor > 0 else 0.0
        excess_returns = df['DailyReturn'] - daily_rf

        # Sharpe: penalizes total volatility of excess returns
        avg_excess_ret = excess_returns.mean()
        std_excess_ret = excess_returns.std()
        sharpe = (avg_excess_ret / std_excess_ret * (ann_factor ** 0.5)) if std_excess_ret > 0 else 0.0

        # Sortino: penalizes only downside volatility of excess returns
        downside_returns = excess_returns[excess_returns < 0]
        down_std = downside_returns.std()
        sortino = (avg_excess_ret / down_std * (ann_factor ** 0.5)) if down_std > 0 else 0.0

        # Calmar: annualized return / max drawdown
        ann_ret   = ((final_val / initial_val) ** (1 / years) - 1) * 100 if years > 0 else 0.0
        total_ret = (final_val - initial_val) / initial_val * 100
        calmar    = ann_ret / abs(max_drawdown) if max_drawdown != 0 else 0.0

        # Win rate
        winning_trades = [t for t in self.portfolio.trade_log if t['direction'] == 'SELL' and t.get('nav_after', 0) > 0]

        metrics = {
            'initial_balance':  initial_val,
            'final_balance':    final_val,
            'total_return_pct': total_ret,
            'ann_return_pct':   ann_ret,
            'max_drawdown_pct': max_drawdown,
            'sharpe':           sharpe,
            'sortino':          sortino,
            'calmar':           calmar,
            'num_trades':       len(self.portfolio.trade_log),
            'ann_factor':       ann_factor,
        }

        w = 58
        print("\n" + "=" * w)
        print(f"  Strategy: {strategy_name}")
        print("=" * w)
        print(f"  Initial Balance:       ${initial_val:>12,.2f}")
        print(f"  Ending Balance:        ${final_val:>12,.2f}")
        print(f"  Cumulative Return:     {total_ret:>+12.2f}%")
        print(f"  Annualized Return:     {ann_ret:>+12.2f}%")
        print(f"  Maximum Drawdown:      {max_drawdown:>12.2f}%")
        print(f"  Sharpe Ratio  (Ann.):  {sharpe:>12.3f}")
        print(f"  Sortino Ratio (Ann.):  {sortino:>12.3f}")
        print(f"  Calmar Ratio  (Ann.):  {calmar:>12.3f}")
        print(f"  Annualization Factor:  {ann_factor:>12.1f}")
        if self.risk_free_rate > 0.0:
            print(f"  Risk-Free Rate:        {self.risk_free_rate * 100:>11.2f}%")
        print(f"  Executed Trades:       {len(self.portfolio.trade_log):>12}")
        print("=" * w + "\n")

        return BacktestResult(
            strategy_name=strategy_name,
            equity_df=df,
            trade_log=self.portfolio.trade_log,
            metrics=metrics,
        )


# ------------------------------------------------------------------
# Standalone chart helper (used by compare_strategies.py too)
# ------------------------------------------------------------------

def save_single_chart(result: BacktestResult, output_dir: str) -> None:
    """Saves a two-panel equity + drawdown chart for a single BacktestResult."""
    df = result.equity_df
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 8), gridspec_kw={'height_ratios': [3, 1]}
    )
    ax1.plot(df['Equity'], color='#1f77b4', linewidth=2, label=result.strategy_name)
    ax1.fill_between(df.index, df['Equity'], alpha=0.10, color='#1f77b4')
    ax1.set_title(f'Equity Curve — {result.strategy_name}', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Portfolio Value ($)', fontsize=12)
    ax1.legend()
    ax1.grid(True, linestyle='--', alpha=0.4)
    ax2.fill_between(df.index, df['Drawdown'] * 100, 0, alpha=0.4, color='#d62728')
    ax2.set_ylabel('Drawdown %')
    ax2.set_xlabel('Date')
    ax2.grid(True, linestyle='--', alpha=0.4)
    plt.tight_layout()
    os.makedirs(output_dir, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in result.strategy_name).lower()
    while '__' in safe:
        safe = safe.replace('__', '_')
    safe = safe.strip('_')
    path = os.path.join(output_dir, f"backtest_{safe}.png")
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Saved chart: {path}")

import logging

from src.engine import BacktestEngine, save_single_chart
from src.strategy.sma_crossover import SMACrossover
from src.execution.sim_broker import SimulatedBroker

if __name__ == "__main__":
    # Show engine output on the console. Use level=logging.DEBUG to also
    # see every individual fill.
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    DATA_DIRECTORY      = "/Users/flipis/dev/antos/data"
    TRADING_INSTRUMENTS = ["SPY", "BTC-USD"]
    STARTING_CAPITAL    = 100_000.0

    strategy = SMACrossover(short_window=50, long_window=200)
    broker   = SimulatedBroker(commission_rate=0.001, slippage_rate=0.0005)

    backtest = BacktestEngine(
        data_dir=DATA_DIRECTORY,
        symbols=TRADING_INSTRUMENTS,
        initial_cash=STARTING_CAPITAL,
        strategy=strategy,
        execution_handler=broker,
    )

    result = backtest.run(strategy_name="SMA Crossover (50/200)")
    save_single_chart(result, DATA_DIRECTORY)

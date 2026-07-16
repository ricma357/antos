"""
LiveBotService — framework-independent core of the paper/live trading bot.

Owns state persistence, bot lifecycle (start/stop/reset), the market-clock
scheduler, and tick execution. The FastAPI layer (api/routes/bot.py) is a
thin adapter that translates domain exceptions into HTTP responses.

Raises domain exceptions (BotError subclasses) instead of HTTP errors so the
service is fully unit-testable without a web server.
"""

import os
import json
import math
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.data_provider import HistoricalCSVDataProvider
from src.live_data_provider import LiveDataProvider
from src.events import MarketEvent, OrderEvent, SignalEvent
from src.execution.sim_broker import SimulatedBroker
from src.scheduler import MarketClockScheduler, EST
from src.journal import TradeJournal
from src.notifier import Notifier

logger = logging.getLogger(__name__)


# --- Domain exceptions (mapped to HTTP codes by the API layer) ---

class BotError(Exception):
    """Base class for bot domain errors."""


class BotAlreadyActive(BotError):
    pass


class BotInactive(BotError):
    pass


class TickInProgress(BotError):
    pass


class DataNotFound(BotError):
    pass


class CredentialsMissing(BotError):
    pass


class LiveDataUnavailable(BotError):
    pass


class StateResetFailed(BotError):
    pass


class LiveBotService:
    """
    Encapsulates all live-bot behavior behind an injectable, testable API.

    Args:
        data_dir: directory containing {symbol}_daily.csv files.
        state_file: path of the JSON state file.
        strategy_factory: callable (strategy_id, params) -> BaseStrategy.
            Injected so this module never imports from the API layer.
    """

    def __init__(self, data_dir: str, state_file: str,
                 strategy_factory: Callable[[str, Dict[str, Any]], Any]):
        self.data_dir = data_dir
        self.state_file = state_file
        self.strategy_factory = strategy_factory

        self._scheduler: Optional[MarketClockScheduler] = None
        self._scheduler_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._tick_lock = threading.Lock()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def default_state(self) -> Dict[str, Any]:
        return {
            "active": False,
            "strategy_id": "",
            "symbols": [],
            "initial_cash": 100000.0,
            "cash": 100000.0,
            "positions": {},  # symbol -> {"qty": int, "avg_cost": float}
            "trade_log": [],
            "equity_curve": [],  # list of {"time": str, "value": float, "drawdown": float}
            "pending_orders": [],  # list of order dicts
            "current_index": 0,
            "params": {},
            "commission_rate": 0.001,
            "slippage_rate": 0.0005,
            "peak_equity": 100000.0,
            "live_mode": False,
            "scheduler_active": False,
            "scheduler_interval": 86400,
            "broker_type": "simulated",
            "metrics": {
                "total_return_pct": 0.0,
                "ann_return_pct": 0.0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "max_drawdown_pct": 0.0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "num_trades": 0
            },
            "insights": ["Bot is currently uninitialized. Start the bot to begin tracking metrics and insights."]
        }

    def load_state(self) -> Dict[str, Any]:
        with self._state_lock:
            if os.path.exists(self.state_file):
                try:
                    with open(self.state_file, "r") as f:
                        state = json.load(f)
                    # Scrub credentials persisted by older versions of the app —
                    # they now live exclusively in environment variables.
                    for legacy_key in ("alpaca_api_key", "alpaca_api_secret", "alpaca_base_url"):
                        state.pop(legacy_key, None)
                    return state
                except Exception as e:
                    logger.error(f"Failed to read state file: {e}")
            return self.default_state()

    def save_state(self, state: Dict[str, Any]) -> None:
        with self._state_lock:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return self.load_state()

    def journal_summary(self, limit: int = 100) -> Dict[str, Any]:
        state = self.load_state()
        strategy_id = state.get("strategy_id")
        journal = TradeJournal()
        return {
            "trades": journal.get_trades(limit=limit, strategy_id=strategy_id),
            "metrics": journal.get_performance_summary(strategy_id=strategy_id),
        }

    def start(
        self,
        strategy_id: str,
        symbols: List[str],
        initial_cash: float = 100000.0,
        commission_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        params: Optional[Dict[str, Any]] = None,
        live_mode: bool = False,
        broker_type: str = "simulated",
    ) -> Dict[str, Any]:
        params = params or {}
        state = self.load_state()
        if state.get("active"):
            raise BotAlreadyActive("Trading bot is already active. Stop or reset it first.")

        # Alpaca credentials must be configured server-side — never sent via the API.
        if broker_type == "alpaca" and not (
            os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_API_SECRET")
        ):
            raise CredentialsMissing(
                "Alpaca broker requires ALPACA_API_KEY and ALPACA_API_SECRET "
                "environment variables to be set on the server."
            )

        # Verify symbol data exists
        for sym in symbols:
            safe_name = sym.lower().replace('-', '_')
            file_path = os.path.join(self.data_dir, f"{safe_name}_daily.csv")
            if not os.path.exists(file_path):
                raise DataNotFound(f"Data for symbol '{sym}' not found. Download it first.")

        # Ingest provider to find valid start index
        provider = HistoricalCSVDataProvider(self.data_dir, symbols)
        event_stream = provider._event_stream

        # Pre-warm window: if live mode, we pre-warm with the entire history to get
        # indicator states. Otherwise, we start at 200 bars as a simulation start point.
        if live_mode:
            warmup_index = max(0, len(event_stream) - 1)
        else:
            warmup_index = min(200, len(event_stream) - 10)
            if warmup_index < 0:
                warmup_index = 0

        current_date = event_stream[warmup_index].timestamp.strftime('%Y-%m-%d')

        state["active"] = True
        state["strategy_id"] = strategy_id
        state["symbols"] = symbols
        state["initial_cash"] = initial_cash
        state["cash"] = initial_cash
        state["positions"] = {sym: {"qty": 0, "avg_cost": 0.0} for sym in symbols}
        state["trade_log"] = []
        state["equity_curve"] = [{"time": current_date, "value": initial_cash, "drawdown": 0.0}]
        state["pending_orders"] = []
        state["current_index"] = warmup_index
        state["params"] = params
        state["commission_rate"] = commission_rate
        state["slippage_rate"] = slippage_rate
        state["peak_equity"] = initial_cash
        state["live_mode"] = live_mode
        state["broker_type"] = broker_type
        state["metrics"] = {
            "total_return_pct": 0.0,
            "ann_return_pct": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "num_trades": 0
        }

        if live_mode:
            state["insights"] = [f"Bot initialized in Live Data Mode using {strategy_id} on {', '.join(symbols)}. Click 'Trigger Daily Tick' to fetch live prices from Yahoo Finance."]
        else:
            state["insights"] = [f"Bot initialized successfully using {strategy_id} on {', '.join(symbols)}. Click 'Trigger Tick' to execute candles."]

        self.save_state(state)
        return state

    def stop(self) -> Dict[str, Any]:
        state = self.load_state()
        state["active"] = False
        state["insights"].insert(0, "Bot has been stopped. Current positions are frozen.")

        with self._scheduler_lock:
            if self._scheduler is not None and self._scheduler.is_active():
                self._scheduler.stop()
                self._scheduler = None
            state["scheduler_active"] = False

        self.save_state(state)
        return state

    def reset(self) -> Dict[str, Any]:
        with self._scheduler_lock:
            if self._scheduler is not None and self._scheduler.is_active():
                self._scheduler.stop()
                self._scheduler = None

        if os.path.exists(self.state_file):
            try:
                os.remove(self.state_file)
            except Exception as e:
                raise StateResetFailed(f"Failed to delete state file: {e}")

        db_file = os.path.join(self.data_dir, "trade_journal.db")
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception as e:
                logger.error(f"Failed to delete trade_journal.db: {e}")

        default_state = self.load_state()
        self.save_state(default_state)
        return default_state

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    def scheduler_next_run_iso(self) -> Optional[str]:
        with self._scheduler_lock:
            if self._scheduler is not None:
                return self._scheduler.get_next_run_iso()
        return None

    def start_scheduler(self) -> Dict[str, Any]:
        state = self.load_state()
        if not state.get("active"):
            raise BotInactive("Bot is inactive. Start the bot first.")

        with self._scheduler_lock:
            if self._scheduler is not None and self._scheduler.is_active():
                return state  # already running — state reflects current schedule
            self._scheduler = MarketClockScheduler(self._run_scheduled_tick)
            self._scheduler.start()
            next_run = self._scheduler.get_next_run_iso()

            state["scheduler_active"] = True
            state["scheduler_interval"] = "market_clock"
            state["next_run_time"] = next_run
            state["insights"].insert(0, f"📅 MarketClock scheduler activated. Ticks at 09:40 & 15:50 ET on business days. Next run: {next_run}")
            self.save_state(state)

        return state

    def stop_scheduler(self) -> Dict[str, Any]:
        state = self.load_state()

        with self._scheduler_lock:
            if self._scheduler is not None and self._scheduler.is_active():
                self._scheduler.stop()
                self._scheduler = None

            state["scheduler_active"] = False
            state["next_run_time"] = None
            state["insights"].insert(0, "📅 MarketClock scheduler stopped.")
            self.save_state(state)

        return state

    def init_from_persisted_state(self) -> None:
        """
        Auto-restart the scheduler after a process restart if state says it
        should be running, then fire a catch-up tick for any missed targets.
        """
        state = self.load_state()
        if state.get("active") and state.get("scheduler_active"):
            logger.info("Auto-initializing MarketClockScheduler from persisted state.")
            with self._scheduler_lock:
                if self._scheduler is None:
                    self._scheduler = MarketClockScheduler(self._run_scheduled_tick)
                    self._scheduler.start()
                    logger.info(f"MarketClockScheduler initialized. Next run: {self._scheduler.get_next_run_iso()}")

            self._run_startup_catchup(state)

    def _run_scheduled_tick(self) -> None:
        """Callback invoked by MarketClockScheduler at 09:40 / 15:50 ET."""
        state = self.load_state()
        if not state.get("active"):
            logger.info("Bot is inactive. Skipping automated tick.")
            return

        phase = MarketClockScheduler.tick_phase()
        logger.info(f"MarketClock: Executing {phase} tick.")
        try:
            self.tick()
            state = self.load_state()
            state["insights"].insert(0, f"🕐 {phase} tick executed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.")
            # Persist the last tick time so startup catch-up knows where we left off
            state["last_tick_time"] = datetime.now().isoformat()
            state["next_run_time"] = self.scheduler_next_run_iso()
            self.save_state(state)
            logger.info(f"Scheduled {phase} tick executed successfully.")
        except Exception as e:
            logger.error(f"Error executing scheduled {phase} tick: {e}", exc_info=True)

    def _run_startup_catchup(self, state: Dict[str, Any]) -> None:
        """
        On startup (after Docker restart or uvicorn reload), check if any
        scheduled ticks were missed while the process was down and fire a
        single catch-up tick. A single tick is sufficient because the live
        data provider always fetches the latest candle from Yahoo Finance.
        """
        last_tick_iso = state.get("last_tick_time")
        if not last_tick_iso:
            logger.info("Startup catch-up: No last_tick_time recorded. Skipping.")
            return

        try:
            last_tick_dt = datetime.fromisoformat(last_tick_iso)
            # Ensure timezone-aware (stored in server TZ, but scheduler uses EST)
            if last_tick_dt.tzinfo is None:
                last_tick_dt = last_tick_dt.replace(tzinfo=EST)

            now = MarketClockScheduler._now_est()
            missed = MarketClockScheduler.missed_ticks_between(last_tick_dt, now)

            if missed:
                logger.info(
                    f"Startup catch-up: {len(missed)} tick(s) missed since {last_tick_iso}. "
                    f"Missed targets: {[t.strftime('%Y-%m-%d %H:%M %Z') for t in missed]}"
                )
                # Fire a single catch-up tick (latest data covers all missed windows)
                self._run_scheduled_tick()
                logger.info("Startup catch-up tick completed.")
            else:
                logger.info("Startup catch-up: No missed ticks. All good.")
        except Exception as e:
            logger.error(f"Error during startup catch-up: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Tick execution
    # ------------------------------------------------------------------

    def tick(self) -> Dict[str, Any]:
        if not self._tick_lock.acquire(blocking=False):
            raise TickInProgress("A market tick execution is already in progress.")
        try:
            return self._execute_tick()
        finally:
            self._tick_lock.release()

    def _execute_tick(self) -> Dict[str, Any]:
        notifier = Notifier()
        journal = TradeJournal()

        state = self.load_state()
        if not state.get("active"):
            raise BotInactive("Bot is inactive. Start the bot first.")

        symbols = state.get("symbols", [])
        current_index = state.get("current_index", 0)
        commission_rate = state.get("commission_rate", 0.001)
        slippage_rate = state.get("slippage_rate", 0.0005)

        # Load all historical events for pre-warming later
        provider = HistoricalCSVDataProvider(self.data_dir, symbols)
        event_stream = provider._event_stream

        day_events: List[MarketEvent] = []
        date_str = datetime.now().strftime('%Y-%m-%d')

        if state.get("live_mode", False):
            live_provider = LiveDataProvider()
            day_events = live_provider.get_latest_bars(symbols)
            if not day_events:
                raise LiveDataUnavailable("Failed to retrieve live Yahoo Finance data for symbols.")
            date_str = max(e.timestamp for e in day_events).strftime('%Y-%m-%d')
            current_index = len(event_stream)  # Keep index at the end of historical records
        else:
            if current_index >= len(event_stream):
                state["active"] = False
                state["insights"].insert(0, "Simulation data boundary reached. Bot halted automatically.")
                self.save_state(state)
                return state

            # 1. Gather all events sharing the target tick timestamp (simulating a trading day)
            target_date = event_stream[current_index].timestamp

            while current_index < len(event_stream) and event_stream[current_index].timestamp == target_date:
                day_events.append(event_stream[current_index])
                current_index += 1

            date_str = target_date.strftime('%Y-%m-%d')

        # Reconstruct broker and portfolio
        broker_type = state.get("broker_type", "simulated")
        if broker_type == "alpaca":
            from src.execution.paper_broker import AlpacaPaperBroker
            # Credentials are read from ALPACA_API_KEY / ALPACA_API_SECRET /
            # ALPACA_BASE_URL environment variables — never from the API or state file.
            broker = AlpacaPaperBroker()
        else:
            broker = SimulatedBroker(commission_rate=commission_rate, slippage_rate=slippage_rate)

        # Restore queued pending orders
        if broker_type == "alpaca":
            for order_dict in state.get("pending_orders", []):
                order_id = order_dict.get("alpaca_order_id")
                if order_id:
                    broker.pending_orders[order_id] = OrderEvent(
                        symbol=order_dict["symbol"],
                        order_type=order_dict["order_type"],
                        quantity=order_dict["quantity"],
                        direction=order_dict["direction"],
                        price=order_dict.get("price")
                    )
        else:
            for order_dict in state.get("pending_orders", []):
                broker.queue_order(OrderEvent(
                    symbol=order_dict["symbol"],
                    order_type=order_dict["order_type"],
                    quantity=order_dict["quantity"],
                    direction=order_dict["direction"],
                    price=order_dict.get("price")
                ))

        # Keep track of filled trades in this tick
        cash = state.get("cash", 100000.0)
        positions = state.get("positions", {})
        trade_log = state.get("trade_log", [])

        # Process fills at the Open price of today's market events
        for event in day_events:
            fills = broker.process_market_event(event)
            for fill in fills:
                symbol = fill.symbol
                qty = fill.quantity
                direction = fill.direction
                price = fill.fill_price
                commission = fill.commission

                # Position bookkeeping
                current_qty = positions.get(symbol, {}).get("qty", 0)
                avg_cost = positions.get(symbol, {}).get("avg_cost", 0.0)

                realized_pnl = 0.0

                if direction == "BUY":
                    # Average cost basis calculation
                    new_qty = current_qty + qty
                    new_avg_cost = ((avg_cost * current_qty) + (price * qty)) / new_qty if new_qty > 0 else 0.0
                    positions[symbol] = {"qty": new_qty, "avg_cost": new_avg_cost}
                    cash -= (price * qty + commission)
                elif direction == "SELL":
                    # Sell off positions
                    new_qty = max(0, current_qty - qty)
                    if current_qty > 0:
                        # Compute simple realized pnl from purchase average cost
                        realized_pnl = ((price - avg_cost) * qty) - commission
                    positions[symbol] = {"qty": new_qty, "avg_cost": avg_cost if new_qty > 0 else 0.0}
                    cash += (price * qty - commission)

                trade_log.append({
                    "timestamp": fill.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    "symbol": symbol,
                    "direction": direction,
                    "quantity": qty,
                    "fill_price": round(price, 2),
                    "commission": round(commission, 2),
                    "remaining_cash": round(cash, 2),
                    "position_after": new_qty,
                    "realized_pnl": round(realized_pnl, 2)
                })

                journal.add_trade(
                    timestamp=fill.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    strategy_id=state.get("strategy_id", "unknown"),
                    symbol=symbol,
                    direction=direction,
                    quantity=qty,
                    price=price,
                    commission=commission,
                    realized_pnl=realized_pnl,
                    remaining_cash=cash,
                    position_after=new_qty
                )

                notifier.notify(
                    f"🔔 <b>Trade Executed!</b>\n"
                    f"Symbol: {symbol}\n"
                    f"Direction: {direction}\n"
                    f"Quantity: {qty}\n"
                    f"Price: ${price:,.2f}\n"
                    f"Commission: ${commission:.2f}"
                )

        # ── Idempotency guard: one signal evaluation per bar date ──────
        # A daily strategy must act on each candle exactly once. The market
        # clock fires twice per trading day (open + close ticks, plus
        # catch-up ticks), so in live mode the same daily candle arrives
        # repeatedly. Re-evaluating it after fills causes order churn:
        # an EXIT fills, the re-run sees a flat position at the same bar,
        # re-enters LONG at the same price, and the ledger fills with
        # duplicate trades. Later ticks on an already-evaluated bar still
        # process fills — they just don't generate new signals.
        already_evaluated = state.get("last_signal_date") == date_str

        new_signals: List[SignalEvent] = []
        close_prices: Dict[str, float] = {}
        for event in day_events:
            close_prices[event.symbol] = event.close_price

        if not already_evaluated:
            # Reconstruct strategy internal history to produce correct current signals
            strategy_id = state.get("strategy_id", "")
            params = state.get("params", {})
            strategy = self.strategy_factory(strategy_id, params)

            # Feed history sequentially to pre-warm indicators via the
            # state-only fast path (no model fitting on historical bars —
            # for rolling_ridge this replaces ~9,500 ridge fits per tick
            # with a single fit on the live bar).
            for i in range(current_index):
                historical_event = event_stream[i]
                # Check positions at that moment (we approximate here by passing current)
                approx_qty = positions.get(historical_event.symbol, {}).get("qty", 0)
                strategy.warmup(historical_event, approx_qty)

            # Evaluate signals on today's Close prices
            for event in day_events:
                current_qty = positions.get(event.symbol, {}).get("qty", 0)
                signals = strategy.calculate_signals(event, current_qty)
                new_signals.extend(signals)

            state["last_signal_date"] = date_str

        # Sizing logic & queue new OrderEvents
        # Calculate today's NAV
        holdings_value = sum(positions.get(sym, {}).get("qty", 0) * close_prices.get(sym, 0.0) for sym in symbols)
        nav = cash + holdings_value

        # Belt-and-braces duplicate guard: never queue a new order for a
        # symbol that already has one in flight (computed after fills, so
        # only genuinely unfilled orders block).
        if broker_type == "alpaca":
            pending_symbols = {o.symbol for o in broker.pending_orders.values()}
        else:
            pending_symbols = {o.symbol for o in broker.pending_orders}

        # Fair-share cap: no symbol may target more than NAV/n_symbols,
        # so a 6-symbol portfolio can't be starved by whichever symbols
        # signal first (event order is alphabetical on ties).
        max_alloc = 1.0 / len(symbols) if symbols else 1.0

        # Convert signals to orders
        for signal in new_signals:
            strength = min(signal.strength, max_alloc)
            symbol = signal.symbol
            close_price = close_prices.get(symbol, 0.0)
            if close_price <= 0:
                continue
            if symbol in pending_symbols:
                logger.warning(f"Skipping {signal.signal_type} signal for {symbol}: order already pending.")
                continue

            current_qty = positions.get(symbol, {}).get("qty", 0)

            if signal.signal_type == "LONG":
                target_value = nav * strength
                target_qty = math.floor(target_value / close_price)
                buy_qty = target_qty - current_qty

                if buy_qty > 0:
                    # Pre-trade clamping checks
                    cost_estimate = buy_qty * close_price * (1.0 + commission_rate + slippage_rate)
                    if cost_estimate > cash:
                        # clamp
                        buy_qty = math.floor(cash / (close_price * (1.0 + commission_rate + slippage_rate)))

                    if buy_qty > 0:
                        broker.queue_order(OrderEvent(
                            symbol=symbol,
                            order_type="MKT",
                            quantity=buy_qty,
                            direction="BUY"
                        ))
                        pending_symbols.add(symbol)
                        notifier.notify(
                            f"📤 <b>Order Placed</b>\n"
                            f"Symbol: {symbol}\n"
                            f"Direction: BUY\n"
                            f"Quantity: {buy_qty}\n"
                            f"Type: MKT"
                        )
            elif signal.signal_type == "EXIT" and current_qty > 0:
                broker.queue_order(OrderEvent(
                    symbol=symbol,
                    order_type="MKT",
                    quantity=current_qty,
                    direction="SELL"
                ))
                pending_symbols.add(symbol)
                notifier.notify(
                    f"📤 <b>Order Placed (EXIT)</b>\n"
                    f"Symbol: {symbol}\n"
                    f"Direction: SELL\n"
                    f"Quantity: {current_qty}\n"
                    f"Type: MKT"
                )

        # Calculate equity curve entry
        peak_equity = max(state.get("peak_equity", nav), nav)
        drawdown = (nav - peak_equity) / peak_equity if peak_equity > 0 else 0.0

        prev_max_dd = min((pt.get("drawdown", 0.0) for pt in state.get("equity_curve", [])), default=0.0)
        if drawdown < -0.10 and drawdown < prev_max_dd:
            notifier.notify(
                f"⚠️ <b>RISK WARNING: Drawdown Breach!</b>\n"
                f"Current Drawdown: {drawdown*100:.2f}%\n"
                f"Net Asset Value (NAV): ${nav:,.2f}"
            )

        equity_curve = state.get("equity_curve", [])
        equity_curve.append({
            "time": date_str,
            "value": round(nav, 2),
            "drawdown": round(drawdown, 4)
        })

        # Serialize pending orders back
        pending_orders_list = []
        if broker_type == "alpaca":
            for order_id, order in broker.pending_orders.items():
                pending_orders_list.append({
                    "alpaca_order_id": order_id,
                    "symbol": order.symbol,
                    "order_type": order.order_type,
                    "quantity": order.quantity,
                    "direction": order.direction,
                    "price": order.price
                })
        else:
            for order in broker.pending_orders:
                pending_orders_list.append({
                    "symbol": order.symbol,
                    "order_type": order.order_type,
                    "quantity": order.quantity,
                    "direction": order.direction,
                    "price": order.price
                })

        # Assemble next state
        state["cash"] = round(cash, 2)
        state["positions"] = positions
        state["trade_log"] = trade_log
        state["equity_curve"] = equity_curve
        state["pending_orders"] = pending_orders_list
        state["current_index"] = current_index
        state["current_date"] = date_str
        state["peak_equity"] = round(peak_equity, 2)
        # Persist latest close prices so the frontend can compute accurate NAV
        # (without this, the UI falls back to avg_cost → stale purchase prices)
        state["last_prices"] = {sym: round(p, 2) for sym, p in close_prices.items()}

        # Recalculate metrics and generate insights
        state["metrics"] = calculate_metrics(state)
        state["insights"] = generate_insights(state, date_str, close_prices)

        self.save_state(state)
        return state


# ----------------------------------------------------------------------
# Analytics helpers (pure functions of state)
# ----------------------------------------------------------------------

def calculate_metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    """Computes bot metrics based on the equity curve and trade logs."""
    trade_log = state.get("trade_log", [])
    equity_curve = state.get("equity_curve", [])
    initial_cash = state.get("initial_cash", 100000.0)

    if not equity_curve:
        return state.get("metrics", {})

    final_equity = equity_curve[-1]["value"]
    total_ret = ((final_equity - initial_cash) / initial_cash) * 100

    # Calculate drawdown metrics
    max_dd = 0.0
    for pt in equity_curve:
        max_dd = min(max_dd, pt.get("drawdown", 0.0))

    # Calculate Win Rate & Profit Factor from realized P&L on SELL fills
    wins = []
    losses = []
    for t in trade_log:
        if t["direction"] == "SELL":
            pnl = t.get("realized_pnl", 0.0)
            if pnl > 0:
                wins.append(pnl)
            elif pnl < 0:
                losses.append(pnl)

    win_rate = (len(wins) / (len(wins) + len(losses)) * 100) if (wins or losses) else 0.0

    gross_profits = sum(wins)
    gross_losses = abs(sum(losses))
    profit_factor = (gross_profits / gross_losses) if gross_losses > 0 else (gross_profits if gross_profits > 0 else 1.0)

    # Calculate daily returns for Sharpe/Sortino
    daily_returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["value"]
        curr = equity_curve[i]["value"]
        if prev > 0:
            daily_returns.append((curr - prev) / prev)

    sharpe = 0.0
    sortino = 0.0
    if len(daily_returns) > 1:
        avg_ret = sum(daily_returns) / len(daily_returns)
        # Simple standard deviation
        var_ret = sum((r - avg_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_ret = math.sqrt(var_ret)

        # Annualized Sharpe (assuming 252 days)
        if std_ret > 0:
            sharpe = (avg_ret / std_ret) * math.sqrt(252)

        downside_returns = [r for r in daily_returns if r < 0]
        if len(downside_returns) > 1:
            down_var = sum(r ** 2 for r in downside_returns) / len(downside_returns)
            down_std = math.sqrt(down_var)
            if down_std > 0:
                sortino = (avg_ret / down_std) * math.sqrt(252)

    # Calculate compound annual return
    years = len(equity_curve) / 252.0 if len(equity_curve) > 0 else 0.0
    ann_ret = ((final_equity / initial_cash) ** (1 / years) - 1) * 100 if years > 0.1 else total_ret

    return {
        "total_return_pct": round(total_ret, 2),
        "ann_return_pct": round(ann_ret, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "num_trades": len(trade_log)
    }


def generate_insights(state: Dict[str, Any], current_date: str,
                      current_close_prices: Dict[str, float]) -> List[str]:
    """Generates qualitative, actionable insights based on active portfolio state."""
    insights = []

    strategy_id = state.get("strategy_id", "Unknown")
    symbols = state.get("symbols", [])
    positions = state.get("positions", {})
    metrics = state.get("metrics", {})
    equity_curve = state.get("equity_curve", [])

    # 1. State/Environment summary
    insights.append(f"System status checked on {current_date}. Strategy [{strategy_id}] is monitoring {', '.join(symbols)}.")

    # 2. Risk/Drawdown alert
    current_dd = equity_curve[-1].get("drawdown", 0.0) * 100 if equity_curve else 0.0
    if current_dd < -10.0:
        insights.append(f"⚠️ RISK ALERT: Portfolio is experiencing a {abs(current_dd):.1f}% drawdown. Volatility limits may be triggered.")
    elif current_dd < 0:
        insights.append(f"Portfolio drawdown is currently at a moderate {abs(current_dd):.1f}%.")
    else:
        insights.append(f"📈 Portfolio is at an all-time equity high. Risk parameters are fully nominal.")

    # 3. Position summary
    active_positions = {sym: pos for sym, pos in positions.items() if pos.get("qty", 0) > 0}
    if active_positions:
        for sym, pos in active_positions.items():
            qty = pos["qty"]
            avg_cost = pos["avg_cost"]
            curr_price = current_close_prices.get(sym, avg_cost)
            pnl = ((curr_price - avg_cost) / avg_cost) * 100
            pnl_direction = "profit" if pnl >= 0 else "loss"
            insights.append(f"Holdings: Active LONG position in {sym} of {qty} units. Cost basis: ${avg_cost:,.2f} | Current: ${curr_price:,.2f} ({pnl:+.2f}% unrealized {pnl_direction}).")
    else:
        insights.append("Market Status: Currently flat (100% Cash). Waiting for entry breakout or crossover signals.")

    # 4. Strategy specific observations
    if metrics.get("num_trades", 0) > 5:
        pf = metrics.get("profit_factor", 1.0)
        wr = metrics.get("win_rate_pct", 50.0)
        if pf > 1.5 and wr > 55.0:
            insights.append(f"Insight: Strategy performance is robust (Profit Factor: {pf}, Win Rate: {wr}%). Sizing parameters can remain optimized.")
        elif pf < 1.0:
            insights.append(f"Insight: Underperforming parameters detected (Profit Factor: {pf}). Consider adjusting strategy threshold or moving average windows.")

    return insights

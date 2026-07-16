import logging
from datetime import datetime
from typing import Dict, List, Optional
from src.events import SignalEvent, OrderEvent, FillEvent, MarketEvent

logger = logging.getLogger(__name__)


class Portfolio:
    """
    Portfolio tracking system managing positions, cash balances, and equity metrics.

    Industry-Standard Design:
    - Position sizing is always calculated as a fraction of Total NAV (Net Asset Value),
      not free cash. This ensures consistent allocation as the portfolio grows.
    - Pre-trade cash clamping prevents orders from exceeding available capital,
      enforcing a strict cash account model (no margin borrowing).
    - Supports Long and Short positions (negative inventory for shorts).
    """

    def __init__(self, initial_cash: float = 100_000.0):
        """
        Args:
            initial_cash (float): Seed capital to start the simulation.
        
        Raises:
            ValueError: If initial_cash is not positive.
        """
        if initial_cash <= 0:
            raise ValueError(f"initial_cash must be positive, got {initial_cash}")

        self.initial_cash = initial_cash
        self.cash = initial_cash

        # Maps symbol to current share count. Positive = Long, Negative = Short.
        self.positions: Dict[str, int] = {}

        # Maps symbol to average entry price for both long and short entries.
        self.holdings_avg_price: Dict[str, float] = {}

        # Snapshots: (timestamp, cash, holdings_value, total_equity)
        self.equity_curve: List[tuple] = []

        # Latest known Close price per symbol (used for valuation)
        self.latest_prices: Dict[str, float] = {}

        # Maps symbol to cash reserved for pending/queued buy orders.
        self.reserved_cash: Dict[str, float] = {}

        # Full log of executed fills
        self.trade_log: List[dict] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _total_nav(self) -> float:
        """
        Computes current Net Asset Value: cash + mark-to-market value of all positions.
        Short positions contribute negative value (quantity is negative).
        """
        holdings_value = sum(
            qty * self.latest_prices.get(sym, 0.0)
            for sym, qty in self.positions.items()
        )
        return self.cash + holdings_value

    def _available_cash(self) -> float:
        """
        Computes cash available for new purchases by subtracting reserved cash from total cash.
        """
        return self.cash - sum(self.reserved_cash.values())

    def _clamp_buy_quantity(self, raw_qty: int, price: float) -> int:
        """
        Clamps a raw buy quantity so the total cost never exceeds available free cash (less reserved cash).
        Enforces the strict cash-account model — no borrowing.
        """
        if price <= 0:
            return 0
        available = self._available_cash()
        if available <= 0:
            return 0
        max_affordable = int(available // price)
        return min(raw_qty, max_affordable)

    def _clamp_short_quantity(self, raw_qty: int, price: float,
                              extra_collateral: float = 0.0) -> int:
        """
        Clamps a short-sale quantity so its notional is fully collateralized
        by free cash (plus any extra collateral, e.g. proceeds from
        liquidating an existing long in the same order).

        Without this, a short can be opened whose later buy-to-cover exceeds
        available cash — leaving a position that can never be closed under
        the strict cash-account model.
        """
        if price <= 0:
            return 0
        collateral = self._available_cash() + extra_collateral
        if collateral <= 0:
            return 0
        max_shortable = int(collateral // price)
        return min(raw_qty, max_shortable)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update_market_price(self, event: MarketEvent) -> None:
        """
        Stores the latest price and records an equity snapshot.
        """
        self.latest_prices[event.symbol] = event.close_price

        holdings_value = sum(
            qty * self.latest_prices.get(sym, 0.0)
            for sym, qty in self.positions.items()
        )
        total_equity = self.cash + holdings_value
        self.equity_curve.append(
            (event.timestamp, self.cash, holdings_value, total_equity)
        )

    def generate_order(self, signal: SignalEvent) -> Optional[OrderEvent]:
        """
        Converts a SignalEvent into a sized, risk-checked OrderEvent.

        Sizing model (industry standard):
            target_notional = Total_NAV * signal.strength
            target_qty      = int(target_notional / current_price)

        Pre-trade checks:
            - BUY orders are clamped so cost never exceeds free cash.
            - Reject orders where the effective quantity rounds to zero.
        """
        symbol = signal.symbol
        latest_price = self.latest_prices.get(symbol)

        if not latest_price or latest_price <= 0:
            return None

        current_qty = self.positions.get(symbol, 0)

        # ── NAV-based target notional ──────────────────────────────────
        nav = self._total_nav()
        target_notional = nav * signal.strength          # e.g. $100k * 0.20 = $20k
        target_qty = int(target_notional // latest_price)

        # ── LONG signal ────────────────────────────────────────────────
        if signal.signal_type == 'LONG':
            if current_qty < 0:
                # Currently short: we need to cover (buy back short) AND go long.
                # Cover quantity is fixed (close the short). New long is sized off NAV.
                cover_qty = abs(current_qty)
                total_buy_qty = self._clamp_buy_quantity(target_qty + cover_qty, latest_price)
                if total_buy_qty > 0:
                    order = OrderEvent(
                        symbol=symbol,
                        order_type='MKT',
                        quantity=total_buy_qty,
                        direction='BUY',
                        price=latest_price,
                    )
                    self.reserved_cash[symbol] = total_buy_qty * latest_price
                    return order
            elif current_qty == 0:
                # Currently flat: open a new long.
                clamped_qty = self._clamp_buy_quantity(target_qty, latest_price)
                if clamped_qty > 0:
                    order = OrderEvent(
                        symbol=symbol,
                        order_type='MKT',
                        quantity=clamped_qty,
                        direction='BUY',
                        price=latest_price,
                    )
                    self.reserved_cash[symbol] = clamped_qty * latest_price
                    return order
            # If already long, ignore duplicate signal.

        # ── SHORT signal ───────────────────────────────────────────────
        elif signal.signal_type == 'SHORT':
            if current_qty > 0:
                # Currently long: liquidate position AND open a short.
                # Liquidation proceeds count as collateral for the new short.
                liquidate_qty = current_qty
                short_qty = self._clamp_short_quantity(
                    target_qty, latest_price,
                    extra_collateral=liquidate_qty * latest_price,
                )
                total_sell_qty = short_qty + liquidate_qty
                if total_sell_qty > 0:
                    return OrderEvent(
                        symbol=symbol,
                        order_type='MKT',
                        quantity=total_sell_qty,
                        direction='SELL',
                        price=latest_price,
                    )
            elif current_qty == 0:
                # Currently flat: open a new short, fully cash-collateralized.
                short_qty = self._clamp_short_quantity(target_qty, latest_price)
                if short_qty > 0:
                    return OrderEvent(
                        symbol=symbol,
                        order_type='MKT',
                        quantity=short_qty,
                        direction='SELL',
                        price=latest_price,
                    )
            # If already short, ignore duplicate signal.

        # ── EXIT signal ────────────────────────────────────────────────
        elif signal.signal_type == 'EXIT':
            if current_qty > 0:
                return OrderEvent(
                    symbol=symbol,
                    order_type='MKT',
                    quantity=current_qty,
                    direction='SELL',
                    price=latest_price,
                )
            elif current_qty < 0:
                # Buy-to-cover: clamped since it costs cash.
                cover_qty = self._clamp_buy_quantity(abs(current_qty), latest_price)
                if cover_qty > 0:
                    order = OrderEvent(
                        symbol=symbol,
                        order_type='MKT',
                        quantity=cover_qty,
                        direction='BUY',
                        price=latest_price,
                    )
                    self.reserved_cash[symbol] = cover_qty * latest_price
                    return order
        else:
            logger.warning(f"Unknown signal type '{signal.signal_type}' for {symbol}, ignoring.")

        return None

    def update_fill(self, fill: FillEvent) -> None:
        """
        Updates cash, inventory, and average cost basis upon order execution.
        Supports long (positive qty) and short (negative qty) inventory states.
        """
        symbol = fill.symbol
        qty = fill.quantity
        fill_price = fill.fill_price
        commission = fill.commission
        current_qty = self.positions.get(symbol, 0)

        if fill.direction == 'BUY':
            cost = (qty * fill_price) + commission
            self.cash -= cost

            # Release reserved cash for this symbol
            self.reserved_cash.pop(symbol, None)

            new_qty = current_qty + qty
            if new_qty > 0 and current_qty >= 0:
                # Adding to or opening a long — recalculate weighted average cost.
                prev_notional = current_qty * self.holdings_avg_price.get(symbol, 0.0)
                self.holdings_avg_price[symbol] = (
                    (prev_notional + qty * fill_price) / new_qty
                )
            else:
                # Covering a short (partially or fully), or flipping to long.
                self.holdings_avg_price[symbol] = fill_price if new_qty > 0 else 0.0

            self.positions[symbol] = new_qty

        elif fill.direction == 'SELL':
            revenue = (qty * fill_price) - commission
            self.cash += revenue

            new_qty = current_qty - qty
            if new_qty < 0 and current_qty <= 0:
                # Adding to or opening a short — recalculate weighted average entry.
                prev_notional = abs(current_qty) * self.holdings_avg_price.get(symbol, 0.0)
                self.holdings_avg_price[symbol] = (
                    (prev_notional + qty * fill_price) / abs(new_qty)
                )
            else:
                # Partially or fully closing a long, or flipping to short.
                self.holdings_avg_price[symbol] = fill_price if new_qty < 0 else 0.0

            self.positions[symbol] = new_qty

        self.trade_log.append({
            'timestamp':      fill.timestamp,
            'symbol':         symbol,
            'direction':      fill.direction,
            'quantity':       qty,
            'fill_price':     fill_price,
            'commission':     commission,
            'remaining_cash': self.cash,
            'position_after': self.positions[symbol],
            'nav_after':      self._total_nav(),
        })

        pos = self.positions[symbol]
        nav = self._total_nav()
        print(
            f"  [{fill.timestamp.strftime('%Y-%m-%d')}] "
            f"{fill.direction} {qty:>5} {symbol:<8} "
            f"@ ${fill_price:>10,.2f}  "
            f"Fee: ${commission:>7.2f}  "
            f"Cash: ${self.cash:>12,.2f}  "
            f"Pos: {pos:>+5}  "
            f"NAV: ${nav:>12,.2f}"
        )

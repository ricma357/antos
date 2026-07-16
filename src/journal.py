import os
import sqlite3
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class TradeJournal:
    """
    SQLite-backed transactional trade journal.
    Ensures persistent audit trails of all executed trades, P&L, 
    and quantitative performance attribution metrics.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(
            os.path.dirname(__file__), "..", "data", "trade_journal.db"
        )
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        # Set a 30.0s busy timeout to handle concurrent access from scheduler daemon & web worker threads
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Creates trade logs table if not exists."""
        query = """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            commission REAL NOT NULL,
            realized_pnl REAL NOT NULL,
            remaining_cash REAL NOT NULL,
            position_after INTEGER NOT NULL
        );
        """
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(query)
        except sqlite3.Error as e:
            logger.error(f"Failed to initialize trade journal database: {e}")
        finally:
            conn.close()

    def add_trade(
        self,
        timestamp: str,
        strategy_id: str,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
        commission: float,
        realized_pnl: float,
        remaining_cash: float,
        position_after: int
    ) -> None:
        """Inserts a trade record into the journal."""
        query = """
        INSERT INTO trades (
            timestamp, strategy_id, symbol, direction, quantity, 
            price, commission, realized_pnl, remaining_cash, position_after
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        conn = self._get_connection()
        try:
            with conn:
                conn.execute(
                    query,
                    (
                        timestamp, strategy_id, symbol, direction.upper(), quantity,
                        price, commission, realized_pnl, remaining_cash, position_after
                    )
                )
            logger.info(f"Logged trade to SQLite journal: {direction} {quantity} {symbol} @ {price}")
        except sqlite3.Error as e:
            logger.error(f"Failed to record trade to SQLite journal: {e}")
        finally:
            conn.close()

    def get_trades(self, limit: int = 100, strategy_id: str = None) -> List[Dict[str, Any]]:
        """Retrieves recent trades with optional strategy filter."""
        query = "SELECT * FROM trades"
        params = []
        if strategy_id:
            query += " WHERE strategy_id = ?"
            params.append(strategy_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Failed to retrieve trades from journal: {e}")
            return []
        finally:
            conn.close()

    def get_performance_summary(self, strategy_id: str = None) -> Dict[str, Any]:
        """Calculates performance attribution metrics directly via SQL aggregates."""
        where_clause = ""
        params = []
        if strategy_id:
            where_clause = "WHERE strategy_id = ?"
            params = [strategy_id]

        queries = {
            "total_trades": f"SELECT COUNT(*) FROM trades {where_clause};",
            "total_pnl": f"SELECT SUM(realized_pnl) FROM trades {where_clause};",
            "winning_trades": f"SELECT COUNT(*) FROM trades {where_clause} {'AND' if strategy_id else 'WHERE'} realized_pnl > 0;",
            "losing_trades": f"SELECT COUNT(*) FROM trades {where_clause} {'AND' if strategy_id else 'WHERE'} realized_pnl < 0;",
            "gross_profits": f"SELECT SUM(realized_pnl) FROM trades {where_clause} {'AND' if strategy_id else 'WHERE'} realized_pnl > 0;",
            "gross_losses": f"SELECT SUM(realized_pnl) FROM trades {where_clause} {'AND' if strategy_id else 'WHERE'} realized_pnl < 0;"
        }

        metrics = {
            "total_trades": 0,
            "total_pnl": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 1.0
        }

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Total Trades
            cursor.execute(queries["total_trades"], params)
            metrics["total_trades"] = cursor.fetchone()[0] or 0
            
            if metrics["total_trades"] == 0:
                return metrics
            
            # Total P&L
            cursor.execute(queries["total_pnl"], params)
            metrics["total_pnl"] = round(cursor.fetchone()[0] or 0.0, 2)
            
            # Win Rate
            cursor.execute(queries["winning_trades"], params)
            wins = cursor.fetchone()[0] or 0
            cursor.execute(queries["losing_trades"], params)
            losses = cursor.fetchone()[0] or 0
            total_outcomes = wins + losses
            metrics["win_rate_pct"] = round((wins / total_outcomes * 100), 2) if total_outcomes > 0 else 0.0
            
            # Profit Factor
            cursor.execute(queries["gross_profits"], params)
            gross_profit = cursor.fetchone()[0] or 0.0
            cursor.execute(queries["gross_losses"], params)
            gross_loss = abs(cursor.fetchone()[0] or 0.0)
            metrics["profit_factor"] = round((gross_profit / gross_loss), 2) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
            
        except sqlite3.Error as e:
            logger.error(f"Failed to calculate performance metrics: {e}")
        finally:
            conn.close()

        return metrics

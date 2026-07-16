from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class StrategyParam(BaseModel):
    name: str
    type: str  # 'int', 'float', 'bool'
    default: Any
    description: str

class StrategyInfo(BaseModel):
    id: str
    name: str
    description: str
    parameters: List[StrategyParam]

class BacktestRequest(BaseModel):
    strategy_id: str
    symbols: List[str]
    initial_cash: float = Field(default=100000.0, gt=0)
    commission_rate: float = Field(default=0.001, ge=0)
    slippage_rate: float = Field(default=0.0005, ge=0)
    risk_free_rate: float = Field(default=0.0, ge=0)
    params: Dict[str, Any] = Field(default_factory=dict)

class TradeLogEntry(BaseModel):
    timestamp: str
    symbol: str
    direction: str
    quantity: int
    fill_price: float
    commission: float
    remaining_cash: float
    position_after: int
    nav_after: float

class EquityPoint(BaseModel):
    time: str  # YYYY-MM-DD
    value: float

class BacktestResponse(BaseModel):
    strategy_name: str
    metrics: Dict[str, Any]
    equity_curve: List[EquityPoint]
    drawdown_curve: List[EquityPoint]
    trade_log: List[TradeLogEntry]
    date_start: str = ""
    date_end: str = ""

"""
HTTP adapter for the live trading bot.

All behavior lives in src/live_bot.py (LiveBotService) — this module only
translates HTTP requests into service calls and domain exceptions into
HTTP status codes.
"""

import os
import logging
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from api.routes.backtest import get_strategy_instance
from src.live_bot import (
    LiveBotService,
    BotError,
    TickInProgress,
    LiveDataUnavailable,
    StateResetFailed,
)

logger = logging.getLogger(__name__)

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
STATE_FILE = os.path.join(DATA_DIR, "live_bot_state.json")

service = LiveBotService(
    data_dir=DATA_DIR,
    state_file=STATE_FILE,
    strategy_factory=get_strategy_instance,
)


class StartBotRequest(BaseModel):
    strategy_id: str
    symbols: List[str]
    initial_cash: float = Field(default=100000.0, gt=0)
    commission_rate: float = Field(default=0.001, ge=0)
    slippage_rate: float = Field(default=0.0005, ge=0)
    params: Dict[str, Any] = Field(default_factory=dict)
    live_mode: bool = Field(default=False)
    broker_type: str = Field(default="simulated")
    drawdown_halt: float = Field(
        default=0.15, ge=0, lt=1,
        description="Halt new entries beyond this portfolio drawdown (0 disables)")


def _http_status(err: BotError) -> int:
    if isinstance(err, TickInProgress):
        return 409
    if isinstance(err, (LiveDataUnavailable, StateResetFailed)):
        return 500
    return 400


@router.get("/status")
def get_bot_status():
    return service.status()


@router.get("/journal")
def get_bot_journal(limit: int = 100):
    return service.journal_summary(limit=limit)


@router.post("/start")
def start_bot(req: StartBotRequest):
    try:
        return service.start(
            strategy_id=req.strategy_id,
            symbols=req.symbols,
            initial_cash=req.initial_cash,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            params=req.params,
            live_mode=req.live_mode,
            broker_type=req.broker_type,
            drawdown_halt=req.drawdown_halt,
        )
    except BotError as e:
        raise HTTPException(status_code=_http_status(e), detail=str(e))


@router.post("/stop")
def stop_bot():
    return service.stop()


@router.post("/reset")
def reset_bot():
    try:
        return service.reset()
    except BotError as e:
        raise HTTPException(status_code=_http_status(e), detail=str(e))


@router.post("/scheduler/start")
def start_scheduler():
    try:
        return service.start_scheduler()
    except BotError as e:
        raise HTTPException(status_code=_http_status(e), detail=str(e))


@router.post("/scheduler/stop")
def stop_scheduler():
    return service.stop_scheduler()


@router.post("/tick")
def trigger_bot_tick():
    try:
        return service.tick()
    except BotError as e:
        raise HTTPException(status_code=_http_status(e), detail=str(e))


# Auto-initialize scheduler from persisted state on startup
try:
    service.init_from_persisted_state()
except Exception as startup_err:
    logger.error(f"Failed to auto-initialize scheduler on import: {startup_err}")

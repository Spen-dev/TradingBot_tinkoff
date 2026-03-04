"""Тесты RiskManager: get_block_reason, is_trading_allowed."""
import pytest

from tinkoff_bot.config import RiskConfig
from tinkoff_bot.risk import RiskManager, RiskState


@pytest.fixture
def risk_cfg():
    return RiskConfig(
        max_drawdown=0.15,
        daily_loss_limit=0.03,
        default_stop_loss_pct=0.05,
        trailing_stop_pct=0.02,
        var_confidence=0.95,
        kelly_fraction_cap=0.5,
        pause_after_consecutive_losses=3,
        pause_hours=24,
        min_pnl_to_count_loss_rub=50.0,
        take_profit_pct=0.03,
        trailing_take_profit_pct=0.02,
    )


def test_get_block_reason_none_when_ok(risk_cfg):
    rm = RiskManager(risk_cfg)
    rm._pause_until = None  # не зависеть от risk_state.json
    state = RiskState(equity=100.0, max_equity_seen=100.0, daily_pnl=0.0)
    assert rm.get_block_reason(state) is None


def test_get_block_reason_drawdown(risk_cfg):
    rm = RiskManager(risk_cfg)
    rm._pause_until = None
    rm._max_equity_seen = 100.0
    rm._daily_equity_start = 100.0
    state = RiskState(equity=80.0, max_equity_seen=100.0, daily_pnl=-20.0)
    reason = rm.get_block_reason(state)
    assert reason is not None
    assert "просадка" in reason


def test_get_block_reason_daily_loss(risk_cfg):
    rm = RiskManager(risk_cfg)
    rm._pause_until = None
    rm._max_equity_seen = 100.0
    rm._daily_equity_start = 100.0
    state = RiskState(equity=96.0, max_equity_seen=100.0, daily_pnl=-4.0)
    reason = rm.get_block_reason(state)
    assert reason is not None
    assert "дневной убыток" in reason


def test_is_trading_allowed_after_drawdown(risk_cfg):
    rm = RiskManager(risk_cfg)
    rm._pause_until = None
    rm._max_equity_seen = 100.0
    rm._daily_equity_start = 100.0
    state = RiskState(equity=80.0, max_equity_seen=100.0, daily_pnl=-20.0)
    assert rm.is_trading_allowed(state) is False


def test_stop_loss_price(risk_cfg):
    rm = RiskManager(risk_cfg)
    assert rm.stop_loss_price(100.0) == 95.0


def test_trailing_stop_price(risk_cfg):
    rm = RiskManager(risk_cfg)
    assert rm.trailing_stop_price(100.0) == 98.0

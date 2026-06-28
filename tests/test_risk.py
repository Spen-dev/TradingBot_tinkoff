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


def test_get_block_reason_none_when_ok(risk_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("tinkoff_bot.risk.RISK_STATE_FILE", tmp_path / "risk_state.json")
    rm = RiskManager(risk_cfg)
    rm._pause_until = None
    rm._max_equity_seen = 100.0
    rm._daily_equity_start = 100.0
    state = RiskState(equity=100.0, max_equity_seen=100.0, daily_pnl=0.0)
    assert rm.get_block_reason(state) is None


def test_get_block_reason_drawdown(risk_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("tinkoff_bot.risk.RISK_STATE_FILE", tmp_path / "risk_state.json")
    rm = RiskManager(risk_cfg)
    rm._pause_until = None
    rm._max_equity_seen = 100.0
    rm._daily_equity_start = 100.0
    state = RiskState(equity=80.0, max_equity_seen=100.0, daily_pnl=-20.0)
    reason = rm.get_block_reason(state)
    assert reason is not None
    assert "просадка" in reason


def test_get_block_reason_daily_loss(risk_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("tinkoff_bot.risk.RISK_STATE_FILE", tmp_path / "risk_state.json")
    rm = RiskManager(risk_cfg)
    rm._pause_until = None
    rm._max_equity_seen = 100.0
    rm._daily_equity_start = 100.0
    state = RiskState(equity=96.0, max_equity_seen=100.0, daily_pnl=-4.0)
    reason = rm.get_block_reason(state)
    assert reason is not None
    assert "дневной убыток" in reason


def test_is_trading_allowed_after_drawdown(risk_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("tinkoff_bot.risk.RISK_STATE_FILE", tmp_path / "risk_state.json")
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


def test_risk_state_persisted(tmp_path, monkeypatch, risk_cfg):
    state_file = tmp_path / "risk_state.json"
    monkeypatch.setattr("tinkoff_bot.risk.RISK_STATE_FILE", state_file)
    rm = RiskManager(risk_cfg)
    rm.update_equity(120_000.0, 120_000.0)
    rm2 = RiskManager(risk_cfg)
    assert rm2._max_equity_seen == 120_000.0
    assert rm2._daily_equity_start == 120_000.0


def test_daily_baseline_reset_on_stale_date(tmp_path, monkeypatch, risk_cfg):
    import json
    state_file = tmp_path / "risk_state.json"
    state_file.write_text(json.dumps({
        "pause_until": None,
        "max_equity_seen": 150_000.0,
        "daily_equity_start": 150_000.0,
        "daily_equity_date": "2020-01-01",
    }), encoding="utf-8")
    monkeypatch.setattr("tinkoff_bot.risk.RISK_STATE_FILE", state_file)
    rm = RiskManager(risk_cfg)
    # Дневной базис устарел (другая дата) — сбрасывается, max_equity_seen сохраняется.
    assert rm._daily_equity_start is None
    assert rm._max_equity_seen == 150_000.0
    # Первый update задаёт свежий дневной базис от текущего equity.
    st = rm.update_equity(100_000.0, 100_000.0)
    assert rm._daily_equity_start == 100_000.0
    assert st.daily_pnl == 0.0

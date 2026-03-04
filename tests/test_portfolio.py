"""Тесты PortfolioManager.build_rebalance_orders с моком брокера."""
from unittest.mock import MagicMock

import pytest

from tinkoff_bot.config import PortfolioConfig, RiskConfig, InstrumentConfig
from tinkoff_bot.portfolio import PortfolioManager
from tinkoff_bot.risk import RiskManager, RiskState


@pytest.fixture
def portfolio_cfg():
    return PortfolioConfig(
        base_currency="RUB",
        rebalance_frequency="daily",
        rebalance_time="10:00",
        commission_rate=0.0003,
        dry_run=False,
        limit_price_pct=0.001,
        rebalance_by_price=True,
        rebalance_on_drift=True,
        rebalance_drift_pct=0.05,
        rebalance_check_interval_minutes=30,
        rebalance_cooldown_minutes=60,
        rebalance_interval_hours=0.0,
    )


@pytest.fixture
def risk_cfg():
    return RiskConfig(
        max_drawdown=0.15,
        daily_loss_limit=0.03,
        default_stop_loss_pct=0.05,
        trailing_stop_pct=0.02,
        var_confidence=0.95,
        kelly_fraction_cap=0.5,
    )


@pytest.fixture
def instruments():
    return [
        InstrumentConfig(figi="F1", ticker="A", strategy="rl", target_weight=0.5, strategy_params={"rl_model_path": "x.zip"}, lot=1),
        InstrumentConfig(figi="F2", ticker="B", strategy="rl", target_weight=0.5, strategy_params={"rl_model_path": "y.zip"}, lot=1),
    ]


def test_build_rebalance_orders_returns_list(portfolio_cfg, risk_cfg, instruments):
    broker = MagicMock()
    broker.get_portfolio.return_value = {}
    broker.get_cash_balance.return_value = 100_000.0
    broker.get_last_price.return_value = 100.0
    broker.get_historical_candles.return_value = None

    risk = RiskManager(risk_cfg)
    pm = PortfolioManager(portfolio_cfg, instruments, broker, risk)
    orders = pm.build_rebalance_orders(100_000.0)
    assert isinstance(orders, list)

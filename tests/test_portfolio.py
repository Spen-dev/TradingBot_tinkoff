"""Тесты PortfolioManager.build_rebalance_orders с моком брокера."""
from unittest.mock import MagicMock

import pytest
from t_tech.invest import OrderDirection

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
        InstrumentConfig(figi="F1", ticker="A", strategy="adaptive", target_weight=0.5, strategy_params={}, lot=1),
        InstrumentConfig(figi="F2", ticker="B", strategy="momentum", target_weight=0.5, strategy_params={}, lot=1),
    ]


def test_build_rebalance_orders_returns_list(portfolio_cfg, risk_cfg, instruments):
    broker = MagicMock()
    broker.get_equity_snapshot.return_value = (100_000.0, 100_000.0, {})
    broker.get_last_price.return_value = 100.0
    broker.get_historical_candles.return_value = None

    risk = RiskManager(risk_cfg)
    pm = PortfolioManager(portfolio_cfg, instruments, broker, risk)
    orders = pm.build_rebalance_orders(100_000.0)
    assert isinstance(orders, list)


def test_target_values_normalizes_learned_weights(portfolio_cfg, risk_cfg, instruments, monkeypatch):
    broker = MagicMock()
    risk = RiskManager(risk_cfg)
    pm = PortfolioManager(portfolio_cfg, instruments, broker, risk)
    monkeypatch.setattr(
        "tinkoff_bot.portfolio.load_learned_params",
        lambda: {"F1": {"target_weight": 0.9}, "F2": {"target_weight": 0.1}},
    )
    targets = pm._target_values(100_000.0)
    assert abs(sum(targets.values()) - 100_000.0) < 1.0
    assert abs(targets["F1"] - 90_000.0) < 1.0


def test_target_values_ignores_prices_with_rebalance_by_price(portfolio_cfg, risk_cfg, instruments):
    broker = MagicMock()
    risk = RiskManager(risk_cfg)
    pm = PortfolioManager(portfolio_cfg, instruments, broker, risk)
    prices = {"F1": 100.0, "F2": 500.0}
    targets = pm._target_values(100_000.0, prices)
    assert abs(targets["F1"] - 50_000.0) < 1.0
    assert abs(targets["F2"] - 50_000.0) < 1.0


def test_sell_capped_at_held_quantity(portfolio_cfg, risk_cfg, monkeypatch):
  """SELL не больше фактической лонг-позиции (защита от шорта в sandbox)."""
  monkeypatch.setattr("tinkoff_bot.portfolio.load_learned_params", lambda: {})
  monkeypatch.setattr("tinkoff_bot.portfolio._load_position_peaks", lambda: {})
  monkeypatch.setattr("tinkoff_bot.portfolio._load_last_trades", lambda: {})
  monkeypatch.setattr(
    "tinkoff_bot.advisor_ensemble.resolve_rebalance_advisor_flags",
    lambda **kw: (False, False, False, False),
  )
  cfg = PortfolioConfig(
    **{
      **portfolio_cfg.__dict__,
      "aggressive_rebalance": True,
      "signal_confirmation_candles": 0,
      "use_moex_advisor": False,
      "use_finam_advisor": False,
      "use_openrouter_advisor": False,
      "gap_risk_enabled": False,
    }
  )
  instruments = [
    InstrumentConfig(
      figi="F1", ticker="A", strategy=None, target_weight=0.1,
      strategy_params={}, lot=1,
    ),
    InstrumentConfig(
      figi="F2", ticker="B", strategy=None, target_weight=0.9,
      strategy_params={}, lot=1,
    ),
  ]
  broker = MagicMock()
  pos = MagicMock()
  pos.value = 80_000.0
  pos.quantity = 50
  pos.current_price = 100.0
  pos.average_price = 100.0
  broker.get_equity_snapshot.return_value = (100_000.0, 20_000.0, {"F1": pos})
  broker.get_last_price.return_value = 100.0
  broker.get_historical_candles.return_value = None

  risk = RiskManager(risk_cfg)
  pm = PortfolioManager(cfg, instruments, broker, risk)
  orders = pm.build_rebalance_orders(100_000.0)
  sells = [o for o in orders if o.direction == OrderDirection.ORDER_DIRECTION_SELL]
  assert len(sells) == 1
  assert sells[0].quantity == 50


def test_rebalance_needed_uses_config_weights_not_prices(portfolio_cfg, risk_cfg, instruments):
    broker = MagicMock()
    pos_f1 = MagicMock()
    pos_f1.value = 50_000.0
    pos_f2 = MagicMock()
    pos_f2.value = 50_000.0
    broker.get_equity_snapshot.return_value = (100_000.0, 0.0, {"F1": pos_f1, "F2": pos_f2})
    broker.get_last_price.side_effect = lambda figi: 100.0 if figi == "F1" else 500.0

    risk = RiskManager(risk_cfg)
    pm = PortfolioManager(portfolio_cfg, instruments, broker, risk)
    assert pm.rebalance_needed(100_000.0, 0.05) is False

"""Тесты load_config и validate_config."""
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from tinkoff_bot.config import load_config, validate_config, InstrumentConfig, PortfolioConfig, RiskConfig


@patch("tinkoff_bot.learned_params.load_learned_params", return_value={})
def test_validate_config_empty_instruments(mock_load):
    class T:
        token = "tok"
        account_id = "00000000-0000-0000-0000-000000000001"
        use_sandbox = True

    class Tel:
        token = "tg"
        admin_chat_id = 1

    class Cfg:
        instruments = []
        mode = "sandbox"
        tinkoff = T()
        telegram = Tel()

    cfg = Cfg()
    ok, errs = validate_config(cfg)
    assert ok is False
    assert any("инструмент" in e.lower() or "нет" in e.lower() for e in errs)


@patch("tinkoff_bot.learned_params.load_learned_params", return_value={})
def test_validate_config_weights_not_one(mock_load):
    class Inst:
        figi = "BBG000"
        ticker = "X"
        strategy = "momentum"
        target_weight = 0.5
        strategy_params = {}
        lot = 1

    class T:
        token = "tok"
        account_id = "00000000-0000-0000-0000-000000000001"
        use_sandbox = True

    class Tel:
        token = "tg"
        admin_chat_id = 1

    class Cfg:
        instruments = [Inst()]
        mode = "sandbox"
        tinkoff = T()
        telegram = Tel()

    cfg = Cfg()
    ok, errs = validate_config(cfg)
    assert ok is False
    assert any("1.0" in e or "target_weight" in e or "сумма" in e for e in errs)


def test_load_config_minimal():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump({
            "tinkoff": {"token": "", "account_id": "", "use_sandbox": True},
            "telegram": {"token": "", "admin_chat_id": 0},
            "mode": "sandbox",
            "portfolio": {
                "base_currency": "RUB",
                "rebalance_frequency": "daily",
                "rebalance_time": "10:00",
                "commission_rate": 0.0003,
                "dry_run": False,
            },
            "risk": {
                "max_drawdown": 0.15,
                "daily_loss_limit": 0.03,
                "default_stop_loss_pct": 0.05,
                "trailing_stop_pct": 0.02,
                "var_confidence": 0.95,
                "kelly_fraction_cap": 0.5,
            },
            "web": {"host": "0.0.0.0", "port": 8000, "dashboard_url": ""},
            "instruments": [
                {"figi": "F1", "ticker": "A", "strategy": "rl", "target_weight": 0.5, "strategy_params": {}, "lot": 1},
                {"figi": "F2", "ticker": "B", "strategy": "rl", "target_weight": 0.5, "strategy_params": {}, "lot": 1},
            ],
        }, f, allow_unicode=True)
        path = f.name
    try:
        cfg = load_config(path)
        assert cfg.portfolio.base_currency == "RUB"
        assert cfg.portfolio.auto_rebalance_when_stopped is True
        assert len(cfg.instruments) == 2
        assert cfg.risk.max_drawdown == 0.15
    finally:
        Path(path).unlink(missing_ok=True)

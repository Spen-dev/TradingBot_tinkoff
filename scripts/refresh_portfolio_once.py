"""Однократное принудительное обновление динамического портфеля (для деплоя/CLI)."""
from dotenv import load_dotenv

load_dotenv()

from tinkoff_bot.config import load_config
from tinkoff_bot.broker import TinkoffBroker
from tinkoff_bot.dynamic_portfolio import refresh_dynamic_portfolio


def main() -> None:
  cfg = load_config("config.yaml")
  broker = TinkoffBroker(cfg.tinkoff)
  dp = cfg.dynamic_portfolio
  if not dp or not dp.enabled:
    print("dynamic_portfolio disabled")
    return
  inst, msg, changed, comparison = refresh_dynamic_portfolio(
    dp,
    broker,
    cfg.instruments,
    force=True,
    history_days=cfg.portfolio.llm_history_days,
    openrouter_model=cfg.portfolio.openrouter_model,
    finam_cfg=cfg.finam,
    openrouter_cfg=cfg.openrouter,
    macro_news_cfg=getattr(cfg, "macro_news", None),
    ai_mode=bool(getattr(cfg.portfolio, "ai_mode", False)),
    ai_priority=bool(getattr(cfg.portfolio, "advisor_ai_priority", True)),
  )
  print(msg)
  if comparison:
    print(comparison)
  print("changed:", changed)
  for i in inst:
    print(f"  {i.ticker} {i.target_weight:.1%}")


if __name__ == "__main__":
  main()

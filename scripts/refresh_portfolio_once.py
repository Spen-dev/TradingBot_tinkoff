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
  inst, msg, changed = refresh_dynamic_portfolio(
    dp,
    broker,
    cfg.instruments,
    force=True,
    history_days=cfg.portfolio.deepseek_history_days,
    deepseek_model=cfg.portfolio.deepseek_model,
    gemini_model=cfg.portfolio.gemini_model,
    groq_model=cfg.portfolio.groq_model,
    openrouter_model=cfg.portfolio.openrouter_model,
    finam_cfg=cfg.finam,
    gemini_cfg=cfg.gemini,
    groq_cfg=cfg.groq,
    openrouter_cfg=cfg.openrouter,
  )
  print(msg)
  print("changed:", changed)
  for i in inst:
    print(f"  {i.ticker} {i.target_weight:.1%}")


if __name__ == "__main__":
  main()

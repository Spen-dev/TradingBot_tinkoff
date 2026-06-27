"""Проверка доступности всех внешних API бота."""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def check_moex() -> dict:
  try:
    from tinkoff_bot.moex_client import MoexClient

    bars = MoexClient().get_daily_bars("SBER", 10)
    ok = len(bars) >= 3
    return {"ok": ok, "bars": len(bars), "last_close": bars[-1]["close"] if bars else None}
  except Exception as e:
    return {"ok": False, "error": str(e)[:200]}


def check_finam() -> dict:
  try:
    from tinkoff_bot.finam_client import FinamClient

    fc = FinamClient()
    if not fc.configured:
      return {"ok": False, "configured": False, "error": "FINAM_API_TOKEN not set"}
    bars = fc.get_daily_bars("SBER", 10)
    ok = len(bars) >= 3
    return {"ok": ok, "configured": True, "bars": len(bars), "last_close": bars[-1]["close"] if bars else None}
  except Exception as e:
    return {"ok": False, "configured": bool(os.environ.get("FINAM_API_TOKEN")), "error": str(e)[:200]}


def check_openrouter() -> dict:
  try:
    from tinkoff_bot.openrouter_client import api_key, chat
    from tinkoff_bot.ops_automation import fetch_openrouter_remaining_usd

    if not api_key():
      return {"ok": False, "configured": False, "error": "OPENROUTER_API_KEY not set"}
    remaining_usd = fetch_openrouter_remaining_usd()
    text, model = chat(
      "Reply with OK only.",
      "ping",
      model="google/gemini-2.5-flash-lite",
      max_tokens=16,
    )
    return {
      "ok": bool(text),
      "configured": True,
      "model": model,
      "remaining_usd": remaining_usd,
      "preview": (text or "")[:60],
    }
  except Exception as e:
    return {"ok": False, "configured": bool(os.environ.get("OPENROUTER_API_KEY")), "error": str(e)[:200]}


def check_macro_news() -> dict:
  try:
    from tinkoff_bot.config import load_config
    from tinkoff_bot.news_client import collect_macro_headlines

    cfg = load_config("config.yaml")
    mn = getattr(cfg, "macro_news", None)
    urls = list(getattr(mn, "rss_urls", None) or [])
    headlines = collect_macro_headlines(
      urls,
      max_per_feed=int(getattr(mn, "max_headlines_per_feed", 10) or 10),
      max_total=int(getattr(mn, "max_headlines_total", 25) or 25),
      cache_hours=0,
      cache_file=str(getattr(mn, "cache_file", "data/macro_news_cache.json")),
      timeout=float(getattr(mn, "request_timeout_seconds", 20) or 20),
      force_refresh=True,
    )
    return {"ok": len(headlines) > 0, "headlines": len(headlines)}
  except Exception as e:
    return {"ok": False, "error": str(e)[:200]}


def check_tinkoff() -> dict:
  try:
    from tinkoff_bot.broker import TinkoffBroker
    from tinkoff_bot.config import load_config

    cfg = load_config("config.yaml")
    if not (cfg.tinkoff.token or "").strip():
      return {"ok": False, "configured": False, "error": "TINKOFF_TOKEN not set"}
    br = TinkoffBroker(cfg.tinkoff)
    eq, cash, pos = br.get_equity_snapshot()
    price = br.get_last_price(cfg.instruments[0].figi) if cfg.instruments else None
    return {
      "ok": True,
      "configured": True,
      "sandbox": cfg.tinkoff.use_sandbox,
      "equity": round(eq, 2),
      "cash": round(cash, 2),
      "positions": len(pos),
      "sample_price": price,
    }
  except Exception as e:
    return {"ok": False, "configured": bool(os.environ.get("TINKOFF_TOKEN")), "error": str(e)[:200]}


def check_telegram() -> dict:
  token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
  chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or ""
  if not token:
    return {"ok": False, "configured": False, "error": "TELEGRAM_TOKEN not set"}
  try:
    import urllib.request

    url = f"https://api.telegram.org/bot{token}/getMe"
    with urllib.request.urlopen(url, timeout=15) as resp:
      data = json.loads(resp.read().decode("utf-8"))
    ok = bool(data.get("ok"))
    username = (data.get("result") or {}).get("username")
    return {"ok": ok, "configured": True, "bot": username, "admin_chat_id": chat_id or None}
  except Exception as e:
    return {"ok": False, "configured": True, "error": str(e)[:200]}


def main() -> int:
  results = {
    "moex": check_moex(),
    "finam": check_finam(),
    "openrouter": check_openrouter(),
    "macro_news": check_macro_news(),
    "tinkoff": check_tinkoff(),
    "telegram": check_telegram(),
  }
  print(json.dumps(results, ensure_ascii=False, indent=2))
  all_ok = all(r.get("ok") for r in results.values())
  return 0 if all_ok else 1


if __name__ == "__main__":
  raise SystemExit(main())

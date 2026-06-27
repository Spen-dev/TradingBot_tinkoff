"""Автоматизация эксплуатации: баланс LLM, бэкапы, sandbox, macro-триггеры."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def fetch_openrouter_remaining_usd(api_key_override: Optional[str] = None) -> Optional[float]:
  """Остаток кредитов OpenRouter (USD). None если ключ не задан или API недоступен."""
  from .openrouter_client import api_key

  key = api_key(api_key_override)
  if not key:
    return None
  url = "https://openrouter.ai/api/v1/credits"
  try:
    req = urllib.request.Request(
      url,
      headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
      data = json.loads(resp.read().decode("utf-8"))
    inner = data.get("data") if isinstance(data, dict) else None
    if not isinstance(inner, dict):
      return None
    total = float(inner.get("total_credits") or inner.get("limit") or 0)
    used = float(inner.get("total_usage") or inner.get("usage") or 0)
    if total <= 0 and used <= 0:
      return None
    return max(0.0, total - used)
  except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, TypeError, ValueError) as e:
    logger.debug("OpenRouter credits: %s", e)
    return None


def headlines_fingerprint(headlines: List[Dict[str, str]]) -> str:
  blob = "|".join(sorted((h.get("title") or "").strip().lower()[:120] for h in headlines if h.get("title")))
  return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load_news_fingerprint(path: Path) -> str:
  if not path.exists():
    return ""
  try:
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data.get("fingerprint") or "")
  except Exception:
    return ""


def save_news_fingerprint(path: Path, fp: str, headline_count: int) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    json.dumps(
      {"fingerprint": fp, "headline_count": headline_count, "updated_at": datetime.now().isoformat()},
      ensure_ascii=False,
      indent=2,
    ),
    encoding="utf-8",
  )


def should_refresh_portfolio_for_news(
  macro_cfg: Any,
  *,
  base_dir: Path,
  refresh_on_news_change: bool = True,
  force_refresh: bool = False,
) -> tuple[bool, str]:
  """True, если RSS изменился с прошлого macro-refresh."""
  if force_refresh:
    return True, "force"
  if not refresh_on_news_change:
    return False, "disabled"
  from .news_client import collect_macro_headlines

  headlines = collect_macro_headlines(
    list(getattr(macro_cfg, "rss_urls", None) or []),
    max_per_feed=int(getattr(macro_cfg, "max_headlines_per_feed", 10) or 10),
    max_total=int(getattr(macro_cfg, "max_headlines_total", 25) or 25),
    cache_hours=0,
    cache_file=str(getattr(macro_cfg, "cache_file", "data/macro_news_cache.json")),
    timeout=float(getattr(macro_cfg, "request_timeout_seconds", 20) or 20),
    base_dir=base_dir,
    force_refresh=True,
  )
  fp = headlines_fingerprint(headlines)
  state_path = base_dir / "data" / "macro_news_fingerprint.json"
  prev = load_news_fingerprint(state_path)
  if not fp:
    return False, "no_headlines"
  if not prev:
    save_news_fingerprint(state_path, fp, len(headlines))
    return False, "initial_fingerprint"
  if fp != prev:
    save_news_fingerprint(state_path, fp, len(headlines))
    return True, f"news_changed ({len(headlines)} headlines)"
  return False, "news_unchanged"


def backup_learned_params(base_dir: Path) -> Optional[str]:
  """Копия learned_params/params.json в data/backups/."""
  src = base_dir / "learned_params" / "params.json"
  if not src.exists():
    return None
  dest_dir = base_dir / "data" / "backups"
  dest_dir.mkdir(parents=True, exist_ok=True)
  stamp = datetime.now().strftime("%Y%m%d")
  dest = dest_dir / f"learned_params_{stamp}.json"
  shutil.copy2(src, dest)
  return str(dest)


def ensure_sandbox_funded(broker: Any, currency: str = "RUB") -> Optional[str]:
  """Пополнить песочницу до SANDBOX_TARGET_CASH, если баланс сильно ниже."""
  target = float(os.getenv("SANDBOX_TARGET_CASH", "100000") or 0)
  if target <= 0:
    return None
  try:
    equity, cash, npos = broker.get_equity_snapshot(currency)
  except Exception as e:
    logger.warning("ensure_sandbox_funded: %s", e)
    return None
  if equity > target * 0.05 and cash > target * 0.05:
    return None
  need = max(0.0, target - cash)
  if need < 1000:
    need = target
  try:
    broker.set_sandbox_balance(need, currency=currency)
    return f"пополнено +{need:.0f} {currency} (было equity={equity:.0f})"
  except Exception as e:
    logger.warning("set_sandbox_balance: %s", e)
    return None

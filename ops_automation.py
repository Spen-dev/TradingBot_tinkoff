"""Автоматизация эксплуатации: баланс LLM, бэкапы, sandbox, macro-триггеры."""

from __future__ import annotations

import hashlib
import json
import logging
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
  trigger_keywords: Optional[List[str]] = None,
  refresh_cooldown_days: int = 3,
) -> tuple[bool, str]:
  """True, если RSS изменился и есть значимые ключевые слова (с cooldown)."""
  if force_refresh:
    return True, "force"
  if not refresh_on_news_change:
    return False, "disabled"
  from .news_client import collect_macro_headlines

  headlines = collect_macro_headlines(
    list(getattr(macro_cfg, "rss_urls", None) or []),
    max_per_feed=int(getattr(macro_cfg, "max_headlines_per_feed", 15) or 15),
    max_total=int(getattr(macro_cfg, "max_headlines_total", 40) or 40),
    max_age_days=int(getattr(macro_cfg, "max_age_days", 14) or 14),
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
  if fp == prev:
    return False, "news_unchanged"

  keywords = [k.lower() for k in (trigger_keywords or []) if k]
  if keywords:
    blob = " ".join(
      f"{h.get('title', '')} {h.get('description', '')}".lower() for h in headlines
    )
    if not any(k in blob for k in keywords):
      save_news_fingerprint(state_path, fp, len(headlines))
      return False, "news_changed_no_keywords"

  if refresh_cooldown_days > 0 and state_path.exists():
    try:
      data = json.loads(state_path.read_text(encoding="utf-8"))
      last_refresh = str(data.get("last_refresh_at") or "")
      if last_refresh:
        last_dt = datetime.fromisoformat(last_refresh)
        if (datetime.now() - last_dt).days < refresh_cooldown_days:
          return False, f"cooldown_{refresh_cooldown_days}d"
    except Exception:
      pass

  save_news_fingerprint(state_path, fp, len(headlines))
  try:
    data = json.loads(state_path.read_text(encoding="utf-8"))
  except Exception:
    data = {"fingerprint": fp, "headline_count": len(headlines)}
  data["last_refresh_at"] = datetime.now().isoformat()
  state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
  return True, f"news_changed ({len(headlines)} headlines)"


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


def no_trades_alert_payload(
  now: datetime,
  *,
  no_trades_hours: float,
  last_trade_time: Optional[datetime],
  robot_started_at: datetime,
  robot_active: bool,
  trading_enabled: bool,
  already_alerted_for: Optional[datetime],
) -> tuple[bool, Optional[datetime], str]:
  """Нужен ли алерт «нет сделок» (в т.ч. если сделок не было вообще с запуска)."""
  if no_trades_hours <= 0 or not trading_enabled or not robot_active:
    return False, already_alerted_for, ""
  reference = last_trade_time if last_trade_time is not None else robot_started_at
  if (now - reference).total_seconds() < no_trades_hours * 3600:
    return False, already_alerted_for, ""
  alert_key = last_trade_time if last_trade_time is not None else robot_started_at
  if already_alerted_for == alert_key:
    return False, already_alerted_for, ""
  hours = int(no_trades_hours)
  if last_trade_time is None:
    msg = (
      f"⚠️ Ни одной сделки с запуска более {hours} ч. "
      "Проверьте /portfolio, rebalance_decisions.log и bot.log."
    )
  else:
    msg = f"⚠️ Нет сделок более {hours} ч. Проверьте логи и доступ к брокеру."
  return True, alert_key, msg

"""Динамический состав портфеля через советников (Finam / MOEX / OpenRouter / Macro)."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import DynamicPortfolioConfig, InstrumentConfig
from .strategy_names import normalize_strategy_name

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = "data/dynamic_portfolio.json"


def normalize_weights(
  selections: List[Dict[str, Any]],
  max_weight: float,
  min_instruments: int,
  max_instruments: int,
) -> List[Dict[str, Any]]:
  """Нормализует веса и обрезает число инструментов."""
  cleaned: List[Dict[str, Any]] = []
  for row in selections:
    ticker = (row.get("ticker") or "").strip().upper()
    if not ticker:
      continue
    w = max(0.0, float(row.get("target_weight", 0)))
    if w <= 0:
      continue
    cleaned.append({"ticker": ticker, "target_weight": w, "reason": row.get("reason", "")})
  if not cleaned:
    return []
  cleaned.sort(key=lambda x: x["target_weight"], reverse=True)
  cleaned = cleaned[: max(1, max_instruments)]
  if len(cleaned) < min_instruments:
    logger.warning(
      "LLM вернул %d инструментов (минимум %d), используем как есть",
      len(cleaned),
      min_instruments,
    )
  cap = max(0.05, min(1.0, max_weight))
  for row in cleaned:
    row["target_weight"] = min(row["target_weight"], cap)
  total = sum(r["target_weight"] for r in cleaned)
  if total <= 0:
    return []
  for row in cleaned:
    row["target_weight"] = row["target_weight"] / total
  return cleaned


def build_candidate_summary(
  broker: Any,
  tickers: List[str],
  history_days: int = 10,
) -> Dict[str, str]:
  """Краткая статистика по кандидатам для промпта LLM."""
  summary: Dict[str, str] = {}
  to_dt = datetime.now()
  from_dt = to_dt - timedelta(days=max(5, history_days))
  for ticker in tickers:
    try:
      figi, _ = broker.resolve_ticker(ticker)
      df = broker.get_historical_candles(figi, from_dt, to_dt)
      if df is None or len(df) < 2 or "close" not in df.columns:
        summary[ticker] = "мало данных"
        continue
      close = df["close"]
      price = float(close.iloc[-1])
      r5 = (price / float(close.iloc[-min(5, len(close))]) - 1) * 100 if len(close) >= 5 else 0.0
      r10 = (price / float(close.iloc[0]) - 1) * 100
      high = df["high"].values if "high" in df.columns else close.values
      low = df["low"].values if "low" in df.columns else close.values
      tr = []
      for i in range(1, min(len(close), len(high), len(low))):
        tr.append(max(high[i] - low[i], abs(high[i] - close.iloc[i - 1]), abs(low[i] - close.iloc[i - 1])))
      atr_pct = (sum(tr[-14:]) / max(len(tr[-14:]), 1) / price * 100) if price > 0 and tr else 0.0
      peak = float(close.max())
      dd = (price / peak - 1) * 100 if peak > 0 else 0.0
      summary[ticker] = f"price={price:.2f} return_5d={r5:.1f}% return_10d={r10:.1f}% atr_pct={atr_pct:.1f}% dd={dd:.1f}%"
    except Exception as e:
      summary[ticker] = f"ошибка: {e}"
  return summary


def instruments_from_selections(
  selections: List[Dict[str, Any]],
  broker: Any,
  default_strategy: str = "adaptive",
) -> List[InstrumentConfig]:
  """Преобразует выбор советника в InstrumentConfig с FIGI и лотами."""
  strategy = normalize_strategy_name(default_strategy)
  out: List[InstrumentConfig] = []
  for row in selections:
    ticker = (row.get("ticker") or "").strip().upper()
    if not ticker:
      continue
    try:
      figi, lot = broker.resolve_ticker(ticker)
    except Exception as e:
      logger.warning("dynamic_portfolio: пропуск %s — не найден FIGI: %s", ticker, e)
      continue
    strategy_params: Dict[str, Any] = {}
    out.append(
      InstrumentConfig(
        figi=figi,
        ticker=ticker,
        lot=lot,
        strategy=strategy,
        target_weight=float(row["target_weight"]),
        strategy_params=strategy_params,
      )
    )
  return out


def load_state(path: Path) -> Optional[dict]:
  if not path.exists():
    return None
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except Exception as e:
    logger.warning("dynamic_portfolio: не удалось прочитать %s: %s", path, e)
    return None


def save_state(
  path: Path,
  instruments: List[InstrumentConfig],
  summary: str = "",
  advisor_source: str = "",
) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  payload = {
    "updated_at": datetime.now().isoformat(),
    "summary": summary,
    "advisor_source": advisor_source,
    "instruments": [
      {
        "figi": i.figi,
        "ticker": i.ticker,
        "lot": i.lot,
        "strategy": i.strategy,
        "target_weight": i.target_weight,
        "strategy_params": i.strategy_params,
      }
      for i in instruments
    ],
  }
  path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def instruments_from_state(state: dict) -> List[InstrumentConfig]:
  rows = state.get("instruments") or []
  out: List[InstrumentConfig] = []
  for row in rows:
    out.append(
      InstrumentConfig(
        figi=row["figi"],
        ticker=row["ticker"],
        lot=int(row.get("lot", 1) or 1),
        strategy=normalize_strategy_name(row.get("strategy", "adaptive")),
        target_weight=float(row.get("target_weight", 0)),
        strategy_params=dict(row.get("strategy_params") or {}),
      )
    )
  return out


def is_refresh_needed(state: Optional[dict], interval_days: int) -> bool:
  if interval_days <= 0:
    return False
  if not state or not state.get("updated_at"):
    return True
  try:
    updated = datetime.fromisoformat(str(state["updated_at"]))
    return datetime.now() - updated >= timedelta(days=interval_days)
  except Exception:
    return True


def get_candidates(dp: DynamicPortfolioConfig, fallback_instruments: List[InstrumentConfig]) -> List[str]:
  if dp.candidates:
    return [t.upper() for t in dp.candidates]
  return [i.ticker.upper() for i in fallback_instruments]


def refresh_dynamic_portfolio(
  dp: DynamicPortfolioConfig,
  broker: Any,
  fallback_instruments: List[InstrumentConfig],
  *,
  force: bool = False,
  history_days: int = 10,
  openrouter_model: str = "google/gemini-2.5-flash-lite",
  base_dir: Optional[Path] = None,
  finam_cfg: Any = None,
  openrouter_cfg: Any = None,
  macro_news_cfg: Any = None,
) -> Tuple[List[InstrumentConfig], str, bool]:
  """
  Обновляет состав портфеля через все активные советники; при pick_best_advisor — лучший по бэктесту.
  Возвращает (instruments, message, changed).
  """
  base = base_dir or Path(__file__).resolve().parent
  state_path = base / (dp.state_file or DEFAULT_STATE_FILE)
  state = load_state(state_path)

  if not force and state and not is_refresh_needed(state, dp.refresh_interval_days):
    instruments = instruments_from_state(state)
    if instruments:
      updated = state.get("updated_at", "")[:16]
      return instruments, f"Динамический портфель из кэша ({updated})", False

  candidates = get_candidates(dp, fallback_instruments)
  if not candidates:
    return fallback_instruments, "Нет кандидатов для динамического портфеля", False

  try:
    equity, _, _ = broker.get_equity_snapshot()
  except Exception:
    equity = 0.0

  market_context = ""

  summary_map = build_candidate_summary(broker, candidates, history_days=history_days)

  from .finam_client import FinamClient
  from .moex_client import MoexClient
  from . import finam_advisor, moex_advisor
  from .advisor_ensemble import pick_best_portfolio
  from .market_data_client import CompositeMarketClient

  finam_client = FinamClient(
    api_token=getattr(finam_cfg, "api_token", "") if finam_cfg else "",
    base_url=getattr(finam_cfg, "base_url", "https://api.finam.ru") if finam_cfg else "https://api.finam.ru",
    exchange_mic=getattr(finam_cfg, "exchange_mic", "MISX") if finam_cfg else "MISX",
  )
  moex_client = MoexClient()
  market_client = CompositeMarketClient(finam_client=finam_client, moex_client=moex_client)

  proposals: List[Tuple[str, List[Dict[str, Any]], str]] = []

  use_llm = dp.use_openrouter
  if use_llm:
    from .openrouter_advisor import select_universe_via_openrouter

    or_primary = openrouter_model or getattr(openrouter_cfg, "model", "google/gemini-2.5-flash-lite") if openrouter_cfg else openrouter_model
    or_models = list(getattr(openrouter_cfg, "models", None) or []) if openrouter_cfg else None
    llm_sel, llm_summary = select_universe_via_openrouter(
      candidates=candidates,
      candidate_summary=summary_map,
      min_instruments=dp.min_instruments,
      max_instruments=dp.max_instruments,
      max_weight=dp.max_weight_per_instrument,
      model=or_primary,
      models=or_models,
      api_key_override=getattr(openrouter_cfg, "api_key", "") if openrouter_cfg else "",
      base_url=getattr(openrouter_cfg, "base_url", "https://openrouter.ai/api/v1") if openrouter_cfg else "https://openrouter.ai/api/v1",
      site_url=getattr(openrouter_cfg, "site_url", "") if openrouter_cfg else "",
      equity=equity,
      market_context=market_context,
    )
    if llm_sel:
      proposals.append(("llm", llm_sel, llm_summary))

  if dp.use_macro and macro_news_cfg:
    from .macro_advisor import select_portfolio_via_macro
    from .openrouter_client import api_key as or_api_key

    or_key = or_api_key(getattr(openrouter_cfg, "api_key", "") if openrouter_cfg else "")
    if or_key:
      or_primary = openrouter_model or getattr(openrouter_cfg, "model", "google/gemini-2.5-flash-lite") if openrouter_cfg else openrouter_model
      or_models = list(getattr(openrouter_cfg, "models", None) or []) if openrouter_cfg else None
      macro_sel, macro_summary = select_portfolio_via_macro(
        candidates,
        summary_map,
        min_instruments=dp.min_instruments,
        max_instruments=dp.max_instruments,
        max_weight=dp.max_weight_per_instrument,
        macro_cfg=macro_news_cfg,
        model=or_primary,
        models=or_models,
        api_key_override=getattr(openrouter_cfg, "api_key", "") if openrouter_cfg else "",
        base_url=getattr(openrouter_cfg, "base_url", "https://openrouter.ai/api/v1") if openrouter_cfg else "https://openrouter.ai/api/v1",
        site_url=getattr(openrouter_cfg, "site_url", "") if openrouter_cfg else "",
        equity=equity,
        base_dir=base,
      )
      if macro_sel:
        proposals.append(("macro", macro_sel, macro_summary))
    else:
      logger.debug("macro advisor: OPENROUTER_API_KEY не задан")

  if dp.use_finam and finam_client.configured:
    fm_sel, fm_summary = finam_advisor.select_portfolio_via_finam(
      finam_client,
      candidates,
      min_instruments=dp.min_instruments,
      max_instruments=dp.max_instruments,
      max_weight=dp.max_weight_per_instrument,
      history_days=max(history_days, 60),
    )
    if fm_sel:
      proposals.append(("finam", fm_sel, fm_summary))

  if dp.use_moex:
    mx_sel, mx_summary = moex_advisor.select_portfolio_via_moex(
      moex_client,
      candidates,
      min_instruments=dp.min_instruments,
      max_instruments=dp.max_instruments,
      max_weight=dp.max_weight_per_instrument,
      history_days=max(history_days, 60),
    )
    if mx_sel:
      proposals.append(("moex", mx_sel, mx_summary))

  selections: List[Dict[str, Any]] = []
  advisor_source = ""
  combined_summary = ""

  if not proposals:
    pass
  elif len(proposals) == 1 or not dp.pick_best_advisor:
    advisor_source = proposals[0][0]
    selections = proposals[0][1]
    combined_summary = proposals[0][2]
  else:
    advisor_source, selections, combined_summary, _ = pick_best_portfolio(
      proposals,
      market_client,
      history_days=max(history_days, 60),
    )

  if not selections:
    if dp.fallback_to_static and fallback_instruments:
      msg = "Советники недоступны, используется статический конфиг ({0} инструментов)".format(len(fallback_instruments))
      if state and instruments_from_state(state):
        cached = instruments_from_state(state)
        return cached, msg + " (кэш сохранён ранее)", False
      return fallback_instruments, msg, False
    return fallback_instruments, "Советники не вернули состав, изменений нет", False

  instruments = instruments_from_selections(selections, broker, dp.default_strategy)
  if not instruments:
    msg = "Советник вернул тикеры, но FIGI не найдены — fallback"
    logger.warning("dynamic_portfolio: %s", msg)
    if dp.fallback_to_static and fallback_instruments:
      if state and instruments_from_state(state):
        return instruments_from_state(state), msg + " (кэш)", False
      return fallback_instruments, msg, False
    return fallback_instruments, msg, False

  tickers = ", ".join(f"{i.ticker} {i.target_weight:.0%}" for i in instruments)
  msg = combined_summary or f"{advisor_source} выбрал: {tickers}"
  if advisor_source and "выбран" not in msg.lower():
    msg = f"[{advisor_source}] {msg}"

  old_tickers = {i.ticker for i in instruments_from_state(state)} if state else set()
  new_tickers = {i.ticker for i in instruments}
  changed = old_tickers != new_tickers or not state

  save_state(state_path, instruments, summary=combined_summary, advisor_source=advisor_source)
  return instruments, msg, changed

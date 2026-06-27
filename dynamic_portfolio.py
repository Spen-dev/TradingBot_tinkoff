"""Динамический состав портфеля по рекомендациям DeepSeek."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import DynamicPortfolioConfig, InstrumentConfig

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = "data/dynamic_portfolio.json"


def _parse_deepseek_json(text: str) -> dict:
  text = (text or "").strip()
  if text.startswith("```"):
    parts = text.split("```")
    text = parts[1] if len(parts) > 1 else text
    if text.startswith("json"):
      text = text[4:]
  return json.loads(text.strip())


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
      "DeepSeek вернул %d инструментов (минимум %d), используем как есть",
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
  """Краткая статистика по кандидатам для промпта DeepSeek."""
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


def select_universe_via_deepseek(
  candidates: List[str],
  candidate_summary: Dict[str, str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  model: str = "deepseek-chat",
  equity: float = 0.0,
  market_context: str = "",
) -> Tuple[List[Dict[str, Any]], str]:
  """Запрос к DeepSeek: выбрать состав портфеля из кандидатов."""
  api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
  if not api_key:
    return [], "DEEPSEEK_API_KEY не задан"

  lines = [f"Капитал портфеля: {equity:.0f} RUB.", "Кандидаты (тикер: метрики):"]
  for t in candidates:
    lines.append(f"  {t}: {candidate_summary.get(t, 'нет данных')}")
  if market_context:
    lines.append(f"\nКонтекст рынка: {market_context}")

  prompt = f"""Ты — портфельный аналитик российского фондового рынка (MOEX).

{chr(10).join(lines)}

Выбери оптимальный портфель ТОЛЬКО из перечисленных тикеров-кандидатов.

Верни JSON без markdown:
{{"portfolio": [{{"ticker": "<TICKER>", "target_weight": <0..1>, "reason": "<кратко>"}}], "summary": "<1-2 предложения>"}}

Правила:
- Выбери от {min_instruments} до {max_instruments} акций из списка кандидатов (не добавляй другие).
- target_weight в сумме = 1.0.
- Максимальный вес одной акции: {max_weight:.0%}.
- Диверсификация по секторам, избегай концентрации в одной отрасли.
- Учитывай momentum, волатильность и просадку; не гонись только за доходностью 5d."""

  try:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
      model=model,
      messages=[
        {"role": "system", "content": "Ты отвечаешь только валидным JSON без пояснений."},
        {"role": "user", "content": prompt},
      ],
      temperature=0.35,
      max_tokens=1536,
    )
    data = _parse_deepseek_json(resp.choices[0].message.content or "")
    raw = data.get("portfolio") or data.get("recommendations") or []
    summary = str(data.get("summary") or "").strip()
    allowed = {t.upper() for t in candidates}
    filtered = [r for r in raw if (r.get("ticker") or "").strip().upper() in allowed]
    normalized = normalize_weights(filtered, max_weight, min_instruments, max_instruments)
    return normalized, summary
  except Exception as e:
    logger.warning("DeepSeek dynamic portfolio: %s", e)
    return [], str(e)


def instruments_from_selections(
  selections: List[Dict[str, Any]],
  broker: Any,
  default_strategy: str = "deepseek",
) -> List[InstrumentConfig]:
  """Преобразует выбор DeepSeek в InstrumentConfig с FIGI и лотами."""
  out: List[InstrumentConfig] = []
  for row in selections:
    ticker = row["ticker"]
    figi, lot = broker.resolve_ticker(ticker)
    strategy_params: Dict[str, Any] = {}
    if default_strategy == "rl":
      strategy_params["rl_model_path"] = f"data/rl_model_{ticker}.zip"
    out.append(
      InstrumentConfig(
        figi=figi,
        ticker=ticker,
        lot=lot,
        strategy=default_strategy,
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
        strategy=row.get("strategy", "deepseek"),
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
  deepseek_model: str = "deepseek-chat",
  gemini_model: str = "gemini-2.0-flash",
  groq_model: str = "llama-3.3-70b-versatile",
  openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free",
  base_dir: Optional[Path] = None,
  finam_cfg: Any = None,
  gemini_cfg: Any = None,
  groq_cfg: Any = None,
  openrouter_cfg: Any = None,
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

  if dp.use_deepseek:
    ds_sel, ds_summary = select_universe_via_deepseek(
      candidates=candidates,
      candidate_summary=summary_map,
      min_instruments=dp.min_instruments,
      max_instruments=dp.max_instruments,
      max_weight=dp.max_weight_per_instrument,
      model=deepseek_model,
      equity=equity,
      market_context=market_context,
    )
    if ds_sel:
      proposals.append(("deepseek", ds_sel, ds_summary))

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

  if dp.use_gemini:
    from .gemini_advisor import select_universe_via_gemini

    gm_sel, gm_summary = select_universe_via_gemini(
      candidates=candidates,
      candidate_summary=summary_map,
      min_instruments=dp.min_instruments,
      max_instruments=dp.max_instruments,
      max_weight=dp.max_weight_per_instrument,
      model=gemini_model,
      api_key=getattr(gemini_cfg, "api_key", "") if gemini_cfg else "",
      equity=equity,
      market_context=market_context,
    )
    if gm_sel:
      proposals.append(("gemini", gm_sel, gm_summary))

  if dp.use_groq:
    from .groq_advisor import select_universe_via_groq

    gq_sel, gq_summary = select_universe_via_groq(
      candidates=candidates,
      candidate_summary=summary_map,
      min_instruments=dp.min_instruments,
      max_instruments=dp.max_instruments,
      max_weight=dp.max_weight_per_instrument,
      model=groq_model,
      api_key=getattr(groq_cfg, "api_key", "") if groq_cfg else "",
      equity=equity,
      market_context=market_context,
    )
    if gq_sel:
      proposals.append(("groq", gq_sel, gq_summary))

  if dp.use_openrouter:
    from .openrouter_advisor import select_universe_via_openrouter

    or_sel, or_summary = select_universe_via_openrouter(
      candidates=candidates,
      candidate_summary=summary_map,
      min_instruments=dp.min_instruments,
      max_instruments=dp.max_instruments,
      max_weight=dp.max_weight_per_instrument,
      model=openrouter_model,
      api_key=getattr(openrouter_cfg, "api_key", "") if openrouter_cfg else "",
      base_url=getattr(openrouter_cfg, "base_url", "https://openrouter.ai/api/v1") if openrouter_cfg else "https://openrouter.ai/api/v1",
      site_url=getattr(openrouter_cfg, "site_url", "") if openrouter_cfg else "",
      equity=equity,
      market_context=market_context,
    )
    if or_sel:
      proposals.append(("openrouter", or_sel, or_summary))

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
  tickers = ", ".join(f"{i.ticker} {i.target_weight:.0%}" for i in instruments)
  msg = combined_summary or f"{advisor_source} выбрал: {tickers}"
  if advisor_source and "выбран" not in msg.lower():
    msg = f"[{advisor_source}] {msg}"

  old_tickers = {i.ticker for i in instruments_from_state(state)} if state else set()
  new_tickers = {i.ticker for i in instruments}
  changed = old_tickers != new_tickers or not state

  save_state(state_path, instruments, summary=combined_summary, advisor_source=advisor_source)
  return instruments, msg, changed

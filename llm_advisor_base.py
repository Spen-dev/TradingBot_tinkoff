"""Общая логика LLM-советников (портфель и рекомендации)."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ChatFn = Callable[[str, str], str]


def parse_llm_json(text: str) -> dict:
  text = (text or "").strip()
  if text.startswith("```"):
    parts = text.split("```")
    if len(parts) >= 2:
      text = parts[1]
      if text.startswith("json"):
        text = text[4:]
  text = text.strip()
  return json.loads(text)


def normalize_weights(
  raw: List[dict],
  max_weight: float,
  min_instruments: int,
  max_instruments: int,
) -> List[Dict[str, Any]]:
  if not raw:
    return []
  cap = max(0.05, min(1.0, max_weight))
  trimmed = raw[: max(1, max_instruments)]
  if len(trimmed) < min_instruments and len(raw) >= min_instruments:
    trimmed = raw[:min_instruments]
  total = sum(float(r.get("target_weight", 0) or 0) for r in trimmed) or 1.0
  out: List[Dict[str, Any]] = []
  for r in trimmed:
    ticker = (r.get("ticker") or "").strip().upper()
    if not ticker:
      continue
    tw = float(r.get("target_weight", 0) or 0) / total
    tw = min(cap, max(0.0, tw))
    out.append(
      {
        "ticker": ticker,
        "target_weight": tw,
        "reason": str(r.get("reason") or "").strip(),
      }
    )
  wsum = sum(x["target_weight"] for x in out) or 1.0
  for x in out:
    x["target_weight"] /= wsum
  return out


def select_universe_via_llm(
  chat_fn: ChatFn,
  *,
  candidates: List[str],
  candidate_summary: Dict[str, str],
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  equity: float = 0.0,
  market_context: str = "",
  provider_label: str = "LLM",
) -> Tuple[List[Dict[str, Any]], str]:
  lines = [
    f"Капитал портфеля: {equity:.0f} RUB." if equity > 0 else "Капитал: не указан.",
    "Кандидаты (тикер: метрики):",
  ]
  for t in candidates:
    key = t.upper()
    lines.append(f"  {key}: {candidate_summary.get(key, candidate_summary.get(t, 'нет данных'))}")
  if market_context:
    lines.append(f"\nКонтекст рынка: {market_context}")

  user_prompt = f"""Ты — портфельный аналитик российского фондового рынка (MOEX).

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
    text = chat_fn("Ты отвечаешь только валидным JSON без пояснений.", user_prompt)
    if not text:
      return [], f"{provider_label}: API ключ не задан"
    data = parse_llm_json(text)
    raw = data.get("portfolio") or data.get("recommendations") or []
    summary = str(data.get("summary") or "").strip()
    allowed = {t.upper() for t in candidates}
    filtered = [r for r in raw if (r.get("ticker") or "").strip().upper() in allowed]
    normalized = normalize_weights(filtered, max_weight, min_instruments, max_instruments)
    return normalized, summary
  except Exception as e:
    logger.warning("%s dynamic portfolio: %s", provider_label, e)
    return [], str(e)


def get_recommendations_via_llm(
  chat_fn: ChatFn,
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  *,
  history_summary: Optional[Dict[str, str]] = None,
  provider_label: str = "LLM",
) -> Dict[str, Dict[str, Any]]:
  lines = [
    f"Портфель: equity={equity:.0f} RUB, cash={cash:.0f} RUB.",
    "Инструменты (тикер, FIGI, целевой вес из конфига, текущая позиция RUB, цена):",
  ]
  for ins in instruments:
    figi = getattr(ins, "figi", "")
    ticker = getattr(ins, "ticker", "")
    tw = getattr(ins, "target_weight", 0)
    pos = positions.get(figi)
    value = pos.value if pos and getattr(pos, "value", None) else 0.0
    price = last_prices.get(figi, 0.0) or (getattr(pos, "current_price", None) if pos else 0.0)
    lines.append(
      f"  {ticker} (FIGI={figi[:12]}...): target_weight={tw:.2f}, position_value={value:.0f}, price={price:.2f}"
    )
  context = "\n".join(lines)
  if history_summary:
    context += "\n\nИстория по инструментам (доходность, волатильность, просадка за период):\n"
    for ticker, summary in history_summary.items():
      context += f"  {ticker}: {summary}\n"

  user_prompt = f"""Ты — консультант по управлению портфелем акций на российском рынке. Данные текущего состояния:

{context}

Верни JSON без markdown, в формате:
{{"recommendations": [{{"ticker": "<тикер>", "action": "buy"|"sell"|"hold", "target_weight": <число 0..1>, "strength": <0.3..1.0>}}]}}

Правила: target_weight по инструментам в сумме должны давать 1.0. action: buy — увеличить долю, sell — уменьшить, hold — без изменений. strength — уверенность (для buy/sell). Учитывай диверсификацию и разумный риск."""

  try:
    text = chat_fn("Ты отвечаешь только валидным JSON без пояснений.", user_prompt)
    if not text:
      return {}
    data = parse_llm_json(text)
    recs = data.get("recommendations") or []
    ticker_to_figi = {getattr(ins, "ticker", ""): getattr(ins, "figi", "") for ins in instruments}
    out: Dict[str, Dict[str, Any]] = {}
    for r in recs:
      ticker = (r.get("ticker") or "").strip()
      figi = ticker_to_figi.get(ticker)
      if not figi:
        continue
      action = (r.get("action") or "hold").lower()
      if action not in ("buy", "sell", "hold"):
        action = "hold"
      tw = max(0.0, min(1.0, float(r.get("target_weight", 0))))
      strength = max(0.3, min(1.0, float(r.get("strength", 0.7))))
      out[figi] = {"action": action, "target_weight": tw, "strength": strength}
    return out
  except Exception as e:
    logger.warning("%s advisor: %s", provider_label, e)
    return {}


def select_universe_via_macro_events(
  chat_fn: ChatFn,
  *,
  candidates: List[str],
  candidate_summary: Dict[str, str],
  events_text: str,
  min_instruments: int,
  max_instruments: int,
  max_weight: float,
  equity: float = 0.0,
) -> Tuple[List[Dict[str, Any]], str]:
  """Портфель MOEX с упором на мировые/макро-события и новости."""
  lines = [
    f"Капитал портфеля: {equity:.0f} RUB." if equity > 0 else "Капитал: не указан.",
    "Кандидаты MOEX (тикер: технические метрики):",
  ]
  for t in candidates:
    key = t.upper()
    lines.append(f"  {key}: {candidate_summary.get(key, candidate_summary.get(t, 'нет данных'))}")

  user_prompt = f"""Ты — macro-аналитик портфеля акций MOEX. Твоя задача — собрать портфель с учётом мировых событий и новостей.

{chr(10).join(lines)}

Недавние новости и события (геополитика, санкции, нефть/газ, ставки ЦБ, сырьё, MOEX, секторы):
{events_text}

Выбери портфель ТОЛЬКО из перечисленных тикеров-кандидатов.

Верни JSON без markdown:
{{"portfolio": [{{"ticker": "<TICKER>", "target_weight": <0..1>, "reason": "<связь с событиями>"}}], "summary": "<1-2 предложения: ключевые события и логика>"}}

Правила:
- От {min_instruments} до {max_instruments} акций, только из списка кандидатов.
- target_weight в сумме = 1.0, макс. вес одной акции: {max_weight:.0%}.
- Учитывай сектора: нефть/газ (ROSN, TATN, LKOH, NVTK), металлы (GMKN, NLMK, CHMF, PLZL), банки (SBER, VTBR), потреб (MGNT, MTSS) и т.д.
- Снижай вес секторов под негативными геополитическими/сырьевыми рисками; повышай при позитивном макро для РФ/MOEX.
- Не выдумывай факты beyond заголовков; при неясности — диверсифицируй."""

  try:
    text = chat_fn(
      "Ты macro-аналитик MOEX. Отвечай только валидным JSON без markdown.",
      user_prompt,
    )
    if not text:
      return [], "macro: пустой ответ LLM"
    data = parse_llm_json(text)
    raw = data.get("portfolio") or data.get("recommendations") or []
    summary = str(data.get("summary") or "").strip()
    allowed = {t.upper() for t in candidates}
    filtered = [r for r in raw if (r.get("ticker") or "").strip().upper() in allowed]
    normalized = normalize_weights(filtered, max_weight, min_instruments, max_instruments)
    return normalized, summary
  except Exception as e:
    logger.warning("macro dynamic portfolio: %s", e)
    return [], str(e)

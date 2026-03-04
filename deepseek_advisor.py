# Модуль советника DeepSeek для решений по портфелю.
# Требует: DEEPSEEK_API_KEY в .env, pip install openai.

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def get_recommendations(
  instruments: List[Any],
  positions: Dict[str, Any],
  equity: float,
  cash: float,
  last_prices: Dict[str, float],
  model: str = "deepseek-chat",
) -> Dict[str, Dict[str, Any]]:
  """
  Запрос к DeepSeek API: по текущему портфелю и ценам возвращает рекомендации по каждому тикеру.
  Возвращает: { figi: {"action": "buy"|"sell"|"hold", "target_weight": float, "strength": float} }.
  При ошибке или отсутствии ключа — пустой dict.
  """
  api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
  if not api_key:
    logger.debug("DEEPSEEK_API_KEY не задан, советник DeepSeek отключён")
    return {}

  # Собираем сводку по инструментам
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
    lines.append(f"  {ticker} (FIGI={figi[:12]}...): target_weight={tw:.2f}, position_value={value:.0f}, price={price:.2f}")
  context = "\n".join(lines)

  prompt = f"""Ты — консультант по управлению портфелем акций на российском рынке. Данные текущего состояния:

{context}

Верни JSON без markdown, в формате:
{{"recommendations": [{{"ticker": "<тикер>", "action": "buy"|"sell"|"hold", "target_weight": <число 0..1>, "strength": <0.3..1.0>}}]}}

Правила: target_weight по инструментам в сумме должны давать 1.0. action: buy — увеличить долю, sell — уменьшить, hold — без изменений. strength — уверенность (для buy/sell). Учитывай диверсификацию и разумный риск."""

  try:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
      model=model,
      messages=[
        {"role": "system", "content": "Ты отвечаешь только валидным JSON без пояснений."},
        {"role": "user", "content": prompt},
      ],
      temperature=0.3,
      max_tokens=1024,
    )
    text = (resp.choices[0].message.content or "").strip()
    # Убрать обёртку markdown если есть
    if text.startswith("```"):
      text = text.split("```")[1]
      if text.startswith("json"):
        text = text[4:]
    data = json.loads(text)
    recs = data.get("recommendations") or []
    ticker_to_figi = {getattr(ins, "ticker", ""): getattr(ins, "figi", "") for ins in instruments}
    out = {}
    for r in recs:
      ticker = (r.get("ticker") or "").strip()
      figi = ticker_to_figi.get(ticker)
      if not figi:
        continue
      action = (r.get("action") or "hold").lower()
      if action not in ("buy", "sell", "hold"):
        action = "hold"
      tw = float(r.get("target_weight", 0))
      tw = max(0.0, min(1.0, tw))
      strength = float(r.get("strength", 0.7))
      strength = max(0.3, min(1.0, strength))
      out[figi] = {"action": action, "target_weight": tw, "strength": strength}
    return out
  except Exception as e:
    logger.warning("DeepSeek advisor: %s", e)
    return {}

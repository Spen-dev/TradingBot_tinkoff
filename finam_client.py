"""Клиент Finam Trade API (REST): JWT и исторические свечи."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.finam.ru"


def _decimal_value(obj: Any) -> float:
  if obj is None:
    return 0.0
  if isinstance(obj, (int, float)):
    return float(obj)
  if isinstance(obj, dict):
    return float(obj.get("value") or 0)
  try:
    return float(str(obj))
  except (TypeError, ValueError):
    return 0.0


class FinamClient:
  """Синхронный REST-клиент Finam Trade API."""

  def __init__(
    self,
    api_token: str = "",
    base_url: str = DEFAULT_BASE_URL,
    exchange_mic: str = "MISX",
    timeout: float = 30.0,
  ):
    self.api_token = (api_token or os.environ.get("FINAM_API_TOKEN", "")).strip()
    self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    self.exchange_mic = (exchange_mic or "MISX").strip()
    self.timeout = timeout
    self._jwt: Optional[str] = None
    self._jwt_expires_at: float = 0.0

  @property
  def configured(self) -> bool:
    return bool(self.api_token)

  def symbol(self, ticker: str) -> str:
    return f"{ticker.upper()}@{self.exchange_mic}"

  def _request(
    self,
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, str]] = None,
    body: Optional[dict] = None,
    auth: bool = False,
  ) -> dict:
    url = f"{self.base_url}{path}"
    if params:
      url = f"{url}?{urllib.parse.urlencode(params)}"
    data = None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth:
      jwt = self._ensure_jwt()
      headers["Authorization"] = f"Bearer {jwt}"
    if body is not None:
      data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
      with urllib.request.urlopen(req, timeout=self.timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
      if auth and e.code == 401:
        self._jwt = None
        self._jwt_expires_at = 0.0
      try:
        err_body = e.read().decode("utf-8")
      except Exception:
        err_body = str(e)
      raise RuntimeError(f"Finam API {method} {path}: HTTP {e.code} {err_body}") from e

  def _ensure_jwt(self) -> str:
    if self._jwt and time.time() < self._jwt_expires_at - 60:
      return self._jwt
    if not self.api_token:
      raise RuntimeError("FINAM_API_TOKEN не задан")
    data = self._request("POST", "/v1/sessions", body={"secret": self.api_token})
    token = (data.get("token") or "").strip()
    if not token:
      raise RuntimeError("Finam API: пустой JWT в ответе /v1/sessions")
    self._jwt = token
    self._jwt_expires_at = time.time() + 3600
    return token

  def get_daily_bars(self, ticker: str, days: int = 90) -> List[Dict[str, float]]:
    """Дневные свечи: [{open, high, low, close, volume}, ...] по возрастанию времени."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(5, days))
    params = {
      "timeframe": "TIME_FRAME_D",
      "interval.start_time": start.strftime("%Y-%m-%dT00:00:00Z"),
      "interval.end_time": end.strftime("%Y-%m-%dT23:59:59Z"),
    }
    data = self._request(
      "GET",
      f"/v1/instruments/{urllib.parse.quote(self.symbol(ticker), safe='@')}/bars",
      params=params,
      auth=True,
    )
    rows: List[Dict[str, float]] = []
    for bar in data.get("bars") or []:
      rows.append(
        {
          "open": _decimal_value(bar.get("open")),
          "high": _decimal_value(bar.get("high")),
          "low": _decimal_value(bar.get("low")),
          "close": _decimal_value(bar.get("close")),
          "volume": _decimal_value(bar.get("volume")),
        }
      )
    return rows

  def get_last_quote(self, ticker: str) -> float:
    data = self._request(
      "GET",
      f"/v1/instruments/{urllib.parse.quote(self.symbol(ticker), safe='@')}/quotes/latest",
      auth=True,
    )
    quote = data.get("quote") or data
    for key in ("last", "last_price", "price", "close"):
      if key in quote:
        return _decimal_value(quote[key])
    return _decimal_value(quote)

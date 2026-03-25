from dataclasses import dataclass
from typing import Dict, List, Tuple
from contextlib import contextmanager
from datetime import datetime, timezone

import pandas as pd
from decimal import Decimal

from tinkoff.invest import (
  Client,
  CandleInterval,
  InstrumentIdType,
  Quotation,
  OrderDirection,
  OrderType,
  MoneyValue,
)
from tinkoff.invest.utils import decimal_to_quotation
from tinkoff.invest.sandbox.client import SandboxClient

from .config import TinkoffConfig


def _quotation_to_float(q: Quotation) -> float:
  return q.units + q.nano / 1e9


def _money_to_float(m) -> float:
  """MoneyValue/Quotation -> float (units + nano/1e9)."""
  return getattr(m, "units", 0) + getattr(m, "nano", 0) / 1e9


def _as_list(x):
  if x is None:
    return []
  if isinstance(x, (list, tuple)):
    return list(x)
  return [x]


@dataclass
class Position:
  figi: str
  quantity: float
  average_price: float
  current_price: float
  value: float


class TinkoffBroker:
  # Валютные FIGI — в «бумагах» не учитываем; ликвидность задаём остатком от total_amount_portfolio.
  _CURRENCY_FIGIS = frozenset({"RUB000UTSTOM", "BBG0013HGFT4", "BBG0013HJJ31"})

  def __init__(self, cfg: TinkoffConfig):
    self._cfg = cfg

  @contextmanager
  def _client(self):
    client_cls = SandboxClient if self._cfg.use_sandbox else Client
    with client_cls(self._cfg.token) as client:
      yield client

  def _fetch_portfolio_raw(self):
    with self._client() as client:
      if self._cfg.use_sandbox:
        return client.sandbox.get_sandbox_portfolio(account_id=self._cfg.account_id)
      return client.operations.get_portfolio(account_id=self._cfg.account_id)

  def _positions_from_response(self, resp) -> Dict[str, Position]:
    positions: Dict[str, Position] = {}
    for p in resp.positions:
      figi = p.figi
      itype = str(getattr(p, "instrument_type", "") or "").lower()
      if figi in self._CURRENCY_FIGIS or "currency" in itype or itype == "3":
        continue
      current_price = _quotation_to_float(p.current_price)
      avg_price = _quotation_to_float(p.average_position_price)
      qty = _quotation_to_float(p.quantity)
      positions[figi] = Position(
        figi=figi,
        quantity=qty,
        average_price=avg_price,
        current_price=current_price,
        value=qty * current_price,
      )
    return positions

  def get_portfolio(self) -> Dict[str, Position]:
    return self._positions_from_response(self._fetch_portfolio_raw())

  def _cash_from_positions_api(self, currency: str) -> float:
    """Деньги по operations.get_positions (money − blocked). При ошибке — 0."""
    with self._client() as client:
      try:
        pos = client.operations.get_positions(account_id=self._cfg.account_id)
      except Exception:
        pos = None
    if pos is None:
      return 0.0
    money_sum = sum(
      _money_to_float(m) for m in (getattr(pos, "money", None) or [])
      if getattr(m, "currency", "").upper() == currency.upper()
    )
    blocked_sum = sum(
      _money_to_float(b) for b in (getattr(pos, "blocked", None) or [])
      if getattr(b, "currency", "").upper() == currency.upper()
    )
    return max(0.0, money_sum - blocked_sum)

  def get_equity_snapshot(self, currency: str = "RUB") -> Tuple[float, float, Dict[str, Position]]:
    """Один запрос портфеля: эквити, свободно в валюте (остаток относительно оценки бумаг), позиции без валюты.

    Эквити берём из total_amount_portfolio (согласованная оценка брокера); cash = equity − сумма(бумаги),
    чтобы не смешивать get_positions и get_portfolio (иначе возможно cash > equity).
    Если total_amount_portfolio нет или валюта не совпала — fallback: cash из get_positions, equity = cash + бумаги.
    """
    resp = self._fetch_portfolio_raw()
    positions = self._positions_from_response(resp)
    sec_total = sum(p.value for p in positions.values())
    tap = getattr(resp, "total_amount_portfolio", None)
    cur = str(getattr(tap, "currency", "") or "").upper() if tap is not None else ""
    if tap is not None and cur == currency.upper():
      equity = _money_to_float(tap)
      cash = max(0.0, equity - sec_total)
      return equity, cash, positions
    cash = self._cash_from_positions_api(currency)
    if cash <= 0 and sec_total <= 0:
      m = getattr(resp, "total_amount_currencies", None)
      if m is not None and getattr(m, "currency", "").upper() == currency.upper():
        cash = _money_to_float(m)
    equity = cash + sec_total
    return equity, cash, positions

  def get_cash_balance(self, currency: str = "RUB") -> float:
    """Свободные средства в одной методике со get_equity_snapshot (предпочтительно остаток от total_amount_portfolio)."""
    return self.get_equity_snapshot(currency)[1]

  def get_historical_candles(
    self,
    figi: str,
    from_dt: datetime,
    to_dt: datetime,
    interval: CandleInterval = CandleInterval.CANDLE_INTERVAL_DAY,
  ) -> pd.DataFrame:
    with self._client() as client:
      resp = client.market_data.get_candles(
        figi=figi,
        from_=from_dt.replace(tzinfo=timezone.utc),
        to=to_dt.replace(tzinfo=timezone.utc),
        interval=interval,
      )

    rows = []
    for c in resp.candles:
      rows.append(
        {
          "time": c.time.replace(tzinfo=None),
          "open": _quotation_to_float(c.open),
          "high": _quotation_to_float(c.high),
          "low": _quotation_to_float(c.low),
          "close": _quotation_to_float(c.close),
          "volume": c.volume,
        }
      )
    return pd.DataFrame(rows).set_index("time")

  def place_order(
    self,
    figi: str,
    quantity: int,
    direction: OrderDirection,
    order_type: OrderType = OrderType.ORDER_TYPE_MARKET,
    price: float | None = None,
  ) -> str:
    """price — обязателен для лимитной заявки. В песочнице лимитные заявки избегают 30034."""
    kwargs: dict = {
      "figi": figi,
      "quantity": quantity,
      "direction": direction,
      "account_id": self._cfg.account_id,
      "order_type": order_type,
    }
    if price is not None and order_type == OrderType.ORDER_TYPE_LIMIT:
      kwargs["price"] = decimal_to_quotation(Decimal(str(price)))

    with self._client() as client:
      if self._cfg.use_sandbox:
        resp = client.sandbox.post_sandbox_order(**kwargs)
      else:
        resp = client.orders.post_order(**kwargs)
    return resp.order_id

  def get_open_orders(self) -> List[Dict[str, str]]:
    """Список активных заявок: [{"order_id": ..., "figi": ..., "order_type": ...}, ...]."""
    with self._client() as client:
      if self._cfg.use_sandbox:
        resp = client.sandbox.get_sandbox_orders(account_id=self._cfg.account_id)
      else:
        resp = client.orders.get_orders(account_id=self._cfg.account_id)
    out = []
    for o in getattr(resp, "orders", []) or []:
      oid = getattr(o, "order_id", None)
      figi = getattr(o, "figi", None)
      if oid and figi:
        otype = getattr(o, "order_type", None)
        type_name = getattr(otype, "name", str(otype))
        out.append({"order_id": oid, "figi": figi, "order_type": type_name})
    return out

  def cancel_orders(self, order_ids: List[str]) -> None:
    if not order_ids:
      return
    with self._client() as client:
      cancel_fn = client.sandbox.cancel_sandbox_order if self._cfg.use_sandbox else client.orders.cancel_order
      for oid in order_ids:
        try:
          cancel_fn(account_id=self._cfg.account_id, order_id=oid)
        except Exception:
          continue

  def get_last_price(self, figi: str) -> float:
    """Последняя цена инструмента для расчёта заявок при отсутствии позиции."""
    with self._client() as client:
      resp = client.market_data.get_last_prices(figi=[figi])
    for lp in getattr(resp, "last_prices", []) or []:
      if lp.figi == figi:
        return _quotation_to_float(lp.price)
    return 0.0

  def get_order_book_mid(self, figi: str) -> tuple[float | None, float | None, float | None]:
    """(best_bid, best_ask, mid) по стакану. При ошибке возвращает (None, None, None)."""
    try:
      with self._client() as client:
        ob = client.market_data.get_order_book(figi=figi, depth=1)
      bids = list(getattr(ob, "bids", []) or [])
      asks = list(getattr(ob, "asks", []) or [])
      best_bid = _quotation_to_float(bids[0].price) if bids else None
      best_ask = _quotation_to_float(asks[0].price) if asks else None
      if best_bid is not None and best_ask is not None and best_ask > 0:
        mid = (best_bid + best_ask) / 2.0
      else:
        mid = None
      return best_bid, best_ask, mid
    except Exception:
      return None, None, None

  def get_lot_size(self, figi: str) -> int:
    """Размер лота по FIGI. Нужен для округления количества при выставлении заявок."""
    with self._client() as client:
      resp = client.instruments.share_by(
        id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
        id=figi,
      )
    return max(1, getattr(resp.instrument, "lot", 1))

  def set_sandbox_balance(self, amount: float, currency: str = "RUB") -> None:
    if not self._cfg.use_sandbox:
      return
    with self._client() as client:
      client.sandbox.sandbox_pay_in(
        account_id=self._cfg.account_id,
        amount=MoneyValue(currency=currency, units=int(amount), nano=int((amount % 1) * 1e9)),
      )


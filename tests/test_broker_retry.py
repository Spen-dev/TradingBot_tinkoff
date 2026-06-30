"""Тесты retry-логики брокера."""
import grpc
import pytest
from t_tech.invest.exceptions import RequestError

from tinkoff_bot.broker import _is_retryable_broker_error, _with_broker_retry


def test_retryable_timeout_and_unavailable():
  assert _is_retryable_broker_error(TimeoutError()) is True
  assert _is_retryable_broker_error(
    RequestError(grpc.StatusCode.UNAVAILABLE, "503 unavailable", None)
  ) is True


def test_not_retryable_business_order_error():
  assert _is_retryable_broker_error(
    RequestError(grpc.StatusCode.INVALID_ARGUMENT, "30034 invalid price", None)
  ) is False


def test_with_broker_retry_succeeds_after_transient_failures():
  calls = {"n": 0}

  def fn():
    calls["n"] += 1
    if calls["n"] < 3:
      raise RequestError(grpc.StatusCode.UNAVAILABLE, "503 unavailable", None)
    return 42

  assert _with_broker_retry(fn, label="test") == 42
  assert calls["n"] == 3


def test_with_broker_retry_raises_immediately_on_business_error():
  calls = {"n": 0}

  def fn():
    calls["n"] += 1
    raise RequestError(grpc.StatusCode.INVALID_ARGUMENT, "30034 invalid", None)

  with pytest.raises(RequestError):
    _with_broker_retry(fn, label="test")
  assert calls["n"] == 1

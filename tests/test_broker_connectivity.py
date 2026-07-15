import asyncio

from tinkoff_bot.run_bot import _BrokerConnectivity, _format_error


class _FakeTg:
  pass


def test_broker_connectivity_single_down_alert(monkeypatch):
  sent: list[tuple[str, str]] = []

  async def fake_send(tg, message, alert_type, force=False, require_telegram=False):
    sent.append((alert_type, message))
    return True

  monkeypatch.setattr("tinkoff_bot.run_bot.send_alert", fake_send)
  conn = _BrokerConnectivity()
  tg = _FakeTg()
  err = TimeoutError()

  async def run():
    assert await conn.note_failure(tg, err, context="test") is True
    assert await conn.note_failure(tg, err, context="test") is True

  asyncio.run(run())
  assert len(sent) == 1
  assert sent[0][0] == "broker_unavailable"
  assert "TimeoutError" in sent[0][1]


def test_broker_connectivity_recovery_alert(monkeypatch):
  sent: list[str] = []

  async def fake_send(tg, message, alert_type, force=False, require_telegram=False):
    sent.append(alert_type)
    return True

  monkeypatch.setattr("tinkoff_bot.run_bot.send_alert", fake_send)
  conn = _BrokerConnectivity()
  tg = _FakeTg()

  async def run():
    await conn.note_failure(tg, TimeoutError())
    await conn.note_success(tg)
    await conn.note_success(tg)

  asyncio.run(run())
  assert sent == ["broker_unavailable", "broker_recovered"]


def test_broker_connectivity_ignores_non_connect_errors(monkeypatch):
  sent: list[str] = []

  async def fake_send(tg, message, alert_type, force=False, require_telegram=False):
    sent.append(alert_type)
    return True

  monkeypatch.setattr("tinkoff_bot.run_bot.send_alert", fake_send)
  conn = _BrokerConnectivity()
  tg = _FakeTg()

  async def run():
    assert await conn.note_failure(tg, ValueError("bad token")) is False

  asyncio.run(run())
  assert sent == []


def test_format_error_timeout():
  assert _format_error(TimeoutError()) == "TimeoutError"

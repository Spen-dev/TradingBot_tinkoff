"""Тесты паузы по инструменту после серии убытков."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tinkoff_bot import instrument_pause as ip


@pytest.fixture
def pause_file(tmp_path, monkeypatch):
  path = tmp_path / "instrument_pause.json"
  monkeypatch.setattr(ip, "PAUSE_FILE", path)
  return path


def test_update_pauses_alerts_only_once(pause_file):
  figi = "BBG004730RP0"
  consec = {figi: 3}
  first = ip.update_pauses(consec, threshold=3, pause_hours=24.0)
  assert first == [figi]
  second = ip.update_pauses(consec, threshold=3, pause_hours=24.0)
  assert second == []


def test_update_pauses_repairs_bad_until_without_alert(pause_file):
  figi = "BBG004730RP0"
  pause_file.write_text(json.dumps({figi: "not-a-date"}), encoding="utf-8")
  consec = {figi: 3}
  result = ip.update_pauses(consec, threshold=3, pause_hours=24.0)
  assert result == []
  data = json.loads(pause_file.read_text(encoding="utf-8"))
  assert ip._parse_until(data[figi]) is not None
  assert ip._parse_until(data[figi]) > datetime.now()


def test_update_pauses_re_alerts_after_expiry(pause_file):
  figi = "BBG004730RP0"
  past = (datetime.now() - timedelta(hours=1)).isoformat()
  pause_file.write_text(json.dumps({figi: past}), encoding="utf-8")
  consec = {figi: 3}
  result = ip.update_pauses(consec, threshold=3, pause_hours=24.0)
  assert result == [figi]

"""Тесты автоочистки логов."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import tinkoff_bot.logging_config as lc


def test_cleanup_old_logs_by_filename_date(tmp_path, monkeypatch):
  monkeypatch.setattr(lc, "LOG_DIR", tmp_path)
  old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
  recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
  (tmp_path / "bot.log").write_text("current\n", encoding="utf-8")
  (tmp_path / f"bot.log.{old}").write_text("old\n", encoding="utf-8")
  (tmp_path / f"bot.log.{recent}").write_text("recent\n", encoding="utf-8")
  removed = lc.cleanup_old_logs(retention_days=14)
  assert removed == 1
  assert (tmp_path / f"bot.log.{old}").exists() is False
  assert (tmp_path / f"bot.log.{recent}").exists() is True

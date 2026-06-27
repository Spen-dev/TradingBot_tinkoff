"""Тесты health_server: auth и маршруты."""
import os

from tinkoff_bot import health_server as hs


def test_dashboard_auth_skipped_when_no_token(monkeypatch):
  monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
  assert hs._dashboard_auth_ok("GET /api/status HTTP/1.1") is True


def test_dashboard_auth_requires_token(monkeypatch):
  monkeypatch.setenv("DASHBOARD_TOKEN", "secret")
  assert hs._dashboard_auth_ok("GET /api/status HTTP/1.1") is False
  assert hs._dashboard_auth_ok("GET /api/status?token=secret HTTP/1.1") is True


def test_needs_dashboard_auth():
  assert hs._needs_dashboard_auth("GET /health HTTP/1.1") is False
  assert hs._needs_dashboard_auth("GET /metrics HTTP/1.1") is False
  assert hs._needs_dashboard_auth("GET /api/status HTTP/1.1") is True
  assert hs._needs_dashboard_auth("GET /dashboard HTTP/1.1") is True

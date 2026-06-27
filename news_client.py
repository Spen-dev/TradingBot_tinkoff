"""Загрузка заголовков новостей (RSS) для macro-советника."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILE = "data/macro_news_cache.json"

DEFAULT_RSS_URLS = [
  "https://news.google.com/rss/search?q=Russia+economy+oil+MOEX+stocks&hl=en&gl=US&ceid=US:en",
  "https://news.google.com/rss/search?q=ЦБ+РФ+нефть+санкции+биржа+MOEX&hl=ru&gl=RU&ceid=RU:ru",
  "https://news.google.com/rss/search?q=global+markets+geopolitics+commodities&hl=en&gl=US&ceid=US:en",
]


def _strip_html(text: str) -> str:
  return re.sub(r"<[^>]+>", "", text or "").strip()


def _encode_url(url: str) -> str:
  """Percent-encode URL (urllib.Request не принимает кириллицу в query)."""
  parts = urlsplit(url.strip())
  if not parts.scheme or not parts.netloc:
    return url.strip()
  path = quote(parts.path, safe="/%")
  query = quote(parts.query, safe="=&?%+")
  return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def _parse_rss_xml(raw: str, source: str, max_items: int) -> List[Dict[str, str]]:
  out: List[Dict[str, str]] = []
  try:
    root = ET.fromstring(raw)
  except ET.ParseError as e:
    logger.debug("RSS parse %s: %s", source, e)
    return out
  for item in root.findall(".//item")[: max(1, max_items)]:
    title = _strip_html((item.findtext("title") or "").strip())
    if not title:
      continue
    pub = (item.findtext("pubDate") or item.findtext("published") or "").strip()
    link = (item.findtext("link") or "").strip()
    out.append({"title": title, "published": pub, "source": source, "link": link})
  return out


def fetch_rss_headlines(
  url: str,
  *,
  max_items: int = 10,
  timeout: float = 20.0,
) -> List[Dict[str, str]]:
  url = _encode_url(url)
  if not url:
    return []
  try:
    req = urllib.request.Request(url, headers={"User-Agent": "tinkoff_bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      raw = resp.read().decode("utf-8", errors="replace")
    return _parse_rss_xml(raw, url, max_items)
  except (urllib.error.URLError, TimeoutError, OSError) as e:
    logger.warning("RSS %s: %s", url[:80], e)
    return []


def _load_cache(path: Path) -> Optional[dict]:
  if not path.exists():
    return None
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except Exception:
    return None


def _save_cache(path: Path, headlines: List[Dict[str, str]]) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    json.dumps({"fetched_at": datetime.now().isoformat(), "headlines": headlines}, ensure_ascii=False, indent=2),
    encoding="utf-8",
  )


def collect_macro_headlines(
  rss_urls: Optional[List[str]] = None,
  *,
  max_per_feed: int = 10,
  max_total: int = 25,
  cache_hours: float = 6.0,
  cache_file: str = DEFAULT_CACHE_FILE,
  timeout: float = 20.0,
  base_dir: Optional[Path] = None,
  force_refresh: bool = False,
) -> List[Dict[str, str]]:
  """Собирает уникальные заголовки; кэширует на диск."""
  urls = [u for u in (rss_urls or DEFAULT_RSS_URLS) if (u or "").strip()]
  base = base_dir or Path(__file__).resolve().parent
  cache_path = base / cache_file

  if cache_hours > 0 and not force_refresh:
    cached = _load_cache(cache_path)
    if cached and cached.get("headlines"):
      try:
        ts = datetime.fromisoformat(str(cached.get("fetched_at", "")))
        if (datetime.now() - ts).total_seconds() < cache_hours * 3600:
          return list(cached["headlines"])[:max_total]
      except Exception:
        pass

  seen: set[str] = set()
  merged: List[Dict[str, str]] = []
  for url in urls:
    for row in fetch_rss_headlines(url, max_items=max_per_feed, timeout=timeout):
      key = row["title"].lower()[:120]
      if key in seen:
        continue
      seen.add(key)
      merged.append(row)
      if len(merged) >= max_total:
        break
    if len(merged) >= max_total:
      break

  if merged and cache_hours > 0:
    _save_cache(cache_path, merged)
  return merged


def format_headlines_for_llm(headlines: List[Dict[str, str]], max_lines: int = 25) -> str:
  if not headlines:
    return ""
  lines: List[str] = []
  for i, h in enumerate(headlines[:max_lines], 1):
    title = h.get("title", "")
    pub = h.get("published", "")
    prefix = f"{pub}: " if pub else ""
    lines.append(f"{i}. {prefix}{title}")
  return "\n".join(lines)

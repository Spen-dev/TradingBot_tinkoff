"""Загрузка заголовков новостей (RSS) для macro-советника."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILE = "data/macro_news_cache.json"

_CONTENT_NS = {"content": "http://purl.org/rss/1.0/modules/content"}

DEFAULT_RSS_URLS = [
  "https://news.google.com/rss/search?q=Russia+economy+oil+MOEX+stocks&hl=en&gl=US&ceid=US:en",
  "https://news.google.com/rss/search?q=ЦБ+РФ+нефть+санкции+биржа+MOEX&hl=ru&gl=RU&ceid=RU:ru",
  "https://news.google.com/rss/search?q=global+markets+geopolitics+commodities&hl=en&gl=US&ceid=US:en",
  "https://news.google.com/rss/search?q=MOEX+IMOEX+индекс+акции&hl=ru&gl=RU&ceid=RU:ru",
  "https://news.google.com/rss/search?q=ЦБ+РФ+ключевая+ставка&hl=ru&gl=RU&ceid=RU:ru",
  "https://news.google.com/rss/search?q=Brent+oil+price+OPEC&hl=en&gl=US&ceid=US:en",
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


def _parse_pub_date(raw: str) -> Optional[datetime]:
  text = (raw or "").strip()
  if not text:
    return None
  try:
    dt = parsedate_to_datetime(text)
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return dt
  except Exception:
    pass
  try:
    dt = datetime.fromisoformat(text[:26].replace(" ", "T"))
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return dt
  except Exception:
    return None


def _item_description(item: ET.Element) -> str:
  for tag in ("description", "summary"):
    el = item.find(tag)
    if el is not None and (el.text or "").strip():
      return _strip_html(el.text or "")
  enc = item.find("content:encoded", _CONTENT_NS)
  if enc is not None and (enc.text or "").strip():
    return _strip_html(enc.text or "")
  for child in item:
    if child.tag.endswith("encoded") and (child.text or "").strip():
      return _strip_html(child.text or "")
  return ""


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
    desc = _item_description(item)
    row: Dict[str, str] = {"title": title, "published": pub, "source": source, "link": link}
    if desc:
      row["description"] = desc
    ts = _parse_pub_date(pub)
    if ts is not None:
      row["published_ts"] = ts.isoformat()
    out.append(row)
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


def _headline_datetime(row: Dict[str, str]) -> Optional[datetime]:
  ts_raw = row.get("published_ts") or row.get("published") or ""
  if row.get("published_ts"):
    try:
      return datetime.fromisoformat(str(row["published_ts"]))
    except Exception:
      pass
  return _parse_pub_date(str(ts_raw))


def _filter_and_sort_headlines(
  headlines: List[Dict[str, str]],
  *,
  max_age_days: int,
) -> List[Dict[str, str]]:
  """Свежие первыми; отбрасываем записи старше max_age_days (если дата распознана)."""
  if not headlines:
    return []
  now = datetime.now(timezone.utc)
  kept: List[Dict[str, str]] = []
  for row in headlines:
    ts = _headline_datetime(row)
    if max_age_days > 0 and ts is not None:
      age_days = (now - ts.astimezone(timezone.utc)).total_seconds() / 86400.0
      if age_days > max_age_days:
        continue
    kept.append(row)

  def _sort_key(row: Dict[str, str]) -> tuple:
    ts = _headline_datetime(row)
    if ts is None:
      return (1, 0.0)
    return (0, -ts.timestamp())

  kept.sort(key=_sort_key)
  return kept


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
  max_age_days: int = 14,
  cache_hours: float = 6.0,
  cache_file: str = DEFAULT_CACHE_FILE,
  timeout: float = 20.0,
  base_dir: Optional[Path] = None,
  force_refresh: bool = False,
) -> List[Dict[str, str]]:
  """Собирает уникальные заголовки; кэширует на диск; фильтрует по возрасту."""
  urls = [u for u in (rss_urls or DEFAULT_RSS_URLS) if (u or "").strip()]
  base = base_dir or Path(__file__).resolve().parent
  cache_path = base / cache_file

  if cache_hours > 0 and not force_refresh:
    cached = _load_cache(cache_path)
    if cached and cached.get("headlines"):
      try:
        ts = datetime.fromisoformat(str(cached.get("fetched_at", "")))
        if (datetime.now() - ts).total_seconds() < cache_hours * 3600:
          filtered = _filter_and_sort_headlines(list(cached["headlines"]), max_age_days=max_age_days)
          return filtered[:max_total]
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
    if len(merged) >= max_total * 2:
      break

  merged = _filter_and_sort_headlines(merged, max_age_days=max_age_days)[:max_total]

  if merged and cache_hours > 0:
    _save_cache(cache_path, merged)
  return merged


def format_headlines_for_llm(
  headlines: List[Dict[str, str]],
  max_lines: int = 25,
  *,
  include_description: bool = True,
  max_description_chars: int = 200,
) -> str:
  if not headlines:
    return ""
  lines: List[str] = []
  for i, h in enumerate(headlines[:max_lines], 1):
    title = h.get("title", "")
    pub = h.get("published", "")
    prefix = f"{pub}: " if pub else ""
    line = f"{i}. {prefix}{title}"
    if include_description:
      desc = _strip_html(str(h.get("description") or ""))
      if desc:
        if max_description_chars > 0:
          desc = desc[:max_description_chars].rstrip()
          if len(h.get("description") or "") > max_description_chars:
            desc += "…"
        line += f"\n   {desc}"
    lines.append(line)
  return "\n".join(lines)

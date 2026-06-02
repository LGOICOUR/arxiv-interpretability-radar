"""Ingest: pull the latest new submissions from arXiv's per-category RSS feeds.

Why RSS and not the export query API: the query API aggressively 429s bursty
and cloud IPs (GitHub Actions runners get blocked outright), which would zero
out the author + keyword paths every day. The RSS feeds are CDN-served, not
rate-limited, and are literally arXiv's "new announcements" feed — exactly what
a daily radar wants. Each feed is the most recent announcement batch for one
category; we keep genuinely-new papers (announce_type new/cross, skip the
'replace' revisions of old papers) within the lookback window, deduped across
categories.
"""

import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import requests

import util

RSS = "https://rss.arxiv.org/rss/{}"
UA = ("arxiv-interpretability-radar/1.0 "
      "(https://github.com/LGOICOUR; mailto:luis.goicouria@gmail.com)")
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
DC_NS = "{http://purl.org/dc/elements/1.1/}"


def _get(session, url, max_retries=4):
    """GET with backoff on transient errors / 429 / 503 (RSS rarely needs it)."""
    delay = 4.0
    for attempt in range(max_retries):
        try:
            r = session.get(url, timeout=(10, 60))
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise
            print(f"  ! RSS request error ({type(e).__name__}); retrying in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
            continue
        if r.status_code == 200:
            return r.text
        if r.status_code in (429, 503):
            if attempt == max_retries - 1:
                r.raise_for_status()
            ra = r.headers.get("Retry-After", "")
            wait = max(delay, float(ra)) if ra.isdigit() else delay
            print(f"  ! RSS {r.status_code}; backing off {wait:.0f}s")
            time.sleep(wait)
            delay *= 2
            continue
        r.raise_for_status()
    return ""


def _pubdate(item):
    raw = item.findtext("pubDate", "")
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None


def _record(item):
    link = item.findtext("link", "") or ""
    arxiv_id = util.short_id(link)
    desc = item.findtext("description", "") or ""
    abstract = desc.split("Abstract:", 1)[-1].strip() if "Abstract:" in desc else desc.strip()
    creator = item.findtext(DC_NS + "creator", "") or ""
    authors = [a.strip() for a in creator.split(",") if a.strip()]
    cats = [c.text for c in item.findall("category") if c.text]
    pub = _pubdate(item)
    return {
        "id": arxiv_id,
        "title": " ".join((item.findtext("title", "") or "").split()),
        "abstract": abstract,
        "authors": authors,
        "categories": cats,
        "published": pub.isoformat() if pub else "",
        "abs_url": util.abs_url(arxiv_id),
        "pdf_url": util.pdf_url(arxiv_id),
        "tags": [],
        "source": "ingest",
        "score": None,
        "reason": None,
    }


def fetch_recent(categories, lookback_hours, max_results=2000, delay_seconds=1.0):
    """Return new submissions from the category RSS feeds, deduped by ID."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    by_id, skipped_old, skipped_replace = {}, 0, 0
    for i, cat in enumerate(categories):
        try:
            xml = _get(session, RSS.format(cat))
            channel = ET.fromstring(xml).find("channel")
            items = channel.findall("item") if channel is not None else []
        except Exception as e:
            print(f"  ! RSS feed {cat} failed ({type(e).__name__}: {e}); skipping")
            continue

        kept = 0
        for item in items:
            if (item.findtext(ARXIV_NS + "announce_type", "") or "") == "replace":
                skipped_replace += 1
                continue
            pub = _pubdate(item)
            if pub is not None and pub < cutoff:
                skipped_old += 1
                continue
            rec = _record(item)
            if not rec["id"] or not rec["title"]:
                continue
            if rec["id"] in by_id:                 # cross-listed in another feed
                for c in rec["categories"]:
                    if c not in by_id[rec["id"]]["categories"]:
                        by_id[rec["id"]]["categories"].append(c)
            elif len(by_id) < max_results:
                by_id[rec["id"]] = rec
                kept += 1
        print(f"  ingest: {cat} feed -> {kept} new")
        if i < len(categories) - 1:
            time.sleep(delay_seconds)  # politeness between feeds

    print(f"  ingest: {len(by_id)} unique new papers within {lookback_hours}h "
          f"(skipped {skipped_replace} replacements, {skipped_old} older)")
    return list(by_id.values())

"""Ingest: pull recent papers from the configured arXiv categories.

Talks to the arXiv export API directly (requests + stdlib XML) rather than the
`arxiv` package, which 429s on its default request pattern. arXiv asks for a
descriptive User-Agent and <=1 request / 3 seconds; we honor both and back off
on 429/503. We walk newest-first and stop as soon as we cross the cutoff.
"""

import time
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import requests

import util

API = "http://export.arxiv.org/api/query"
UA = ("arxiv-interpretability-radar/1.0 "
      "(https://github.com/LGOICOUR; mailto:luis.goicouria@gmail.com)")
ATOM = "{http://www.w3.org/2005/Atom}"
PAGE_SIZE = 100


def _text(el, tag):
    child = el.find(tag)
    return child.text if (child is not None and child.text) else ""


def _parse_dt(s):
    return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))


def _record(entry):
    raw_id = _text(entry, ATOM + "id")
    arxiv_id = util.short_id(raw_id)
    pub = _parse_dt(_text(entry, ATOM + "published"))
    authors = [_text(a, ATOM + "name") for a in entry.findall(ATOM + "author")]
    cats = [c.get("term") for c in entry.findall(ATOM + "category") if c.get("term")]
    rec = {
        "id": arxiv_id,
        "title": " ".join(_text(entry, ATOM + "title").split()),
        "abstract": _text(entry, ATOM + "summary").strip(),
        "authors": authors,
        "categories": cats,
        "published": pub.isoformat(),
        "abs_url": util.abs_url(arxiv_id),
        "pdf_url": util.pdf_url(arxiv_id),
        "tags": [],
        "source": "ingest",
        "score": None,
        "reason": None,
    }
    return rec, pub


def _get_page(session, params, max_retries=5):
    """GET one page, retrying on transient network errors and 429/503.

    export.arxiv.org is intermittently slow, so we use a generous read timeout
    and back off on timeouts/connection errors as well as rate limits.
    """
    delay = 5.0
    for attempt in range(max_retries):
        try:
            r = session.get(API, params=params, timeout=(10, 60))
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise
            print(f"  ! arXiv request error ({type(e).__name__}); "
                  f"retrying in {delay:.0f}s")
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
            print(f"  ! arXiv {r.status_code}; backing off {wait:.0f}s")
            time.sleep(wait)
            delay *= 2
            continue
        r.raise_for_status()
    return ""


def fetch_recent(categories, lookback_hours, max_results=2000, delay_seconds=3.0):
    """Return normalized records submitted within the last `lookback_hours`."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    query = " OR ".join(f"cat:{c}" for c in categories)
    session = requests.Session()
    session.headers["User-Agent"] = UA

    records, start, stop = [], 0, False
    try:
        while start < max_results and not stop:
            xml = _get_page(session, {
                "search_query": query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": start,
                "max_results": min(PAGE_SIZE, max_results - start),
            })
            entries = ET.fromstring(xml).findall(ATOM + "entry")
            if not entries:
                break  # end of results
            for entry in entries:
                if "/api/errors" in _text(entry, ATOM + "id"):
                    continue
                rec, pub = _record(entry)
                if pub < cutoff:
                    stop = True
                    break
                records.append(rec)
            start += len(entries)
            if not stop and start < max_results:
                time.sleep(delay_seconds)  # arXiv politeness: <=1 req / 3s
    except Exception as e:
        print(f"  ! arXiv ingest stopped early ({type(e).__name__}: {e}); "
              f"keeping {len(records)} record(s)")

    print(f"  ingest: {len(records)} papers in the last {lookback_hours}h "
          f"across {', '.join(categories)}")
    return records

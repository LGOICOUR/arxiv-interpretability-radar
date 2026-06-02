"""Citation path: papers that cite the anchor papers.

This is the highest-signal feed — if someone cites the belief-state-geometry
line of work, that's a strong topical signal, so citers ship unscored. We hit
Semantic Scholar's citations endpoint per anchor, keep citers from a recent
window (wider than the 48h ingest lookback, because the citation graph lags
arXiv by weeks), and normalize to the same record shape as ingest.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests

import util

S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{}/citations"
S2_FIELDS = "title,abstract,authors,externalIds,publicationDate,year"
S2_PAGE = "https://www.semanticscholar.org/paper/{}"


def _get(url, params, headers, max_retries=4):
    """GET with exponential backoff on 429 / transient errors."""
    delay = 3.0
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise
            print(f"  ! S2 request error ({e}); retrying in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 429:
            if attempt == max_retries - 1:
                resp.raise_for_status()
            print(f"  ! S2 rate-limited (429); backing off {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    return {}


def _is_recent(paper, cutoff_str, cutoff_year):
    pub = paper.get("publicationDate")
    if pub:
        return pub >= cutoff_str
    year = paper.get("year")          # no day-level date: fall back to year
    return bool(year) and year >= cutoff_year


def _record(paper, anchor_name):
    ext = paper.get("externalIds") or {}
    arxiv_ref = ext.get("ArXiv")
    if arxiv_ref:
        arxiv_id = util.short_id(arxiv_ref)
        rec_id, abs_url, pdf_url = arxiv_id, util.abs_url(arxiv_id), util.pdf_url(arxiv_id)
    else:
        pid = paper.get("paperId", "")
        rec_id, abs_url, pdf_url = f"s2:{pid}", S2_PAGE.format(pid), None
    tag = f"cites:{anchor_name}"
    return {
        "id": rec_id,
        "title": " ".join((paper.get("title") or "").split()),
        "abstract": (paper.get("abstract") or "").strip(),
        "authors": [a.get("name", "") for a in (paper.get("authors") or [])],
        "categories": [],
        "published": paper.get("publicationDate") or str(paper.get("year") or ""),
        "abs_url": abs_url,
        "pdf_url": pdf_url,
        "tags": [tag],
        "source": tag,
        "score": None,
        "reason": None,
    }


def fetch_anchor_citers(anchors, lookback_days, api_key=None):
    """Return recent citers of every anchor, deduped, tagged cites:<name>."""
    api_key = api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    headers = {"x-api-key": api_key} if api_key else {}
    polite = 1.0 if api_key else 3.0

    cutoff = datetime.now(timezone.utc).date() - timedelta(days=lookback_days)
    cutoff_str, cutoff_year = cutoff.isoformat(), cutoff.year

    by_id = {}
    for anchor in anchors:
        anchor_id, name = anchor["id"], anchor["name"]
        url = S2_BASE.format(anchor_id)
        kept = 0
        offset = 0
        try:
            for _ in range(3):  # up to 3 pages of 1000 — plenty for these anchors
                data = _get(url, {"fields": S2_FIELDS, "limit": 1000, "offset": offset},
                            headers)
                rows = data.get("data", [])
                for row in rows:
                    paper = row.get("citingPaper") or {}
                    if not _is_recent(paper, cutoff_str, cutoff_year):
                        continue
                    rec = _record(paper, name)
                    if not rec["title"]:
                        continue
                    if rec["id"] in by_id:        # cites >1 anchor: merge tags
                        existing = by_id[rec["id"]]
                        for t in rec["tags"]:
                            if t not in existing["tags"]:
                                existing["tags"].append(t)
                    else:
                        by_id[rec["id"]] = rec
                        kept += 1
                offset = data.get("next")
                if offset is None:
                    break
                time.sleep(polite)
        except requests.HTTPError as e:
            print(f"  ! citations for {anchor_id} ({name}) failed: {e}")
        else:
            print(f"  citations: {kept} recent citer(s) of {anchor_id} ({name})")
        time.sleep(polite)

    return list(by_id.values())

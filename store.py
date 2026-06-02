"""JSON dedup store.

A single committed file, data/seen.json: {arxiv_id: {first_seen, score, tags}}.
It does two jobs — dedup across daily runs (so a paper ships once, ever) and
keep enough history for a later weekly rollup. The GitHub Actions workflow
commits it back so the cloud run remembers what it has already sent.

Why JSON over SQLite here: this repo is public and CI commits state every day,
so a human-readable file that diffs cleanly and merges trivially beats a binary
blob. Keys are written sorted so each day's diff is just the new IDs appended.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _save(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def init_store(path):
    if not Path(path).exists():
        _save(path, {})


def filter_unseen(records, path):
    """Return only the records whose ID isn't already in the store."""
    seen = _load(path)
    return [r for r in records if r["id"] not in seen]


def mark_seen(records, path):
    """Record each paper so it never ships again. First-seen wins."""
    seen = _load(path)
    now = _now()
    for r in records:
        seen.setdefault(r["id"], {
            "first_seen": now,
            "score": r.get("score"),
            "tags": r.get("tags", []),
        })
    _save(path, seen)


def recent(path, since_iso):
    """IDs first seen at/after `since_iso`, best score first — for rollups."""
    seen = _load(path)
    rows = [{"arxiv_id": k, **v} for k, v in seen.items()
            if v.get("first_seen", "") >= since_iso]
    rows.sort(key=lambda r: (r.get("score") is None, -(r.get("score") or 0)))
    return rows

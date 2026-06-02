#!/usr/bin/env python3
"""arXiv Interpretability Radar — pipeline entry point.

    python main.py                 # full run: fetch, score, write, email
    python main.py --dry-run       # print the digest, write nothing-but-archive, no email
    python main.py --since 168     # override lookback (hours) — e.g. a week
    python main.py --no-email      # write files, skip the email
    python main.py --reset-db      # wipe the dedup DB first (re-test from scratch)

Three signal paths feed one ranked digest. The citation and author paths are
trusted and ship unscored; only the keyword path goes through the Claude gate.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import citations
import config
import deliver
import filter
import ingest
import render
import score
import store


def _gh_output(**kv):
    """Emit step outputs when running under GitHub Actions."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a") as f:
        for k, v in kv.items():
            f.write(f"{k}={v}\n")


def _merge(into, rec):
    """Merge rec into an existing same-ID record: union tags, fill score/abstract."""
    for t in rec.get("tags", []):
        if t not in into["tags"]:
            into["tags"].append(t)
    if into.get("score") is None and rec.get("score") is not None:
        into["score"] = rec["score"]
        into["reason"] = rec.get("reason")
    if not into.get("abstract") and rec.get("abstract"):
        into["abstract"] = rec["abstract"]


def _bucket_of(rec):
    if any(t.startswith("cites:") for t in rec["tags"]):
        return "cites"
    if any(t.startswith("author:") for t in rec["tags"]):
        return "author"
    return "topic"


def main():
    ap = argparse.ArgumentParser(description="arXiv Interpretability Radar")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the digest to stdout; no email, no dedup write")
    ap.add_argument("--since", type=int, metavar="HOURS",
                    help="override lookback_hours for the ingest path")
    ap.add_argument("--no-email", action="store_true", help="write files, skip email")
    ap.add_argument("--reset-db", action="store_true",
                    help="wipe the dedup DB before running")
    args = ap.parse_args()

    cfg = config.load()
    lookback = args.since if args.since is not None else cfg["lookback_hours"]
    date_str = datetime.now(timezone.utc).date().isoformat()

    print(f"arXiv Interpretability Radar — {date_str}"
          f"{' (dry run)' if args.dry_run else ''}")

    if args.reset_db and config.SEEN_PATH.exists():
        config.SEEN_PATH.unlink()
        print("  reset: dedup store wiped")
    store.init_store(config.SEEN_PATH)

    # --- Three signal paths --------------------------------------------------
    ingested = ingest.fetch_recent(cfg["categories"], lookback, cfg["max_ingest_results"])
    citers = citations.fetch_anchor_citers(cfg["anchors"], cfg["citation_lookback_days"])
    author_hits = filter.match_authors(ingested, cfg["authors"])
    keyword_hits = filter.match_keywords(ingested, cfg["keywords"])
    scored = score.score_papers(keyword_hits, cfg["score_threshold"], cfg["score_model"])

    # --- Merge + dedup by ID (priority: citers > authors > scored) -----------
    chosen = {}
    for rec in [*citers, *author_hits, *scored]:
        rid = rec["id"]
        if rid in chosen:
            _merge(chosen[rid], rec)
        else:
            chosen[rid] = rec
    final = list(chosen.values())

    # Dedup across runs: never ship a paper twice.
    final = store.filter_unseen(final, config.SEEN_PATH)

    # --- Bucket + rank -------------------------------------------------------
    buckets = {"cites": [], "author": [], "topic": []}
    for r in final:
        buckets[_bucket_of(r)].append(r)
    buckets["cites"].sort(key=lambda r: r["published"], reverse=True)
    buckets["author"].sort(key=lambda r: r["published"], reverse=True)
    buckets["topic"].sort(key=lambda r: (r.get("score") or 0, r["published"]), reverse=True)

    total = len(final)
    md = render.render_markdown(date_str, buckets)
    html = render.markdown_to_html(md)
    has_content = total > 0

    paths = deliver.write_digest(md, html, date_str, config.DIGESTS_DIR,
                                 config.PROJECT_ROOT, has_content)
    print(f"\n  digest: {total} paper(s) -> {paths['dated']}")

    if args.dry_run:
        print("\n" + "=" * 72 + "\n")
        print(md)
        _gh_output(today=date_str, has_content="false")
        return 0

    # Real run: remember what we shipped so it never repeats.
    store.mark_seen(final, config.SEEN_PATH)

    if has_content and not args.no_email:
        subject = f"arXiv Interp Radar — {date_str} ({total} paper{'s' if total != 1 else ''})"
        deliver.send_email(subject, html, paths["md"], cfg["digest_to"])
    elif not has_content:
        print("  (empty digest — nothing emailed)")

    _gh_output(today=date_str, has_content=str(has_content).lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The author and keyword paths over the ingested set.

match_authors  -> HIGH precision, trusted, ships unscored (tag author:<name>)
match_keywords -> MEDIUM precision, feeds the Claude relevance gate (tag topic)
"""

import re

import util

# ε / ϵ both fold to "epsilon" so 'ε-machine', 'epsilon-machine', and
# 'epsilon machine' all collapse to the same normalized token sequence.
_EPSILONS = ("ε", "ϵ")


def _normalize(text):
    """Lower-case, fold epsilon, and reduce punctuation to single spaces.

    Returns the text padded with a leading/trailing space so that substring
    tests on normalized keywords behave like whole-word / whole-phrase matches.
    """
    s = (text or "").lower()
    for e in _EPSILONS:
        s = s.replace(e, "epsilon")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return f" {s.strip()} "


def match_authors(records, authors):
    """Tag and return records co-authored by anyone on the watchlist."""
    hits = []
    for r in records:
        matched = util.matched_watchlist_names(r["authors"], authors)
        if matched:
            for name in matched:
                tag = f"author:{name}"
                if tag not in r["tags"]:
                    r["tags"].append(tag)
            hits.append(r)
    print(f"  authors: {len(hits)} paper(s) by watchlist authors")
    return hits


def match_keywords(records, keywords):
    """Tag and return records whose title/abstract hits any keyword."""
    norm_kws = [(_normalize(k).strip(), k) for k in keywords]
    hits = []
    for r in records:
        haystack = _normalize(f"{r['title']} {r['abstract']}")
        # Leading word-boundary, open trailing end: anchors the start of the
        # phrase (no mid-word matches) but still catches plurals and -ing forms
        # ('sparse autoencoder' -> 'sparse autoencoders'). 'circuits' still
        # won't match 'circuitry' since that doesn't begin with 'circuits'.
        matched = [orig for norm, orig in norm_kws if f" {norm}" in haystack]
        if matched:
            if "topic" not in r["tags"]:
                r["tags"].append("topic")
            r["matched_keywords"] = matched
            hits.append(r)
    print(f"  keywords: {len(hits)} paper(s) matched the topic prefilter")
    return hits

"""Shared helpers: arXiv ID normalization and author-name matching.

These are the fiddly bits the spec calls out — version-stripping IDs so v1/v2
dedupe, and matching "F. Last" against "First Last" across diacritics.
"""

import re
import unicodedata

ARXIV_ABS = "https://arxiv.org/abs/{}"
ARXIV_PDF = "https://arxiv.org/pdf/{}"


def short_id(entry_id):
    """Normalize any arXiv reference to a bare, version-less ID.

    'http://arxiv.org/abs/2405.15943v2' -> '2405.15943'
    'arXiv:2502.01954'                  -> '2502.01954'
    """
    s = str(entry_id).strip()
    if "arxiv.org" in s:
        s = s.rsplit("/", 1)[-1]
    s = re.sub(r"^ar[Xx]iv:", "", s)
    s = re.sub(r"v\d+$", "", s)
    return s


def abs_url(arxiv_id):
    return ARXIV_ABS.format(arxiv_id)


def pdf_url(arxiv_id):
    return ARXIV_PDF.format(arxiv_id)


# --- Author-name matching -----------------------------------------------------

def _strip_diacritics(s):
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _norm_token(tok):
    """Casefold, strip diacritics, drop anything but letters."""
    tok = _strip_diacritics(tok)
    tok = re.sub(r"[^A-Za-z]", "", tok)
    return tok.casefold()


def _split_name(name):
    """Return (given, surname) normalized tokens. Handles 'Last, First'."""
    name = name.strip()
    if "," in name:
        last, _, first = name.partition(",")
        first, last = first.strip(), last.strip()
    else:
        parts = name.split()
        if len(parts) == 1:
            first, last = "", parts[0]
        else:
            first, last = parts[0], parts[-1]
    return _norm_token(first), _norm_token(last)


def names_match(a, b):
    """True if two names plausibly refer to the same person.

    Matches on surname plus a compatible given name, where 'compatible' means
    identical, OR one side is an initial of the other ('A. Shai' ~ 'Adam Shai').
    Surname must always match — this keeps precision high.
    """
    fa, la = _split_name(a)
    fb, lb = _split_name(b)
    if not la or not lb or la != lb:
        return False
    if not fa or not fb:        # only a surname on one side
        return True
    if fa == fb:
        return True
    # initial match: one given name is a single letter equal to the other's first
    return fa[0] == fb[0] and (len(fa) == 1 or len(fb) == 1)


def matched_watchlist_names(candidate_authors, watchlist):
    """Return the watchlist names that any of `candidate_authors` matches."""
    hits = []
    for w in watchlist:
        if any(names_match(w, ca) for ca in candidate_authors):
            hits.append(w)
    return hits

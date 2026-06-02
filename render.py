"""Render the ranked buckets into Markdown (the archived/attached artifact)
and into simple styled HTML (the email body).

Section order is fixed: trusted citation hits first, then watchlist authors,
then the scored topic matches. Empty sections are dropped entirely.
"""

import html
import re

SECTIONS = [
    ("cites", "⭐ Cites your anchor papers"),
    ("author", "👤 Watchlist authors"),
    ("topic", "🔍 Topic matches (scored)"),
]


def _format_authors(authors):
    authors = [a for a in authors if a]
    if not authors:
        return ""
    if len(authors) > 6:
        return ", ".join(authors[:6]) + ", et al."
    return ", ".join(authors)


def _meta_line(r, kind):
    parts = []
    if kind == "cites":
        parts += [f"`{t}`" for t in r["tags"] if t.startswith("cites:")]
    elif kind == "author":
        parts += [f"`{t}`" for t in r["tags"] if t.startswith("author:")]
    elif kind == "topic":
        parts.append("`topic`")
        scored = f"**{r['score']}/10**" if r.get("score") is not None else ""
        if r.get("reason"):
            scored = f"{scored} — {r['reason']}" if scored else r["reason"]
        if scored:
            parts.append(scored)
    if r.get("pdf_url"):
        parts.append(f"[PDF]({r['pdf_url']})")
    return " · ".join(parts)


def _entry(r, kind):
    authors = _format_authors(r["authors"])
    head = f"- **[{r['title']}]({r['abs_url']})**"
    if authors:
        head += f" — {authors}"
    return f"{head}\n  {_meta_line(r, kind)}"


def render_markdown(date_str, buckets):
    """buckets: {'cites': [...], 'author': [...], 'topic': [...]}"""
    total = sum(len(buckets.get(k, [])) for k, _ in SECTIONS)
    lines = [f"# arXiv Interpretability Radar — {date_str}", ""]

    summary = (f"_{total} paper(s): {len(buckets.get('cites', []))} citing your "
               f"anchors, {len(buckets.get('author', []))} by watchlist authors, "
               f"{len(buckets.get('topic', []))} topic match(es)._")
    lines += [summary, ""]

    if total == 0:
        lines += ["No new papers cleared the bar today. (That's the point — "
                  "precision over recall.)", ""]

    for key, title in SECTIONS:
        items = buckets.get(key, [])
        if not items:
            continue
        lines += [f"## {title}", ""]
        lines += [_entry(r, key) for r in items]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# --- Markdown -> HTML (tuned to the subset render_markdown emits) -------------

_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_CODE = re.compile(r"`([^`]+)`")


def _inline(s):
    s = html.escape(s)
    s = _CODE.sub(r"<code>\1</code>", s)
    s = _LINK.sub(r'<a href="\2">\1</a>', s)
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    return s


_STYLE = """
  body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       max-width:720px;margin:24px auto;padding:0 16px;color:#1a1a1a}
  h1{font-size:20px;border-bottom:2px solid #eee;padding-bottom:8px}
  h2{font-size:16px;margin-top:28px}
  ul{list-style:none;padding:0}
  li{margin:0 0 14px}
  .meta{color:#666;font-size:13px;margin-top:2px}
  code{background:#f4f4f4;padding:1px 5px;border-radius:3px;font-size:12px}
  a{color:#2563eb;text-decoration:none}
"""


def markdown_to_html(md):
    """Convert the digest Markdown to a standalone HTML document."""
    out, in_list, pending = [], False, None

    def close_list():
        nonlocal in_list, pending
        if pending is not None:
            out.append(pending + "</li>")
            pending = None
        if in_list:
            out.append("</ul>")
            in_list = False

    for line in md.splitlines():
        if line.startswith("# "):
            close_list()
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            close_list()
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("- "):
            if pending is not None:
                out.append(pending + "</li>")
                pending = None
            if not in_list:
                out.append("<ul>")
                in_list = True
            pending = f"<li>{_inline(line[2:])}"
        elif line.startswith("  ") and pending is not None:
            pending += f'<div class="meta">{_inline(line.strip())}</div>'
        elif line.strip().startswith("_") and line.strip().endswith("_") and len(line.strip()) > 1:
            close_list()
            out.append(f"<p><em>{_inline(line.strip()[1:-1])}</em></p>")
        elif line.strip():
            close_list()
            out.append(f"<p>{_inline(line.strip())}</p>")
    close_list()

    body = "\n".join(out)
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<style>{_STYLE}</style></head><body>\n{body}\n</body></html>")

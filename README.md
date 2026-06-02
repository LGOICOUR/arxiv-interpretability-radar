# arXiv Interpretability Radar

A small, durable, low-noise daily digest of new arXiv papers relevant to
**mechanistic interpretability** and **computational mechanics** — delivered by
email and archived as Markdown.

The design priority is **precision over recall**. Three to seven excellent
papers a day is the goal; fifty mediocre ones is a failure. The arXiv firehose
is already overwhelming — this tool exists to cut it down, not mirror it.

It runs two ways:

- **In GitHub Actions** on a daily schedule (the live path) — emails the digest
  and commits the archive + dedup state back to the repo.
- **Locally on macOS** for development and one-off runs (`--dry-run`, `--since`),
  with an optional launchd schedule.

## How it works

```
ingest (arXiv RSS: new submissions in cs.LG/cs.CL/cs.AI/stat.ML)
   │
   ├── citation path ── Semantic Scholar: papers citing the ANCHORS (last N days)
   │
   ├── author path ──── exact match against the watchlist → HIGH precision, skip scoring
   │
   └── keyword path ─── title/abstract keyword prefilter → MEDIUM precision
                              │
                        LLM relevance scoring (Claude) → keep score ≥ threshold
   │
merge + dedup (SQLite of seen IDs) → rank → render Markdown → deliver (email + file)
```

Three signal paths feed one ranked digest:

| Path | Signal | Trusted? |
|------|--------|----------|
| ⭐ **Citation** | Papers that cite your anchor papers (the belief-state-geometry line of work). The highest-signal feed. | Yes — ships unscored |
| 👤 **Author** | New papers by anyone on your watchlist (Simplex core, comp-mech foundations, frontier-lab interp). | Yes — ships unscored |
| 🔍 **Keyword** | Title/abstract keyword hits, then a Claude relevance pass against your rubric. | No — must clear the score threshold |

Only the broad keyword path goes through the Claude gate, because that's where
the noise lives. The author and citation paths are trusted by construction.

## Quick start (local)

```bash
git clone <this repo> && cd arxiv-interpretability-radar
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill in ANTHROPIC_API_KEY (see below)

# Dry run over the last week — prints the digest, sends nothing:
python main.py --dry-run --since 168
```

Flags:

| Flag | Effect |
|------|--------|
| `--dry-run` | Print the digest to stdout; no email, no dedup write |
| `--since HOURS` | Override the ingest lookback (e.g. `--since 168` for a week) |
| `--no-email` | Write files but skip the email |
| `--reset-db` | Wipe the dedup DB first (re-test from a clean slate) |

The citation and author paths need **no API key** — only the keyword path's
relevance scoring calls Claude. Without `ANTHROPIC_API_KEY` set, scoring is
skipped with a warning and the trusted paths still ship.

## Configuration

Everything tunable lives in [`config.yaml`](config.yaml):

- **`anchors`** — the single highest-signal feed. Papers citing these ship
  unscored. Keep these three accurate; add one whenever a paper lands squarely
  in your lane.
- **`authors`** — the watchlist, lifted from your author map. New names from
  each digest: add. Names you stop caring about: delete.
- **`keywords`** — the topic prefilter. Case-insensitive, matched at word
  starts so plurals/`-ing` forms are caught (`sparse autoencoder` →
  `sparse autoencoders`). The `ε-machine` / `epsilon-machine` / `epsilon machine`
  variants all fold together.
- **`score_threshold`** — keyword-path papers must score ≥ this (0–10). Starts
  at **6**. Keep it high for the first week, then lower one notch if you feel
  you're missing things. Over-filtering is the safer failure here.
- **`score_model`** — `claude-sonnet-4-6` by default (precision matters and the
  volume is a few cents/day). Swap to `claude-haiku-4-5-20251001` to make it
  nearly free.
- **`citation_lookback_days`** — wider than the ingest window (default 30),
  because Semantic Scholar's citation graph lags arXiv by weeks.

## The relevance rubric

The scoring prompt (in [`score.py`](score.py)) asks Claude to score, 0–10, how
much *this specific researcher* — mechanistic interpretability through a
computational-mechanics lens, neuroscience background — would want to read each
paper:

- **HIGH (7–10):** belief-state geometry / predictive-state representations;
  computational mechanics, ε-machines, mixed-state presentations; transformer
  internal geometry (residual stream, what's linearly encoded); SAE /
  superposition / polysemanticity *foundations and critiques* (not "we trained
  an SAE"); singular learning theory / developmental interp; genuine
  neuroscience↔ML representation bridges.
- **LOW (0–3):** benchmark-chasing with no mechanistic claim; prompt-engineering
  / RAG / agent scaffolding; release notes & system cards; applied fine-tuning;
  fairness/policy with no internals; generic "we built an LLM for X."

Claude returns strict JSON (`{"score", "reason", "tags"}`); anything that fails
to parse or clear the threshold is dropped and logged.

## Delivery & scheduling

### GitHub Actions (the live path)

[`.github/workflows/radar.yml`](.github/workflows/radar.yml) runs daily at
**14:00 UTC (≈7am Pacific)** and on the manual "Run workflow" button. It:

1. runs the pipeline (`python main.py --no-email`),
2. emails the digest via [`dawidd6/action-send-mail`](https://github.com/dawidd6/action-send-mail)
   over Gmail SMTP (same mechanism as the eb-rank ranker),
3. commits the dated digest + dedup DB back to `main` so the cloud run
   remembers what it has already sent.

> The workflow has **no `push` trigger** on purpose — it commits state back to
> `main`, which would otherwise re-trigger itself in a loop. Use the
> `workflow_dispatch` button (also on the GitHub mobile app) to run on demand.

**Repository secrets** (Settings → Secrets and variables → Actions):

| Secret | Required | Notes |
|--------|----------|-------|
| `ANTHROPIC_API_KEY` | yes | Relevance scoring. A few cents/day. |
| `GMAIL_APP_PASSWORD` | yes | A 16-char Gmail [App Password](https://myaccount.google.com/apppasswords) (needs 2FA). Same one the eb-rank ranker uses. |
| `SEMANTIC_SCHOLAR_API_KEY` | no | Raises citation-path rate limits. Works without it. |

```bash
gh secret set ANTHROPIC_API_KEY
gh secret set GMAIL_APP_PASSWORD
# optional:
gh secret set SEMANTIC_SCHOLAR_API_KEY
```

Sender/recipient (`luis.goicouria@gmail.com`) are in the workflow file — edit
there for a different inbox.

### launchd (optional local alternative)

[`deploy/com.luisgoicouria.arxiv-radar.plist`](deploy/com.luisgoicouria.arxiv-radar.plist)
schedules a local 07:00 run. Use **either** Actions **or** launchd — running
both means two emails a day and two diverging dedup DBs.

```bash
cp deploy/com.luisgoicouria.arxiv-radar.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.luisgoicouria.arxiv-radar.plist
launchctl start com.luisgoicouria.arxiv-radar   # run once now to test
```

For a local run to email, set `GMAIL_APP_PASSWORD` in `.env` — `deliver.py`
sends over Gmail SMTP itself (the Actions path uses the send-mail action
instead).

## Files

| File | Role |
|------|------|
| `config.yaml` | **The file you'll edit** — anchors, authors, keywords, threshold |
| `main.py` | Orchestrator + CLI flags |
| `ingest.py` | arXiv RSS feeds → normalized records (requests + stdlib XML) |
| `citations.py` | Semantic Scholar citers of each anchor |
| `filter.py` | Author + keyword matching (handles `F. Last` and ε-machine variants) |
| `score.py` | Claude relevance gate (keyword path only) |
| `render.py` | Markdown digest + email HTML |
| `deliver.py` | Write the dated `.md`; send email locally |
| `store.py` | JSON dedup store (`data/seen.json`) |
| `util.py` | arXiv-ID + author-name normalization |
| `.github/workflows/radar.yml` | Cloud scheduler + Gmail sender + state commit-back |
| `digests/YYYY-MM-DD.md` | The committed archive of every day's digest |
| `data/seen.json` | Dedup store (committed so the cloud run has memory) |

## Notes & tradeoffs

- **Why commit `data/seen.json` back?** GitHub's runners are ephemeral, so
  dedup state has to live somewhere persistent. It's a small, sorted JSON file,
  so each day's commit is a clean text diff (just the new IDs) and the cloud run
  stays the single source of truth — no binary churn in the public history.
- **Why RSS, not the export query API?** The export query API
  (`export.arxiv.org/api/query`) aggressively returns HTTP 429 to bursty and
  cloud IPs — it blocks GitHub Actions runners outright, which silently zeroed
  the author + keyword paths. The per-category RSS feeds (`rss.arxiv.org`) are
  CDN-served, not rate-limited, and are exactly arXiv's "new submissions" feed.
  Ingest keeps `new`/`cross` announcements (skips `replace` revisions) within
  the lookback window. One consequence: RSS exposes the latest announcement
  batch, so `--since` filters within it rather than paging arbitrarily far back.
- **Weekend digests are thin** — arXiv doesn't announce on weekends, so a
  Monday run is naturally short. The citation path (30-day window) still fires.

## Roadmap (stretch goals)

- Weekly rollup (Sunday) aggregating the week's top scores from SQLite.
- Atom/RSS output alongside email.
- Slack webhook delivery.
- Cross-link each paper to its alphaXiv page.

*(Deliberately **not** building an embedding/semantic-search pipeline — the
Claude relevance pass replaces it. Keep this small.)*

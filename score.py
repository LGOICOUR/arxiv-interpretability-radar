"""Claude relevance gate — runs ONLY over keyword-path candidates.

The author and citation paths are trusted and skip this entirely. Here we ask
Claude to score how much *this specific researcher* wants to read each paper,
parse strict JSON, and keep only those at/above the threshold. Anything that
fails to parse or score is dropped (and logged) — precision over recall.
"""

import json
import os
import re

SYSTEM = """\
You are screening brand-new arXiv papers for a researcher whose focus is \
mechanistic interpretability viewed through a computational-mechanics lens, \
with a neuroscience background. Score how much this specific researcher would \
want to read each paper, 0-10.

Score HIGH (7-10): belief-state geometry / predictive-state representations; \
computational mechanics, epsilon-machines, mixed-state presentations; the \
internal representations and geometry of transformers (residual stream \
structure, what's linearly encoded); theory and critique of sparse \
autoencoders, superposition, and polysemanticity (foundations, failure modes \
- not just "we trained an SAE"); singular learning theory / developmental \
interpretability; anything genuinely bridging neuroscience and ML \
representations.

Score LOW (0-3): benchmark-chasing with no mechanistic claim; \
prompt-engineering / RAG / agent scaffolding; model-release notes and system \
cards; applied fine-tuning; fairness/policy pieces with no internals; generic \
"we built an LLM for X."

Middle scores for adjacent interpretability that isn't squarely in the above.

Return only this JSON, nothing else: \
{"score": <int 0-10>, "reason": "<=20 words on why it matters to THIS \
researcher>", "tags": ["..."]}"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse(text):
    """Pull the JSON object out of the model's reply, tolerating code fences."""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if "score" not in obj:
        return None
    try:
        obj["score"] = int(obj["score"])
    except (TypeError, ValueError):
        return None
    return obj


def score_papers(records, threshold, model, api_key=None):
    """Score each record; return only those meeting the threshold."""
    if not records:
        return []

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(f"  ! ANTHROPIC_API_KEY not set — skipping {len(records)} "
              f"keyword candidate(s) (trusted paths still ship)")
        return []

    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)

    kept, dropped, errored = [], 0, 0
    for i, r in enumerate(records, 1):
        user = f"Title: {r['title']}\n\nAbstract: {r['abstract']}"
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=300,
                temperature=0,
                system=SYSTEM,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in msg.content if b.type == "text")
        except Exception as e:
            errored += 1
            print(f"  ! scoring error on {r['id']} ({type(e).__name__}: {e})")
            continue

        obj = _parse(text)
        if obj is None:
            dropped += 1
            print(f"  ! unparseable score for {r['id']}; dropped")
            continue

        if obj["score"] >= threshold:
            r["score"] = obj["score"]
            r["reason"] = obj.get("reason", "")
            r["model_tags"] = obj.get("tags", [])
            kept.append(r)
        else:
            dropped += 1

    print(f"  scored {len(records)} -> kept {len(kept)} (>= {threshold}), "
          f"dropped {dropped}, errored {errored}")
    return kept

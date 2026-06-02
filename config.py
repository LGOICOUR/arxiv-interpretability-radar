"""Config loading: reads config.yaml and loads .env into the environment.

Secrets never live in config.yaml — they come from environment variables
(.env locally, encrypted repository secrets in GitHub Actions). This module
just makes sure .env is loaded and hands back the YAML as a plain dict, plus
the canonical filesystem paths the rest of the pipeline writes to.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"
SEEN_PATH = DATA_DIR / "seen.json"
DIGESTS_DIR = PROJECT_ROOT / "digests"

# Load .env at import, with the file authoritative locally (override=True) so a
# blank/stale shell var — e.g. an empty ANTHROPIC_API_KEY injected by an editor's
# terminal — can't shadow the real value in .env. In CI there is NO .env file
# (it's gitignored), so load_dotenv is a no-op there and the workflow-injected
# repository secrets are used untouched.
load_dotenv(PROJECT_ROOT / ".env", override=True)


def load():
    """Return the parsed config.yaml as a dict, with env-derived overrides."""
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    # DIGEST_TO env var overrides the committed default.
    cfg["digest_to"] = os.environ.get("DIGEST_TO", cfg.get("digest_to", ""))
    return cfg

#!/usr/bin/env bash
# One-command deploy of this repo to a Hugging Face Docker Space.
#
# Prerequisites (once):
#   pip install -U huggingface_hub          # provides the `hf` CLI
#   hf auth login                           # write-scope token
#   export TOKEN_FACTORY_API_KEY=...        # or have it in ./.env (never committed)
#
# Usage:
#   HF_SPACE=<user-or-org>/invisu-preservation ./deploy_space.sh
#   ./deploy_space.sh <user-or-org>/invisu-preservation
#
# What it does: creates the Space (Docker SDK) if missing, uploads the working
# tree (no .git, no .env), sets TOKEN_FACTORY_API_KEY as a Space secret, prints
# the URL. The Space builds the Dockerfile and serves on port 7860.
set -euo pipefail
cd "$(dirname "$0")"

SPACE="${1:-${HF_SPACE:-}}"
if [ -z "$SPACE" ]; then
  echo "usage: HF_SPACE=<user-or-org>/invisu-preservation $0   (or pass it as the first argument)" >&2
  exit 1
fi

KEY="${TOKEN_FACTORY_API_KEY:-}"
if [ -z "$KEY" ] && [ -f .env ]; then
  KEY="$(grep -m1 '^TOKEN_FACTORY_API_KEY=' .env | cut -d= -f2- | tr -d '"\r' || true)"
fi

if ! command -v hf >/dev/null 2>&1; then
  echo "hf CLI not found: pip install -U huggingface_hub" >&2
  exit 1
fi
hf auth whoami >/dev/null 2>&1 || { echo "not logged in: run 'hf auth login' first" >&2; exit 1; }

echo "== create Space $SPACE (docker) if missing"
hf repo create "$SPACE" --repo-type space --space-sdk docker --exist-ok 2>/dev/null \
  || hf repo create "$SPACE" --repo-type space --space_sdk docker 2>/dev/null \
  || echo "   (create skipped — Space may already exist)"

echo "== upload working tree"
hf upload "$SPACE" . . --repo-type space \
  --exclude ".git/*" --exclude ".env" --exclude "__pycache__/*" --exclude "*/__pycache__/*" \
  --exclude "*.pyc" --exclude "runs/*" --exclude "*.log" \
  --commit-message "deploy $(date -u +%Y-%m-%dT%H:%MZ)"

if [ -n "$KEY" ]; then
  echo "== set Space secret TOKEN_FACTORY_API_KEY"
  HF_SPACE_ID="$SPACE" TF_KEY="$KEY" python - <<'EOF'
import os
from huggingface_hub import add_space_secret
add_space_secret(os.environ["HF_SPACE_ID"], "TOKEN_FACTORY_API_KEY", os.environ["TF_KEY"])
print("   secret set")
EOF
else
  echo "== no TOKEN_FACTORY_API_KEY in env or .env — the Space will run index-only until the secret is set"
fi

echo "== done: https://huggingface.co/spaces/$SPACE  (first build takes a few minutes)"

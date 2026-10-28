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
hf repo create "$SPACE" --repo-type space --space-sdk docker 
  || echo "   (create skipped - the Space already exists)"

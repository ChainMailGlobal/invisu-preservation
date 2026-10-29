#!/usr/bin/env bash
# Deploy the static demo to a free Hugging Face STATIC Space.
# (Docker Spaces need a paid plan; the Dockerfile here is for running the full
#  app with Nemotron anywhere else.)
#
# Prerequisites (once):
#   pip install -U huggingface_hub          # provides the `hf` CLI
#   hf auth login                           # write-scope token
#
# Usage:
#   ./deploy_space.sh                       # -> CRE808iVE/invisu-preservation
#   ./deploy_space.sh <user-or-org>/<space>
#   HF_SPACE=<user-or-org>/<space> ./deploy_space.sh
#   PROJECT_DIR=data/<set> SITE_DIR=site_<set> ./deploy_space.sh <user>/<space>   # a second set
#
# Steps: export site/ from data/ (no model calls) -> create the Space if missing
# -> upload site/ replacing everything on the Space -> print the URLs.
set -euo pipefail
cd "$(dirname "$0")"

SPACE="${1:-${HF_SPACE:-CRE808iVE/invisu-preservation}}"
command -v hf >/dev/null 2>&1 || { echo "hf CLI not found: pip install -U huggingface_hub" >&2; exit 1; }
hf auth whoami >/dev/null 2>&1 || { echo "not logged in: run 'hf auth login' first" >&2; exit 1; }

PROJECT_DIR="${PROJECT_DIR:-data/iolani-palace}"
SITE_DIR="${SITE_DIR:-site}"
echo "== export $SITE_DIR/ from $PROJECT_DIR/ (no model calls)"
python -m preservation.export_static "$PROJECT_DIR" --out "$SITE_DIR"

echo "== create static Space $SPACE if missing"
hf repo create "$SPACE" --repo-type space --space-sdk static || echo "   (create skipped - the Space already exists)"

echo "== upload site/ (replaces everything on the Space)"
# python API rather than `hf upload --delete "*"`: Git Bash expands the glob into the cwd file list
HF_SPACE_ID="$SPACE" SITE_DIR="$SITE_DIR" python - <<'PY'
import os, time
from huggingface_hub import HfApi
HfApi().upload_folder(folder_path=os.environ["SITE_DIR"], repo_id=os.environ["HF_SPACE_ID"], repo_type="space",
                      commit_message=time.strftime("deploy %Y-%m-%dT%H:%MZ", time.gmtime()),
                      delete_patterns=["*.json", "*.png", "*.html", "*.md", "pages/*", "thumbs/*", "view/*"])
PY

HOST="$(echo "$SPACE" | tr '[:upper:]' '[:lower:]' | tr '/' '-')"
echo "== done"
echo "   Space:  https://huggingface.co/spaces/$SPACE"
echo "   Page:   https://$HOST.static.hf.space/"

"""deploy_live_space — put the full app, model calls included, on a Hugging Face Docker Space.

The static Spaces (deploy_space.sh) are index search over exported JSON with no
model call. A Docker Space runs app/server.py itself: NVIDIA Nemotron 3 Ultra on
Nebius Token Factory answers each question live, with the receipts verified in
code, exactly as the local app does. Docker Spaces need a Hugging Face PRO
account; CPU basic hardware is enough (the model runs on Nebius, not here).

Prerequisites (once):
  pip install -U huggingface_hub          # the Hub client
  hf auth login                           # write-scope token
  TOKEN_FACTORY_API_KEY in .env           # uploaded as a Space SECRET, never printed

Usage:
  python tools/deploy_live_space.py CRE808iVE/invisu-ask-the-sheet --project data/iolani-palace --cap 60
  python tools/deploy_live_space.py CRE808iVE/invisu-ask-lahaina --project data/lahaina-courthouse --cap 40 \
      --duplicate-from CRE808iVE/invisu-ask-the-sheet     # server-side copy, no second upload

What it does, in order:
  1. create the Space (sdk docker) if missing
  2. secret TOKEN_FACTORY_API_KEY + variables (PROJECT_DIR, AGENT_THINKING=auto,
     AGENT_MAX_TOKENS=4000, ASK_DAILY_CAP=<cap>, ASK_CONCURRENCY=2)
  3. one commit holding exactly `git ls-files` at HEAD (so the Space equals the
     public repository) plus a README with the Space front matter; .env, runs/,
     site*/ are never tracked, so they are never uploaded
  4. wait until the Space reports RUNNING, then GET /api/health through the public URL

The per-day cap is the public demo's budget guard (app/server.py ASK_DAILY_CAP);
the local app has none.
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from preservation import tokenfactory as tf  # noqa: E402

SKIP_PREFIXES = ("site/", "site_", "runs/", ".github/")


def space_readme(title: str, project: str) -> bytes:
    body = (ROOT / "README.md").read_text(encoding="utf-8")
    short = f"Ask a Library of Congress drawing set; get the sheet ({project})"[:60]
    front = (
        "---\n"
        f"title: {json.dumps(title)}\n"
        "emoji: \U0001f4d0\n"
        "colorFrom: gray\n"
        "colorTo: blue\n"
        "sdk: docker\n"
        "app_port: 7860\n"
        "pinned: false\n"
        "license: mit\n"
        f"short_description: {json.dumps(short)}\n"
        "---\n\n"
        "> **Live app.** Every question here is answered by NVIDIA Nemotron 3 Ultra on Nebius Token Factory,\n"
        "> with the receipts verified in code. The public demo answers a capped number of questions per day;\n"
        "> the repository below runs without a cap: https://github.com/ChainMailGlobal/invisu-preservation\n\n"
    )
    return (front + body).encode("utf-8")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    files = [f for f in out.decode("utf-8").split("\0") if f]
    return [f for f in files if f != "README.md" and not f.startswith(SKIP_PREFIXES)]


def head_sha() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()


def public_url(space: str) -> str:
    return "https://" + space.lower().replace("/", "-") + ".hf.space"


def wait_running(api: HfApi, space: str, timeout_s: int) -> str:
    t0, last = time.time(), None
    while time.time() - t0 < timeout_s:
        rt = api.get_space_runtime(space)
        stage = str(rt.stage)
        if stage != last:
            print(f"   {time.strftime('%H:%M:%S')} stage {stage}", flush=True)
            last = stage
        if stage.endswith("RUNNING"):
            return stage
        if "ERROR" in stage:
            raise SystemExit(f"Space entered {stage}; read the build logs on the Space page")
        time.sleep(20)
    raise SystemExit(f"Space not RUNNING after {timeout_s}s (last stage {last})")


def health(space: str) -> dict:
    with urllib.request.urlopen(public_url(space) + "/api/health", timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("space", help="<user-or-org>/<space>")
    ap.add_argument("--project", default="data/iolani-palace", help="set directory inside the repo")
    ap.add_argument("--cap", type=int, default=60, help="model calls per UTC day on the public demo")
    ap.add_argument("--title", default=None)
    ap.add_argument("--duplicate-from", default=None,
                    help="copy an existing Space server-side instead of uploading the repo again")
    ap.add_argument("--timeout", type=int, default=1200, help="seconds to wait for RUNNING")
    ap.add_argument("--no-wait", action="store_true")
    a = ap.parse_args()

    project_dir = (ROOT / a.project).resolve()
    if not (project_dir / "index.db").exists():
        raise SystemExit(f"no index.db in {project_dir}")
    pj = project_dir / "project.json"
    set_name = json.loads(pj.read_text(encoding="utf-8")).get("name", project_dir.name) if pj.exists() \
        else project_dir.name
    title = a.title or f"Ask the Sheet, {set_name.split(' (')[0]}"
    key = tf.api_key()  # raises NoApiKey when absent; the value is never printed
    variables = {
        "PROJECT_DIR": f"/app/{a.project.strip('/')}",
        "AGENT_THINKING": "auto",
        "AGENT_MAX_TOKENS": "4000",
        "ASK_DAILY_CAP": str(a.cap),
        "ASK_CONCURRENCY": "2",
    }

    api = HfApi()
    who = api.whoami()["name"]
    print(f"== Hub user {who}; Space {a.space}; set '{set_name}' from {a.project}; cap {a.cap}/day")

    if a.duplicate_from:
        print(f"== duplicate {a.duplicate_from} -> {a.space} (server-side)")
        api.duplicate_space(a.duplicate_from, a.space, exist_ok=True, hardware="cpu-basic",
                            variables=[{"key": k, "value": v} for k, v in variables.items()],
                            secrets=[{"key": "TOKEN_FACTORY_API_KEY", "value": key}])
        print("== Space README with this set's title")
        api.upload_file(path_or_fileobj=io.BytesIO(space_readme(title, a.project)), path_in_repo="README.md",
                        repo_id=a.space, repo_type="space", commit_message=f"README for {set_name}")
    else:
        print("== create the Space if missing (sdk docker)")
        api.create_repo(a.space, repo_type="space", space_sdk="docker", exist_ok=True)
        print("== secret TOKEN_FACTORY_API_KEY + variables")
        api.add_space_secret(a.space, "TOKEN_FACTORY_API_KEY", key)
        for k, v in variables.items():
            api.add_space_variable(a.space, k, v)
        files = tracked_files()
        sha = head_sha()
        print(f"== one commit: {len(files)} tracked files at {sha} + Space README")
        ops = [CommitOperationAdd(path_in_repo=f, path_or_fileobj=str(ROOT / f)) for f in files]
        ops.append(CommitOperationAdd(path_in_repo="README.md",
                                      path_or_fileobj=io.BytesIO(space_readme(title, a.project))))
        api.create_commit(repo_id=a.space, repo_type="space", operations=ops,
                          commit_message=f"deploy {sha} ({set_name}, cap {a.cap}/day)")

    print(f"== Space:  https://huggingface.co/spaces/{a.space}")
    print(f"== App:    {public_url(a.space)}/")
    if a.no_wait:
        return
    print("== waiting for the build (CPU basic, pip install + 90 MB of pages)")
    wait_running(api, a.space, a.timeout)
    for attempt in range(6):
        try:
            h = health(a.space)
            break
        except Exception as e:  # the container answers a little after RUNNING
            print(f"   health not up yet ({type(e).__name__}); retry in 15 s")
            time.sleep(15)
    else:
        raise SystemExit("RUNNING but /api/health never answered")
    print("== /api/health:", json.dumps({k: h.get(k) for k in
                                         ("ok", "pages", "index", "model", "provider", "model_callable",
                                          "model_note", "daily_cap", "asks_today")}, indent=1))
    if not h.get("model_callable"):
        raise SystemExit("the Space cannot call the model: check the secret")
    print("== live")


if __name__ == "__main__":
    main()

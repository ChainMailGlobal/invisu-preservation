"""photo_index — caption and classify a set's photographs with the vision model.

HABS/HAER records include survey photographs. Per photo the model is asked:
exterior/interior/detail/document, the subject, the view, how much of the
subject is visible, a quality score and a one-sentence caption. The result
(<project>/photos.json) is indexed as searchable text per photo page, so
"which photographs show the throne room" has receipts too.

Usage: python -m preservation.photo_index <project_dir> [--kind photo]
                                           [--thinking auto|off|on] [--limit N]
Already-captioned pages are skipped; delete photos.json to redo everything.
"""
from __future__ import annotations

import argparse
import base64
import glob
import io
import json
import os
import sys

from . import tokenfactory as tf
from .read_scans import parse_json, thinking_extra

PROMPT = (
    "This is a photograph from a historic building survey. Return STRICT JSON, "
    "no prose:\n"
    '  "kind": "exterior" | "interior" | "detail" | "document",\n'
    '  "subject": short name of what is shown (e.g. "main facade", "throne room", '
    '"staircase", "cornice detail"),\n'
    '  "view": for exterior: which side/angle if inferable ("front", "rear", '
    '"left side", "right side", "corner", "oblique"); for interior: the room,\n'
    '  "coverage": "whole building" | "most of building" | "partial" | "close-up",\n'
    '  "quality": 1-5 integer, how clear and well-framed the photo is,\n'
    '  "caption": one sentence describing it.'
)


def b64(path, edge=1100):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if max(im.size) > edge:
        im.thumbnail((edge, edge))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--kind", default="photo")
    ap.add_argument("--thinking", choices=["auto", "off", "on"], default="auto")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    pdir = os.path.abspath(a.project_dir)
    out_path = os.path.join(pdir, "photos.json")
    rows = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else []
    done = {r["page"] for r in rows}
    pages = sorted(int(os.path.basename(p).split(".")[0])
                   for p in glob.glob(os.path.join(pdir, "*.png")))
    n = 0
    try:
        for pg in pages:
            if pg in done:
                continue
            sj = os.path.join(pdir, f"{pg}.scene.json")
            s = json.load(open(sj, encoding="utf-8")) if os.path.exists(sj) else {}
            if a.kind != "any" and s.get("kind") != a.kind:
                continue
            if a.limit and n >= a.limit:
                break
            n += 1
            messages = [{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{b64(os.path.join(pdir, f'{pg}.png'))}"}}]}]
            reply, err = tf.chat(tf.EYES, messages, max_tokens=600, temperature=0,
                                 extra=thinking_extra(a.thinking), purpose=f"photo {pg}")
            if err:
                print(f"[{pg}] ERROR {err}", flush=True)
                continue
            d = parse_json(reply["text"])
            if not d:
                print(f"[{pg}] unparseable: {reply['text'][:120]!r}", flush=True)
                continue
            d["page"] = pg
            rows.append(d)
            json.dump(rows, open(out_path, "w", encoding="utf-8"), indent=1)
            print(f"[{pg}] {str(d.get('kind')):9} {str(d.get('subject'))[:34]:34} "
                  f"q{d.get('quality')}  {reply['usage'].get('prompt_tokens', 0)} in / "
                  f"{reply['usage'].get('completion_tokens', 0)} out", flush=True)
    except (tf.CreditsExhausted, tf.SpendCapReached, tf.NoApiKey) as e:
        print(f"STOP: {e}")
        sys.exit(2)
    print(f"DONE captioned={len(rows)}")
    print(tf.cost_line())


if __name__ == "__main__":
    main()

"""export_static — write the demo as static files for a free static host.

Produces <out>/ (default site/):
  index.html          the same UI as the FastAPI app; it detects the static host
  README.md           Hugging Face Space front matter (sdk: static)
  set.json            what GET /api/set returns (page urls made relative)
  pages/PG-NN.json    what GET /api/page/PG-NN returns, for every page
  texts.json          every texts row: {sheet, text, bbox, src}
  refs.json           typed references and the cross-reference check
  thumbs/N.png        220 px thumbnails          (from <project>/thumbs)
  view/N.png          2400 px sheet renditions   (from <project>/view)
  pages/N.png         full-resolution pages — kept while the whole site stays
                      under 150 MB and every file under 10 MB; otherwise the
                      sheets' full-res files are dropped and "full resolution"
                      points at the view rendition

In the static build "Ask" makes no model call: the browser searches texts.json
with the same rules as the server and labels the outcome MODEL_UNAVAILABLE.

Usage: python -m preservation.export_static [project_dir] [--out site] [--no-fullres]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import time
from pathlib import Path

from preservation import archive
from preservation import tokenfactory as tf
from app.server import page_payload, page_rows

ROOT = Path(__file__).resolve().parent.parent
STATIC_NOTE = "static demo: no model call — Nemotron runs in the local app and the video"
SITE_LIMIT = 150_000_000
FILE_LIMIT = 10_000_000

SPACE_README = """---
title: iNViSU Preservation Reader
emoji: 🏛️
colorFrom: gray
colorTo: indigo
sdk: static
pinned: false
license: mit
short_description: Ask a Library of Congress drawing set. Get the sheet.
---

# iNViSU Preservation Reader — static demo

The Iolani Palace set (Library of Congress HABS No. HI-1, loc.gov record
hi0047): 85 pages, every page's text, typed cross-references, search in the
browser. This static build makes no model call; in the full app
(https://github.com/ChainMailGlobal/invisu-preservation) NVIDIA
Nemotron-3.5-Super-VL reads the scanned sheets and Nemotron-3-Ultra answers
questions with page receipts, both through Nebius Token Factory.

Deep links: `#PG-14` selects a page, `?q=throne%20room` runs a search.
"""


def _copy(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copyfile(src, dst)
    return src.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir", nargs="?", default=str(ROOT / "data" / "iolani-palace"))
    ap.add_argument("--out", default=str(ROOT / "site"))
    ap.add_argument("--no-fullres", action="store_true")
    a = ap.parse_args()
    pdir, out = Path(a.project_dir).resolve(), Path(a.out).resolve()
    db = pdir / "index.db"
    if not db.exists():
        raise SystemExit(f"no index at {db} — run build_index first")
    conn = sqlite3.connect(str(db))
    (out / "pages").mkdir(parents=True, exist_ok=True)

    pages = page_rows(conn)
    total = 0
    for p in pages:
        n = p["page"]
        total += _copy(pdir / "thumbs" / f"{n}.png", out / "thumbs" / f"{n}.png")
        total += _copy(pdir / "view" / f"{n}.png", out / "view" / f"{n}.png")
    # pages with no view rendition (photos, PDF pages) need their full file anyway
    need_full = [p for p in pages if not (pdir / "view" / f"{p['page']}.png").exists()]
    for p in need_full:
        total += _copy(pdir / f"{p['page']}.png", out / "pages" / f"{p['page']}.png")
    sheets_full = [p for p in pages if p not in need_full]
    full_bytes = sum((pdir / f"{p['page']}.png").stat().st_size for p in sheets_full)
    include_full = (not a.no_fullres and total + full_bytes <= SITE_LIMIT
                    and all((pdir / f"{p['page']}.png").stat().st_size <= FILE_LIMIT
                            for p in sheets_full))
    if include_full:
        for p in sheets_full:
            total += _copy(pdir / f"{p['page']}.png", out / "pages" / f"{p['page']}.png")
    else:
        for p in sheets_full:
            (out / "pages" / f"{p['page']}.png").unlink(missing_ok=True)

    for p in pages:
        n = p["page"]
        p["thumb_url"] = f"thumbs/{n}.png"
        has_view = (out / "view" / f"{n}.png").exists()
        p["view_url"] = f"view/{n}.png" if has_view else f"pages/{n}.png"
        p["image_url"] = f"pages/{n}.png" if (out / "pages" / f"{n}.png").exists() else p["view_url"]

    pj = pdir / "project.json"
    name = json.loads(pj.read_text(encoding="utf-8")).get("name", pdir.name) if pj.exists() else pdir.name
    set_payload = dict(name=name, summary=archive.summary(conn), pages=pages,
                       issues=[m for (m,) in conn.execute("SELECT message FROM issues")],
                       model=tf.BRAIN, provider=tf.PROVIDER, **{"eyes": tf.EYES, "eyes_provider": tf.PROVIDER, **archive.eyes_provenance(pdir)}, model_note=STATIC_NOTE, mode="static",
                       exported=time.strftime("%Y-%m-%dT%H:%M:%S"))
    (out / "set.json").write_text(json.dumps(set_payload), encoding="utf-8")

    for p in pages:
        payload = page_payload(conn, p["id"])
        (out / "pages" / f"{p['id']}.json").write_text(json.dumps(payload), encoding="utf-8")

    texts = [dict(sheet=s, text=t, bbox=[x1, y1, x2, y2], src=src) for s, t, x1, y1, x2, y2, src in
             conn.execute("SELECT sheet_no, text, x1, y1, x2, y2, src FROM texts ORDER BY rowid")]
    (out / "texts.json").write_text(json.dumps(texts), encoding="utf-8")
    refs = dict(refs=[dict(sheet=s, text=t, points_to=pt, bbox=[x1, y1, x2, y2]) for s, t, pt, x1, y1, x2, y2 in
                      conn.execute("SELECT sheet_no, text, points_to, x1, y1, x2, y2 FROM findings "
                                   "WHERE kind='ref' ORDER BY sheet_no")],
                issues=[dict(sheet=s, severity=sev, message=m) for s, sev, m in
                        conn.execute("SELECT sheet_no, severity, message FROM issues")])
    (out / "refs.json").write_text(json.dumps(refs), encoding="utf-8")

    shutil.copyfile(ROOT / "app" / "static" / "index.html", out / "index.html")
    (out / "README.md").write_text(SPACE_README, encoding="utf-8")

    files = [f for f in out.rglob("*") if f.is_file()]
    size = sum(f.stat().st_size for f in files)
    big = [f for f in files if f.stat().st_size > FILE_LIMIT]
    print(f"site: {len(files)} files, {size / 1e6:.1f} MB at {out}")
    print(f"  pages {len(pages)} · texts {len(texts)} · refs {len(refs['refs'])} · "
          f"full-res sheets {'included' if include_full else 'DROPPED (view used)'}")
    if big:
        print("  WARNING files over 10 MB:", ", ".join(str(f.relative_to(out)) for f in big))


if __name__ == "__main__":
    main()

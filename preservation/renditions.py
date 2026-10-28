"""renditions — browser-sized copies of the pages for the web app.

  <project>/thumbs/N.png   220 px wide, every page (the left-hand list)
  <project>/view/N.png     2400 px wide, only pages wider than that (the big
                           scanned sheets; photographs and PDF pages are served
                           as they are). Full resolution stays at /pages/N.png.

Usage: python -m preservation.renditions <project_dir> [--thumb 220] [--view 2400]
Idempotent: existing renditions are kept unless --force.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from PIL import Image


def render(src: Path, dst: Path, width: int) -> None:
    with Image.open(src) as im:
        if im.mode == "1":
            im = im.convert("L")
        elif im.mode not in ("L", "RGB"):
            im = im.convert("RGB")
        if im.width > width:
            h = max(1, round(im.height * width / im.width))
            im = im.resize((width, h), Image.LANCZOS)
        im.save(dst, "PNG", optimize=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--thumb", type=int, default=220)
    ap.add_argument("--view", type=int, default=2400)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    pdir = Path(a.project_dir)
    (pdir / "thumbs").mkdir(exist_ok=True)
    (pdir / "view").mkdir(exist_ok=True)
    pages = sorted((p for p in pdir.glob("*.png") if p.stem.isdigit()),
                   key=lambda p: int(p.stem))
    n_t = n_v = 0
    for p in pages:
        t = pdir / "thumbs" / p.name
        if a.force or not t.exists():
            render(p, t, a.thumb)
            n_t += 1
        with Image.open(p) as im:
            wide = im.width > a.view
        v = pdir / "view" / p.name
        if wide and (a.force or not v.exists()):
            render(p, v, a.view)
            n_v += 1
        print(f"{p.stem:>3} thumb{' view' if wide else ''}", flush=True)
    size = sum(f.stat().st_size for d in ("thumbs", "view") for f in (pdir / d).glob("*.png"))
    print(f"DONE thumbs={n_t} views={n_v} renditions total {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

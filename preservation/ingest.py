"""ingest — turn Library of Congress HABS/HAER source files into project pages.

A HABS/HAER record on loc.gov ships as: a caption PDF (index to photographs),
a data PDF (written historical report), the measured drawings as 1-bit TIFF
scans, and photographs as JPEG. This tool appends any of those to a project
folder as numbered pages (N.png + N.scene.json), numbered continuously across
files so cross-references span the whole set.

  * Vector PDF pages keep their own text layer: every word with its box,
    tagged src="text".
  * Raster scans (TIFF / JPEG / PNG) start with an EMPTY text layer; run
    read_scans.py afterwards to fill it with Nemotron-3.5-Super-VL.

Usage:
  python -m preservation.ingest <src> <project_dir> [--dpi 150] [--name "Display name"]
                                [--kind document|sheet|photo]
Prints "PAGES <n>" as the last line on success.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys


def empty_scene(w: float, h: float, kind: str) -> dict:
    return {"width": w, "height": h, "kind": kind, "title": None, "sheet_no": None,
            "spans": [], "bubbles": []}


def guess_kind(raw: bytes, path: str) -> str:
    if raw[:4] == b"%PDF":
        return "document"
    if raw[:4] in (b"II*\x00", b"MM\x00*"):
        return "sheet"            # HABS measured drawings arrive as TIFF
    return "photo"                # JPEG / PNG photographs


def add_pdf(raw: bytes, pdir: str, offset: int, dpi: int, kind: str) -> int:
    import fitz  # pymupdf
    doc = fitz.open(stream=raw, filetype="pdf")
    n = 0
    for i, page in enumerate(doc):
        pg = offset + i + 1
        scene = empty_scene(page.rect.width, page.rect.height, kind)
        for x0, y0, x1, y1, word, *_ in page.get_text("words"):
            word = word.strip()
            if word:
                scene["spans"].append([word, x0, y0, x1, y1, "text"])
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        pix.save(os.path.join(pdir, f"{pg}.png"))
        json.dump(scene, open(os.path.join(pdir, f"{pg}.scene.json"), "w",
                              encoding="utf-8"))
        n += 1
        print(f"page {pg} ({kind}, pdf) words={len(scene['spans'])}", flush=True)
    return n


def add_raster(raw: bytes, pdir: str, offset: int, kind: str) -> int:
    from PIL import Image, ImageSequence
    im = Image.open(io.BytesIO(raw))
    n = 0
    for i, frame in enumerate(ImageSequence.Iterator(im)):
        pg = offset + i + 1
        # 1-bit scans stay 1-bit (lossless, small); everything else goes RGB
        out = frame if frame.mode == "1" else frame.convert("RGB")
        out.save(os.path.join(pdir, f"{pg}.png"), optimize=True)
        json.dump(empty_scene(out.width, out.height, kind),
                  open(os.path.join(pdir, f"{pg}.scene.json"), "w", encoding="utf-8"))
        n += 1
        print(f"page {pg} ({kind}, {out.width}x{out.height}, pending eyes)", flush=True)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("project_dir")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--name", default=None)
    ap.add_argument("--kind", choices=["document", "sheet", "photo"], default=None)
    a = ap.parse_args()

    pdir = os.path.abspath(a.project_dir)
    os.makedirs(pdir, exist_ok=True)
    nums = [int(f.split(".")[0]) for f in os.listdir(pdir)
            if f.endswith(".png") and f.split(".")[0].isdigit()]
    offset = max(nums) if nums else 0
    raw = open(a.src, "rb").read()
    kind = a.kind or guess_kind(raw, a.src)

    if raw[:4] == b"%PDF":
        n = add_pdf(raw, pdir, offset, a.dpi, kind)
    elif raw[:4] in (b"II*\x00", b"MM\x00*") or raw[:2] == b"\xff\xd8" \
            or raw[:4] == b"\x89PNG":
        n = add_raster(raw, pdir, offset, kind)
    else:
        sys.exit("unsupported file type (need PDF, TIFF, JPEG or PNG)")

    pj = os.path.join(pdir, "project.json")
    meta = json.load(open(pj, encoding="utf-8")) if os.path.exists(pj) \
        else {"name": a.name or os.path.basename(pdir), "sources": []}
    if a.name:
        meta["name"] = a.name
    meta["sources"].append({"file": os.path.basename(a.src), "pages": n,
                            "offset": offset, "kind": kind})
    json.dump(meta, open(pj, "w", encoding="utf-8"), indent=1)
    print(f"PAGES {n}")


if __name__ == "__main__":
    main()

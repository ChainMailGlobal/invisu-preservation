"""read_scans — read scanned HABS/HAER sheets with Nemotron-3.5-Super-VL (Token Factory).

For every page in a project whose text layer is empty (the measured drawings
arrive as 1-bit TIFF scans with no text), send the rendered page to the vision
model and get back STRICT JSON: a title, a 2-4 sentence description, and every
legible piece of text with a rough box. Transcriptions land in N.scene.json as
spans tagged src="eyes" (then build_index -> search -> agent); descriptions
accumulate in <project>/context.txt.

Usage:
  python -m preservation.read_scans <project_dir>
         [--only N] [--limit N] [--edge 1400] [--thinking auto|off|on]
         [--kind sheet|any] [--tiles] [--force]

--only N      read exactly page N (re-reads even if it already has text)
--edge        longest side of the image sent to the model, px (default 1400)
--thinking    auto = send no chat_template_kwargs; off/on = enable_thinking flag
--tiles       second pass: re-read already-read pages in four higher-res
              quadrants and merge new finds (costs 4 calls per page)
--max-tokens  completion ceiling per call (default 4000)
--rep-penalty vLLM repetition_penalty (e.g. 1.05). Needed on the self-served
              Nemotron 3 Nano Omni endpoint: at temperature 0 it locked into
              repeating one dimension string ("11'-8\"" x80) on sheet 11 until
              it hit the ceiling. A loop guard also cuts any run of 6+
              identical consecutive texts and records read.loop_cut_at.
Stops with exit code 2 if Token Factory returns 402 or the spend cap is hit.
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

PROMPT = (
    "This is a scanned historical architectural drawing sheet from the Historic "
    "American Buildings Survey. Return STRICT JSON, no prose, with keys:\n"
    '  "title": the sheet\'s title/caption if legible else null,\n'
    '  "description": 2-4 sentences describing what is drawn (building, view type, '
    "notable architectural features, materials, style),\n"
    '  "texts": a list of EVERY legible piece of text on the sheet, each as '
    '{"t": "the text", "box": [x0, y0, x1, y1]} with coordinates as fractions of '
    "the image (0.0-1.0). Transcribe hand lettering faithfully, including room "
    "names, dimensions, notes, sheet numbers and references such as SEE SHEET N; "
    "skip illegible marks."
)

TILE_PROMPT = (
    "This is one quadrant of a scanned historical architectural drawing, at higher "
    "resolution. Return STRICT JSON: {\"texts\": [{\"t\": \"the text\", \"box\": "
    "[x0, y0, x1, y1]}]} listing EVERY legible piece of text in THIS image, "
    "coordinates as fractions (0.0-1.0) of THIS image. Transcribe hand lettering "
    "faithfully; skip illegible marks. No prose.")


def repair_json(fragment: str):
    """Salvage a truncated response: close the texts array at the last complete
    item. Better a partial transcription than none. Tails cover both the
    asked-for object and a bare array of items."""
    pos = len(fragment)
    for _ in range(60):
        pos = fragment.rfind("}", 0, pos)
        if pos <= 0:
            return None
        for tail in ("]", "}]", "]}", "}]}"):
            try:
                return json.loads(fragment[:pos + 1] + tail)
            except Exception:
                pass
    return None


def parse_json(out: str):
    """Model text -> dict with a "texts" list. Accepts the asked-for object or
    a bare array of items — Nemotron 3 Nano Omni answers the quadrant prompt
    with `[{"t": ..., "box": [...]}, ...]` and no wrapping object, which the
    first version of this parser threw away (92 tile replies, zero merged)."""
    i_obj, i_arr = out.find("{"), out.find("[")
    if i_arr >= 0 and (i_obj < 0 or i_arr < i_obj):
        start = i_arr
    elif i_obj >= 0:
        start = i_obj
    else:
        return None
    end = max(out.rfind("}"), out.rfind("]"))
    try:
        d = json.loads(out[start:end + 1])
    except Exception:
        d = repair_json(out[start:])
    if isinstance(d, list):
        d = {"texts": d}
    return d if isinstance(d, dict) else None


def thinking_extra(mode: str):
    if mode == "off":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    if mode == "on":
        return {"chat_template_kwargs": {"enable_thinking": True}}
    return None


def call_vlm(png_b64: str, *, max_tokens=4000, prompt=None, thinking="auto",
             purpose="", rep_penalty: float | None = None):
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt or PROMPT},
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{png_b64}"}}]}]
    extra = dict(thinking_extra(thinking) or {})
    if rep_penalty:
        extra["repetition_penalty"] = rep_penalty   # vLLM extra sampling param
    return tf.chat(tf.EYES, messages, max_tokens=max_tokens, temperature=0,
                   extra=extra or None, purpose=purpose, timeout=300)


def cut_loop(spans, run: int = 6):
    """Degenerate decoding shows up as the same text repeated many times in a
    row. A sheet can legitimately repeat a bay dimension a few times; `run`
    identical consecutive entries is a loop. Cut at its onset and report
    where, so the page is flagged rather than indexed with junk."""
    n = 0
    for i in range(1, len(spans)):
        n = n + 1 if spans[i][0] == spans[i - 1][0] else 0
        if n >= run - 1:
            return spans[:i - n], i - n
    return spans, None


def shrink(png_path: str, edge=1400):
    """Downsample for the wire; returns (b64 png, sent width, sent height)."""
    from PIL import Image
    im = Image.open(png_path)
    if im.mode == "1":
        im = im.convert("L")
    im = im.convert("RGB")
    if max(im.size) > edge:
        im.thumbnail((edge, edge), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode(), im.size[0], im.size[1]


def norm_box(box, W, H, tw, th):
    """Models return boxes in whatever scale they feel like: fractions (asked),
    percents, or pixels of the image they saw. Detect and normalize to page px."""
    try:
        vals = [float(v) for v in box]
    except Exception:
        return None
    if len(vals) != 4:
        return None
    mx = max(vals)
    if mx <= 1.001:
        fx, fy = W, H                       # fractions — as requested
    elif mx <= 100.001:
        fx, fy = W / 100.0, H / 100.0       # percent
    elif mx <= 1000.001 and max(tw, th) <= 1000.001 * 1.0 and mx > max(tw, th):
        fx, fy = W / 1000.0, H / 1000.0     # per-mille grid (some VLMs)
    else:
        fx, fy = W / tw, H / th             # pixels of the sent thumbnail

    def sc(v, page, f):
        # One box can mix scales (Omni on quadrants: x in pixels, y as 0.0836).
        # A value under 1 with a fractional part is a fraction of the page
        # whatever the rest of the box says; 0 and 1 stay on the box's scale.
        if mx > 1.001 and v < 1.0 and v != int(v):
            return v * page
        return v * f
    x0, y0, x1, y1 = sc(vals[0], W, fx), sc(vals[1], H, fy), sc(vals[2], W, fx), sc(vals[3], H, fy)
    x0, x1 = sorted((max(0, min(W, x0)), max(0, min(W, x1))))
    y0, y1 = sorted((max(0, min(H, y0)), max(0, min(H, y1))))
    return x0, y0, x1, y1


def degenerate(spans, W, H):
    """True when a page's boxes are junk: mostly zero-area or corner-piled."""
    if not spans:
        return False
    bad = sum(1 for s in spans
              if (s[3] - s[1]) * (s[4] - s[2]) < 4
              or (s[1] >= 0.98 * W and s[2] >= 0.98 * H))
    return bad / len(spans) > 0.3


def spans_from(d: dict, W, H, tw, th, ox=0.0, oy=0.0, scale=1.0):
    """Model JSON -> page-pixel spans. ox/oy/scale place a quadrant read."""
    spans = []
    for t in (d.get("texts") or []):
        if not isinstance(t, dict):
            continue
        txt = str(t.get("t") or "").strip()
        box = t.get("box") or []
        if not txt or len(box) != 4:
            continue
        nb = norm_box(box, W * scale, H * scale, tw, th)
        if nb is None:
            continue
        x0, y0, x1, y1 = (nb[0] + ox * W, nb[1] + oy * H, nb[2] + ox * W, nb[3] + oy * H)
        if x1 - x0 < 2:
            x1 = min(W, x0 + 0.02 * W * max(1, len(txt) / 8))
        if y1 - y0 < 2:
            y1 = min(H, y0 + 0.015 * H)
        spans.append([txt, x0, y0, x1, y1, "eyes"])
    return spans


def fmt_cost(reply):
    u = reply["usage"]
    usd = f"${reply['usd']:.4f}" if reply["usd"] is not None else "$?"
    return (f"{u.get('prompt_tokens', 0)} in / {u.get('completion_tokens', 0)} out, "
            f"{usd}, {reply['latency_s']}s, finish={reply['finish']}")


def read_page(png: str, s: dict, *, edge: int, thinking: str, pg: str,
              max_tokens: int = 4000, rep_penalty: float | None = None):
    """One full-sheet read. Returns (scene dict or None, description, reply)."""
    b64, tw, th = shrink(png, edge)
    reply, err = call_vlm(b64, thinking=thinking, purpose=f"read page {pg}",
                          max_tokens=max_tokens, rep_penalty=rep_penalty)
    if err:
        print(f"[{pg}] ERROR {err}", flush=True)
        return None, "", None
    out = reply["text"]
    d = parse_json(out)
    if not d:
        print(f"[{pg}] unparseable response ({len(out)} chars): {out[:200]!r}",
              flush=True)
        return None, "", reply
    W, H = s.get("width") or 1, s.get("height") or 1
    spans, loop_at = cut_loop(spans_from(d, W, H, tw, th))
    if loop_at is not None:
        print(f"[{pg}] LOOP: identical text repeated from entry {loop_at}; "
              f"cut there", flush=True)
    s["spans"] = spans
    title = (d.get("title") or "").strip() or None
    s["title"] = title
    desc = (d.get("description") or "").strip()
    s["description"] = desc
    # provenance of this read — which model, where, with what settings
    s["read"] = {"model": tf.EYES, "provider": tf.PROVIDER, "edge": edge,
                 "max_tokens": max_tokens, "rep_penalty": rep_penalty,
                 "thinking": thinking, "finish": reply["finish"],
                 "latency_s": reply["latency_s"], "loop_cut_at": loop_at,
                 "ts": __import__("time").strftime("%Y-%m-%dT%H:%M:%S")}
    return s, desc, reply


def tile_pass(png: str, s: dict, *, thinking: str, pg: str,
              rep_penalty: float | None = None):
    """Re-read the sheet in four full-resolution quadrants and merge new finds."""
    from PIL import Image
    W, H = s.get("width") or 1, s.get("height") or 1
    im = Image.open(png)
    if im.mode == "1":
        im = im.convert("L")
    im = im.convert("RGB")
    spans = s.get("spans") or []
    have = {(sp[0].upper(), round(sp[1] / W, 2), round(sp[2] / H, 2)) for sp in spans}
    added = 0
    for r in range(2):
        for c in range(2):
            crop = im.crop((c * im.width // 2, r * im.height // 2,
                            (c + 1) * im.width // 2, (r + 1) * im.height // 2))
            if max(crop.size) > 1400:
                crop.thumbnail((1400, 1400), Image.LANCZOS)
            buf = io.BytesIO()
            crop.save(buf, "PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode()
            reply, err = call_vlm(b64, max_tokens=6000, prompt=TILE_PROMPT,
                                  thinking=thinking, purpose=f"tile {pg} q{r}{c}",
                                  rep_penalty=rep_penalty)
            if err:
                print(f"[{pg}] tile q{r}{c} ERROR {err}", flush=True)
                continue
            d = parse_json(reply["text"])
            if not d:
                continue
            tile_spans, loop_at = cut_loop(spans_from(
                d, W, H, crop.size[0], crop.size[1], ox=c * 0.5, oy=r * 0.5, scale=0.5))
            if loop_at is not None:
                print(f"[{pg}] tile q{r}{c} LOOP from entry {loop_at}; cut", flush=True)
            for sp in tile_spans:
                key = (sp[0].upper(), round(sp[1] / W, 2), round(sp[2] / H, 2))
                if key in have:
                    continue
                have.add(key)
                spans.append(sp)
                added += 1
            print(f"[{pg}] tile q{r}{c}: {fmt_cost(reply)}", flush=True)
    # a quadrant re-reads lettering the full sheet already had, at a slightly
    # different box: collapse same-text spans with near-identical centres
    from .archive import dedupe_spans
    before = len(spans)
    spans = dedupe_spans(spans, W, H)
    added -= before - len(spans)
    s["spans"] = spans
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--edge", type=int, default=1400)
    ap.add_argument("--thinking", choices=["auto", "off", "on"], default="auto")
    ap.add_argument("--kind", default="sheet", help="page kind to read, or 'any'")
    ap.add_argument("--tiles", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-read pages with text")
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--rep-penalty", type=float, default=None,
                    help="vLLM repetition_penalty, e.g. 1.05 (see module doc)")
    a = ap.parse_args()

    pdir = os.path.abspath(a.project_dir)
    ctx_path = os.path.join(pdir, "context.txt")
    pages = sorted(glob.glob(os.path.join(pdir, "*.scene.json")),
                   key=lambda p: int(os.path.basename(p).split(".")[0]))
    done = read = 0
    try:
        for sj in pages:
            pg = os.path.basename(sj).split(".")[0]
            if a.only is not None and int(pg) != a.only:
                continue
            s = json.load(open(sj, encoding="utf-8"))
            if a.kind != "any" and s.get("kind", "sheet") != a.kind:
                continue
            png = os.path.join(pdir, f"{pg}.png")
            if not os.path.exists(png):
                continue
            eyes = [sp for sp in (s.get("spans") or []) if len(sp) > 5 and sp[5] == "eyes"]
            W, H = s.get("width") or 1, s.get("height") or 1
            if a.tiles:
                if not eyes:
                    continue
                added = tile_pass(png, s, thinking=a.thinking, pg=pg,
                                  rep_penalty=a.rep_penalty)
                json.dump(s, open(sj, "w", encoding="utf-8"))
                read += 1
                print(f"[{pg}] +{added} texts (tile pass) -> {len(s['spans'])}", flush=True)
                continue
            good = s.get("spans") and not (eyes and degenerate(eyes, W, H))
            if good and not (a.force or a.only is not None):
                continue
            if a.limit and done >= a.limit:
                break
            done += 1
            s2, desc, reply = read_page(png, s, edge=a.edge, thinking=a.thinking, pg=pg,
                                        max_tokens=a.max_tokens, rep_penalty=a.rep_penalty)
            if reply is not None:
                print(f"[{pg}] call: {fmt_cost(reply)}"
                      + (f" reasoning_chars={len(reply['reasoning'])}"
                         if reply["reasoning"] else ""), flush=True)
            if s2 is None:
                continue
            json.dump(s2, open(sj, "w", encoding="utf-8"))
            if desc:
                with open(ctx_path, "a", encoding="utf-8") as ctx:
                    ctx.write(f"[page {pg}] {s2.get('title') or ''} — {desc}\n")
            read += 1
            sample = "; ".join(sp[0] for sp in s2["spans"][:6])
            print(f"[{pg}] {len(s2['spans'])} texts · title={s2.get('title')!r}\n"
                  f"      e.g. {sample[:220]}", flush=True)
    except (tf.CreditsExhausted, tf.SpendCapReached, tf.NoApiKey) as e:
        print(f"STOP: {e}", flush=True)
        print(tf.cost_line())
        sys.exit(2)
    print(f"DONE pages_read={read} of {done} attempted")
    print(tf.cost_line())


if __name__ == "__main__":
    main()

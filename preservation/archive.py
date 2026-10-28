"""archive — the SQLite index over one HABS/HAER set: sheets, texts, references,
cross-reference check, text search.

One database per set (default <project_dir>/index.db). Tables:
  sheets   (sheet_no, page, kind, habs_no, title, png, width, height, indexed_at)
  texts    (sheet_no, text, x1, y1, x2, y2, src)   src = text | eyes | title | photo
  findings (id, sheet_no, kind, x1, y1, x2, y2, text, points_to, confidence)
  issues   (id, finding_id, sheet_no, severity, message)   the cross-reference check
  activity (ts, source, message)

Sheet ids are page ids, PG-NN. A measured-drawing sheet also carries its own
HABS number (habs_no) when the sheet's "SHEET N OF M" lettering was read.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path

from PIL import Image

SCHEMA = """
CREATE TABLE IF NOT EXISTS sheets(
  sheet_no TEXT PRIMARY KEY, page INT, kind TEXT, habs_no INT, title TEXT,
  png TEXT, width INT, height INT, indexed_at REAL);
CREATE TABLE IF NOT EXISTS texts(
  sheet_no TEXT, text TEXT, x1 INT, y1 INT, x2 INT, y2 INT, src TEXT DEFAULT 'text');
CREATE INDEX IF NOT EXISTS texts_sheet ON texts(sheet_no);
CREATE TABLE IF NOT EXISTS findings(
  id TEXT PRIMARY KEY, sheet_no TEXT, kind TEXT,
  x1 INT, y1 INT, x2 INT, y2 INT, text TEXT, points_to TEXT, confidence REAL);
CREATE TABLE IF NOT EXISTS issues(
  id TEXT PRIMARY KEY, finding_id TEXT, sheet_no TEXT, severity TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS activity(ts REAL, source TEXT, message TEXT);
"""


def page_id(pg) -> str:
    return f"PG-{int(pg):02d}"


def open_db(path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    return conn


def log_activity(conn, msg, source="index"):
    conn.execute("INSERT INTO activity VALUES(?,?,?)", (time.time(), source, msg))
    conn.commit()


# ---------- ingest ----------

def _first_line(spans, H):
    """Top text band of a page in reading order — the title of a document page."""
    if not spans:
        return None
    band = max(12.0, H / 250.0)
    top = min(((sp[2] + sp[4]) / 2) for sp in spans)
    words = sorted((sp for sp in spans if abs((sp[2] + sp[4]) / 2 - top) < band),
                   key=lambda sp: sp[1])
    return " ".join(str(sp[0]) for sp in words)[:120] or None


def eyes_provenance(pdir) -> dict:
    """Which model read the scanned sheets, and on which surface: taken from the
    read provenance each page carries, so the UI reports the eyes that actually
    produced the index rather than whatever the environment says today."""
    for sj in sorted(Path(pdir).glob("*.scene.json")):
        try:
            d = json.loads(sj.read_text(encoding="utf-8"))
        except Exception:
            continue
        r = d.get("read")
        if d.get("kind") == "sheet" and r and r.get("model"):
            return {"eyes": r.get("model"), "eyes_provider": r.get("provider")}
    return {}


def dedupe_spans(spans, W, H, tol: float = 0.025):
    """The same lettering read twice (a full-sheet pass, then a quadrant pass)
    lands as two spans with the same text and nearly the same position; the
    evidence pack then repeats it and a small brain loops on the repetition.
    Keep the first; a duplicate is the same text (case-insensitive, whitespace
    collapsed) whose centre lies within `tol` of the page diagonal of a kept one."""
    import math
    diag = math.hypot(W or 1, H or 1) or 1.0
    kept, seen = [], {}
    for sp in spans:
        try:
            t = " ".join(str(sp[0]).split()).upper()
            cx, cy = (float(sp[1]) + float(sp[3])) / 2, (float(sp[2]) + float(sp[4])) / 2
        except Exception:
            kept.append(sp)
            continue
        if any(math.hypot(cx - x, cy - y) < tol * diag for x, y in seen.get(t, ())):
            continue
        seen.setdefault(t, []).append((cx, cy))
        kept.append(sp)
    return kept


def ingest_page(conn, pdir: Path, pg: int, photos: dict | None = None,
                source="index"):
    """Index one page: its text layer, title, photo caption, typed references."""
    pdir = Path(pdir)
    sj = pdir / f"{pg}.scene.json"
    png = pdir / f"{pg}.png"
    if not sj.exists() or not png.exists():
        return None
    s = json.loads(sj.read_text(encoding="utf-8"))
    with Image.open(png) as im:
        W, H = im.size
    sw, sh = s.get("width") or W, s.get("height") or H
    fx, fy = W / sw, H / sh
    sid = page_id(pg)
    kind = s.get("kind") or "sheet"
    spans = s.get("spans") or []
    if kind == "sheet":   # model-read lettering; PDF text layers are left as they are
        spans = dedupe_spans(spans, sw, sh)

    conn.execute("DELETE FROM texts WHERE sheet_no=?", (sid,))
    conn.execute("DELETE FROM findings WHERE sheet_no=?", (sid,))
    for sp in spans:
        try:
            t, x1, y1, x2, y2 = str(sp[0]), *map(float, sp[1:5])
        except Exception:
            continue
        src = sp[5] if len(sp) > 5 else "text"
        if t.strip():
            conn.execute("INSERT INTO texts VALUES(?,?,?,?,?,?,?)",
                         (sid, t.strip(), round(x1 * fx), round(y1 * fy),
                          round(x2 * fx), round(y2 * fy), src))

    title = (s.get("title") or "").strip() or None
    if kind == "photo" and photos and pg in photos:
        p = photos[pg]
        title = ", ".join(str(p[k]) for k in ("subject", "view") if p.get(k)) or None
        cap = (p.get("caption") or "").strip()
        if cap:
            conn.execute("INSERT INTO texts VALUES(?,?,?,?,?,?,?)",
                         (sid, cap, 0, 0, W, H, "photo"))
        if p.get("kind"):
            conn.execute("INSERT INTO texts VALUES(?,?,?,?,?,?,?)",
                         (sid, f"photograph: {p['kind']} view, {title}", 0, 0, 0, 0,
                          "photo"))
    if not title and kind == "document":
        title = _first_line(spans, sh)
    if title and kind != "photo":
        conn.execute("INSERT INTO texts VALUES(?,?,?,?,?,?,?)",
                     (sid, title, 0, 0, 0, 0, "title"))
    desc = (s.get("description") or "").strip()
    if desc:
        conn.execute("INSERT INTO texts VALUES(?,?,?,?,?,?,?)",
                     (sid, desc, 0, 0, 0, 0, "description"))

    # typed references: "SEE SHEET N" lettering mapped to a page by type_refs.py
    n_ref = 0
    for i, b in enumerate(s.get("bubbles") or []):
        if not b.get("typed_ref"):
            continue
        toks = [str(t) for t in (b.get("tokens") or []) if str(t)]
        bbox = b.get("bbox") or [0, 0, 0, 0]
        conn.execute("INSERT INTO findings VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (f"{sid}:r{i}", sid, "ref",
                      round(bbox[0] * fx), round(bbox[1] * fy),
                      round(bbox[2] * fx), round(bbox[3] * fy),
                      toks[0] if toks else "?", b.get("target"),
                      0.9 if b.get("target") else 0.5))
        n_ref += 1

    conn.execute("INSERT OR REPLACE INTO sheets VALUES(?,?,?,?,?,?,?,?,?)",
                 (sid, pg, kind, s.get("habs_no"), title, png.name, W, H, time.time()))
    conn.commit()
    return dict(sheet_no=sid, kind=kind, texts=len(spans), refs=n_ref, title=title)


def recheck_issues(conn) -> int:
    """Cross-reference pass: every reference whose target is not an indexed
    sheet becomes an issue (warn). References with no resolvable target at all
    (the sheet number named was never read as a self-number) are warned too."""
    conn.execute("DELETE FROM issues")
    have = {r[0] for r in conn.execute("SELECT sheet_no FROM sheets")}
    n = 0
    for fid, sheet, text, ref in conn.execute(
            "SELECT id, sheet_no, text, points_to FROM findings WHERE kind='ref'"):
        if ref and ref in have:
            continue
        n += 1
        msg = (f"Reference '{text}' on {sheet}: target {ref} is not an indexed page"
               if ref else
               f"Reference '{text}' on {sheet}: no page in the set identifies itself "
               f"with that sheet number")
        conn.execute("INSERT INTO issues VALUES(?,?,?,?,?)",
                     (f"i{n}", fid, sheet, "warn", msg))
    conn.commit()
    return n


def ingest_project(pdir, db_path=None, source="index") -> sqlite3.Connection:
    pdir = Path(pdir)
    db_path = Path(db_path) if db_path else pdir / "index.db"
    if db_path.exists():
        db_path.unlink()
    conn = open_db(db_path)
    photos = {}
    pj = pdir / "photos.json"
    if pj.exists():
        photos = {int(p["page"]): p for p in json.loads(pj.read_text(encoding="utf-8"))}
    pages = sorted(int(p.stem) for p in pdir.glob("*.png") if p.stem.isdigit())
    for pg in pages:
        r = ingest_page(conn, pdir, pg, photos, source)
        if r:
            print(f"{r['sheet_no']} {r['kind']:8} texts={r['texts']:3} refs={r['refs']} "
                  f"title={r['title']!r}", flush=True)
    n = recheck_issues(conn)
    log_activity(conn, f"Indexed {len(pages)} pages; {n} unresolved reference(s)", source)
    return conn


def summary(conn) -> dict:
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    return dict(
        pages=q("SELECT COUNT(*) FROM sheets"),
        sheets=q("SELECT COUNT(*) FROM sheets WHERE kind='sheet'"),
        photos=q("SELECT COUNT(*) FROM sheets WHERE kind='photo'"),
        documents=q("SELECT COUNT(*) FROM sheets WHERE kind='document'"),
        texts=q("SELECT COUNT(*) FROM texts"),
        texts_eyes=q("SELECT COUNT(*) FROM texts WHERE src='eyes'"),
        texts_vector=q("SELECT COUNT(*) FROM texts WHERE src='text'"),
        refs=q("SELECT COUNT(*) FROM findings WHERE kind='ref'"),
        unresolved_refs=q("SELECT COUNT(*) FROM issues WHERE severity='warn'"))


# ---------- search (used by the agent's evidence pack) ----------

_STOP = {"how", "many", "much", "is", "are", "there", "the", "a", "an", "of", "on",
         "in", "find", "where", "show", "me", "all", "count", "what", "which", "do",
         "we", "have", "does", "this", "set", "sheet", "sheets", "page", "pages",
         "reference", "references", "refs", "for", "with", "and", "any", "list",
         "search", "that", "from", "into", "about", "was", "were", "who", "when",
         "did", "its", "has", "can", "you", "tell", "please", "drawing", "drawings"}


def search_terms(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z][\w\-'.]{2,}", question)
    out = []
    for w in words:
        if w.lower() in _STOP:
            continue
        t = w.upper().rstrip(".-'")
        if t.endswith("S") and len(t) > 3:        # plural -> stem
            t = t[:-1]
        if t and t not in out:
            out.append(t)
    return out


def _term_filter(root: str):
    """Tag-like terms (digits/hyphens) match on token boundaries; plain words
    match as substrings so ROOM still hits ROOMS."""
    if any(c.isdigit() for c in root) or "-" in root:
        rx = re.compile(rf"(?<![A-Z0-9]){re.escape(root)}(?![A-Z0-9])")
        return lambda text: bool(rx.search(text.upper()))
    return lambda text: root in text.upper()


def term_rows(conn, root: str):
    keep = _term_filter(root)
    return [r for r in conn.execute(
        "SELECT sheet_no, text, x1, y1, x2, y2, src FROM texts WHERE UPPER(text) LIKE ?",
        (f"%{root}%",)) if keep(r[1])]


def sheet_text(conn, sheet_no: str, cap: int = 20000) -> str:
    """Full text of a page reconstructed in reading order: entries banded into
    lines by vertical position, left to right."""
    row = conn.execute("SELECT height FROM sheets WHERE sheet_no=?",
                       (sheet_no.upper(),)).fetchone()
    H = row[0] if row else 1000
    rows = conn.execute("SELECT text, x1, y1, y2, src FROM texts WHERE sheet_no=? "
                        "ORDER BY y1, x1", (sheet_no.upper(),)).fetchall()
    if not rows:
        return ""
    band = max(12.0, H / 250.0)
    head, bands = [], {}
    for t, x1, y1, y2, src in rows:
        if src in ("title", "description", "photo"):
            head.append(f"[{src}] {t}")
            continue
        bands.setdefault(int(((y1 + y2) / 2) / band), []).append((x1, t))
    out = head + [" | ".join(t for _, t in sorted(bands[k])) for k in sorted(bands)]
    return "\n".join(out)[:cap]


if __name__ == "__main__":
    import sys
    conn = ingest_project(sys.argv[1])
    print("SUMMARY:", summary(conn))

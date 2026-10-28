"""server — the web app: pick a page, ask the set, see the answer with receipts.

GET  /                      the page (app/static/index.html)
GET  /api/health            index present, page count, whether the model can be called
GET  /api/set               set name, summary, page inventory
GET  /api/page/{sheet_id}   one page's texts (with boxes), references, issues
GET  /api/search?q=         local index hits for a question — no model call
POST /api/ask               {question, sheet_id} -> agent outcome + receipts + local hits
GET  /pages/{n}.png         full-resolution page
GET  /view/{n}.png          browser rendition (<= 2400 px wide) when present, else the page
GET  /thumbs/{n}.png        thumbnail; generated into a cache if not committed

Everything but POST /api/ask runs from the committed index.db and PNGs. When
the model cannot be called (no key, Token Factory 402, spend cap, network) the
answer comes back with outcome MODEL_UNAVAILABLE and the reason, and the local
index hits are still returned — the page never crashes on a missing model.

Env: PROJECT_DIR (default data/iolani-palace), TOKEN_FACTORY_API_KEY,
     AGENT_DISABLED=1 (never call the model), AGENT_THINKING=auto|off|on
Run: uvicorn app.server:app --host 0.0.0.0 --port 7860
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from preservation import agent, archive
from preservation import tokenfactory as tf

ROOT = Path(__file__).resolve().parent.parent
PROJECT = Path(os.environ.get("PROJECT_DIR", ROOT / "data" / "iolani-palace")).resolve()
DB = PROJECT / "index.db"
STATIC = Path(__file__).resolve().parent / "static"
CACHE = Path(os.environ.get("RENDITION_CACHE", tempfile.gettempdir())) / "invisu-thumbs"
THUMB_W = 220
ASK_TIMEOUT_S = 480

app = FastAPI(title="INViSU Preservation Reader")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def db() -> sqlite3.Connection:
    if not DB.exists():
        raise HTTPException(503, f"no index at {DB} — run preservation.build_index")
    return sqlite3.connect(str(DB))


def project_name() -> str:
    pj = PROJECT / "project.json"
    if pj.exists():
        return json.loads(pj.read_text(encoding="utf-8")).get("name", PROJECT.name)
    return PROJECT.name


def model_disabled_reason() -> str | None:
    if os.environ.get("AGENT_DISABLED"):
        return "model disabled (AGENT_DISABLED is set)"
    if not tf.has_key():
        return "model unavailable: no TOKEN_FACTORY_API_KEY"
    return None


def page_rows(conn):
    text_counts = {r[0]: r[1] for r in conn.execute(
        "SELECT sheet_no, COUNT(*) FROM texts WHERE src IN ('text','eyes') GROUP BY sheet_no")}
    out = []
    for sid, pg, kind, habs, title, w, h in conn.execute(
            "SELECT sheet_no, page, kind, habs_no, title, width, height FROM sheets ORDER BY page"):
        out.append(dict(id=sid, page=pg, kind=kind, habs_no=habs, title=title,
                        width=w, height=h, texts=text_counts.get(sid, 0),
                        thumb_url=f"/thumbs/{pg}.png", view_url=f"/view/{pg}.png",
                        image_url=f"/pages/{pg}.png"))
    return out


def local_hits(conn, question: str, cap: int = 300):
    roots, hits, combined = [], [], {}
    for root in archive.search_terms(question):
        roots.append(root)
        for sid, txt, x1, y1, x2, y2, src in archive.term_rows(conn, root):
            if len(hits) < cap:
                hits.append(dict(sheet=sid, text=txt, bbox=[x1, y1, x2, y2], src=src, term=root))
            combined[sid] = combined.get(sid, 0) + 1
    sheets = [dict(id=s, count=combined[s]) for s in sorted(combined, key=lambda s: -combined[s])]
    return roots, hits, sheets


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    ok = DB.exists()
    n = 0
    if ok:
        conn = db()
        n = conn.execute("SELECT COUNT(*) FROM sheets").fetchone()[0]
        conn.close()
    return dict(ok=ok, index=str(DB), pages=n, model=tf.BRAIN, eyes=tf.EYES,
                model_callable=model_disabled_reason() is None,
                model_note=model_disabled_reason())


@app.get("/api/set")
def get_set():
    conn = db()
    try:
        s = archive.summary(conn)
        pages = page_rows(conn)
        issues = [m for (m,) in conn.execute("SELECT message FROM issues")]
    finally:
        conn.close()
    return dict(name=project_name(), summary=s, pages=pages, issues=issues,
                model=tf.BRAIN, eyes=tf.EYES, model_note=model_disabled_reason())


@app.get("/api/page/{sheet_id}")
def get_page(sheet_id: str):
    sid = sheet_id.upper()
    conn = db()
    try:
        row = conn.execute("SELECT sheet_no, page, kind, habs_no, title, width, height "
                           "FROM sheets WHERE sheet_no=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, f"no page {sid}")
        texts = [dict(text=t, bbox=[x1, y1, x2, y2], src=src) for t, x1, y1, x2, y2, src in
                 conn.execute("SELECT text, x1, y1, x2, y2, src FROM texts WHERE sheet_no=? "
                              "ORDER BY y1, x1", (sid,))]
        refs = [dict(text=t, points_to=p, bbox=[x1, y1, x2, y2]) for t, p, x1, y1, x2, y2 in
                conn.execute("SELECT text, points_to, x1, y1, x2, y2 FROM findings "
                             "WHERE sheet_no=? AND kind='ref'", (sid,))]
        back = [dict(sheet=s, text=t) for s, t in conn.execute(
            "SELECT sheet_no, text FROM findings WHERE points_to=? AND kind='ref'", (sid,))]
        issues = [m for (m,) in conn.execute("SELECT message FROM issues WHERE sheet_no=?", (sid,))]
    finally:
        conn.close()
    return dict(id=row[0], page=row[1], kind=row[2], habs_no=row[3], title=row[4],
                width=row[5], height=row[6], texts=texts, refs=refs,
                referenced_by=back, issues=issues,
                reading_order=archive.sheet_text(db(), sid, cap=12000))


@app.get("/api/search")
def search(q: str = ""):
    conn = db()
    try:
        roots, hits, sheets = local_hits(conn, q)
    finally:
        conn.close()
    return dict(roots=roots, hits=hits, sheets=sheets)


class AskReq(BaseModel):
    question: str
    sheet_id: str | None = None


@app.post("/api/ask")
async def ask(req: AskReq):
    q = req.question.strip()
    if not q:
        raise HTTPException(400, "empty question")
    conn = db()
    try:
        roots, hits, sheets = local_hits(conn, q)
    finally:
        conn.close()
    base = dict(question=q, sheet_id=req.sheet_id, roots=roots, hits=hits, sheets=sheets,
                top_sheet=sheets[0]["id"] if sheets else None, model=tf.BRAIN)
    reason = model_disabled_reason()
    if reason:
        return dict(base, outcome="MODEL_UNAVAILABLE", answer=reason, receipts=[],
                    verified=False, notes=[reason], available=False)
    loop = asyncio.get_running_loop()
    thinking = os.environ.get("AGENT_THINKING", "auto")
    try:
        r = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: agent.ask(PROJECT, q, req.sheet_id,
                                                         thinking=thinking)),
            timeout=ASK_TIMEOUT_S)
    except tf.CreditsExhausted:
        reason = "model unavailable: credits (Token Factory answered HTTP 402)"
    except tf.SpendCapReached as e:
        reason = f"model unavailable: spend cap reached ({e})"
    except tf.NoApiKey:
        reason = "model unavailable: no TOKEN_FACTORY_API_KEY"
    except asyncio.TimeoutError:
        reason = f"model unavailable: no answer within {ASK_TIMEOUT_S}s"
    except Exception as e:  # never crash the page on a model problem
        reason = f"model unavailable: {type(e).__name__}: {str(e)[:120]}"
    else:
        if r.get("error"):
            reason = f"model unavailable: {r['error'][:160]}"
        else:
            return dict(base, outcome=r.get("outcome") or "UNPARSED", answer=r.get("answer", ""),
                        receipts=r.get("receipts", []), verified=r.get("verified", False),
                        notes=r.get("notes", []), invented=r.get("invented", []),
                        usage=r.get("usage"), usd=r.get("usd"), latency_s=r.get("latency_s"),
                        reasoning_chars=r.get("reasoning_chars", 0),
                        pack_chars=r.get("pack_chars"), raw=r.get("raw"), available=True)
    return dict(base, outcome="MODEL_UNAVAILABLE", answer=reason, receipts=[],
                verified=False, notes=[reason], available=False)


def _page_file(n: int) -> Path:
    p = PROJECT / f"{n}.png"
    if not p.exists():
        raise HTTPException(404, f"no page {n}")
    return p


@app.get("/pages/{n}.png")
def page_png(n: int):
    return FileResponse(_page_file(n), media_type="image/png")


@app.get("/view/{n}.png")
def view_png(n: int):
    v = PROJECT / "view" / f"{n}.png"
    return FileResponse(v if v.exists() else _page_file(n), media_type="image/png")


@app.get("/thumbs/{n}.png")
def thumb_png(n: int):
    t = PROJECT / "thumbs" / f"{n}.png"
    if t.exists():
        return FileResponse(t, media_type="image/png")
    src = _page_file(n)
    CACHE.mkdir(parents=True, exist_ok=True)
    c = CACHE / f"{PROJECT.name}-{n}.png"
    if not c.exists():
        from preservation.renditions import render
        render(src, c, THUMB_W)
    return FileResponse(c, media_type="image/png")

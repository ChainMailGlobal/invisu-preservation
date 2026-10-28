"""agent — ask the set a question; get the sheet.

The agent builds an evidence pack from the index (page inventory, typed
references, the cross-reference check, term hits, then the FULL text of every
page in evidence order under a character budget) and asks Nemotron-3-Ultra on
Nebius Token Factory. The model is allowed exactly one of four outcomes:

  ANSWERED              supported by text in the pack; every claim carries [PG-NN]
  ANSWERED_FROM_MEMORY  the set does not contain it; general knowledge, with its
                        date, flagged as not confirmed by the set
  NOT_IN_THE_SET        the question is about this set but nothing read answers it
  UNKNOWN_ENTITY        the question names a place/sheet/thing that is not this set

Receipts are verified in code, not trusted: any [PG-NN] the model cites that is
not an indexed page is flagged and the result is marked unverified. In the
ANSWERED outcome numbers, areas, dates and sheet numbers may only be quoted
from the pack, never supplied by the model.

Usage:
  python -m preservation.agent <project_dir> "question"
         [--sheet PG-11] [--dry-run] [--save docs/transcripts/name.md]
         [--thinking auto|off|on] [--budget 150000]
--dry-run prints the evidence pack and makes no model call.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from . import archive
from . import tokenfactory as tf

OUTCOMES = ("ANSWERED", "ANSWERED_FROM_MEMORY", "NOT_IN_THE_SET", "UNKNOWN_ENTITY")
PAGE_RE = re.compile(r"\bPG-(\d{2})\b")

SYSTEM = """You are the reading agent for one Library of Congress Historic American Buildings Survey (HABS) drawing set, indexed by iNViSU. The EVIDENCE PACK below is everything that has been read from the set: a page inventory, typed cross-references, the cross-reference check, text-search hits for the question, and the full transcribed text of the pages, in reading order. Pages are identified as PG-NN; measured-drawing sheets also carry the HABS sheet number lettered on them.

You must answer with exactly ONE of four outcomes:

ANSWERED - the answer is supported by text in the pack. Quote the exact text you relied on and cite every supporting page as [PG-NN], giving its HABS sheet number and title when the inventory has them. Every number, dimension, date, room name and sheet number in your answer must appear in the pack.

ANSWERED_FROM_MEMORY - the question is about this building or set but the pack does not contain the answer, and you know it from general knowledge. Say so explicitly, give the date of that knowledge (your training data), and state that the set does not confirm it. Cite no pages as receipts.

NOT_IN_THE_SET - the question is about this building or set, the pack does not contain the answer, and you have no reliable memory of it. Say so plainly and name the pages you checked that came closest.

UNKNOWN_ENTITY - the question names a building, place, person, sheet or object that is not this set and does not appear in the pack.

Never invent a page id, sheet number, dimension, area, date or room name. Never estimate an area or a quantity. If the pack is ambiguous, say what is ambiguous rather than choosing. Answer the question itself, the way a reader of the set would use it: for a location question, name the sheet(s) and quote the lettering that places it (the plan sheet and the room label, not just the building); for a reference question, list the references verbatim; for a which-sheets question, list every matching sheet with its HABS sheet number. Keep the answer under 150 words.

Reply in exactly this form, nothing else:
OUTCOME: <one of ANSWERED | ANSWERED_FROM_MEMORY | NOT_IN_THE_SET | UNKNOWN_ENTITY>
ANSWER: <the answer>
RECEIPTS: <comma-separated page ids like PG-24, PG-25 — or none>"""


def evidence_pack(conn: sqlite3.Connection, question: str, sheet_id: str | None = None,
                  budget: int = 150_000, set_name: str = "") -> tuple[str, dict]:
    s = archive.summary(conn)
    lines = [f"SET: {set_name or 'HABS set'} — {s['pages']} pages: {s['documents']} "
             f"document pages, {s['sheets']} measured-drawing sheets, {s['photos']} "
             f"photographs. Text entries indexed: {s['texts']} "
             f"({s['texts_eyes']} transcribed from scans by the vision model, "
             f"{s['texts_vector']} from PDF text layers).",
             "", "PAGE INVENTORY (page id · kind · HABS sheet no · title):"]
    inv = {}
    for sid, pg, kind, habs, title in conn.execute(
            "SELECT sheet_no, page, kind, habs_no, title FROM sheets ORDER BY page"):
        inv[sid] = (kind, habs, title)
        habs_s = f"HABS sheet {habs}" if habs else "-"
        lines.append(f"  {sid} · {kind} · {habs_s} · {title or '(no title read)'}")
    refs = conn.execute("SELECT sheet_no, text, points_to FROM findings WHERE kind='ref' "
                        "ORDER BY sheet_no").fetchall()
    # the same lettering read twice (full sheet, then a quadrant) is one reference
    refs = list(dict.fromkeys((sid, " ".join(str(t).split()), tgt) for sid, t, tgt in refs))
    lines += ["", f"TYPED REFERENCES from 'SEE SHEET N' lettering ({len(refs)}):"]
    for sid, text, target in refs:
        lines.append(f"  {sid}: '{text}' -> {target or 'no page identifies itself with that number'}")
    issues = [m for (m,) in conn.execute("SELECT message FROM issues")]
    lines += ["", f"CROSS-REFERENCE CHECK: {len(issues)} unresolved"]
    lines += [f"  - {m}" for m in issues]

    # Pages the question names ("HABS sheet 12", "sheet 12", "PG-19") are
    # resolved through the inventory and their typed links listed up front, so
    # a reference question is answered from the lettering, not from guesswork.
    named: list[str] = []
    for n in re.findall(r"\bsheet\s*(?:no\.?\s*)?(\d{1,3})\b", question, re.I):
        for sid, (kind, habs, title) in inv.items():
            if str(habs) == n and sid not in named:
                named.append(sid)
    for n in PAGE_RE.findall(question.upper()):
        if f"PG-{n}" in inv and f"PG-{n}" not in named:
            named.append(f"PG-{n}")
    if named:
        lines += ["", "PAGES NAMED IN THE QUESTION (resolved through the inventory):"]
        for sid in named:
            kind, habs, title = inv[sid]
            on = [f"'{t}' -> {tgt or 'unresolved'}" for s_, t, tgt in refs if s_ == sid]
            back = [f"{s_}: '{t}'" for s_, t, tgt in refs if tgt == sid]
            lines.append(f"  {sid} · {kind}" + (f" · HABS sheet {habs}" if habs else "")
                         + (f" · {title}" if title else ""))
            lines.append("    WHAT THIS PAGE REFERENCES (its own 'SEE SHEET' lettering, outgoing): "
                         + ("; ".join(on) if on else "none read"))
            lines.append("    what references THIS page (other pages' lettering, incoming): "
                         + ("; ".join(back) if back else "none"))

    lines += ["", "TEXT SEARCH for the question's terms:"]
    combined: dict[str, int] = {}
    for root in archive.search_terms(question):
        rows = archive.term_rows(conn, root)
        if not rows:
            lines.append(f"  '{root}': no hits")
            continue
        by: dict[str, list[str]] = {}
        for sid, txt, *_ in rows:
            by.setdefault(sid, []).append(txt)
            combined[sid] = combined.get(sid, 0) + 1
        lines.append(f"  '{root}': {len(rows)} hits — " + "; ".join(
            f"{sid} x{len(v)} (e.g. {', '.join(sorted(set(v))[:4])[:160]})"
            for sid, v in sorted(by.items(), key=lambda kv: -len(kv[1]))[:12]))

    # Full text of every page: the open page first, then by hit count, then the
    # rest, under a budget — anything dropped is named, never silently lost.
    all_pages = [r[0] for r in conn.execute("SELECT DISTINCT sheet_no FROM texts")]
    all_pages.sort(key=lambda x: int(x[3:]))
    ordered = []
    if sheet_id and sheet_id.upper() in all_pages:
        ordered.append(sheet_id.upper())
    for sid in named:
        if sid in all_pages and sid not in ordered:
            ordered.append(sid)
    for sid in sorted(combined, key=lambda x: -combined[x]):
        if sid in all_pages and sid not in ordered:
            ordered.append(sid)
    ordered += [sid for sid in all_pages if sid not in ordered]
    used = sum(len(l) for l in lines)
    included, dropped = [], []
    for sid in ordered:
        d = archive.sheet_text(conn, sid, cap=20000)
        if not d:
            continue
        if used + len(d) > budget:
            dropped.append(sid)
            continue
        used += len(d)
        included.append(sid)
        kind, habs, title = inv.get(sid, ("?", None, None))
        tag = " (THE PAGE THE USER IS VIEWING)" if sheet_id and sid == sheet_id.upper() else ""
        head = f"{sid}{tag} · {kind}" + (f" · HABS sheet {habs}" if habs else "") \
            + (f" · {title}" if title else "")
        lines.append(f"\n=== FULL TEXT OF {head}, reading order ===\n{d}")
    if dropped:
        lines.append(f"\n(NOT included, size limit: {', '.join(dropped)})")
    meta = {"pages_included": included, "pages_dropped": dropped,
            "hit_pages": combined, "chars": sum(len(l) for l in lines)}
    return "\n".join(lines), meta


def parse_reply(text: str, known_pages: set[str]) -> dict:
    # A reasoning model served without a reasoning parser puts its thinking
    # inline, before the answer form. The form comes last: strip <think>
    # blocks and parse from the LAST "OUTCOME:"; what precedes it is counted
    # as inline reasoning, never shown as the answer.
    body = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    inline_reasoning = 0
    if "</think>" in body:          # the chat template opened the tag; only the close is in the output
        head, _, body = body.rpartition("</think>")
        inline_reasoning = len(head.strip())
    k = body.rfind("OUTCOME:")
    if k > 0:
        inline_reasoning += len(body[:k].strip())
    if k >= 0:
        body = body[k:]
    outcome = None
    m = re.search(r"OUTCOME:\s*([A-Z_]+)", body)
    if m and m.group(1) in OUTCOMES:
        outcome = m.group(1)
    elif k < 0:
        # No form at all: accept a bare outcome word as the first token (the
        # 30B brain with reasoning off sometimes answers just "NOT_IN_THE_SET").
        bare = re.match(r"\s*(ANSWERED_FROM_MEMORY|ANSWERED|NOT_IN_THE_SET|UNKNOWN_ENTITY)\b", body)
        if bare:
            outcome = bare.group(1)
    am = re.search(r"ANSWER:\s*(.*?)(?:\nRECEIPTS:|\Z)", body, re.S)
    if am:
        answer = am.group(1).strip()
    else:
        # strip a bare outcome word and a receipts line from what is left
        answer = re.sub(r"^\s*(ANSWERED_FROM_MEMORY|ANSWERED|NOT_IN_THE_SET|UNKNOWN_ENTITY)\b[:\s]*", "", body, count=1)
        answer = re.sub(r"RECEIPTS:.*", "", answer, flags=re.S).strip()
    rm = re.search(r"RECEIPTS:\s*(.*)", body, re.S)
    cited = sorted({f"PG-{n}" for n in PAGE_RE.findall((rm.group(1) if rm else "") + " " + answer)})
    invented = [p for p in cited if p not in known_pages]
    verified = outcome is not None and not invented and \
        (outcome != "ANSWERED" or bool(cited))
    notes = []
    if outcome is None:
        notes.append("model did not state one of the four outcomes")
    if invented:
        notes.append(f"cited pages that are not in the index: {', '.join(invented)}")
    if outcome == "ANSWERED" and not cited:
        notes.append("ANSWERED without any page receipt")
    if outcome in ("ANSWERED_FROM_MEMORY", "NOT_IN_THE_SET", "UNKNOWN_ENTITY") and \
            outcome == "ANSWERED_FROM_MEMORY" and not re.search(r"\b(19|20)\d{2}\b", answer):
        notes.append("memory answer carries no date")
    return {"outcome": outcome, "answer": answer, "receipts": cited,
            "invented": invented, "verified": verified, "notes": notes,
            "inline_reasoning_chars": inline_reasoning}


def ask(pdir, question: str, sheet_id: str | None = None, *, thinking="auto",
        budget=150_000, dry_run=False, db_path=None, max_tokens: int = 900,
        rep_penalty: float | None = None) -> dict:
    pdir = Path(pdir)
    db_path = Path(db_path) if db_path else pdir / "index.db"
    if not db_path.exists():
        raise SystemExit(f"no index at {db_path} — run build_index first")
    conn = archive.open_db(db_path)
    set_name = ""
    pj = pdir / "project.json"
    if pj.exists():
        set_name = json.loads(pj.read_text(encoding="utf-8")).get("name", "")
    pack, meta = evidence_pack(conn, question, sheet_id, budget, set_name)
    known = {r[0] for r in conn.execute("SELECT sheet_no FROM sheets")}
    result = {"question": question, "sheet_id": sheet_id, "model": tf.BRAIN,
              "provider": tf.PROVIDER, "thinking": thinking, "max_tokens": max_tokens,
              "pack_chars": meta["chars"], "pages_included": meta["pages_included"],
              "pages_dropped": meta["pages_dropped"],
              "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    if dry_run:
        result["pack"] = pack
        return result
    extra = {}
    if thinking == "off":
        extra["chat_template_kwargs"] = {"enable_thinking": False}
    elif thinking == "on":
        extra["chat_template_kwargs"] = {"enable_thinking": True}
    if rep_penalty:
        # the 30B brain looped inside its own reasoning ("Also PG-14: ..." x300)
        # without this; 1.05 is mild enough to leave quoting intact
        extra["repetition_penalty"] = rep_penalty
    extra = extra or None
    result["rep_penalty"] = rep_penalty
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"=== EVIDENCE PACK ===\n{pack}\n\n"
                                            f"=== QUESTION ===\n{question}"}]
    reply, err = tf.chat(tf.BRAIN, messages, max_tokens=max_tokens, temperature=0,
                         extra=extra, purpose=f"agent: {question[:60]}", timeout=420)
    if err:
        result.update(error=err)
        return result
    parsed = parse_reply(reply["text"], known)
    raw = reply["text"]
    if parsed["outcome"] is None and reply["finish"] == "stop":
        # The model answered but skipped the OUTCOME line (it happens with the
        # 30B brain). Ask it to state the outcome itself rather than inferring
        # one in code; the second call is short, reasoning off, and recorded.
        follow = messages + [{"role": "assistant", "content": raw},
                             {"role": "user", "content":
                              "Your reply is missing the OUTCOME line. Repeat your answer in exactly "
                              "the required form (OUTCOME / ANSWER / RECEIPTS), content unchanged."}]
        r2, err2 = tf.chat(tf.BRAIN, follow, max_tokens=400, temperature=0,
                           extra={"chat_template_kwargs": {"enable_thinking": False}},
                           purpose=f"agent outcome line: {question[:50]}", timeout=120)
        if not err2:
            p2 = parse_reply(r2["text"], known)
            if p2["outcome"] is not None:
                parsed = p2
                parsed["notes"] = parsed.get("notes", []) + ["outcome line stated in a second call"]
                raw += "\n\n--- second call (outcome line requested) ---\n" + r2["text"]
                reply["latency_s"] = round(reply["latency_s"] + r2["latency_s"], 1)
                for k_ in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    reply["usage"][k_] = reply["usage"].get(k_, 0) + r2["usage"].get(k_, 0)
    result.update(parsed)
    result.update(raw=raw, reasoning_chars=len(reply["reasoning"]),
                  usage=reply["usage"], usd=reply["usd"], latency_s=reply["latency_s"],
                  finish=reply["finish"])
    return result


def transcript_md(r: dict) -> str:
    usd = f"${r['usd']:.4f}" if r.get("usd") is not None else "price not configured"
    u = r.get("usage", {})
    where = {"token-factory": "Nebius Token Factory"}.get(
        r.get("provider", ""), f"a Nebius AI Cloud Serverless endpoint ({r.get('provider')})")
    lines = [f"# {r['question']}", "",
             f"- Model: `{r['model']}` via {where}; reasoning mode: {r.get('thinking')}, "
             f"max_tokens {r.get('max_tokens')}",
             f"- Time: {r['ts']}",
             f"- Evidence pack: {r['pack_chars']:,} chars, pages included: "
             f"{len(r['pages_included'])}, dropped: {len(r['pages_dropped'])}",
             f"- Tokens: {u.get('prompt_tokens', 0):,} in / {u.get('completion_tokens', 0):,} "
             f"out ({usd}, {r.get('latency_s', '?')}s, reasoning chars: {r.get('reasoning_chars', 0)}"
             f" separate / {r.get('inline_reasoning_chars', 0)} inline)",
             f"- Outcome: **{r.get('outcome')}** — receipts verified against the index: "
             f"**{'yes' if r.get('verified') else 'NO'}**"
             + (f" ({'; '.join(r['notes'])})" if r.get("notes") else ""),
             "", "## Answer", "", r.get("answer", r.get("error", "")), "",
             f"Receipts: {', '.join(r.get('receipts') or []) or 'none'}", "",
             "## Raw model reply", "", "```", r.get("raw", ""), "```", ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("question")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--save", default=None, help="write a markdown transcript here")
    ap.add_argument("--thinking", choices=["auto", "off", "on"], default="auto")
    ap.add_argument("--budget", type=int, default=150_000)
    ap.add_argument("--max-tokens", type=int, default=900,
                    help="raise (e.g. 4000) when reasoning mode is on and the "
                         "server has no reasoning parser: the thinking is inline")
    ap.add_argument("--rep-penalty", type=float, default=None,
                    help="vLLM repetition_penalty for the brain, e.g. 1.05")
    a = ap.parse_args()
    try:
        r = ask(a.project_dir, a.question, a.sheet, thinking=a.thinking,
                budget=a.budget, dry_run=a.dry_run, max_tokens=a.max_tokens,
                rep_penalty=a.rep_penalty)
    except (tf.CreditsExhausted, tf.SpendCapReached, tf.NoApiKey) as e:
        print(f"STOP: {e}")
        sys.exit(2)
    if a.dry_run:
        print(r["pack"])
        print(f"\n[dry run] pack {r['pack_chars']:,} chars; pages included "
              f"{len(r['pages_included'])}, dropped {r['pages_dropped']}")
        return
    print(f"OUTCOME: {r.get('outcome')}  verified={r.get('verified')}  "
          f"receipts={r.get('receipts')}  notes={r.get('notes')}")
    print(f"ANSWER: {r.get('answer') or r.get('error')}")
    if r.get("usage"):
        print(f"[{r['usage'].get('prompt_tokens', 0)} in / "
              f"{r['usage'].get('completion_tokens', 0)} out, {r['latency_s']}s, "
              f"reasoning_chars={r.get('reasoning_chars', 0)}]")
    if a.save:
        Path(a.save).parent.mkdir(parents=True, exist_ok=True)
        Path(a.save).write_text(transcript_md(r), encoding="utf-8")
        print(f"saved {a.save}")
    print(tf.cost_line())


if __name__ == "__main__":
    main()

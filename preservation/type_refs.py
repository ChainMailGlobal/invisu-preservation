"""type_refs — turn "SEE SHEET N" lettering into typed cross-references.

Historic HABS sheets carry references as hand lettering, not callout symbols:
each sheet self-identifies ("SHEET 7 OF 22 SHEETS") and points elsewhere
("SEE SHEET 12"). This pass maps every page's own sheet number from its
transcript, then turns every other "SHEET N" mention into a typed reference
pointing at that page — so the index, the cross-reference check and the agent
can follow them. Mentions whose target sheet number was never read as a
self-number are kept as unresolved references (the check reports them).

Usage: python -m preservation.type_refs <project_dir>
Run AFTER read_scans; then build_index.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

SELF_RE = re.compile(r"\bSHEET\s*(?:NO\.?\s*)?(\d{1,3})\s+OF\s+\d", re.I)
REF_RE = re.compile(r"\bSHEET\s*(?:NO\.?\s*)?(\d{1,3})\b(?!\s*OF)", re.I)


def page_id(pg) -> str:
    return f"PG-{int(pg):02d}"


def main(pdir: str):
    pdir = os.path.abspath(pdir)
    pages = sorted(glob.glob(os.path.join(pdir, "*.scene.json")),
                   key=lambda p: int(os.path.basename(p).split(".")[0]))
    scenes, selfnum = {}, {}
    for sj in pages:
        pg = int(os.path.basename(sj).split(".")[0])
        s = json.load(open(sj, encoding="utf-8"))
        scenes[pg] = (sj, s)
        s.pop("habs_no", None)
        for sp in s.get("spans") or []:
            m = SELF_RE.search(str(sp[0]))
            if m:
                n = int(m.group(1))
                if n not in selfnum:
                    selfnum[n] = page_id(pg)
                    s["habs_no"] = n
    print("self-number map (HABS sheet -> page):",
          {k: v for k, v in sorted(selfnum.items())})
    n_refs = n_open = 0
    for pg, (sj, s) in scenes.items():
        me = page_id(pg)
        bubbles = [b for b in (s.get("bubbles") or []) if not b.get("typed_ref")]
        seen = set()
        for sp in s.get("spans") or []:
            txt = str(sp[0])
            if SELF_RE.search(txt):
                continue                                  # self-id, not a reference
            for m in REF_RE.finditer(txt):
                n = int(m.group(1))
                target = selfnum.get(n)
                if target == me:
                    continue
                key = (n, round(float(sp[1])), round(float(sp[2])))
                if key in seen:
                    continue
                seen.add(key)
                bubbles.append({"bbox": [sp[1], sp[2], sp[3], sp[4]],
                                "tokens": [txt.strip()[:60], target or f"SHEET {n}"],
                                "typed_ref": True, "sheet": n, "target": target})
                n_refs += 1
                if not target:
                    n_open += 1
        s["bubbles"] = bubbles
        json.dump(s, open(sj, "w", encoding="utf-8"))
    print(f"typed references: {n_refs} ({n_open} to sheet numbers not identified in the set)")


if __name__ == "__main__":
    main(sys.argv[1])

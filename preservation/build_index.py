"""build_index — type the cross-references, then build <project>/index.db.

Usage: python -m preservation.build_index <project_dir> [--db PATH]
Run after ingest (and after read_scans for the scanned sheets). Safe to rerun:
the database is rebuilt from the page files every time.
"""
from __future__ import annotations

import argparse
import json
import os

from . import archive, type_refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project_dir")
    ap.add_argument("--db", default=None)
    a = ap.parse_args()
    pdir = os.path.abspath(a.project_dir)
    type_refs.main(pdir)
    conn = archive.ingest_project(pdir, a.db)
    s = archive.summary(conn)
    print("SUMMARY:", json.dumps(s))
    for (m,) in conn.execute("SELECT message FROM issues"):
        print("  issue:", m)
    pending = [r[0] for r in conn.execute(
        "SELECT s.sheet_no FROM sheets s WHERE s.kind='sheet' AND NOT EXISTS "
        "(SELECT 1 FROM texts t WHERE t.sheet_no=s.sheet_no AND t.src='eyes')")]
    if pending:
        print(f"  pending eyes ({len(pending)} scanned sheets with no transcription yet): "
              + ", ".join(pending))


if __name__ == "__main__":
    main()

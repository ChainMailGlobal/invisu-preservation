# INViSU Preservation Reader

**Ask a Library of Congress drawing set a question. Get the sheet.**

The Library of Congress holds about 55,000 public-domain documentation sets of
American buildings — the Historic American Buildings Survey (HABS), Historic
American Engineering Record (HAER) and Historic American Landscapes Survey
(HALS). They are scans of hand-lettered measured drawings plus survey
photographs and typed reports. None of them can be asked a question. This
reader makes one of them answerable, with every answer carrying the sheet it
came from, and it refuses to answer when the set does not contain the answer.

Built by [INViSU AI](https://github.com/ChainMailGlobal) for the
**Nebius x NVIDIA Global AI Hackathon**, track **Best Apps and Agents**.

## Nebius + NVIDIA usage

Every model call in this repository goes to **Nebius Token Factory**
(`https://api.tokenfactory.nebius.com/v1`) and every model is an **NVIDIA
Nemotron** open model:

| Seat | Model (Token Factory id) | Job |
|---|---|---|
| Eyes | `nvidia/Nemotron-3.5-Super-VL` | reads each scanned sheet: title, description, every legible piece of hand lettering with a box; captions the photographs |
| Brain | `nvidia/Nemotron-3-Ultra-550b-a55b` | answers a question over the evidence pack built from the index, with page receipts, in one of four allowed outcomes |

There is no other inference provider, no GPU and no training in this project.
`preservation/tokenfactory.py` is the only network client: it writes one
ledger line per call (tokens, latency, dollars) to `docs/cost_ledger.jsonl`,
enforces a hard spend cap (`TF_CAP_USD`, default $5) and stops on HTTP 402.

## Demo set: Iolani Palace, Honolulu (HABS No. HI-1, loc.gov record hi0047)

Fetched from loc.gov record `hi0047` (the sheets and data pages carry HABS
No. HI-1). The set as indexed here is **85 pages**:

- 5 PDF pages — the HABS photograph index (caption pages) and the written data
  pages, with their own text layer
- 23 scanned measured-drawing sheets — a title sheet and 22 numbered sheets,
  surveyed 1964–66, several redrawn from 1903 plans (the sheets say so)
- 57 survey photographs

Questions the demo is built to answer, each with sheet receipts:
*where is the throne room* · *which sheets show the Richards Street elevation*
· *what does sheet 12 reference* — and a question whose answer is not in the
set, which must come back as **NOT IN THE SET**.

## How it works

```
loc.gov files ──> ingest ──> pages N.png + N.scene.json
                              │
          Nemotron-3.5-Super-VL (Token Factory) reads each scanned sheet
                              │  title · description · every text with a box
                              ▼
                 type_refs: "SHEET 7 OF 22" self-numbers,
                            "SEE SHEET 12" -> typed reference to that page
                              ▼
                 build_index: SQLite — sheets, texts, references,
                              cross-reference check (unresolved targets)
                              ▼
   question ──> evidence pack (inventory · references · check · term hits ·
                full text of every page in evidence order, under a budget)
                              ▼
          Nemotron-3-Ultra (Token Factory) ──> ONE of four outcomes
```

The four outcomes the agent may return — and nothing else:

| Outcome | Meaning |
|---|---|
| `ANSWERED` | supported by text in the pack; every claim cites `[PG-NN]` and quotes the text relied on |
| `ANSWERED_FROM_MEMORY` | the set does not contain it; general knowledge, dated, flagged as not confirmed by the set |
| `NOT_IN_THE_SET` | the question is about this set but nothing read answers it; names the closest pages checked |
| `UNKNOWN_ENTITY` | the question names a building, sheet or thing that is not this set |

Receipts are verified in code, not trusted: a cited page that is not in the
index is flagged and the result is marked unverified. Numbers, areas, dates and
sheet numbers are never estimated — in the `ANSWERED` outcome they may only be
quoted from the pack.

## Setup

Python 3.11+ (tested on 3.13), no GPU.

```bash
git clone https://github.com/ChainMailGlobal/invisu-preservation
cd invisu-preservation
pip install -r requirements.txt
cp .env.example .env            # put your Token Factory key in TOKEN_FACTORY_API_KEY
```

A Token Factory key comes from https://tokenfactory.nebius.com. The `.env`
file is git-ignored; the key is read from the environment or from `.env`.

## Run

Ask the demo set (the index is in the repo; the first three questions need
the scanned sheets read, see Status):

```bash
python -m preservation.agent data/iolani-palace "where is the throne room"
python -m preservation.agent data/iolani-palace "which sheets show the Richards Street elevation"
python -m preservation.agent data/iolani-palace "what does sheet 12 reference" --save docs/transcripts/sheet12.md
python -m preservation.agent data/iolani-palace "where is the throne room" --dry-run   # prints the evidence pack, no model call
```

Build (or rebuild) the demo set from the LOC files:

```bash
# 1. pages: PDFs keep their text layer, TIFF/JPEG scans start empty
python -m preservation.ingest hi0047cap.pdf   data/iolani-palace --name "Iolani Palace (HABS HI-1)"
python -m preservation.ingest hi0047data.pdf  data/iolani-palace
for f in sheet_000*.tif; do python -m preservation.ingest "$f" data/iolani-palace; done
for f in *pv.jpg;        do python -m preservation.ingest "$f" data/iolani-palace; done

# 2. eyes: read one sheet first and look at what came back, then the rest
python -m preservation.read_scans data/iolani-palace --only 11
python -m preservation.read_scans data/iolani-palace
python -m preservation.photo_index data/iolani-palace          # captions the photographs

# 3. references + index
python -m preservation.build_index data/iolani-palace

# cost line, from the ledger
python -m preservation.tokenfactory
```

Any other HABS/HAER/HALS record works the same way: download its drawings
(TIFF), photographs (JPEG) and PDFs from loc.gov into a folder and run the
three steps against a new `data/<record>` directory.

## Web app

One FastAPI service and one static page: the 85 pages on the left as
thumbnails with ids and titles, the selected page in the middle with the cited
lettering boxed, and on the right the question, the outcome label, the answer
and clickable receipts that jump to the cited page.

```bash
uvicorn app.server:app --reload --port 7860      # http://localhost:7860
```

It runs from the committed `index.db` and PNGs. When the model cannot be
called (no key, Token Factory 402, spend cap) the answer panel shows
`MODEL UNAVAILABLE` with the reason and the index hits still work — the page
never crashes on a missing model. `AGENT_DISABLED=1` keeps it index-only on
purpose.

### Hugging Face Space (static demo)

Docker Spaces need a paid plan, so the public demo is a free **static** Space:
the same page, fed by exported JSON, with search in the browser and no model
call ("Ask" labels the outcome MODEL UNAVAILABLE and still shows the index
hits). Live: https://cre808ive-invisu-preservation.static.hf.space/ — deep links
`#PG-14` (select a page) and `?q=throne%20room` (run a search).

```bash
python -m preservation.export_static   # data/ + index.db -> site/ (JSON, images, index.html)
./deploy_space.sh                      # hf repo create (static) + hf upload site/ — needs `hf auth login`
```

The full app — Nemotron-3.5-Super-VL reading, Nemotron-3-Ultra answering via
Nebius Token Factory — runs locally with `uvicorn` (above) or anywhere the
`Dockerfile` runs. The UI is one file that detects which mode it is in.

## Cost

`docs/cost_ledger.jsonl` holds one line per model call. Token counts come from
the API response; dollars are computed from the `PRICES` table in
`preservation/tokenfactory.py`. Prices for the two models used here were not
yet confirmed from the Token Factory price list at the time of writing, so the
ledger records tokens and leaves `usd` null until the table is filled in —
the cost line never invents a number.

## Status — 2026-10-27

Done and verified locally:

- ingest of the LOC files: 5 PDF pages with 860 vector words, 23 scanned sheets
  (lossless 1-bit PNG), 57 photographs with captions from an earlier pass
- index built: 85 pages, typed-reference pass, cross-reference check, agent
  evidence pack (`--dry-run`)
- the Token Factory client, ledger and cap; both model ids confirmed present
  on `GET /v1/models`
- web app (FastAPI + one page) tested against the committed index with the
  model unavailable; thumbnails and 2400 px view renditions committed
- static demo exported and deployed to a free Hugging Face static Space:
  https://cre808ive-invisu-preservation.static.hf.space/ (browse, search, deep links;
  no model call); `Dockerfile` kept for running the full app elsewhere

Blocked — the Token Factory account answered **HTTP 402
`credit_balance_exhausted`** on the first chat call (the smallest model fails
the same way, so it is the account, not the model; the Nebius AI Studio key
answers 402 as well). Until credits are added:

- the 23 scanned sheets have **no transcription yet** (the `texts` table has
  zero `eyes` rows); searches over the drawings return only photo captions and
  the PDF pages
- the agent has **not** been run against Nemotron-3-Ultra; the four
  transcripts in `docs/transcripts/` are not there yet
- whether Nemotron-3.5-Super-VL needs `chat_template_kwargs.enable_thinking=false`
  is untested (`--thinking off` is one flag away)

Resume, in order, once the account has credits: `read_scans --only 11`, look
at the output, `read_scans`, `build_index`, then the four agent questions with
`--save`.

## Attribution and license

- Source documents: Historic American Buildings Survey, Library of Congress
  Prints and Photographs Division, HABS No. HI-1 / loc.gov record hi0047 (Iolani
  Palace). HABS/HAER/HALS
  documentation is in the public domain. Files are fetched from loc.gov; the
  pages in `data/iolani-palace/` are reproduced only for this demo set and
  nothing else is redistributed.
- Lineage: the page index and cross-reference check descend from INViSU's public
  [PlanGraph](https://github.com/ChainMailGlobal/plangraph) repository (MIT).
- Not in this repository: INViSU's Spatial Memory learning layer (verified by
  MAG), its fine-tuned perception adapters, and its measurement tools. This
  repo is the open method on open models.
- Code: MIT, see `LICENSE`.

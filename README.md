# iNViSU Preservation Reader

**Ask a Library of Congress drawing set a question. Get the sheet.**

The Library of Congress holds about 55,000 public-domain documentation sets of
American buildings — the Historic American Buildings Survey (HABS), Historic
American Engineering Record (HAER) and Historic American Landscapes Survey
(HALS). They are scans of hand-lettered measured drawings plus survey
photographs and typed reports. None of them can be asked a question. This
reader makes one of them answerable, with every answer carrying the sheet it
came from, and it refuses to answer when the set does not contain the answer.

Built by [iNViSU AI](https://github.com/ChainMailGlobal) for the
**Nebius x NVIDIA Global AI Hackathon**, track **Best Apps and Agents**.

## Nebius + NVIDIA usage

Every model call in this repository goes to Nebius and every model is an
**NVIDIA Nemotron** open model. One OpenAI-compatible client,
`preservation/tokenfactory.py`, is the only network code; it is repointed by
environment variables, writes one ledger line per call (tokens, latency,
dollars, provider) to `docs/cost_ledger.jsonl`, enforces a hard spend cap and
stops on HTTP 402.

| Seat | Designed for (Token Factory) | What ran the live demo (Nebius AI Cloud, one L40S) | Job |
|---|---|---|---|
| Eyes | `nvidia/Nemotron-3.5-Super-VL` | `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8` | reads each scanned sheet: title, description, every legible piece of hand lettering with a box |
| Brain | `nvidia/Nemotron-3-Ultra-550b-a55b` | the same Omni endpoint, reasoning mode on | answers a question over the evidence pack built from the index, with page receipts, in one of four allowed outcomes |

Why two columns: on build night Token Factory answered `402
credit_balance_exhausted`, so the set was read on a **Nebius AI Cloud
Serverless AI endpoint** we created in the console — the stock
`vllm/vllm-openai:v0.20.0` image serving the Omni FP8 weights on one
preemptible NVIDIA L40S (48 GB, $0.77/hour on the console estimate). NVIDIA's
model card names a single L40S as that build's minimum GPU. Same client, same
JSON contract, same ledger: `docs/RUN_AI_CLOUD_ENDPOINT.md` is the recipe.
There is no other inference provider and no training in this project.

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
· *what does HABS sheet 12 reference* — and a question whose answer is not in the
set, which must come back as **NOT IN THE SET**.

## How it works

```
loc.gov files ──> ingest ──> pages N.png + N.scene.json
                              │
          Nemotron eyes (Omni on a Nebius AI Cloud endpoint; Super-VL on
          Token Factory by design) read each scanned sheet, then four quadrants
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
          Nemotron brain (Omni, reasoning on; Ultra on Token Factory by
          design) ──> ONE of four outcomes, receipts verified in code
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

To run against a Nemotron you serve yourself on a Nebius AI Cloud Serverless
endpoint (the way the demo was read), set these instead — nothing else changes:

```bash
export TOKEN_FACTORY_BASE_URL="https://<your endpoint>/v1"
export INFERENCE_API_KEY="<the endpoint's bearer token>"
export INFERENCE_PROVIDER="ai-cloud-l40s"            # written on every ledger row
export EYES_MODEL="nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8"
export BRAIN_MODEL="$EYES_MODEL"
```

## Run

Ask the demo set (the index is in the repo; the first three questions need
the scanned sheets read, see Status):

```bash
python -m preservation.agent data/iolani-palace "where is the throne room" --thinking on --max-tokens 4000
python -m preservation.agent data/iolani-palace "which sheets show the Richards Street elevation" --thinking on --max-tokens 4000
python -m preservation.agent data/iolani-palace "what does HABS sheet 12 reference" --thinking on --max-tokens 4000 --save docs/transcripts/sheet12.md
python -m preservation.agent data/iolani-palace "where is the throne room" --dry-run   # prints the evidence pack, no model call
```

Build (or rebuild) the demo set from the LOC files:

```bash
# 1. pages: PDFs keep their text layer, TIFF/JPEG scans start empty
python -m preservation.ingest hi0047cap.pdf   data/iolani-palace --name "Iolani Palace (HABS HI-1)"
python -m preservation.ingest hi0047data.pdf  data/iolani-palace
for f in sheet_000*.tif; do python -m preservation.ingest "$f" data/iolani-palace; done
for f in *pv.jpg;        do python -m preservation.ingest "$f" data/iolani-palace; done

# 2. eyes: read one sheet first and LOOK at what came back, then the rest, then quadrants
#    (--rep-penalty 1.05 stops Omni's repetition loop at temperature 0; --thinking off)
python -m preservation.read_scans data/iolani-palace --only 11 --thinking off --rep-penalty 1.05 --max-tokens 6000
python -m preservation.read_scans data/iolani-palace --thinking off --rep-penalty 1.05 --max-tokens 6000
python -m preservation.read_scans data/iolani-palace --tiles --thinking off --rep-penalty 1.05
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

The full app — Nemotron reading and answering through the client above — runs
locally with `uvicorn` (above) or anywhere the `Dockerfile` runs. The UI is one
file that detects which mode it is in.

## Cost

`docs/cost_ledger.jsonl` holds one line per model call (tokens, latency,
provider) plus `gpu_session` lines for self-served endpoints (lifetime in
minutes × the hourly rate; the GPU bills from creation to deletion, not per
call). Token Factory dollars come from the `PRICES` table in
`preservation/tokenfactory.py`; entries left `None` make the ledger record
`usd: null` rather than a guessed number. `python -m preservation.tokenfactory`
prints the cost line; `--gpu-session NAME --rate R --minutes M` records an
endpoint's lifetime.

## Status — 2026-10-28

Done and verified, from the committed ledger and index:

- ingest of the LOC files: 5 PDF pages with 860 vector words, 23 scanned sheets
  (lossless 1-bit PNG), 57 photographs with captions from the August pass
- **all 23 scanned sheets read** by Nemotron-3-Nano-Omni (FP8) on one L40S:
  every full-sheet call finished on `stop`, every sheet has a title, 21 of 23
  carry their own "SHEET N OF 22" number; 1,818 text entries from
  the scans after the quadrant pass, 47 typed cross-references, 7
  unresolved (all "SEE SHEET 22" — this LOC record has no sheet 22)
- the four agent transcripts in `docs/transcripts/`, reasoning mode on,
  receipts verified against the index: {{TRANSCRIPT_SUMMARY}}
- web app (FastAPI + one page) run against the live endpoint; thumbnails and
  2400 px view renditions committed
- static demo exported and deployed to a free Hugging Face static Space:
  https://cre808ive-invisu-preservation.static.hf.space/ (browse, search, deep links;
  no model call); `Dockerfile` kept for running the full app elsewhere
- endpoint time: {{GPU_MINUTES}} minutes of one preemptible L40S, {{GPU_USD}}
  on the console rate; {{N_CALLS}} model calls, {{N_TOKENS}} tokens

Not done: Token Factory still answers **HTTP 402 `credit_balance_exhausted`**
(the Nebius AI Studio key as well), so Nemotron-3.5-Super-VL and
Nemotron-3-Ultra — the models this repo was written for — have not been
exercised. The moment credits exist, the same four questions run on Ultra with
`INFERENCE_PROVIDER=token-factory`; the transcripts say which model answered.

## Limitations and failure cases

Stated plainly, because a reader that refuses to invent should also say what it
cannot do.

- One structure in the demo set (Iolani Palace). The pipeline is generic; the
  evidence is not yet.
- The static Space never calls a model: it is index search over exported JSON.
  The four outcomes, the receipts and their verification exist only in the
  local app (and in the video).
- Scanned sheets are read at 1,400 px on the long side, so small hand lettering
  can be missed. Mitigation: a quadrant pass (`read_scans --tiles`) re-reads a
  sheet in four higher-resolution tiles, at four calls per sheet.
- Model boxes are normalized (fractions, percent or pixels — whatever the model
  returned), but their precision is unverified until measured against our
  vector-truth harness. Today they are good enough to point at lettering, not
  to measure from.
- English only: prompts, stop-word list and the transcription target.
- Typed references depend on each sheet's own "SHEET N OF 22" lettering being
  read. A sheet whose self-number was missed cannot be a reference target; the
  cross-reference check reports that instead of guessing.
- The four-outcome contract is enforced by the prompt plus code-side receipt
  verification. An answer whose receipt fails verification is shown as
  unverified, not hidden — and the model can still be wrong inside a page that
  verifies.
- Photo captions come from the August read on Token Factory (Nemotron-3-Nano-
  Omni, since removed from that catalog); they were not re-read.
- The live run's brain is a 30B-A3B model on one L40S, not Nemotron-3-Ultra.
  It answered with verified receipts, but on "where is the throne room" it
  cited the interior sheets and missed the floor plan that places the room. A
  larger brain is the design, not a claim.
- Quadrant re-reads produce cut words at quadrant edges ("CENTR", "SEE SH");
  they are indexed as read.
- Not built for accessibility; no claim is made.
- Failure cases surfaced by the real read: sheet 11's repetition loop (eighty
  copies of one dimension string until the token ceiling, before
  `--rep-penalty` existed); 92 quadrant replies in bare-array JSON that the
  first parser dropped, reported as "+0" per sheet; boxes mixing pixel and
  fraction scales; sheets 6 and 18 without a readable self-number; seven typed
  references to a sheet 22 the record does not contain, reported as issues
  rather than resolved by guessing.

## Attribution and license

- Source documents: Historic American Buildings Survey, Library of Congress
  Prints and Photographs Division, HABS No. HI-1 / loc.gov record hi0047 (Iolani
  Palace). HABS/HAER/HALS
  documentation is in the public domain. Files are fetched from loc.gov; the
  pages in `data/iolani-palace/` are reproduced only for this demo set and
  nothing else is redistributed.
- Lineage: the page index and cross-reference check descend from iNViSU's public
  [PlanGraph](https://github.com/ChainMailGlobal/plangraph) repository (MIT).
- Not in this repository: iNViSU's Spatial Memory learning layer (verified by
  MAG), its fine-tuned perception adapters, and its measurement tools. This
  repo is the open method on open models.
- Code: MIT, see `LICENSE`.

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

**Demo video (2:54):** https://youtu.be/3TxEhdhZjrA — recorded from the running app by
`tools/make_video.py`; every answer on screen is a live call.
**Static demo:** https://cre808ive-invisu-preservation.static.hf.space/

## Nebius + NVIDIA usage

Every model call in this repository goes to Nebius and every model is an
**NVIDIA Nemotron** open model. One OpenAI-compatible client,
`preservation/tokenfactory.py`, is the only network code; it is repointed by
environment variables, writes one ledger line per call (tokens, latency,
dollars, provider) to `docs/cost_ledger.jsonl`, enforces a hard spend cap and
stops on HTTP 402.

Model ids are exactly as Token Factory's `GET /v1/models` listed them on 2026-10-27 and 2026-10-28 (the suffixes are the catalog's, not a custom build).

| Seat | Designed for (Token Factory) | What ran | Job |
|---|---|---|---|
| Eyes | `nvidia/Nemotron-3.5-Super-VL` | `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8` | reads each scanned sheet: title, description, every legible piece of hand lettering with a box |
| Brain | `nvidia/Nemotron-3-Ultra-550b-a55b` | **Ultra on Token Factory** in the submitted video (credits landed the same day); the Omni endpoint, reasoning on, before that | answers a question over the evidence pack built from the index, with page receipts, in one of four allowed outcomes |

Why two columns: on build night Token Factory answered `402
credit_balance_exhausted`, so the set was read on a **Nebius AI Cloud
Serverless AI endpoint** we created in the console — the stock
`vllm/vllm-openai:v0.20.0` image serving the Omni FP8 weights on one
preemptible NVIDIA L40S (48 GB, $0.77/hour on the console estimate). NVIDIA's
model card names a single L40S as that build's minimum GPU. Same client, same
JSON contract, same ledger: `docs/RUN_AI_CLOUD_ENDPOINT.md` is the recipe.
Credits arrived later that day; Nemotron-3-Ultra on Token Factory then took the
brain seat with the index unchanged, which is the tiering the track describes:
Nano for the everyday reads on a per-second GPU, Ultra for the reasoning.
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

Receipts are verified in code, not trusted, in two steps: a cited page that is
not in the index is flagged and the result is marked unverified, and every span
the answer quotes must appear on a cited page or the result is marked
unverified with the missing quote named. Numbers, areas, dates and
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
  receipts verified against the index: throne room ANSWERED (PG-24, HABS sheet 17), Richards Street elevation ANSWERED (PG-14, PG-18), HABS sheet 12 references ANSWERED (sheet 21, receipt PG-19), balustrade wood species NOT_IN_THE_SET (PG-13, PG-14, PG-28 checked)
- web app (FastAPI + one page) run against the live endpoint; thumbnails and
  2400 px view renditions committed
- static demo exported and deployed to a free Hugging Face static Space:
  https://cre808ive-invisu-preservation.static.hf.space/ (browse, search, deep links;
  no model call); `Dockerfile` kept for running the full app elsewhere
- self-review: `tools/self_review.py` scored this package against the organizers'
  published rubric and tips with Nemotron 3 Ultra and had Nemotron 3.5 Super-VL
  review the video frame by frame (runs kept locally). Applied from it: the
  quote check on receipts, the Submission Period provenance statement, the
  description leading with who it is for, the static demo pointing at the video.
  Declined: a re-record over a header the vision model misread as "Nexus Token
  Factory".
- endpoint time: about 124 minutes of one preemptible L40S, about $1.59
  on the console rate; 253 model calls, 1,857,971 tokens

Token Factory, once the hackathon credits landed later the same day:

- **Nemotron-3-Ultra** answered the same four questions
  (`docs/transcripts/token_factory/`): median 4.7 s per ~30k-token question,
  reasoning returned separately, every receipt verified. The Richards Street
  answer names both sheets and why, the sheet-12 answer quotes both links, the
  refusal lists what it checked. This is the brain in the submitted video.
- **Nemotron-3.5-Super-VL** read the same 23 sheets into
  `data/iolani-palace-supervl/` (reasoning on, which read better than off).
  `python tools/compare_readers.py data/iolani-palace data/iolani-palace-supervl`
  prints the two columns: Omni on one L40S, 1,818 entries, 22/23 self-numbers,
  47 reference letterings, median 13.3 s per sheet, every call finished;
  Super-VL on Token Factory, 1,779 entries, 19/23, 37, median 19.5 s, 28 of 117
  calls at the token ceiling while reasoning; titles agree on 18 of 23. On this
  set, at these settings. It is a measurement, not a ranking.
- Ledger: 19 Ultra calls (565k in / 15k out) and 117 Super-VL calls (196k in /
  548k out). Token Factory publishes no machine-readable price, so those rows
  carry `usd: null`; the console is the receipt.

## Limitations and failure cases

Stated plainly, because a reader that refuses to invent should also say what it
cannot do.

- Two sets, four records: Iolani Palace in depth, and three small Lahaina
  records read the same way. A county-scale batch is the next step, not a claim.
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
- Two brains are on record. The 30B Omni on one L40S answered with verified
  receipts but, on "where is the throne room", cited the interior sheets and
  missed the floor plan; Ultra on Token Factory, the brain in the submitted
  video, cited the floor plan with its lettering. A verified page is not a
  verified reading: the second check (every quoted span must appear on a
  cited page) catches an invented quote, not a wrong one.
- On "what does HABS sheet 12 reference" the brain answered the reverse
  direction until the evidence pack named incoming versus outgoing links; one
  command-line run without a page open still flipped. The reader comparison
  is one set at one resolution and two settings; it says what was measured.
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

## Second set: Lahaina, three buildings the 2023 fire burned to their walls

On August 8, 2023 the Lahaina wildfire destroyed most of the Lahaina Historic
District. Three of its buildings had been measured by HABS in 1966; each now
stands as outer walls only. The same pipeline, unchanged, read all three on Token
Factory (Nemotron-3.5-Super-VL, reasoning on) on the night of October 28:

| Building | Built | HABS | Pages | Sheets | Entries from scans | After the fire | Static demo |
|---|---|---|---|---|---|---|---|
| Old Lahaina Courthouse | 1859, rebuilt 1925 | HI-9 (loc.gov hi0014) | 17 | 8 | 732 | outer walls standing, roof and interior destroyed | https://cre808ive-invisu-lahaina-courthouse.static.hf.space/ |
| Master's Reading Room | 1834 | HI-13 (hi0015) | 10 | 5 | 487 | coral and stone walls only | https://cre808ive-invisu-lahaina-reading-room.static.hf.space/ |
| Hale Aloha Church | 1858 | HI-10 (hi0017) | 16 | 6 | 506 | outer walls standing; roof, bell tower and interior destroyed | https://cre808ive-invisu-lahaina-hale-aloha.static.hf.space/ |

(Condition after the fire: the Lahaina Historic District record and NPR's report of
August 16, 2023; the Master's Reading Room from the Maui Historic Trust as quoted
by the Honolulu Star-Advertiser.)

Transcripts in `docs/transcripts/lahaina/` (Nemotron-3-Ultra on Token Factory,
receipts and quotes verified). "What are the walls built of", asked of the
courthouse, answers from the drawings: "ORIGINAL CORAL WALLS 21\" THICK" and
"CORAL AND RUBBLE WALLS WITH CEMENT PLASTER FINISH" (HABS sheets 8 and 5–7), the
walls that survived. "Where is the bell tower and how tall is it", asked of Hale
Aloha, finds the bell-tower elevation on sheet 2 and says plainly that no single
overall height is lettered. "What happened in August 2023", asked of each set,
comes back NOT IN THE SET: the drawings end in 1966, and the reader does not
invent what it was not given.

Every sheet's own "SHEET N OF M" number was read; three were misread (a 5 of 5
read as 8 of 10, a 3 of 6 as 5 of 6, a 2 of 6 as 2 of 5). These sets carry no
typed cross-references, so nothing resolved through them. Monticello (HABS
VA-241, 32 sheets) was fetched as a candidate second set and not used.

## What existed before, and what was built during the Submission Period

The page index and the cross-reference check descend from our public
[PlanGraph](https://github.com/ChainMailGlobal/plangraph) repository (MIT,
August 2026). Everything else in this repository was built on October 27–28,
2026, inside the Submission Period: the Nemotron scan reader and its quadrant
pass, the typed-reference pass, the four-outcome agent with receipt and quote
verification, the evidence pack, the FastAPI app and its static export, the
Nebius AI Cloud endpoint run, the Token Factory runs, the reader comparison, the
video recorder and the self-review tool. The commit history is the record.

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

# Devpost submission text — paste-ready

Fill every `{{placeholder}}` from the real read (README Status, `docs/transcripts/`,
`docs/cost_ledger.jsonl`) before pasting. Nothing in braces may be guessed.

---

## Title

iNViSU Preservation Reader

## Tagline

Ask a Library of Congress drawing set a question. Get the sheet.

## Track

Best Apps and Agents

## Links

- Repo (MIT): https://github.com/ChainMailGlobal/invisu-preservation
- Demo (static: browse, search, deep links — no model call): https://cre808ive-invisu-preservation.static.hf.space/
- The model-backed app runs locally from the repo (README → Run); the live answers are in the video and in `docs/transcripts/`
- Video: {{YOUTUBE_URL}}

## Inspiration

The Library of Congress holds about 55,000 public-domain documentation sets of
American buildings — the Historic American Buildings Survey and its engineering
and landscape siblings. Measured drawings, hand-lettered, scanned at 400 dpi;
survey photographs; typed data pages. They are the primary record of what the
country built. Not one of them can be asked a question: the drawings have no
text layer, the lettering is by hand, and the cross-references are words on the
sheet ("SEE SHEET 12"), not links. Preservation architects, historians and the
people who maintain these buildings read them the way they were read in 1964 —
sheet by sheet, by eye.

We work on reading construction documents for a living. The question was
whether an open vision model and an open reasoning model, on a pay-per-token
cloud, could make one of these sets answerable without a GPU, without
training, and without ever inventing a sheet.

## What it does

Pick Iolani Palace, Honolulu — HABS No. HI-1, loc.gov record hi0047: 85 pages
(5 caption and data pages, 23 scanned drawing sheets from the 1964–66 survey,
several redrawn from 1903 plans, and 57 photographs). Ask it a question.

- "where is the throne room" → **ANSWERED**, with the pages it relied on as
  clickable receipts; the lettering it used is boxed on the sheet
- "which sheets show the Richards Street elevation" → the sheets, with receipts
- "what does sheet 12 reference" → the typed cross-references on that sheet,
  and what the cross-reference check says about them
- a question the set does not answer → **NOT IN THE SET**, with the pages it
  checked

Exactly four outcomes are allowed: answered with receipts, answered from
memory with its date (flagged as not confirmed by the set), not in the set,
unknown entity. Receipts are verified in code: a cited page that is not in the
index is flagged and the answer is marked unverified. Numbers, areas, dates and
sheet numbers are never estimated.

Read by the model, not typed by us: {{N_TEXT_ENTRIES}} text entries and
{{N_TITLES}} sheet titles across the 23 scanned sheets.

## How we built it

Everything runs on **Nebius Token Factory** and every model is an **NVIDIA
Nemotron** open model:

- **`nvidia/Nemotron-3.5-Super-VL`** is the eyes. Each scanned sheet (1-bit TIFF
  from loc.gov, rendered to PNG) goes to the model once with a STRICT-JSON
  prompt: title, 2–4 sentence description, every legible text with a box in
  image fractions. Box scales are normalized (the model may answer in
  fractions, percent or pixels), truncated JSON is salvaged at the last complete
  item, and junk boxes are detected so a bad page is re-read, not indexed.
- **`nvidia/Nemotron-3-Ultra-550b-a55b`** is the brain. For each question the
  index builds an evidence pack — page inventory, typed references, the
  cross-reference check, term hits, then the full text of every page in evidence
  order under a character budget (anything dropped is named) — and the model
  must answer in one of the four outcomes with `[PG-NN]` receipts.
- The index is SQLite: `sheets`, `texts` (vector words from the PDFs, model
  transcriptions from the scans, photo captions), `findings` (typed "SEE SHEET
  N" references mapped through each sheet's own "SHEET N OF 22" lettering) and
  `issues` (every reference whose target is not in the set).
- One client talks to Token Factory. It writes a ledger line per call (tokens,
  latency, dollars), enforces a hard spend cap and stops on HTTP 402.
- The app is FastAPI plus one static page. The public demo is that same page
  exported to a free Hugging Face static Space (browse, search, deep links; no
  model call) because Docker Spaces need a paid plan; the UI detects which mode
  it is in. Dependencies: pymupdf, pillow, fastapi, uvicorn. No GPU, no training,
  no other inference provider.

Lineage: the index and cross-reference check descend from our public PlanGraph
repository (MIT).

## Challenges

- **The vision model we had used was removed.** Our August reader ran on
  `nvidia/Nemotron-3-Nano-Omni`; by October it was gone from `GET /v1/models`
  with no deprecation we saw. We moved to Nemotron-3.5-Super-VL and had to
  re-verify everything: JSON compliance, box scale, whether it needs
  `chat_template_kwargs.enable_thinking=false` the way Omni did
  ({{SUPER_VL_THINKING_FINDING}}).
- **Hand lettering on 400-dpi 1-bit scans.** A 9,360×7,584 px sheet has to be
  downsampled for the wire; small lettering goes first. We read at 1,400 px and
  keep a quadrant pass for sheets whose read is thin. {{SUPER_VL_QUALITY_NOTE}}
- **Credits.** On the night we started the build the Token Factory account
  answered `402 credit_balance_exhausted` on the first call — and so did the
  separate Nebius AI Studio pot. We built everything that needs no model call
  (ingest, index, agent, app, Space packaging) and wrote a resume runbook, then
  finished the read once credits were live. The app degrades on purpose: with
  no model it still searches the index and labels the model unavailable rather
  than failing.
- **Not inventing.** A reasoning model will happily cite "sheet 9" because it
  sounds right. The four-outcome contract plus code-side receipt verification is
  what makes the refusal ("not in the set") a real outcome instead of a prompt
  suggestion.

## Accomplishments we are proud of

A public-domain drawing set that answers questions with receipts, on open
models, for {{TOTAL_USD}} of inference ({{N_CALLS}} calls, {{N_TOKENS}} tokens —
from the committed ledger). And a reader that says "not in the set" when the set
does not say.

## What we learned

{{LESSONS — two or three sentences from the transcripts: e.g. how Super-VL handled
hand lettering vs. the earlier Omni read, where Ultra's four-outcome discipline held
and where it needed the code-side check.}}

## What's next

The same three steps — ingest, read, index — work on any HABS/HAER/HALS record.
Next is a batch runner over loc.gov record ids, so a preservation office can
point at its county and get every set answerable; then the verified-outcome
layer we run in our product (iNViSU Spatial Memory, verified by MAG) on top,
so answers that a human confirmed are remembered across sets. The eyes stay
open models on Token Factory; the sets stay public domain.

## Feedback for Nebius and NVIDIA

**Nebius Token Factory.** (1) Model availability changed under us: a model id we
had built on (`Nemotron-3-Nano-Omni`) disappeared from `/v1/models` between
August and October with no deprecation header, changelog entry or email we
found. A `deprecation`/`sunset` header on responses, or a dated changelog for the
model list, would have saved a rewrite. (2) The 402 experience: both Token
Factory and AI Studio return `credit_balance_exhausted` only when you make a
paid call; there is no balance endpoint and no remaining-credit header, so a
script cannot check before it spends and a dashboard visit is the only way to
know. A `GET /v1/balance` (or `x-credits-remaining` on every response) would
let a cost cap be enforced on the client side. (3) Pricing for
`Nemotron-3.5-Super-VL` and `Nemotron-3-Ultra-550b-a55b` is not
machine-readable from the API or an unauthenticated page; a `pricing` field on
`/v1/models` would let ledgers compute dollars without a human copying numbers.
(4) Latency: {{TF_LATENCY_NOTE — median seconds per 1,400-px sheet read on Super-VL
and per ~30k-token Ultra question, from the ledger}}. (5) What worked: the
OpenAI-compatible surface meant the whole project is `urllib` and JSON; no SDK.

**NVIDIA Nemotron.** (1) Super-VL on hand lettering: {{SUPER_VL_BEHAVIOUR —
JSON compliance, whether enable_thinking=false was needed, box scale it chose,
transcription quality vs. the earlier Omni read}}. (2) Ultra's adherence to a
four-outcome contract: {{ULTRA_OUTCOME_NOTE — did it ever cite a page not in the
pack, did NOT_IN_THE_SET fire cleanly, reasoning tokens used}}. (3) A request: a
documented, stable JSON mode (or `response_format` support) on the VL model
would remove the truncated-JSON salvage code entirely. (4) A documentation note
on the chat template — which Nemotron ids honor `enable_thinking` and what the
default is — would have saved a test call per model.

## Built with

Python, FastAPI, SQLite, PyMuPDF, Pillow, Nebius Token Factory, NVIDIA
Nemotron-3.5-Super-VL, NVIDIA Nemotron-3-Ultra-550b-a55b, Hugging Face Spaces
(Docker), Library of Congress HABS/HAER (public domain).

# Devpost submission text — paste-ready

Every number here comes from the real read (README Status, `docs/transcripts/`,
`docs/cost_ledger.jsonl`); nothing was guessed. Final as of 2026-10-28.

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
- Video: https://youtu.be/3TxEhdhZjrA

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
- "what does HABS sheet 12 reference" → the typed cross-references on that sheet,
  and what the cross-reference check says about them
- a question the set does not answer → **NOT IN THE SET**, with the pages it
  checked

Exactly four outcomes are allowed: answered with receipts, answered from
memory with its date (flagged as not confirmed by the set), not in the set,
unknown entity. Receipts are verified in code: a cited page that is not in the
index is flagged and the answer is marked unverified. Numbers, areas, dates and
sheet numbers are never estimated.

Read by the model, not typed by us: 1,818 text entries and
23 sheet titles across the 23 scanned sheets.

## How we built it

Every model is an **NVIDIA Nemotron** open model and every call goes to Nebius,
through one OpenAI-compatible client that is repointed by environment variables.
The entry was designed for **Token Factory** (Nemotron-3.5-Super-VL as the eyes,
Nemotron-3-Ultra as the brain). On build night Token Factory answered
`402 credit_balance_exhausted`, so the live run you see in the video and in
`docs/transcripts/` was served by us on **Nebius AI Cloud Serverless AI**: one
endpoint, one **NVIDIA L40S (48 GB)**, the stock `vllm/vllm-openai:v0.20.0`
image, and **`nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8`**. NVIDIA's
model card names a single L40S as that build's minimum GPU. It is. Credits
landed later the same day, and **`nvidia/Nemotron-3-Ultra-550b-a55b` on Token
Factory** took the brain seat with the index unchanged: that is the submitted
video. Nano for the everyday reads on a per-second GPU, Ultra for the serious
reasoning, one client on both surfaces. Every step is a chained, unattended
workflow: loc.gov download, ingest, full-sheet read, quadrant re-read, dedupe,
typed cross-references, index, evidence pack, brain, code-side receipt
verification, and a second call if the model skips its outcome line.

- **Eyes.** Each scanned sheet (1-bit TIFF from loc.gov, rendered to PNG,
  1,400 px on the long side) goes to the model once with a STRICT-JSON prompt:
  title, 2–4 sentence description, every legible text with a box. A second
  pass re-reads each sheet in four higher-resolution quadrants. Box scales are
  normalized (the model answers in fractions, percent or pixels, sometimes
  mixed inside one box), truncated JSON is salvaged at the last complete item,
  a repetition loop is cut at its onset and flagged, and junk boxes are detected
  so a bad page is re-read, not indexed.
- **Brain.** For each question the index builds an evidence pack — page
  inventory, typed references, the cross-reference check, term hits, then the
  full text of every page in evidence order under a character budget (anything
  dropped is named) — and the model must answer in one of the four outcomes
  with `[PG-NN]` receipts. Reasoning mode is on; the endpoint has no reasoning
  parser, so the thinking arrives inline and the agent parses the last outcome
  block. On Token Factory, Ultra returns its reasoning separately and needs
  none of that: median 4.7 s per ~30k-token question. Every transcript names
  the model and the surface that answered; both sets are committed.
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

- **The vision model we had used was removed, then came back under our own
  control.** Our August reader ran Nemotron-3-Nano-Omni on Token Factory; by
  October that id was gone from `GET /v1/models` with no deprecation we saw. We
  rewrote for Nemotron-3.5-Super-VL, then could not call it (402). The fix was
  to serve the Omni weights ourselves on AI Cloud: same model family, now
  pinned by us, on a GPU billed by the second.
- **Hand lettering on 400-dpi 1-bit scans.** A 9,360×7,584 px sheet has to be
  downsampled for the wire; small lettering goes first. We read at 1,400 px and
  add a quadrant pass. At 1,400 px Omni read every sheet title and 21 of 23
  sheets' own "SHEET N OF 22" numbers; the quadrant pass is what catches the
  small notes, and it also produces cut words at quadrant edges.
- **Three model behaviours, found by reading the output, not the logs.** (1) At
  temperature 0 the first sheet locked into repeating one dimension string
  eighty times until the token ceiling; `repetition_penalty 1.05` cured it and
  a loop guard now cuts and flags any recurrence. (2) The quadrant prompt gets a
  bare JSON array back instead of the requested object; the first parser
  silently dropped all 92 replies and reported "+0" per sheet. Zero is a result
  that has to be read. (3) Boxes can mix pixels and fractions inside one box.
  All three are handled in `read_scans.py` and reported in the feedback below.
- **Credits.** On the night we started the build the Token Factory account
  answered `402 credit_balance_exhausted` on the first call — and so did the
  separate Nebius AI Studio pot. We built everything that needs no model call
  (ingest, index, agent, app, Space packaging), then found $9.78 on the AI
  Cloud balance, which bills GPU-seconds, not tokens. One preemptible L40S
  endpoint at $0.77 an hour read the whole set. The app degrades on purpose:
  with no model it still searches the index and labels the model unavailable
  rather than failing.
- **Not inventing.** A reasoning model will happily cite "sheet 9" because it
  sounds right. The four-outcome contract plus code-side receipt verification is
  what makes the refusal ("not in the set") a real outcome instead of a prompt
  suggestion.

## Accomplishments we are proud of

A public-domain drawing set that answers questions with receipts, on open
models, for about $1.59 of GPU time of inference (253 calls, 1,857,971 tokens —
from the committed ledger). And a reader that says "not in the set" when the set
does not say.

And a measurement the credits allowed: the same 23 sheets read by
Nemotron-3.5-Super-VL on Token Factory, scored on the same metric
(`tools/compare_readers.py`): 1,779 entries, 19 of 23 self-numbers, 37 reference
letterings, 28 of 117 calls at the token ceiling while reasoning, against the
30B Omni's 1,818, 22 and 47 on one L40S with every call finished. At these
settings, on this set. Not a ranking.

## What we learned

A 30B model on one GPU reads hand lettering well enough to index a set, and it answers well enough only when the evidence is clean and the question's own pages are resolved for it: duplicated lettering made it loop, a stray note made it answer the reverse direction, and both were fixed in the evidence pack, not in the model. Every failure we found came from reading the model's output; none showed in the logs. The four-outcome contract held on every final run, including the refusal, once a missing outcome line could be asked for in a second call.

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
- Two brains are on record. The 30B Omni on one L40S answered with verified
  receipts but, on "where is the throne room", cited the interior sheets and
  missed the floor plan; Ultra on Token Factory cited the floor plan with its
  lettering. The reader comparison is one set at one resolution and two
  settings; it says what was measured, not which model is better.
- On "what does HABS sheet 12 reference" the brain answered the reverse direction (what
  references sheet 12, from a note on sheet 20) until the evidence pack named the direction
  of each link; every run through the app then read it correctly, and one command-line run
  without a page open still flipped. Receipts verified either way: a verified page is not a
  verified reading.
- Quadrant re-reads produce cut words at quadrant edges ("CENTR", "SEE SH");
  they are indexed as read.
- Not built for accessibility; no claim is made.
- Failure cases surfaced by the real read: sheet 11's repetition loop (cut at
  entry 20 before the penalty existed); 92 quadrant replies in bare-array form
  that the first parser dropped; mixed-scale boxes; sheets 6 and 18 without a
  readable self-number (the cover sheet, and "Elevations with temporary
  additions"); seven typed references to a sheet 22 that this LOC record does
  not contain, reported as issues rather than resolved by guessing.

## What's next

The same three steps, ingest, read, index, work on any HABS/HAER/HALS record; a batch runner over loc.gov record IDs lets a preservation office point at its county and get every set answerable. The eyes get trained: Nemotron-Nano-V2-12B VL is fine-tunable on Token Factory, and we have a 228,000-box self-labeled corpus of drawing text with exact positions built for exactly that, because transcription without real localization is the gap every general vision model still has. Then the verified-outcome layer from our product, iNViSU Spatial Memory verified by MAG, so answers a human confirmed are remembered across sets. Vector drawings already need no model at all; the model is for scans and reasoning, which is what makes a small, measured Seer on an ordinary laptop the end of this road.

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
(4) What worked: the OpenAI-compatible surface meant the whole project is
`urllib` and JSON; no SDK, and the same client moved to AI Cloud by changing
four environment variables. Once funded, Token Factory was fast: Ultra answered
~30k-token questions in a median 4.7 s with reasoning returned separately, and
Super-VL read a 1,400-px sheet in a median 19.5 s with reasoning on. The first
key we tried belonged to a different organization than the one the promo landed
in; the API said only `credit_balance_exhausted`, which cost ten minutes of
probing. A 402 that names the organization would have saved them.

**Nebius AI Cloud Serverless AI** (the surface that actually ran the entry).
(5) It worked, from a browser, with no Nebius CLI (there is no Windows build;
the install script covers Ubuntu and macOS): a custom endpoint with the stock
vLLM image, a bearer token from SecretStash, one L40S, public static IP.
Status reached `Running` about five minutes after creation; vLLM served about
27 minutes after creation, the rest being the 35 GB download. Per-second
billing; the console estimate for a preemptible L40S was $0.77 an hour.
(6) "Running" means the container, not the model. For 22 minutes the tunnel
answered 404 then 503 while vLLM downloaded; a readiness signal distinct from
container state, or the model's own `/health` surfaced in the console, would
remove the guesswork. (7) Every restart re-downloads the weights into the
container disk; a mountable Hugging Face cache volume, or a "pull model to
volume" step, would cut restarts from ~25 minutes to ~2. (8) Serverless AI has
no row on the public price page; the console estimate is the only number.
(9) Latency on one L40S, from the ledger: median 13.3 s per full-sheet read (7–24 s), 6.4 s per quadrant, 10–35 s per ~30k-token question with reasoning on, plus a one-time ~27 minutes from endpoint creation to the first served token.

**NVIDIA Nemotron.** (1) Nemotron 3 Nano Omni (FP8) on hand lettering, served
by vLLM: `enable_thinking` via `chat_template_kwargs` is honored; with it off
the model returns clean STRICT-JSON for the full-sheet prompt and read every
sheet title and 21 of 23 self-numbers at 1,400 px. Three behaviours needed
code: a repetition loop at temperature 0 (fixed by `repetition_penalty 1.05`),
a bare JSON array instead of the requested object on the quadrant prompt, and
boxes that mix pixel and fraction scales. The model card's "minimum GPU (FP8):
1× L40S 48GB" held at a 65,536-token context. (1b) Nemotron-3.5-Super-VL on Token Factory honors `enable_thinking`;
with reasoning on it read titles and self-numbers correctly, with it off it
misread 21 as 2 and 11 as II. Reasoning consumed the ceiling: 28 of 117 calls
finished on `length` at 8,000 (6,000 per quadrant). It groups lettering into
fewer, longer entries, and on this set at 1,400 px it read fewer self-numbers
and reference letterings than the 30B Omni did. (2) Adherence to the four-outcome
contract with reasoning on: no run cited a page id that is not in the index; NOT_IN_THE_SET fired cleanly on the balustrade question with the three pages it checked; inline reasoning ran 3,000–16,000 characters per question; one final run omitted the OUTCOME line and stated it in a second short call, which the transcript notes. Without a reasoning
parser the thinking arrives inline before the answer; parsing from the last
outcome block made it usable, and a 900-token ceiling was not enough once
thinking was on. (3) A request: a documented, stable JSON mode (or
`response_format` support) on the VL models would remove the salvage code
entirely. (4) A documentation note on the chat template — which Nemotron ids
honor `enable_thinking` and what the default is — would have saved a test call
per model.

## Built with

Python, FastAPI, SQLite, PyMuPDF, Pillow, Nebius AI Cloud Serverless AI (L40S
endpoint), vLLM, Nebius Token Factory, NVIDIA Nemotron-3-Nano-Omni-30B-A3B
(FP8), NVIDIA Nemotron-3.5-Super-VL and Nemotron-3-Ultra (design target),
Hugging Face Spaces (static), Library of Congress HABS/HAER (public domain).

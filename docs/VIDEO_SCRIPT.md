# Demo video script — under 2:30, screen recording with voice

**Setup before recording.** Run the FULL app locally — `uvicorn app.server:app --port 7860`
with `TOKEN_FACTORY_API_KEY` set — and open `http://localhost:7860` in a clean browser
window at 110% zoom. (The public Space is the static browse/search demo and makes no
model call; the live answers must come from the local app.) Type **where is the throne
room** into the question box BEFORE recording starts; do not press Ask yet. Have the four
transcripts in `docs/transcripts/` open in a second tab in case a live call stalls.
Record at 1080p. Numbers in `{{braces}}` come from the real read — copy them from
`README.md` Status and the transcripts before recording. Never read a number that is not
on screen. Say the brand as "in-VIZ-you".

| Time | On screen — what to click | What to say |
|---|---|---|
| 0:00–0:08 | The app, question already typed. Click **Ask**. | "Where is the throne room?" |
| 0:08–0:22 | The ANSWERED label lands with its receipts. Click the first receipt, {{Q1_RECEIPT}}. The sheet opens with the lettering boxed. | "Answered — with the sheet. Nemotron-3-Ultra answered from the index. Nemotron-3.5-Super-VL read this sheet on Nebius Token Factory; the boxes are the lettering it relied on." |
| 0:22–0:32 | Hold on the boxed sheet. Cursor still. | "The Library of Congress holds about fifty-five thousand public-domain drawing sets of American buildings. Until now, none of them could be asked a question." |
| 0:32–0:50 | Scroll the left list slowly: documents, sheets, photographs. | "This is Iolani Palace, Honolulu — HABS number HI-1, Library of Congress record hi0047. Eighty-five pages: the caption and data pages, twenty-three scanned drawing sheets, fifty-seven photographs. The survey drew the sheets in 1964 and 1966; several say on their face that they were redrawn from the 1903 plans. We say the dates the sheets say." |
| 0:50–1:08 | Click **PG-14** (Richards Street elevation). Scroll the "Page text, reading order" panel. | "Nemotron-3.5-Super-VL read every scanned sheet on Token Factory — title, description, every legible piece of hand lettering with its position. Across the set: {{N_TEXT_ENTRIES}} text entries and {{N_TITLES}} titles, read by the model, not typed by us." |
| 1:08–1:28 | Click the chip **which sheets show the Richards Street elevation**. Hover each receipt. | "Which sheets show the Richards Street elevation. Nemotron-3-Ultra answers over the evidence pack the index builds: {{Q2_RECEIPTS_COUNT}} receipts — {{Q2_RECEIPTS}}. Receipts are verified in code against the index; a page the model cites that does not exist is flagged, not shown as fact." |
| 1:28–1:48 | Click the chip **what does sheet 12 reference**. Click a receipt; point at "References:" in the reading-order panel. | "What does sheet 12 reference. Historic sheets cross-reference by lettering — SEE SHEET N. We type those references, so the answer is {{Q3_SUMMARY}}, and the cross-reference check reports any target that is not in the set." |
| 1:48–2:08 | Type **{{Q4_NOT_IN_SET_QUESTION}}** and press Enter. The blue NOT IN THE SET label lands. | "And the question every archive tool gets wrong. {{Q4_SHORT}}. The set does not say — so Nemotron-3-Ultra answers: not in the set, with the pages it checked. Four outcomes, nothing else: answered with receipts, answered from memory with its date, not in the set, unknown entity." |
| 2:08–2:20 | Switch to the GitHub README (license, models table), then the public static Space for two seconds, then back to the app on the boxed throne-room sheet. | "Open method on open models: MIT on GitHub, every call through Nebius Token Factory on NVIDIA Nemotron, the documents public domain from loc.gov." |
| 2:20–2:28 | Hold on the boxed sheet. | "Nemotron on Nebius reads it today. Next, we train the eyes on Token Factory. The drawings stay public domain, and nothing invents a sheet." |

## Placeholders to fill before recording

| Placeholder | Where it comes from |
|---|---|
| `{{Q1_RECEIPT}}` | first receipt in `docs/transcripts/throne_room.md` (e.g. "PG-24, HABS sheet 17") |
| `{{N_TEXT_ENTRIES}}` | `python -m preservation.build_index data/iolani-palace` → SUMMARY `texts_eyes` (say "text entries read from the scans") |
| `{{N_TITLES}}` | count of sheets with a title in the inventory (`/api/set`, pages with kind=sheet and a title) |
| `{{Q2_RECEIPTS_COUNT}}`, `{{Q2_RECEIPTS}}` | `docs/transcripts/richards_street.md` |
| `{{Q3_SUMMARY}}` | `docs/transcripts/sheet12.md` — the referenced sheets, in the model's words |
| `{{Q4_NOT_IN_SET_QUESTION}}`, `{{Q4_SHORT}}` | the question in `docs/transcripts/not_in_set.md` that came back NOT_IN_THE_SET (candidates in `RESUME_WHEN_CREDITS.md`) |

## If a live call fails on camera

Say: "Token Factory is busy — here is the saved answer," switch to the transcript
tab, read the outcome line and the receipts, click the receipt page in the app.
Do not re-record the whole take for a transient 429.

## Do not say

Benchmark claims; "beats"; any date the sheets do not carry; the HABS number
as HI-47 (it is HI-1; hi0047 is the loc.gov record id); internal product names.

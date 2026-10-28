# Demo video script — 2:30, screen recording with voice

**Setup before recording.** Run the FULL app locally — `uvicorn app.server:app --port 7860`
with `TOKEN_FACTORY_API_KEY` set — and open `http://localhost:7860` in a clean browser
window. (The public Space is the static browse/search demo and makes no model call;
the live answers must come from the local app.) Then: zoom 110%, left list filtered to **All**, no question
asked yet. Have the four transcripts in `docs/transcripts/` open in a second tab
in case a live call stalls — read the saved answer rather than wait. Record at
1080p. Speak at an even pace; the script is ~330 words, which is 2:20 at normal
speed. Numbers in `{{braces}}` come from the real read — copy them from
`README.md` Status and the transcripts before recording. Never read a number
that is not on screen.

Say the brand as "in-VIZ-you".

| Time | On screen — what to click | What to say |
|---|---|---|
| 0:00–0:14 | The app, no interaction. Cursor still. | "The Library of Congress holds about fifty-five thousand public-domain drawing sets of American buildings — the Historic American Buildings Survey. Hand-lettered scans. None of them can be asked a question. This one can." |
| 0:14–0:32 | Hover the header. Then scroll the left list slowly: documents, sheets, photographs. | "This is Iolani Palace in Honolulu — HABS number HI-1, Library of Congress record hi0047. Eighty-five pages: the survey's caption and data pages, twenty-three scanned drawing sheets, and fifty-seven photographs. The sheets were drawn by the survey in 1964 and 1966; several say on their face that they were redrawn from the 1903 plans. We say the dates the sheets say." |
| 0:32–0:52 | Click **PG-14** (Richards Street elevation) in the list. Point at the title and the text count in the page header. Scroll the "Page text, reading order" panel. | "Every scanned sheet was read by NVIDIA's Nemotron-3.5-Super-VL, running on Nebius Token Factory — title, description, and every legible piece of lettering with its position. Across the set that is {{N_TEXT_ENTRIES}} text entries and {{N_TITLES}} sheet titles, read by the model, not typed by us." |
| 0:52–1:14 | Click the example chip **where is the throne room**. Wait for the outcome. Click the first green receipt. | "Now the question. The index builds an evidence pack — every page's text, the typed cross-references, the search hits — and NVIDIA's Nemotron-3-Ultra, also on Token Factory, answers over it. The outcome is ANSWERED, and every claim carries its page. Click the receipt — {{Q1_RECEIPT}} — and the lettering it relied on is boxed on the sheet." |
| 1:14–1:34 | Click the chip **which sheets show the Richards Street elevation**. Let the receipts render; hover each. | "Which sheets show the Richards Street elevation. {{Q2_RECEIPTS_COUNT}} receipts: {{Q2_RECEIPTS}}. The receipts are verified in code against the index — a page the model cites that does not exist is flagged, not shown as fact." |
| 1:34–1:54 | Click the chip **what does sheet 12 reference**. Click one receipt; point at "References:" in the reading-order panel. | "What does sheet 12 reference. Historic sheets cross-reference by lettering — SEE SHEET N — not by symbols. We type those references, so the answer is {{Q3_SUMMARY}}, and the cross-reference check reports any target that is not in the set." |
| 1:54–2:12 | Type **{{Q4_NOT_IN_SET_QUESTION}}** and press Enter. Let the blue NOT IN THE SET label land. | "And the question every archive tool gets wrong. {{Q4_SHORT}}. The set does not say. So the answer is: not in the set — with the pages it checked. Four outcomes are allowed: answered with receipts, answered from memory with its date, not in the set, unknown entity. Nothing else. No invented sheets, no estimated numbers." |
| 2:12–2:30 | Switch to the GitHub repo tab, show README top (license, models table), then the public static demo (https://cre808ive-invisu-preservation.static.hf.space/) for two seconds, then back to the app. | "Open method on open models: MIT, on GitHub, every model call through Nebius Token Factory on NVIDIA Nemotron, source documents public domain from loc.gov. iNViSU — every answer carries its sheet, and when the set does not say, it says so." |

## Placeholders to fill before recording

| Placeholder | Where it comes from |
|---|---|
| `{{N_TEXT_ENTRIES}}` | `python -m preservation.build_index data/iolani-palace` → SUMMARY `texts_eyes` (say "text entries read from the scans") |
| `{{N_TITLES}}` | count of sheets with a title in the inventory (`/api/set`, pages with kind=sheet and a title) |
| `{{Q1_RECEIPT}}` | first receipt in `docs/transcripts/throne_room.md` (e.g. "PG-24, HABS sheet 17") |
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

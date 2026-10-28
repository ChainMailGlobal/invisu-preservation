# Resume runbook — when Token Factory credits are live

Rules in force for every step: **hard cap $5 total** (`TF_CAP_USD`, enforced by the
client before each call) and **stop on the first HTTP 402** (the client raises;
the tools exit 2). Look at every model output before counting it a success — a
run of empty or identical outputs is a failure to report, not progress. Note the
Token Factory balance in the console before step 1 and after step 7.

All commands from the repo root, Git Bash, with the key exported for the shell:

```bash
cd /c/Dev/invisu-preservation
export TOKEN_FACTORY_API_KEY=...        # or: copy .env.example to .env and fill it
python -m preservation.tokenfactory      # cost line — should read 0 calls before you start
```

## 1. One page, eyeballed (one call, cents)

```bash
python -m preservation.read_scans data/iolani-palace --only 11 --thinking auto
```

Page 11 is the second-floor plan. Check, in this order:

- the call line: `finish=stop` (not `length`); if `reasoning_chars=` appears the
  model is thinking — rerun with `--thinking off` and compare token counts
- `title=` is a real sheet title (expected something like `SECOND FLOOR PLAN`)
- the `e.g.` sample holds room names / dimensions / notes, not prose or
  repeated tokens; then dump everything it read:

```bash
python -c "import json;s=json.load(open('data/iolani-palace/11.scene.json'));print(s['title']);print(s['description']);[print(' ',x[0]) for x in s['spans']]"
```

- boxes are spread over the sheet, not piled in one corner (the reader prints
  nothing about this; look at the x/y values or load the page in the app after
  step 3 and see the hit boxes land on lettering)
- if the response was `unparseable`, rerun once with `--thinking off`; if it is
  still unparseable, stop and report — do not loop

Decide the flags here (`--thinking off`, maybe `--edge 1800` if small lettering
was missed) and use the same flags for every sheet below.

## 2. All scanned sheets (22 more calls)

```bash
python -m preservation.read_scans data/iolani-palace            # add --thinking off / --edge if step 1 said so
python -m preservation.tokenfactory                              # cost line
```

Expect `DONE pages_read=22 of 22` (page 11 is skipped as already read). Read the
titles in the log. If more than two sheets came back `unparseable` or with a
handful of texts, run the quadrant pass on them only — it costs 4 calls per
sheet, so decide per sheet:

```bash
python -m preservation.read_scans data/iolani-palace --tiles --only 25
```

Photographs: keep the committed captions (`photos.json`, 57 entries). Do not
re-caption — 57 calls for no new information.

## 3. References and index (no calls)

```bash
python -m preservation.build_index data/iolani-palace
```

The self-number map should show most HABS sheet numbers 1–22 mapped to pages
PG-07..PG-28. Note `texts_eyes` and the title count for the video and Devpost
placeholders. Any `issue:` lines are the cross-reference check — they are
content, keep them.

## 4. The four transcripts (4–6 calls, ~30k tokens each)

```bash
python -m preservation.agent data/iolani-palace "where is the throne room" --save docs/transcripts/throne_room.md
python -m preservation.agent data/iolani-palace "which sheets show the Richards Street elevation" --save docs/transcripts/richards_street.md
python -m preservation.agent data/iolani-palace "what does sheet 12 reference" --save docs/transcripts/sheet12.md
python -m preservation.agent data/iolani-palace "what wood species is the central stair balustrade" --save docs/transcripts/not_in_set.md
```

For each: outcome stated, `verified=True`, receipts are real pages, and the
quoted text actually appears on the receipt page (check with `/api/page/PG-NN`
or `sqlite3 data/iolani-palace/index.db "select text from texts where sheet_no='PG-NN'"`).
If the first call shows `reasoning_chars` in the thousands, set
`--thinking off` for the rest and note the difference in the Devpost feedback.

The fourth question must come back **NOT_IN_THE_SET**. If it is answered from
the set (the sheets may name the species), try the next candidate and keep the
one that is truly absent — do not keep asking past three:

- "what wood species is the central stair balustrade"
- "what is the height of the flagpole on the roof"
- "which sheet shows the kitchen and the bakery"

Keep every transcript, including a failed candidate — they are evidence for the
feedback section.

## 5. Commit (no calls)

```bash
python -m preservation.tokenfactory >> docs/transcripts/COST_LINE.txt
git add data/iolani-palace docs/transcripts docs/cost_ledger.jsonl
git commit -m "feat(data): Iolani sheets read by Nemotron-3.5-Super-VL; index rebuilt; four agent transcripts"   # add the Co-Authored-By trailer the repo uses
git push
```

Then fill the placeholders: README Status (replace the Blocked block with the
real numbers), `docs/VIDEO_SCRIPT.md`, `docs/DEVPOST.md`, and the two prices in
`PRICES` in `preservation/tokenfactory.py` (read them off tokenfactory.nebius.com),
then `python -m preservation.tokenfactory` once more for the dollar line. Commit.

## 6. Space deploy (no model calls; `hf auth login` is done on this laptop as CRE808iVE)

```bash
./deploy_space.sh            # re-exports site/ from the rebuilt index, uploads to the static Space
```

The Space is static — it never calls a model. Open https://cre808ive-invisu-preservation.static.hf.space/
and check: the sheets in the left list now show titles; `?q=throne%20room`
hits drawing sheets, not only photographs; `#PG-14` selects the Richards
Street elevation. Update the README Status numbers and `docs/DEVPOST.md`
placeholders. Commit, push.

## 7. Stop conditions

- any `STOP: HTTP 402` line → stop, report the step and the ledger
- `STOP: ledger total $... >= cap` → stop, report
- a sheet read that returns the same text as another sheet, or an empty
  `texts` list on a sheet that clearly has lettering → stop and report before
  spending on the rest

## 2026-10-28 addendum: AI Cloud route

Token Factory credits never arrived; the AI Cloud balance can serve a Nemotron ourselves on one L40S. Full recipe: docs/RUN_AI_CLOUD_ENDPOINT.md. The steps above are unchanged except the environment block at its section 2; Ultra on Token Factory stays the brain of record if credits land before the deadline.

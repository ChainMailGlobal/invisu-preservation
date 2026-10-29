"""self_review — score this submission against the hackathon's own rubric with the
sponsors' own models, through the same client and ledger as everything else.

Passes (each writes a markdown file to --out):
  judge        Nemotron 3 Ultra scores the package exactly as the organizers said they
               would: pass/fail viability, then four criteria 1-5, with quoted evidence
               and at most seven concrete fixes.
  adversarial  the same inputs to a skeptical judge trying to discount the entry:
               overclaims, inconsistencies between description, README and narration,
               tutorial-not-pitch, tools not unmistakable.
  video        Nemotron 3.5 Super-VL looks at one frame per caption cue of the demo
               video with its caption, six frames per call; Ultra then synthesizes a
               verdict: ship / fix text / re-record.
  premortem    "It is January 11, 2027 and this entry did not place": five ranked
               reasons tied to the rubric, each with its evidence and the change that
               would have prevented it, marked fixable-before-deadline or not.

The judge reads the organizers' material, not our summary of it: --build-corpus turns
what was saved from Devpost and the organizer emails (HTML, PDF, .eml, .txt in
Downloads\\hackathon) into runs/hackathon_corpus/*.txt, and every pass gets the whole
corpus under a HACKATHON MATERIALS header.

Usage:
  python tools/self_review.py --build-corpus [--downloads C:/Users/<me>/Downloads/hackathon]
  python tools/self_review.py --dry-run
  python tools/self_review.py [--pass judge|adversarial|video|premortem|all]
                              [--video runs/video_ultra/invisu-preservation-demo.mp4]
                              [--srt runs/video_ultra/captions.srt] [--token-budget 600000]

Guards: no .env or runs/ content other than the corpus enters a prompt; the file list
comes from `git ls-files`; the tool stops when the review has used more than
--token-budget tokens (Token Factory publishes no machine-readable price) or on 402.
"""
from __future__ import annotations

import argparse
import base64
import email
import email.policy
import json
import re
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from preservation import tokenfactory as tf  # noqa: E402

CORPUS = ROOT / "runs" / "hackathon_corpus"
CRITERIA = ["Technological Implementation", "Design", "Potential Impact", "Quality of the Idea"]


# ----------------------------------------------------------------------------- corpus
class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self):
        super().__init__()
        self.out, self._skip, self.title = [], 0, ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br", "section", "article"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self._skip:
            self.out.append(data)


def _clean(text: str) -> str:
    lines = [" ".join(l.split()) for l in text.splitlines()]
    out, blank = [], 0
    for l in lines:
        if not l:
            blank += 1
            if blank <= 1:
                out.append("")
            continue
        blank = 0
        out.append(l)
    return "\n".join(out).strip()


def _html_text(raw: str) -> tuple[str, str]:
    p = _Text()
    p.feed(raw)
    return p.title.strip(), _clean("".join(p.out))


def _pdf_text(path: Path) -> str:
    import fitz  # pymupdf, already a dependency
    doc = fitz.open(path)
    return _clean("\n".join(page.get_text() for page in doc))


def _eml_text(path: Path) -> tuple[str, str]:
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    subject = str(msg.get("subject", "")).strip()
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return subject, ""
    content = body.get_content()
    if body.get_content_type() == "text/html":
        _, content = _html_text(content)
    head = f"From: {msg.get('from','')}\nDate: {msg.get('date','')}\nSubject: {subject}\n\n"
    return subject, head + _clean(content)


def build_corpus(downloads: Path) -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    rows = []
    for f in sorted(downloads.rglob("*")):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        try:
            if ext in (".html", ".htm"):
                title, text = _html_text(f.read_text(encoding="utf-8", errors="replace"))
            elif ext == ".pdf":
                title, text = f.stem, _pdf_text(f)
            elif ext == ".eml":
                title, text = _eml_text(f)
            elif ext in (".txt", ".md"):
                title, text = f.stem, _clean(f.read_text(encoding="utf-8", errors="replace"))
            else:
                continue   # images, fonts and other page assets from "Webpage, Complete"
        except Exception as e:  # noqa: BLE001
            print(f"  skip {f.name}: {type(e).__name__}: {str(e)[:80]}")
            continue
        if len(text) < 200:
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", (title or f.stem).lower()).strip("_")[:60] or f.stem
        out = CORPUS / f"dl_{slug}.txt"
        out.write_text(f"# {title or f.stem}\n(source file: {f.name})\n\n{text}\n", encoding="utf-8")
        rows.append((out.name, title or f.stem, len(text)))
    seeds = [(p.name, p.read_text(encoding="utf-8").splitlines()[0].lstrip("# "), len(p.read_text(encoding="utf-8")))
             for p in sorted(CORPUS.glob("*.txt")) if not p.name.startswith("dl_")]
    index = ["# Hackathon corpus index", "", "| file | title | chars |", "|---|---|---|"]
    index += [f"| {n} | {t} | {c:,} |" for n, t, c in seeds + rows]
    (CORPUS / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print("\n".join(index))


def corpus_text() -> str:
    parts = []
    for p in sorted(CORPUS.glob("*.txt")):
        parts.append(f"\n----- {p.name} -----\n{p.read_text(encoding='utf-8')}")
    return "".join(parts)


# ----------------------------------------------------------------------------- package
def srt_cues(path: Path) -> list[tuple[float, str]]:
    cues, t, buf = [], None, []
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        m = re.match(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> ", line)
        if m:
            t = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 1000
        elif line.strip() == "" and t is not None:
            if buf:
                cues.append((t, " ".join(buf)))
            t, buf = None, []
        elif t is not None:
            buf.append(line.strip())
    return cues


def transcript(srt: Path) -> str:
    return "\n".join(f"[{int(t)//60:02d}:{int(t)%60:02d}] {text}" for t, text in srt_cues(srt))


def transcripts_summary() -> str:
    out = []
    for folder, label in (("docs/transcripts/token_factory", "Nemotron-3-Ultra on Token Factory"),
                          ("docs/transcripts", "Nemotron-3-Nano-Omni on the AI Cloud endpoint")):
        for p in sorted((ROOT / folder).glob("*.md")):
            s = p.read_text(encoding="utf-8")
            q = s.splitlines()[0].lstrip("# ")
            outcome = re.search(r"- Outcome: \*\*(\w+)\*\*.*", s)
            ans = re.search(r"## Answer\n\n(.*?)\n\nReceipts: (.*?)\n", s, re.S)
            out.append(f"- [{label}] Q: {q}\n  {outcome.group(0) if outcome else ''}\n"
                       f"  A: {ans.group(1).strip()[:600] if ans else '?'}\n  Receipts: {ans.group(2) if ans else '?'}")
    return "\n".join(out)


def devpost_feedback() -> str:
    s = (ROOT / "docs" / "DEVPOST.md").read_text(encoding="utf-8")
    i = s.find("## Limitations and failure cases")
    return s[i:] if i >= 0 else s


def package(srt: Path) -> dict[str, str]:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return {
        "HACKATHON MATERIALS (rules, tracks, judging process, prizes, organizer emails)": corpus_text(),
        "DEVPOST DESCRIPTION (the field judges read first)": (ROOT / "docs" / "DEVPOST_DESCRIPTION.md").read_text(encoding="utf-8"),
        "README.md (repository front page)": (ROOT / "README.md").read_text(encoding="utf-8"),
        "DEVPOST TEXT: limitations, what's next, feedback and built-with sections": devpost_feedback(),
        "DEMO VIDEO NARRATION (captions with timestamps; the video is 2:54, 1080p)": transcript(srt),
        "AGENT TRANSCRIPTS (answers and outcomes, both brains)": transcripts_summary(),
        "REPOSITORY FILE LIST (git ls-files)": files,
    }


def render(pkg: dict[str, str], extra: dict[str, str] | None = None) -> str:
    parts = []
    for k, v in {**pkg, **(extra or {})}.items():
        parts.append(f"\n\n===== {k} =====\n{v.strip()}\n")
    return "".join(parts)


# ----------------------------------------------------------------------------- prompts
JUDGE_SYS = f"""You are a judge for the Nebius x NVIDIA Global AI Hackathon, scoring ONE entry in the
Best Apps and Agents track. Score exactly the way the HACKATHON MATERIALS say judging works:
first a pass/fail check for baseline viability and fit with the theme, then the four equally
weighted criteria, each 1 to 5: {", ".join(CRITERIA)}. Apply the organizers' published tips
literally. Judge only what is in the package; quote the text you score; never invent a fact
about the entry, and say so when something you would want to check is not in the package.

Reply in exactly this form:
VIABILITY: PASS or FAIL — one sentence why, citing the requirement.
SCORE Technological Implementation: n/5 — one paragraph, quoting the package.
SCORE Design: n/5 — one paragraph, quoting the package.
SCORE Potential Impact: n/5 — one paragraph, quoting the package.
SCORE Quality of the Idea: n/5 — one paragraph, quoting the package.
TOP FIXES (at most 7, most valuable first): for each: WHAT / WHERE (description, README, video, form) / WHY it moves which score / MINUTES to do.
RISKS: what a stricter judge would discount, and why."""

ADVERSARIAL_SYS = """You are the most skeptical judge on the Nebius x NVIDIA Global AI Hackathon panel. Your job is
to find every reason to discount this Best Apps and Agents entry, using the HACKATHON MATERIALS
as the standard. Quote the package for every point; never invent a fact about it.

Report, in this order:
OVERCLAIMS: any claim that is not supported by what the package shows, or that is phrased stronger than its evidence.
INCONSISTENCIES: numbers, model names, surfaces or outcomes that differ between the description, the README, the narration and the transcripts.
TUTORIAL NOT PITCH: where the description or narration explains instead of pitching (problem, who it is for, what it does, how it uses Nebius and NVIDIA).
TOOLS NOT UNMISTAKABLE: whether Nebius Token Factory, Nebius AI Cloud and the NVIDIA Nemotron models are named clearly in the description, the Built With list and the narration, with audio.
VIABILITY THREATS: anything that could fail the pass/fail check (platform, open license, README, video length and visibility, demo URL).
VERDICT: the three findings that most lower the score, each with the fix that removes it."""

VIDEO_BATCH_SYS = """You are reviewing frames from a 3-minute hackathon demo video on behalf of its judges. Each
frame comes with its timestamp and the caption spoken at that moment. For each frame say what is
on screen (the app, a web page, an overlay), whether UI text is legible at this size, which
Nebius or NVIDIA names are visible on screen, whether anything on screen contradicts the caption,
and any error state, placeholder, empty panel or stray artifact. Be concrete and brief; quote
visible text where it matters. End with ONE LINE: the single most important observation from
this batch."""

VIDEO_SYNTH_SYS = """You are a judge for the Nebius x NVIDIA Global AI Hackathon deciding whether a demo video
does its job. You have the organizers' tips in the HACKATHON MATERIALS, the full narration with
timestamps, and frame-by-frame notes from a vision model. Answer:
AHA IN 30 S: does the first 30 seconds show the problem and the solution working? Quote the narration.
TOOLS WITH AUDIO: are Nebius Token Factory, Nebius AI Cloud and the NVIDIA Nemotron models named in the narration, not just on screen? Where?
PITCH: problem, who it is for, what it does, how it uses Nebius and NVIDIA — which are present, which missing?
PACING AND LEGIBILITY: from the frame notes.
CONTRADICTIONS: anything on screen that does not match what is said.
FIXES (at most 3): concrete, with the timestamp.
VERDICT: SHIP AS IS / FIX TEXT ONLY / RE-RECORD — one sentence why."""

PREMORTEM_SYS = """It is January 11, 2027. The winners of the Nebius x NVIDIA Global AI Hackathon were announced and
this Best Apps and Agents entry did not place. Write the post-mortem as the judge who scored it,
using the HACKATHON MATERIALS as the standard and quoting the package for evidence.

REASONS (exactly five, most likely first): for each: the reason / the criterion or viability check it
maps to / the evidence in the package a judge pointed at / the ONE change that would have prevented
it / MINUTES to make it / FIXABLE BEFORE THE DEADLINE: yes or no (the deadline is Friday
2026-10-30 7:00 AM HST; the description, README and form can change; a new video is possible but costly).
IF IT HAD WON: the one reason it would have, in two sentences.
STRONGEST REMAINING WEAKNESS: the thing no Friday fix removes."""


# ----------------------------------------------------------------------------- calls
def ask(model: str, system: str, user, *, purpose: str, max_tokens: int, extra: dict | None = None) -> dict:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    reply, err = tf.chat(model, messages, max_tokens=max_tokens, temperature=0, extra=extra,
                         purpose=f"self-review: {purpose}", timeout=600)
    if err:
        raise SystemExit(f"{purpose}: {err}")
    u = reply["usage"]
    print(f"  {purpose}: {u.get('prompt_tokens',0):,} in / {u.get('completion_tokens',0):,} out, "
          f"{reply['latency_s']}s, finish={reply['finish']}, reasoning chars={len(reply['reasoning'])}", flush=True)
    return reply


def tokens_used() -> int:
    return tf.spent()["total"]["prompt_tokens"] + tf.spent()["total"]["completion_tokens"]


class Budget:
    def __init__(self, limit: int):
        self.start, self.limit = tokens_used(), limit

    def check(self, where: str):
        used = tokens_used() - self.start
        print(f"  [budget] {used:,} tokens used by the review so far", flush=True)
        if used > self.limit:
            raise SystemExit(f"token budget {self.limit:,} exceeded after {where} ({used:,}); stopping")


def write(out: Path, name: str, reply: dict, header: str) -> str:
    text = reply["text"].strip()
    body = (f"# {header}\n\n- Model: `{reply.get('model', '')}` via Nebius Token Factory\n"
            f"- Tokens: {reply['usage'].get('prompt_tokens',0):,} in / {reply['usage'].get('completion_tokens',0):,} out, "
            f"{reply['latency_s']}s, reasoning chars {len(reply['reasoning'])}\n\n{text}\n")
    (out / name).write_text(body, encoding="utf-8")
    return text


# ----------------------------------------------------------------------------- video
def frames_for(video: Path, srt: Path, out: Path, width: int = 1280) -> list[tuple[float, str, Path]]:
    fdir = out / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    cues = srt_cues(srt)
    if len(cues) > 32:    # keep one frame per cue but never more than 32 calls' worth
        step = len(cues) / 32
        cues = [cues[int(i * step)] for i in range(32)]
    frames = []
    for t, text in cues:
        f = fdir / f"f_{int(t*10):05d}.png"
        if not f.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t + 0.4:.2f}", "-i", str(video),
                            "-frames:v", "1", "-vf", f"scale={width}:-1", str(f)], check=True)
        frames.append((t, text, f))
    return frames


def video_pass(out: Path, pkg: dict, video: Path, srt: Path, budget: Budget) -> str:
    frames = frames_for(video, srt, out)
    notes = []
    for b in range(0, len(frames), 6):
        batch = frames[b:b + 6]
        content = [{"type": "text", "text":
                    f"Frames {b+1}-{b+len(batch)} of {len(frames)} from the demo video. For each frame the caption spoken at that moment is given first."}]
        for t, text, f in batch:
            content.append({"type": "text", "text": f"\n[{int(t)//60:02d}:{int(t)%60:02d}] caption: {text}"})
            content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()}})
        r = ask(tf.EYES, VIDEO_BATCH_SYS, content, purpose=f"video batch {b//6+1}", max_tokens=6000,
                extra={"repetition_penalty": 1.05})
        notes.append(f"## Frames {b+1}-{b+len(batch)}\n\n{r['text'].strip()}\n")
        budget.check(f"video batch {b//6+1}")
    (out / "video_batches.md").write_text("# Super-VL frame notes\n\n" + "\n".join(notes), encoding="utf-8")
    user = render({k: v for k, v in pkg.items() if k.startswith(("HACKATHON", "DEMO VIDEO"))},
                  {"FRAME NOTES FROM THE VISION MODEL": "\n".join(notes)})
    r = ask(tf.BRAIN, VIDEO_SYNTH_SYS, user, purpose="video verdict", max_tokens=3000)
    r["model"] = tf.BRAIN
    return write(out, "video_verdict.md", r, "Video verdict (Ultra over Super-VL frame notes)")


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-corpus", action="store_true")
    ap.add_argument("--downloads", default=str(Path.home() / "Downloads" / "hackathon"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pass", dest="passes", default="all", help="judge|adversarial|video|premortem|all")
    ap.add_argument("--out", default=None)
    ap.add_argument("--video", default=str(ROOT / "runs" / "video_ultra" / "invisu-preservation-demo.mp4"))
    ap.add_argument("--srt", default=str(ROOT / "runs" / "video_ultra" / "captions.srt"))
    ap.add_argument("--token-budget", type=int, default=600_000)
    a = ap.parse_args()

    if a.build_corpus:
        build_corpus(Path(a.downloads))
        return
    if not list(CORPUS.glob("*.txt")):
        raise SystemExit(f"no corpus in {CORPUS}; run --build-corpus first")
    srt, video = Path(a.srt), Path(a.video)
    pkg = package(srt)
    for k, v in pkg.items():
        assert "TOKEN_FACTORY_API_KEY=" not in v and "v1.Cm" not in v, f"secret-looking text in {k}"
    if a.dry_run:
        for k, v in pkg.items():
            print(f"{len(v):>8,} chars  {k}")
        print(f"{sum(len(v) for v in pkg.values()):>8,} chars total (~{sum(len(v) for v in pkg.values())//4:,} tokens)")
        cues = srt_cues(srt)
        print(f"video: {video.exists()} cues: {len(cues)} -> frames {min(len(cues), 32)}")
        return

    out = Path(a.out) if a.out else ROOT / "runs" / "review" / time.strftime("%Y%m%d_%H%M")
    out.mkdir(parents=True, exist_ok=True)
    want = {"judge", "adversarial", "video", "premortem"} if a.passes == "all" else set(a.passes.split(","))
    budget = Budget(a.token_budget)
    user = render(pkg)
    verdicts: dict[str, str] = {}
    try:
        if "judge" in want:
            r = ask(tf.BRAIN, JUDGE_SYS, user, purpose="judge", max_tokens=4000); r["model"] = tf.BRAIN
            verdicts["judge"] = write(out, "judge.md", r, "Judge (Ultra, the organizers' rubric)")
            budget.check("judge")
        if "adversarial" in want:
            r = ask(tf.BRAIN, ADVERSARIAL_SYS, user, purpose="adversarial", max_tokens=4000); r["model"] = tf.BRAIN
            verdicts["adversarial"] = write(out, "adversarial.md", r, "Adversarial judge (Ultra)")
            budget.check("adversarial")
        if "video" in want:
            verdicts["video"] = video_pass(out, pkg, video, srt, budget)
            budget.check("video")
        if "premortem" in want:
            extra = {f"EARLIER VERDICT: {k}": v for k, v in verdicts.items()}
            r = ask(tf.BRAIN, PREMORTEM_SYS, render(pkg, extra), purpose="premortem", max_tokens=4000); r["model"] = tf.BRAIN
            verdicts["premortem"] = write(out, "premortem.md", r, "Pre-mortem (Ultra)")
            budget.check("premortem")
    except tf.CreditsExhausted as e:
        print(f"STOP: {e}")
        sys.exit(2)
    # summary: the verdict lines, for a human to add apply/decline decisions
    lines = ["# Self-review summary", "", f"Run: {out.name}", ""]
    for k, v in verdicts.items():
        keep = [l for l in v.splitlines() if re.match(r"^(VIABILITY|SCORE|VERDICT|REASONS|IF IT HAD WON|STRONGEST|TOP FIXES|FIXES)", l.strip())]
        lines += [f"## {k}", ""] + (keep or ["(see file)"]) + [""]
    lines += ["## Decisions", "", "(apply / decline per fix, with the reason — filled in by hand)", ""]
    (out / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"DONE {out}")
    print(tf.cost_line())


if __name__ == "__main__":
    main()

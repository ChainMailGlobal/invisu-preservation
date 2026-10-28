"""make_video — record the demo video from the REAL local app, no screen-recording software.

Drives the app in a headless Chromium with Playwright (which records the page at
1080p), speaks the narration with a neural voice (edge-tts; Windows SAPI as a
fallback), burns the captions in, and muxes everything with ffmpeg into one MP4
under three minutes. The timeline (what to click, what to say) is JSON, so the
narration can be edited without touching code, and every number said on camera
is a number the app shows.

Usage:
  uvicorn app.server:app --port 7860          # the full app, endpoint env set
  python tools/make_video.py --timeline docs/video/timeline.json --out runs/video
        [--app http://localhost:7860] [--voice en-US-AndrewMultilingualNeural]
        [--sapi]   use the offline Windows voice instead of edge-tts
        [--mute]   no narration track (captions only)

Needs: playwright (+ `playwright install chromium`), edge-tts, ffmpeg on PATH.
Not needed to run the app; this is how the submission video was produced.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CURSOR_CSS = """
#__cur{position:fixed;z-index:2147483647;width:22px;height:22px;pointer-events:none;
 left:-100px;top:-100px;transition:left .35s ease,top .35s ease;
 background:url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22><path d=%22M4 2l16 9-7 1.5L17 20l-3 1.5-4-7.5L4 18z%22 fill=%22white%22 stroke=%22black%22 stroke-width=%221.5%22/></svg>') no-repeat}
#__ov{position:fixed;inset:0;z-index:2147483646;background:#0b0d10;display:none;align-items:center;justify-content:center}
#__ov img{max-width:100%;max-height:100%;object-fit:contain}
"""


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


def tts_edge(text: str, path: Path, voice: str, rate: str) -> None:
    import edge_tts

    async def run():
        await edge_tts.Communicate(text, voice, rate=rate).save(str(path))
    asyncio.run(run())


def tts_sapi(text: str, path: Path) -> None:
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$s.Rate = 0; $s.SetOutputToWaveFile('%s'); $s.Speak(@'\n%s\n'@); $s.Dispose()"
          % (str(path).replace("'", "''"), text))
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)


def narrate(segments: list[dict], out: Path, *, voice: str, rate: str, sapi: bool, mute: bool) -> list[float]:
    """One audio file per segment; returns their durations (0 when muted)."""
    durs = []
    for i, seg in enumerate(segments):
        text = seg.get("say", "").strip()
        if mute or not text:
            durs.append(0.0)
            continue
        path = out / (f"say_{i:02d}.wav" if sapi else f"say_{i:02d}.mp3")
        if not path.exists() or path.stat().st_size == 0:
            for attempt in range(4):          # the online voice service drops connections now and then
                try:
                    (tts_sapi if sapi else lambda t, p: tts_edge(t, p, voice, rate))(text, path)
                    if path.exists() and path.stat().st_size > 0:
                        break
                except Exception as e:        # noqa: BLE001
                    print(f"  say {i:02d}: attempt {attempt + 1} failed: {type(e).__name__}: {str(e)[:120]}", flush=True)
                    if path.exists():
                        path.unlink()
                    time.sleep(3 * (attempt + 1))
            else:
                raise SystemExit(f"narration for segment {i} failed four times")
        d = ffprobe_duration(path)
        seg["_audio"] = str(path)
        durs.append(d)
        print(f"  say {i:02d}: {d:5.1f}s  {text[:70]}", flush=True)
    return durs


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[dict], starts: list[float], lengths: list[float], path: Path) -> None:
    """Captions: each segment's narration split at sentence ends, timed in
    proportion to character count across the narration's duration."""
    n = 1
    lines = []
    for seg, t0, dur in zip(segments, starts, lengths):
        text = seg.get("say", "").strip()
        if not text:
            continue
        parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", text) if p.strip()]
        total = sum(len(p) for p in parts) or 1
        t = t0
        for p in parts:
            d = dur * len(p) / total
            lines += [str(n), f"{srt_time(t)} --> {srt_time(t + d)}", p, ""]
            n += 1
            t += d
    path.write_text("\n".join(lines), encoding="utf-8")


class Driver:
    def __init__(self, page, app: str, t0: float):
        self.page, self.app, self.t0 = page, app, t0
        self.waits: list[tuple[float, float, float]] = []   # (start, end, seconds) of model waits

    def cursor_to(self, selector: str):
        el = self.page.locator(selector).first
        el.scroll_into_view_if_needed()
        box = el.bounding_box()
        if not box:
            return
        x, y = box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2
        self.page.evaluate("([x,y]) => { const c=document.getElementById('__cur'); c.style.left=x+'px'; c.style.top=y+'px'; }", [x, y])
        self.page.mouse.move(x, y, steps=10)
        self.page.wait_for_timeout(400)

    def click(self, selector: str):
        self.cursor_to(selector)
        self.page.locator(selector).first.click()

    def run(self, action: dict):
        p = self.page
        if "goto" in action:
            p.goto(action["goto"], wait_until="load")
            p.add_style_tag(content=CURSOR_CSS)
            p.evaluate("() => { const c=document.createElement('div'); c.id='__cur'; document.body.appendChild(c);"
                       " const o=document.createElement('div'); o.id='__ov'; o.innerHTML='<img>'; document.body.appendChild(o); }")
        elif "wait_ready" in action:
            p.wait_for_selector("#pages .pg", timeout=60_000)
            p.wait_for_timeout(800)
        elif "type" in action:
            self.cursor_to(action["type"])
            p.locator(action["type"]).first.click()
            p.locator(action["type"]).first.fill("")
            p.keyboard.type(action["text"], delay=action.get("delay_ms", 45))
        elif "press" in action:
            p.keyboard.press(action["press"])
        elif "click" in action:
            self.click(action["click"])
        elif "click_chip" in action:
            self.click(f"#examples .chip >> nth={action['click_chip']}")
        elif "wait_outcome" in action:
            ws = time.time() - self.t0
            p.wait_for_function(
                "() => /ANSWERED|NOT_IN_THE_SET|UNKNOWN_ENTITY|MODEL_UNAVAILABLE|ERROR|UNPARSED/"
                ".test(document.getElementById('outcome').className)", timeout=action.get("timeout_ms", 300_000))
            we = time.time() - self.t0
            self.waits.append((ws, we, we - ws))
            p.wait_for_timeout(600)
        elif "click_receipt" in action:
            self.click(f"#receipts .receipt >> nth={action['click_receipt']}")
            p.wait_for_timeout(900)
        elif "hover_receipts" in action:
            n = p.locator("#receipts .receipt").count()
            for i in range(n):
                self.cursor_to(f"#receipts .receipt >> nth={i}")
                p.wait_for_timeout(500)
        elif "select_page" in action:
            self.click(f"#li-{action['select_page']}")
            p.wait_for_timeout(900)
        elif "scroll" in action:
            sel, px, steps = action["scroll"], action.get("px", 600), action.get("steps", 8)
            for _ in range(steps):
                p.evaluate("([s,d]) => { const e=document.querySelector(s); if(e) e.scrollTop += d; }", [sel, px / steps])
                p.wait_for_timeout(action.get("step_ms", 350))
        elif "overlay" in action:
            data = Path(action["overlay"]).read_bytes()
            import base64
            p.evaluate("(b) => { const o=document.getElementById('__ov'); o.querySelector('img').src='data:image/png;base64,'+b; o.style.display='flex'; }",
                       base64.b64encode(data).decode())
        elif "overlay_off" in action:
            p.evaluate("() => { document.getElementById('__ov').style.display='none'; }")
        elif "hold" in action:
            p.wait_for_timeout(int(action["hold"] * 1000))
        else:
            raise SystemExit(f"unknown action {action}")


def screenshots(pw, shots: list[dict], out: Path) -> None:
    """Still frames of other pages (GitHub README, the public Space) shown as
    overlays inside the single recorded page, so the app keeps its state."""
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1920, "height": 1080})
    pg = ctx.new_page()
    for s in shots:
        path = out / s["file"]
        if path.exists():
            continue
        pg.goto(s["url"], wait_until="load")
        pg.wait_for_timeout(s.get("settle_ms", 2500))
        if s.get("scroll"):
            pg.evaluate("(y) => window.scrollTo(0, y)", s["scroll"])
            pg.wait_for_timeout(400)
        pg.screenshot(path=str(path))
        print(f"  shot {s['file']} <- {s['url']}", flush=True)
    b.close()


def record(timeline: dict, out: Path, app: str, durs: list[float]) -> tuple[Path, list[float], list[float]]:
    from playwright.sync_api import sync_playwright
    segs = timeline["segments"]
    with sync_playwright() as pw:
        screenshots(pw, timeline.get("screenshots", []), out)
        b = pw.chromium.launch(headless=True)
        vdir = out / "raw"
        ctx = b.new_context(viewport={"width": 1920, "height": 1080},
                            record_video_dir=str(vdir), record_video_size={"width": 1920, "height": 1080},
                            device_scale_factor=1)
        t_rec0 = time.time()
        page = ctx.new_page()
        d = Driver(page, app, t_rec0)
        page.wait_for_timeout(600)                   # lead-in before the first frame that matters
        starts, lengths = [], []
        for i, seg in enumerate(segs):
            t0 = time.time() - t_rec0
            actions = seg.get("do", [])
            # narration starts after the actions when the segment waits on the
            # model (the answer must be on screen before it is described)
            say_after = seg.get("say_at", "after" if any("wait_outcome" in a for a in actions) else "start") == "after"
            for a in actions:
                a = {k: (v.replace("{app}", app) if isinstance(v, str) else v) for k, v in a.items()}
                d.run(a)
            t_after = time.time() - t_rec0
            if say_after:
                hold = max(durs[i] + seg.get("pad", 0.6), seg.get("min", 0.0))
                starts.append(t_after)
            else:
                hold = max(durs[i] + seg.get("pad", 0.6), seg.get("min", 0.0)) - (t_after - t0)
                starts.append(t0)
            if hold > 0:
                page.wait_for_timeout(int(hold * 1000))
            lengths.append(time.time() - t_rec0 - starts[-1])
            print(f"  seg {i:02d} {seg.get('id',''):8s}: say at {starts[-1]:6.1f}s  len {lengths[-1]:5.1f}s", flush=True)
        page.wait_for_timeout(800)
        total = time.time() - t_rec0
        ctx.close()
        b.close()
    webm = sorted(vdir.glob("*.webm"), key=lambda p: p.stat().st_mtime)[-1]
    return webm, starts, lengths, d.waits, total


def plan_cuts(waits, keep_head: float, keep_tail: float):
    """A reasoning model on one GPU answers in 20–90 s. The recording keeps the
    first and last moments of each wait and cuts the middle; the cut is
    captioned with the real wait so nothing is hidden."""
    cuts = []
    for ws, we, secs in waits:
        if secs > keep_head + keep_tail + 1.0:
            cuts.append((ws + keep_head, we - keep_tail, secs))
    return cuts


def edited_time(t: float, cuts) -> float:
    """Wall-clock recording time -> time in the cut video."""
    out = t
    for a, b, _ in cuts:
        if t >= b:
            out -= (b - a)
        elif t > a:
            out -= (t - a)
    return out


def mux(webm: Path, segs: list[dict], starts_edited: list[float], cuts, total: float,
        srt: Path, mp4: Path, mute: bool) -> None:
    """Cut the waits out of the recording, lay the narration at its edited
    offsets, burn the captions in, encode H.264/AAC."""
    inputs, filt = ["-i", str(webm)], []
    # video: keep-intervals around the cuts, concatenated
    keeps, pos = [], 0.0
    for a, b, _ in cuts:
        keeps.append((pos, a))
        pos = b
    keeps.append((pos, total))
    for i, (a, b) in enumerate(keeps):
        filt.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
    filt.append("".join(f"[v{i}]" for i in range(len(keeps))) + f"concat=n={len(keeps)}:v=1:a=0[vcat]")
    srt_path = str(srt).replace("\\", "/").replace(":", "\\:")
    filt.append(f"[vcat]subtitles='{srt_path}':force_style='FontName=Segoe UI,FontSize=19,"
                f"PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=4,BackColour=&H80000000,"
                f"Outline=0,Shadow=0,MarginV=34'[vout]")
    audio_inputs = [(i, s) for i, s in enumerate(segs) if s.get("_audio")]
    cmd = ["ffmpeg", "-y", *inputs]
    if audio_inputs and not mute:
        for k, (i, s) in enumerate(audio_inputs, start=1):
            cmd += ["-i", s["_audio"]]
            ms = int(starts_edited[i] * 1000)
            filt.append(f"[{k}:a]aresample=48000,adelay={ms}|{ms}[a{k}]")
        mix = "".join(f"[a{k}]" for k in range(1, len(audio_inputs) + 1))
        filt.append(f"{mix}amix=inputs={len(audio_inputs)}:normalize=0:dropout_transition=0[aout]")
        cmd += ["-filter_complex", ";".join(filt), "-map", "[vout]", "-map", "[aout]",
                "-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-filter_complex", ";".join(filt), "-map", "[vout]", "-an"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(mp4)]
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline", default=str(ROOT / "docs" / "video" / "timeline.json"))
    ap.add_argument("--out", default=str(ROOT / "runs" / "video"))
    ap.add_argument("--app", default="http://localhost:7860")
    ap.add_argument("--voice", default="en-US-AndrewMultilingualNeural")
    ap.add_argument("--rate", default="-4%")
    ap.add_argument("--sapi", action="store_true")
    ap.add_argument("--mute", action="store_true")
    ap.add_argument("--mp4", default=None)
    ap.add_argument("--keep-head", type=float, default=1.5, help="seconds of each model wait kept at its start")
    ap.add_argument("--keep-tail", type=float, default=0.8, help="seconds of each model wait kept at its end")
    ap.add_argument("--wait-caption", default="[the model's answer took {secs:.0f} s; waiting time cut]",
                    help="caption shown where a model wait was cut; {secs} is the real wait")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    timeline = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
    segs = timeline["segments"]
    unfilled = sorted(set(re.findall(r"\{\{[^}]+\}\}", json.dumps(segs))))
    if unfilled:
        raise SystemExit(f"timeline still has placeholders: {unfilled}")
    print("narration:", flush=True)
    durs = narrate(segs, out, voice=a.voice, rate=a.rate, sapi=a.sapi, mute=a.mute)
    print(f"  total narration {sum(durs):.1f}s", flush=True)
    print("recording:", flush=True)
    webm, starts, lengths, waits, total = record(timeline, out, a.app, durs)
    cuts = plan_cuts(waits, a.keep_head, a.keep_tail)
    starts_e = [edited_time(t, cuts) for t in starts]
    srt = out / "captions.srt"
    write_srt(segs, starts_e, [min(l, d + 0.3) if d else l for l, d in zip(lengths, durs)], srt)
    if cuts:   # say on screen what was cut, with the real wait
        extra = srt.read_text(encoding="utf-8").rstrip("\n").split("\n")
        n = sum(1 for l in extra if l.strip().isdigit()) + 1
        for a_, b_, secs in cuts:
            t = edited_time(a_, cuts)
            extra += ["", str(n), f"{srt_time(t)} --> {srt_time(t + 2.2)}",
                      a.wait_caption.format(secs=secs)]
            n += 1
        srt.write_text("\n".join(extra) + "\n", encoding="utf-8")
        print(f"  cuts: {[(round(a_,1), round(b_,1), round(s,1)) for a_, b_, s in cuts]}", flush=True)
    mp4 = Path(a.mp4) if a.mp4 else out / "invisu-preservation-demo.mp4"
    print("muxing:", flush=True)
    mux(webm, segs, starts_e, cuts, total, srt, mp4, a.mute)
    json.dump({"starts_wall": starts, "starts_edited": starts_e, "lengths": lengths, "waits": waits,
               "cuts": cuts, "total_wall": total}, (out / "timing.json").open("w"), indent=1)
    print(f"DONE {mp4}  ({ffprobe_duration(mp4):.1f}s)")


if __name__ == "__main__":
    main()

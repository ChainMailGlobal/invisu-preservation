"""tokenfactory — the one client this project uses to talk to Nebius Token Factory.

Every model call in this repo goes through `chat()`:
  * OpenAI-compatible POST {BASE_URL}/chat/completions
  * one JSONL ledger line per call (tokens, dollars, latency, purpose) so the
    cost line in the README can be re-derived from receipts, not memory
  * a hard spend cap (TF_CAP_USD, default $5) checked BEFORE each call
  * HTTP 402 (credits exhausted) raises immediately — nothing retries past it

Models used by this project (ids as listed by GET /v1/models on 2026-10-27):
  EYES  = nvidia/Nemotron-3.5-Super-VL        reads the scanned sheets
  BRAIN = nvidia/Nemotron-3-Ultra-550b-a55b   answers questions over the index

The same client talks to a self-served Nemotron on a Nebius AI Cloud Serverless
endpoint (vLLM, OpenAI-compatible) — see docs/RUN_AI_CLOUD_ENDPOINT.md. Nothing
changes but the environment:
  TOKEN_FACTORY_BASE_URL   endpoint URL + /v1
  INFERENCE_API_KEY        the endpoint's bearer token (TOKEN_FACTORY_API_KEY also works)
  INFERENCE_PROVIDER       tag written on every ledger row (default: token-factory)
  EYES_MODEL / BRAIN_MODEL model ids served there
GPU time is billed per second, not per token, so it is recorded as a
`gpu_session` ledger row (`python -m preservation.tokenfactory --gpu-session …`).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.environ.get("TOKEN_FACTORY_BASE_URL",
                          "https://api.tokenfactory.nebius.com/v1").rstrip("/")
PROVIDER = os.environ.get("INFERENCE_PROVIDER", "token-factory")
EYES = os.environ.get("EYES_MODEL", "nvidia/Nemotron-3.5-Super-VL")
BRAIN = os.environ.get("BRAIN_MODEL", "nvidia/Nemotron-3-Ultra-550b-a55b")

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path(os.environ.get("TF_LEDGER", ROOT / "docs" / "cost_ledger.jsonl"))
CAP_USD = float(os.environ.get("TF_CAP_USD", "5"))

# USD per 1M tokens: (input, output). Filled from the public Token Factory price
# list; a None entry means "price not confirmed" and the ledger records usd=null
# for that model rather than inventing a number. See README "Cost".
PRICES: dict[str, tuple[float, float] | None] = {
    EYES: None,
    BRAIN: None,
}


class CreditsExhausted(RuntimeError):
    """Token Factory answered HTTP 402 — stop everything, report."""


class SpendCapReached(RuntimeError):
    """The ledger total passed TF_CAP_USD — stop everything, report."""


class NoApiKey(RuntimeError):
    """TOKEN_FACTORY_API_KEY is not set anywhere we look."""


def has_key() -> bool:
    try:
        api_key()
        return True
    except NoApiKey:
        return False


def api_key() -> str:
    key = (os.environ.get("INFERENCE_API_KEY", "").strip()
           or os.environ.get("TOKEN_FACTORY_API_KEY", "").strip())
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("TOKEN_FACTORY_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise NoApiKey("TOKEN_FACTORY_API_KEY not set (export it or copy "
                       ".env.example to .env)")
    return key


def price(model: str, usage: dict) -> float | None:
    p = PRICES.get(model)
    if not p:
        return None
    pin, pout = p
    return (usage.get("prompt_tokens", 0) * pin
            + usage.get("completion_tokens", 0) * pout) / 1_000_000


def ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    rows = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def spent() -> dict:
    """Totals by model and overall: calls, prompt/completion tokens, usd."""
    out: dict = {"total": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                           "usd": 0.0, "unpriced_calls": 0}}
    for r in ledger_rows():
        if r.get("kind") == "gpu_session":
            # GPU time (AI Cloud endpoint): dollars from seconds, no tokens.
            k = f"gpu-session:{r.get('provider', '?')}"
            d = out.setdefault(k, {"calls": 0, "prompt_tokens": 0,
                                   "completion_tokens": 0, "usd": 0.0,
                                   "unpriced_calls": 0, "minutes": 0.0})
            d["minutes"] += float(r.get("minutes", 0))
            d["usd"] += float(r.get("usd", 0))
            out["total"]["usd"] += float(r.get("usd", 0))
            continue
        for k in (r.get("model", "?"), "total"):
            d = out.setdefault(k, {"calls": 0, "prompt_tokens": 0,
                                   "completion_tokens": 0, "usd": 0.0,
                                   "unpriced_calls": 0})
            d["calls"] += 1
            d["prompt_tokens"] += r.get("prompt_tokens", 0)
            d["completion_tokens"] += r.get("completion_tokens", 0)
            if r.get("usd") is None:
                d["unpriced_calls"] += 1
            else:
                d["usd"] += r["usd"]
    return out


def _record(row: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def chat(model: str, messages: list, *, max_tokens: int = 1500,
         temperature: float = 0.0, extra: dict | None = None, purpose: str = "",
         timeout: int = 300, retries: int = 3):
    """One chat completion. Returns (reply, err): reply is a dict with
    text / reasoning / finish / usage / usd / latency_s, err is a string.
    Raises CreditsExhausted on 402 and SpendCapReached when the ledger total
    has passed TF_CAP_USD."""
    total = spent()["total"]["usd"]
    if total >= CAP_USD:
        raise SpendCapReached(f"ledger total ${total:.4f} >= cap ${CAP_USD:.2f}")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature}
    if extra:
        body.update(extra)
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {api_key()}",
                 "Content-Type": "application/json"})
    err = "no attempt"
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 402:
                raise CreditsExhausted(f"HTTP 402 from Token Factory: {detail}")
            err = f"HTTP{e.code}: {detail}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                continue
            return None, err
        except Exception as e:  # timeouts, connection resets
            err = f"{type(e).__name__}: {str(e)[:160]}"
            time.sleep(3 * (attempt + 1))
            continue
        latency = time.time() - t0
        choice = (r.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = r.get("usage") or {}
        reply = {
            "text": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or msg.get("reasoning") or "",
            "finish": choice.get("finish_reason"),
            "usage": usage,
            "usd": price(model, usage),
            "latency_s": round(latency, 1),
        }
        _record({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": model,
                 "provider": PROVIDER, "purpose": purpose,
                 "prompt_tokens": usage.get("prompt_tokens", 0),
                 "completion_tokens": usage.get("completion_tokens", 0),
                 "total_tokens": usage.get("total_tokens", 0),
                 "usd": reply["usd"], "latency_s": reply["latency_s"],
                 "finish_reason": reply["finish"],
                 "content_chars": len(reply["text"]),
                 "reasoning_chars": len(reply["reasoning"])})
        return reply, None
    return None, err


def cost_line() -> str:
    """Human-readable cost summary for reports."""
    s = spent()
    parts = []
    for model, d in s.items():
        if model == "total":
            continue
        if model.startswith("gpu-session:"):
            parts.append(f"{model}: {d['minutes']:.0f} min of GPU time, ${d['usd']:.2f}")
            continue
        usd = f"${d['usd']:.4f}" if not d["unpriced_calls"] else \
            f"${d['usd']:.4f} (+{d['unpriced_calls']} unpriced)"
        parts.append(f"{model}: {d['calls']} calls, {d['prompt_tokens']:,} in / "
                     f"{d['completion_tokens']:,} out, {usd}")
    t = s["total"]
    parts.append(f"TOTAL: {t['calls']} calls, {t['prompt_tokens']:,} in / "
                 f"{t['completion_tokens']:,} out, ${t['usd']:.4f}"
                 + (f" (+{t['unpriced_calls']} unpriced)" if t["unpriced_calls"] else ""))
    return "\n".join(parts)


def record_gpu_session(provider: str, rate_usd_per_hour: float, minutes: float,
                       note: str = "") -> dict:
    """Append one gpu_session row: an AI Cloud endpoint's lifetime, priced
    per second from the published hourly rate. Lifetime, not call time —
    the GPU bills from creation to deletion."""
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "gpu_session",
           "provider": provider, "rate_usd_per_hour": rate_usd_per_hour,
           "minutes": round(minutes, 1),
           "usd": round(rate_usd_per_hour * minutes / 60, 4), "note": note}
    _record(row)
    return row


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="cost line, or record GPU time")
    ap.add_argument("--gpu-session", metavar="PROVIDER",
                    help="record an endpoint lifetime, e.g. ai-cloud-l40s")
    ap.add_argument("--rate", type=float, help="USD per GPU-hour, e.g. 1.55")
    ap.add_argument("--minutes", type=float, help="endpoint lifetime in minutes")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    if a.gpu_session:
        if a.rate is None or a.minutes is None:
            ap.error("--gpu-session needs --rate and --minutes")
        print(json.dumps(record_gpu_session(a.gpu_session, a.rate, a.minutes, a.note)))
    print(cost_line())

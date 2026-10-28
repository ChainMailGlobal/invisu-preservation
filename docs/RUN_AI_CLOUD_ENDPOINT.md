# Running the reader on Nebius AI Cloud (Serverless AI endpoint)

Written 2026-10-28. Token Factory answered 402 on every call; the AI Cloud
balance ($9.78) bills GPU-seconds instead of tokens, and the hackathon accepts
either surface. This runbook serves a Nemotron model ourselves on one GPU with
vLLM and points the unchanged client at it. Same code, same JSON contract, same
ledger — which makes it a Token Factory vs AI Cloud comparison for the feedback
form.

Facts verified 2026-10-28 (docs.nebius.com, nebius.com/prices, model cards):

| Item | Value |
|---|---|
| L40S (48 GB), 1 GPU | `gpu-l40s-a` / `1gpu-8vcpu-32gb`, **$1.55/h on-demand**, region `eu-north1` only |
| H100 (80 GB), 1 GPU | `gpu-h100-sxm` / `1gpu-16vcpu-200gb`, **$4.50/h on-demand**, `eu-north1` only |
| Billing | per second while the endpoint exists; **delete** it to stop (no pause) |
| Create time | about 5 minutes to `Running`, then the model download on top |
| Model (both seats) | `nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8` — 31B total / ~3B active, image+text, 256k context, NVIDIA card: "Minimum GPU (FP8): 1× L40S 48GB"; the same family Token Factory removed in August |
| Alternative eyes | `nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-BF16` — 12.6B, 26.4 GB, document-intelligence model, L40S; text seat would then need a second endpoint |
| vLLM image | `vllm/vllm-openai:v0.20.0` (the Omni card's example; Nebius' tutorial pins `v0.18.0-cu130`, which also lists the Omni architecture as supported) |

Expected spend: ~1.5 h of L40S ≈ **$2.50**. Hard stop: delete the endpoint when
the console balance shows **$2.00** or less, whatever state the run is in.

## 1. CEO: create the endpoint (console, ~3 minutes)

console.nebius.com → **Serverless AI → Endpoints → Create endpoint**

| Field | Value |
|---|---|
| Configuration | Custom |
| Name | `invisu-nemotron` |
| Image path | `vllm/vllm-openai:v0.20.0` |
| Ports | `8000` |
| Entrypoint command | `python3 -m vllm.entrypoints.openai.api_server --model nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8 --trust-remote-code --max-model-len 65536 --max-num-seqs 4 --gpu-memory-utilization 0.92 --kv-cache-dtype fp8 --host 0.0.0.0 --port 8000` |
| Bearer token authentication | Enabled — copy the generated token |
| Computing resources | With GPU |
| Platform | NVIDIA® L40S Intel |
| Preset | 1 GPU — 8 CPUs — 32 GiB RAM |
| Shared memory (if the field exists) | 16 GiB |
| Disk (if the field exists) | 100 GB (the weights are ~34 GB) |
| Network | Public static IP |

Create. Status reaches `Running` in ~5 min; the model then downloads from
Hugging Face. **View logs** shows `Application startup complete` when vLLM is
serving. Then send the CTO two lines: the `https://…` URL from **Public
endpoints**, and the token.

If the platform list has no L40S, the project is not in `eu-north1`: say which
region it shows. If logs end in `CUDA out of memory`: delete, recreate on
**NVIDIA H100, 1 GPU — 16 CPUs — 200 GiB**, same command.

Optional safety: **Billing → Budgets** → alert at $8.

## 2. CTO: run (laptop, ~1 hour of endpoint time)

```bash
cd C:/Dev/invisu-preservation
export TOKEN_FACTORY_BASE_URL="<endpoint URL>/v1"
export INFERENCE_API_KEY="<token>"
export INFERENCE_PROVIDER="ai-cloud-l40s"
export EYES_MODEL="nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-FP8"
export BRAIN_MODEL="$EYES_MODEL"
curl -s -H "Authorization: Bearer $INFERENCE_API_KEY" "$TOKEN_FACTORY_BASE_URL/models"   # smoke
# Settings that worked on 2026-10-28 (see the commit log for why each exists):
#   eyes: --thinking off --rep-penalty 1.05 --max-tokens 6000   (no penalty = repetition loop)
#   brain: --thinking on --max-tokens 4000                       (reasoning is inline; the agent parses the last OUTCOME block)
python -m preservation.read_scans data/iolani-palace --only 11 --thinking off --rep-penalty 1.05 --max-tokens 6000   # inspect by eye
python -m preservation.read_scans data/iolani-palace --kind sheet --thinking off --rep-penalty 1.05 --max-tokens 6000 # all 23, ~25 s each
python -m preservation.read_scans data/iolani-palace --kind sheet --tiles --thinking off --rep-penalty 1.05           # quadrant pass, 92 calls, ~15 min
python -m preservation.build_index data/iolani-palace
python -m preservation.agent data/iolani-palace "where is the throne room" --thinking on --max-tokens 4000 --save docs/transcripts/throne_room.md
# … the other three questions, incl. the one that must say NOT IN THE SET
python -m preservation.tokenfactory --gpu-session ai-cloud-l40s --rate 0.77 --minutes <endpoint lifetime>   # preemptible rate shown by the console
```

Observed 2026-10-28 (L40S, preemptible, console estimate $0.77/h): endpoint Running
after ~5 min, serving after ~27 min (35 GB download). Full-sheet read 7–24 s per
sheet, 23/23 finished on `stop` with the penalty; quadrant call 3–10 s. Omni answers
the quadrant prompt with a bare JSON array and mixes pixel and fraction scales in
one box — both handled in `read_scans.py` now.

## 3. CEO: delete (1 minute)

When the CTO says **done**: Endpoints → row menu → **Delete** → confirm. Check
the balance. Never leave it overnight: an idle L40S is ~$37/day and the balance
is $9.78.

## What goes in the writeup

- Eyes and brain: Nemotron 3 Nano Omni 30B-A3B (FP8) on **one L40S** via a
  Nebius AI Cloud Serverless endpoint; Nemotron Ultra on Token Factory only if
  credits arrive before the deadline.
- Feedback: the same client ran against both Nebius surfaces. Token Factory:
  model removed without notice, 402 with no balance endpoint. AI Cloud: weights
  pinned by us, per-second billing, ~5 min to serve, one GPU. Numbers from the
  ledger.

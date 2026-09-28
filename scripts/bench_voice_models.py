"""
bench_voice_models.py — pick the model chain that answers JARVIS's voice turns.

LAYER: Tools (Voice latency)

Run with:
    python scripts/bench_voice_models.py              # benchmark + write jarvis_data/voice_models.json
    python scripts/bench_voice_models.py --dry-run    # benchmark, print, write nothing
    python scripts/bench_voice_models.py --trials 5

=============================================================================
THE BIG PICTURE
=============================================================================

For voice, the number that decides how JARVIS FEELS is time-to-first-token
(TTFT): speech synthesis starts on the first finished sentence, so a model
that begins answering in 0.6 s beats one that finishes sooner but starts at
3 s. Average full-call latency — the only number model_stats.jsonl keeps —
cannot tell those two apart. This script measures TTFT on a streamed call,
the way brain/voice_path.py will actually use the model.

It also checks the one behaviour the voice fast path depends on: when a
request needs tools, the model must lead with the <<DEEP>> sentinel instead
of improvising an answer. A fast model that ignores the sentinel would make
JARVIS confidently answer questions about files it never opened, so a
candidate that fails the check is not eligible regardless of speed.

The output is a CHAIN, not a single model: fastest eligible paid model
first, fastest eligible free model after it. A paid call refused for credit
(HTTP 402) fails over to the free one immediately at runtime.

=============================================================================
THE FLOW
=============================================================================

STEP 1: For each candidate, run --trials streamed small-talk calls and record
        TTFT (first CONTENT token — reasoning tokens are not speakable) and
        total time. A 402 marks the model unaffordable and skips it.
        |
STEP 2: Run one escalation probe; eligible only if the reply starts <<DEEP>>
        and the small-talk replies do NOT.
        |
STEP 3: Rank eligible models by median TTFT within paid and within free,
        print the table, and write jarvis_data/voice_models.json.
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "jarvis_data" / "voice_models.json"
_URL = "https://openrouter.ai/api/v1/chat/completions"
_IST = timezone(timedelta(hours=5, minutes=30))

PAID = [
    "qwen/qwen3-32b",
    "openai/gpt-oss-120b",
    "google/gemini-2.5-flash-lite",
    "openai/gpt-oss-20b",
    "meta-llama/llama-3.1-8b-instruct",
    "qwen/qwen3-30b-a3b-instruct-2507",
    "deepseek/deepseek-v4-flash",
]
FREE = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-26b-a4b-it:free",
    "openrouter/free",
]

SENTINEL = "<<DEEP>>"
SYSTEM = (
    "You are JARVIS, a calm, dry, precise British AI assistant. Reply in one or two short "
    "spoken sentences, no lists, no markdown. If answering properly would require reading "
    "files, running tools, browsing, or searching memory you do not have in front of you, "
    f"reply with exactly {SENTINEL} and nothing else."
)
SMALL_TALK = ["Hi, JARVIS.", "How are you doing today?", "Good morning."]
ESCALATIONS = [
    "Open scripts/hearth.py and tell me what the main function does on line 243.",
    "Search my knowledge base for what I decided about the Stage 5 adapter.",
    "Check whether the hearth's reindex_memory job failed last night and why.",
]


_SYSTEM_CACHE: Dict[str, str] = {}


def _voice_messages(prompt: str) -> List[Dict[str, str]]:
    if "system" not in _SYSTEM_CACHE:
        sys.path.insert(0, str(_ROOT / "js-development"))
        from jarvis_core.brain.voice_path import VoiceBrain
        _SYSTEM_CACHE["system"] = VoiceBrain(history_fn=lambda s, q: []).prompt("x", "bench")[0]["content"]
    return [{"role": "system", "content": _SYSTEM_CACHE["system"]}, {"role": "user", "content": prompt}]


def _stream(model: str, prompt: str, key: str, client: httpx.Client,
            timeout: float = 40.0) -> Dict[str, Any]:
    t0 = time.perf_counter()
    first_any: Optional[float] = None
    first_content: Optional[float] = None
    text: List[str] = []
    # The REAL voice prompt, not a toy one. Measured 2026-09-27: the same model
    # answered a one-line prompt in 0.37 s and the 6 K-char voice prompt in
    # 2.4 s, so ranking on a toy prompt picked the wrong chain.
    messages = _voice_messages(prompt)
    payload = {"model": model, "stream": True, "max_tokens": 120, "messages": messages,
               "provider": {"sort": "latency"}}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        with client.stream("POST", _URL, json=payload, headers=headers, timeout=timeout) as r:
            if r.status_code != 200:
                body = r.read().decode("utf-8", "replace")[:200]
                return {"ok": False, "status": r.status_code, "error": body}
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if "error" in chunk:
                    return {"ok": False, "status": chunk["error"].get("code"), "error": str(chunk["error"])[:200]}
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                now = time.perf_counter()
                if first_any is None and (delta.get("content") or delta.get("reasoning")):
                    first_any = now - t0
                piece = delta.get("content") or ""
                if piece:
                    if first_content is None:
                        first_content = now - t0
                    text.append(piece)
    except httpx.HTTPError as e:
        return {"ok": False, "status": None, "error": f"{type(e).__name__}: {e}"[:200]}
    reply = "".join(text).strip()
    if first_content is None:
        return {"ok": False, "status": 200, "error": "no content tokens"}
    return {"ok": True, "ttft": first_content, "first_any": first_any,
            "total": time.perf_counter() - t0, "reply": reply}


def bench(model: str, key: str, trials: int, client: httpx.Client) -> Dict[str, Any]:
    # One unmeasured call first: the runtime keeps a warm connection, so a
    # TLS handshake inside the first measurement would overstate TTFT.
    _stream(model, SMALL_TALK[0], key, client)
    runs = []
    for i in range(trials):
        res = _stream(model, SMALL_TALK[i % len(SMALL_TALK)], key, client)
        if not res["ok"]:
            if res.get("status") in (402, "402"):
                return {"model": model, "eligible": False, "reason": "unaffordable (402)"}
            runs.append(res)
            continue
        runs.append(res)
    good = [r for r in runs if r["ok"]]
    if not good:
        return {"model": model, "eligible": False,
                "reason": f"all {trials} calls failed: {runs[0].get('error', '?')[:80]}"}
    leaked = [r for r in good if r["reply"].startswith(SENTINEL)]
    escalated = sum(1 for q in ESCALATIONS
                    if (lambda e: e.get("ok") and e["reply"].startswith(SENTINEL))(_stream(model, q, key, client)))
    obeys = escalated >= 2
    ttfts = [r["ttft"] for r in good]
    out = {
        "model": model,
        "ok_calls": f"{len(good)}/{trials}",
        "ttft_p50": round(statistics.median(ttfts), 3),
        "ttft_max": round(max(ttfts), 3),
        "total_p50": round(statistics.median(r["total"] for r in good), 3),
        "sample": good[0]["reply"][:90],
        "escalates": f"{escalated}/{len(ESCALATIONS)}",
        "false_escalations": len(leaked),
    }
    if not obeys:
        out.update(eligible=False, reason=f"escalated only {escalated}/{len(ESCALATIONS)} tool requests")
    elif leaked:
        out.update(eligible=False, reason="escalated on small talk")
    else:
        out.update(eligible=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        print("OPENROUTER_API_KEY is not set in this environment.")
        return 2

    results: Dict[str, List[Dict[str, Any]]] = {"paid": [], "free": []}
    with httpx.Client(http2=False) as client:
        for tier, models in (("paid", PAID), ("free", FREE)):
            for m in models:
                print(f"  benchmarking {m} ...", flush=True)
                results[tier].append(bench(m, key, args.trials, client))

    print()
    print(f"  {'model':44} {'tier':5} {'ok':5} {'TTFT p50':>9} {'TTFT max':>9} {'total':>7}  verdict")
    print("  " + "-" * 110)
    for tier in ("paid", "free"):
        for r in results[tier]:
            if "ttft_p50" in r:
                verdict = "ELIGIBLE" if r["eligible"] else r["reason"]
                print(f"  {r['model']:44} {tier:5} {r['ok_calls']:5} {r['ttft_p50']:>8.2f}s "
                      f"{r['ttft_max']:>8.2f}s {r['total_p50']:>6.2f}s  {verdict}")
            else:
                print(f"  {r['model']:44} {tier:5} {'-':5} {'-':>9} {'-':>9} {'-':>7}  {r['reason']}")

    def best(tier: str, n: int) -> List[str]:
        ok = sorted((r for r in results[tier] if r.get("eligible")), key=lambda r: r["ttft_p50"])
        return [r["model"] for r in ok[:n]]

    # Two paid models, not one: brain/voice_path.py HEDGES — a stalled first
    # model races the second — and a hedge is only as good as the runner-up.
    chain = best("paid", 2) + best("free", 1)
    print(f"\n  chain: {chain or 'NONE ELIGIBLE'}")
    if not chain:
        print("  No model passed. voice_models.json left unchanged.")
        return 1
    if args.dry_run:
        return 0
    record = {
        "_comment": ("Written by scripts/bench_voice_models.py. brain/voice_path.py streams from "
                     "chain[0] and fails over to the next on error or HTTP 402. Re-run the script "
                     "after a credit top-up or when a model degrades."),
        "measured_at": datetime.now(_IST).isoformat(timespec="seconds"),
        "chain": chain,
        "results": results,
    }
    _OUT.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {_OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

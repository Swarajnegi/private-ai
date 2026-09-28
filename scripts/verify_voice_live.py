"""
verify_voice_live.py — the Phase 1 latency gate for hands-free voice.

LAYER: Tools (Voice verification)

Run with (the hearth must be running):
    python scripts/verify_voice_live.py                 # render test speech once, run all turns
    python scripts/verify_voice_live.py --turns 3
    python scripts/verify_voice_live.py --only "Hi, JARVIS."
    python scripts/verify_voice_live.py --free-only       # every answer from a free model

=============================================================================
THE BIG PICTURE
=============================================================================

"It feels fast" is not a measurement. This script is a scripted user: it
speaks pre-rendered utterances into WS /v1/voice/live at real-time pace,
exactly as a microphone would, and times what the user actually experiences —
from the last word they said to the first sound of JARVIS's reply. That
includes the VAD's end-of-speech wait, which the server's own timings cannot
see because the server only learns the user stopped after that wait.

The "user" is rendered in a different Kokoro voice (am_michael) from JARVIS's
(bm_lewis), so a passing run cannot be JARVIS transcribing itself.

The session id is a throwaway `conv-web-voicegate-<ts>`, opened EPHEMERAL: no
capture row and no fast-path persistence, and the script deletes whatever
conversation file the deep path wrote. Its scripted prompts must never reach
the training corpus as if the owner had said them — that happened on
2026-09-27 before this flag existed (63 queue rows, since removed).

=============================================================================
THE FLOW
=============================================================================

STEP 1: render each prompt to 16 kHz PCM16 once (cached in artifacts/voice-test).
        |
STEP 2: for each prompt: stream it in 32 ms frames at real time, then send
        silence until JARVIS responds; record every event with a timestamp.
        |
STEP 3: print per-turn stage timings and p50/p95 of speech-end -> first audio.
=============================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import asyncio
import json
import statistics
import sys
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "artifacts" / "voice-test"
URL = "ws://127.0.0.1:8756/v1/voice/live?token={token}"
FRAME = 512
RATE = 16000

HELLO_EXTRA: dict = {}

PROMPTS = [
    "Hi, JARVIS.",
    "How are you doing today?",
    "Good morning, JARVIS. Anything I should know?",
    "What's the difference between a thread and a process? Keep it short.",
    "Tell me a quick joke about databases.",
    "Say something encouraging, I've had a long day.",
    "What does idempotent mean?",
    "Thanks, JARVIS.",
    "Explain what a vector database is in one sentence.",
    "Open scripts/hearth.py and tell me what line 243 does.",
]


def render(prompts: List[str]) -> Dict[str, Path]:
    CACHE.mkdir(parents=True, exist_ok=True)
    paths = {p: CACHE / f"{hashlib.sha1(p.encode()).hexdigest()[:12]}.wav" for p in prompts}
    missing = [p for p, f in paths.items() if not f.exists()]
    if missing:
        import torch  # noqa: F401  (load-order rule: torch before anything CUDA-adjacent)
        from kokoro import KPipeline
        pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cpu")  # never compete with the hearth for VRAM
        for p in missing:
            audio = np.concatenate([a.cpu().numpy() for _, _, a in pipe(p, voice="am_michael")])
            a16 = np.interp(np.linspace(0, len(audio), int(len(audio) * RATE / 24000), endpoint=False),
                            np.arange(len(audio)), audio)
            with wave.open(str(paths[p]), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
                w.writeframes((np.clip(a16, -1, 1) * 32767).astype(np.int16).tobytes())
    return paths


def load(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


async def one_turn(ws: Any, pcm: bytes, timeout: float = 90.0) -> Dict[str, Any]:
    events: List[Any] = []
    t_speech_end = None
    got_audio = asyncio.Event()
    done = asyncio.Event()

    async def reader() -> None:
        while not done.is_set():
            msg = await ws.recv()
            now = time.perf_counter()
            if isinstance(msg, bytes):
                events.append((now, "audio", len(msg)))
                got_audio.set()
                continue
            ev = json.loads(msg)
            events.append((now, ev.get("type"), ev))
            if ev.get("type") == "state" and ev.get("state") == "listening" and got_audio.is_set():
                done.set()
            if ev.get("type") == "error":
                done.set()

    task = asyncio.create_task(reader())
    silence = bytes(FRAME * 2)
    step = FRAME / RATE
    t = time.perf_counter()
    for i in range(0, len(pcm), FRAME * 2):
        await ws.send(pcm[i:i + FRAME * 2])
        t += step
        await asyncio.sleep(max(0.0, t - time.perf_counter()))
    t_speech_end = time.perf_counter()
    deadline = t_speech_end + timeout
    while not done.is_set() and time.perf_counter() < deadline:
        await ws.send(silence)
        t += step
        await asyncio.sleep(max(0.0, t - time.perf_counter()))
    done.set()
    task.cancel()

    def first(kind: str, pred=lambda e: True):
        return next((ts for ts, k, e in events if k == kind and pred(e)), None)
    rel = lambda ts: None if ts is None else round(ts - t_speech_end, 3)   # noqa: E731
    heard = next((e.get("text") for _, k, e in events if k == "final"), None)
    answer = next((e for _, k, e in events if k == "answer"), {})
    return {
        "heard": heard,
        "path": answer.get("path"),
        "model": answer.get("model"),
        "answer": (answer.get("text") or "")[:120],
        "final_s": rel(first("final")),
        "first_token_s": rel(first("token")),
        "first_audio_s": rel(first("audio")),
        "error": next((e.get("error") for _, k, e in events if k == "error"), None),
    }


async def main_async(args: argparse.Namespace) -> int:
    import websockets
    token = (ROOT / "jarvis_data" / ".hearth_token").read_text(encoding="utf-8").strip()
    prompts = [args.only] if args.only else PROMPTS[: args.turns]
    paths = render(prompts)
    session = f"conv-web-voicegate-{datetime.now():%Y%m%dT%H%M%S}"
    results = []
    async with websockets.connect(URL.format(token=token), max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "session": session, "hands_free": True, "ephemeral": True, **HELLO_EXTRA}))
        while True:
            ev = json.loads(await ws.recv())
            if ev.get("type") == "state" and ev.get("state") == "listening":
                break
        for p in prompts:
            r = await one_turn(ws, load(paths[p]))
            r["said"] = p
            results.append(r)
            print(f"  said {p!r}\n    heard {r['heard']!r}  path={r['path']} model={r['model']}\n"
                  f"    transcript +{r['final_s']}s  first token +{r['first_token_s']}s  "
                  f"FIRST AUDIO +{r['first_audio_s']}s\n    -> {r['answer']!r}"
                  + (f"\n    ERROR {r['error']}" if r["error"] else ""), flush=True)
            await asyncio.sleep(0.8)
    fa = [r["first_audio_s"] for r in results if r["first_audio_s"] is not None and r["path"] == "fast"]
    if fa:
        fa.sort()
        p95 = fa[min(len(fa) - 1, int(round(0.95 * (len(fa) - 1))))]
        print(f"\n  fast path, speech-end -> first audio: p50 {statistics.median(fa):.2f}s  "
              f"p95 {p95:.2f}s  over {len(fa)} turns  (gate: p50 <= 3.0s)")
    print(f"  session: {session}")
    return 0


async def scenarios(args: argparse.Namespace) -> int:
    """Phase 3 on the REAL engines: a mid-sentence pause longer than the VAD
    endpoint must still yield ONE question, and speaking over JARVIS must stop it."""
    import websockets
    token = (ROOT / "jarvis_data" / ".hearth_token").read_text(encoding="utf-8").strip()
    parts = ["What's the weather usually like", "in Mumbai in the monsoon?",
             "Tell me a long story about a lighthouse keeper.", "Stop. That's enough, thank you."]
    paths = render(parts)
    silence = lambda s: bytes(int(RATE * s) * 2)                      # noqa: E731
    session = f"conv-web-voicegate-{datetime.now():%Y%m%dT%H%M%S}"
    ok = True
    async with websockets.connect(URL.format(token=token), max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "session": session, "hands_free": True, "ephemeral": True, **HELLO_EXTRA}))
        while json.loads(await ws.recv()).get("state") != "listening":
            pass

        async def feed(pcm: bytes) -> None:
            t = time.perf_counter()
            for i in range(0, len(pcm), FRAME * 2):
                await ws.send(pcm[i:i + FRAME * 2])
                t += FRAME / RATE
                await asyncio.sleep(max(0.0, t - time.perf_counter()))

        async def drain(until, timeout: float = 60.0) -> List[Any]:
            got: List[Any] = []
            end = time.perf_counter() + timeout
            while time.perf_counter() < end:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.05)
                except asyncio.TimeoutError:
                    await ws.send(silence(0.032))
                    continue
                ev = ("audio",) if isinstance(msg, bytes) else json.loads(msg)
                got.append(ev)
                if until(ev, got):
                    break
            return got

        # 1. continuation across a pause longer than the endpoint
        await feed(load(paths[parts[0]]) + silence(0.75) + load(paths[parts[1]]))
        got = await drain(lambda ev, g: isinstance(ev, dict) and ev.get("type") == "state"
                          and ev.get("state") == "listening" and any(e == ("audio",) for e in g))
        finals = [e["text"] for e in got if isinstance(e, dict) and e.get("type") == "final"]
        merged = len(finals) == 1 and "mumbai" in finals[0].lower() and "weather" in finals[0].lower()
        ok &= merged
        print(f"  continuation: {len(finals)} committed question(s): {finals}  -> {'PASS' if merged else 'FAIL'}")

        # 2. barge-in: talk over a long answer
        await feed(load(paths[parts[2]]) + silence(0.2))
        await drain(lambda ev, g: isinstance(ev, dict) and ev.get("type") == "audio_start")
        await asyncio.sleep(1.2)                                        # let JARVIS speak a moment
        # Read concurrently with speaking: a reader that starts after the clip
        # finishes would report the clip's length, not the server's reaction.
        stop_at: List[float] = []

        async def watch() -> None:
            while not stop_at:
                msg = await ws.recv()
                if isinstance(msg, str) and json.loads(msg).get("type") == "stop_audio":
                    stop_at.append(time.perf_counter())
        watcher = asyncio.create_task(watch())
        t_barge = time.perf_counter()
        await feed(load(paths[parts[3]]))
        try:
            await asyncio.wait_for(watcher, timeout=5)
        except asyncio.TimeoutError:
            watcher.cancel()
        stopped = bool(stop_at)
        ok &= stopped
        after = f"{stop_at[0] - t_barge:.2f}s" if stopped else "-"
        print(f"  barge-in: playback stopped {after} after the user began speaking  -> {'PASS' if stopped else 'FAIL'}")
        got = await drain(lambda ev, g: isinstance(ev, dict) and ev.get("type") == "final", timeout=15)
        nxt = [e["text"] for e in got if isinstance(e, dict) and e.get("type") == "final"]
        took = bool(nxt) and "enough" in nxt[0].lower()
        ok &= took
        print(f"  barge-in: the interruption became the next question: {nxt}  -> {'PASS' if took else 'FAIL'}")
    print(f"  session: {session}")
    return 0 if ok else 1


def cleanup(prefix: str = "conv-web-voicegate-") -> None:
    """Remove the conversation files this script's sessions created. Ephemeral
    mode stops capture and fast-path persistence; the full orchestrator path
    still writes its own conversation file, so the script owns the cleanup."""
    conv = ROOT / "jarvis_data" / "conversations"
    for f in conv.glob(prefix + "*"):
        f.unlink(missing_ok=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # answers carry em-dashes; cp1252 consoles crash on them
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=len(PROMPTS))
    ap.add_argument("--only")
    ap.add_argument("--scenarios", action="store_true", help="Phase 3: continuation + barge-in")
    ap.add_argument("--free-only", action="store_true", help="FREE MODELS mode: no paid model may answer")
    args = ap.parse_args()
    if args.free_only:
        HELLO_EXTRA["free_only"] = True
    try:
        return asyncio.run(scenarios(args) if args.scenarios else main_async(args))
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())

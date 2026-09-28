"""
voice_path.py — the fast path: one streamed call for a spoken turn.

LAYER: Brain (Orchestration)

Run with:
    PYTHONPATH=js-development python -m jarvis_core.brain.voice_path             # hermetic self-test
    PYTHONPATH=js-development python -m jarvis_core.brain.voice_path --live "Hi, JARVIS."

=============================================================================
THE BIG PICTURE
=============================================================================

orchestrator.ask() is built for work: it decomposes the request, runs a
ReAct loop, may replan, and only then returns. Even "Hi, JARVIS" costs two
sequential non-streamed LLM calls — 9-28 s measured on 2026-09-26 — before
a single word can be spoken.

Most spoken turns do not need tools. This path answers them with ONE
streamed completion that carries the same identity (JARVIS_PSYCHE_PROMPT),
the same boot inhale (profile, activity, self-state), and the same
conversation history as the full path — spoken in the VOICE_SPEC register.
The first sentence reaches the speech engine while the rest is still being
generated.

When a turn DOES need tools, files or memory search, the model says so by
opening with the <<DEEP>> sentinel. That is detected before anything is
spoken, and the turn is handed to orchestrator.ask() intact. The sentinel
is only reliable on models that honour it, which is why
scripts/bench_voice_models.py refuses models that fail its escalation
probes — llama-3.1-8b is the fastest candidate and is excluded for exactly
this reason (it answered questions about files it had never opened).

=============================================================================
TWO CONTRACTS THIS PATH MUST NOT BREAK
=============================================================================

1. OUTBOUND REDACTION. brain/outbound_policy.redact_outbound strips client
   identifiers from what leaves the machine, but the full path applies it
   only inside ContextInjector. This path therefore takes its inhale through
   ContextInjector — never around it — and additionally redacts the history
   and the question, which the full path does not.

2. PERSISTENCE PARITY. The 43-question interview, the training corpora and
   the activity digest all read what a turn leaves behind. persist_turn()
   writes the same capture row and the same two conversation turns the full
   path writes (orchestrator.py build_observation/append_observation and
   ConversationStore.append_turn) — after the answer is spoken, so it costs
   no latency.

=============================================================================
THE FLOW
=============================================================================

STEP 1: prompt() = persona + voice register + cached inhale + redacted
        history (ConversationStore.load_context) + the question.
        |
STEP 2: respond() streams from voice_models.json's chain. The first
        len(<<DEEP>>) characters are held back; if they ARE the sentinel,
        yield {"type": "deep"} and stop. Failover to the next model happens
        only before the first token.
        |
STEP 3: tokens are yielded as {"type": "token"}; the caller chunks them into
        sentences for speech. {"type": "done"} closes the turn.
        |
STEP 4: persist_turn() runs after playback starts.
=============================================================================
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jarvis_core.config import DATA_ROOT  # noqa: E402

SENTINEL = "<<DEEP>>"
MODELS_PATH = Path(DATA_ROOT) / "voice_models.json"
FALLBACK_CHAIN = ("qwen/qwen3-30b-a3b-instruct-2507", "nvidia/nemotron-3-super-120b-a12b:free")
INHALE_TTL_S = 180.0
MAX_TOKENS = 450
HEDGE_S = 1.2
# Tried only after every named model has refused, never raced in by the hedge.
# Measured 2026-09-27 in FREE MODELS mode: the router out-raced nemotron
# (TTFT ~1.6 s > HEDGE_S), never emitted the escalation sentinel (0/3), and
# twice routed to a safety classifier whose whole reply was "User Safety: safe".
LAST_RESORT = frozenset({"openrouter/free"})
_VERDICT_HEADS = ("user safety:", "response safety:", "prompt safety:", "safety:")
_CLASSIFIER_VERDICT = re.compile(r"^(?:user |response |prompt )?safety\s*:\s*(?:safe|unsafe)\b", re.I)


def _maybe_verdict(probe: str) -> bool:
    """Could these first characters still become a classifier label?"""
    p = probe.lower()
    return len(p) < 24 and any(h.startswith(p) or p.startswith(h) for h in _VERDICT_HEADS)

VOICE_REGISTER = f"""VOICE MODE. You are speaking aloud, not writing. Everything you say is read out by a speech engine.
- Length by content type: an acknowledgement is at most six words ("Done, sir."); a status or observation is one or two short sentences; anything technical is two to four sentences with the mechanism in a clause. Never lists, bullet points, tables, headings, code blocks or markdown.
- "Sir" is rhythm, not deference: mid-sentence or as a comma-tag, and not in every reply.
- Dry wit, delivered completely straight. No exclamation marks, no emoji.
- Never narrate your own actions. Raise an objection once, then comply.
- Never state a number, percentage, measurement or system status you were not given in this conversation or the context above. "All well, sir" is fine; "running at 92% efficiency" is invention.
- Banned: "I'd recommend", "you might consider", "it's worth noting", "let me know if", "I hope this helps", "feel free to".
- Asked about your owner ("who am I", "tell me about myself", "what do you know about me"): answer the way a close friend who knows them would, in three to five spoken sentences that weave it together - where they come from, what drives them and why, how they work, what chapter they are in now, the people in their life. Their own words and plain speech, never the profile's jargon, never a recital of patterns; then offer to go deeper. Asked about a person in their life, say what you know plainly and warmly.
- If answering properly needs reading files, running tools, browsing, checking the knowledge base, or anything you cannot see in this conversation, reply with exactly {SENTINEL} and nothing else. Never guess at the contents of a file or a log."""


def load_chain(path: Optional[Path] = None) -> List[str]:
    try:
        data = json.loads((path or MODELS_PATH).read_text(encoding="utf-8"))
        chain = [m for m in data.get("chain", []) if isinstance(m, str) and m]
        if chain:
            return chain
    except (OSError, ValueError):
        pass
    return list(FALLBACK_CHAIN)


def is_free_model(model: str) -> bool:
    return model.endswith(":free") or model == "openrouter/free"


def free_chain(chain: Optional[List[str]] = None) -> List[str]:
    """The free subset of a chain, never empty: FREE MODELS mode must not
    fall through to a paid id when the balance is zero."""
    free = [m for m in (chain if chain is not None else load_chain()) if is_free_model(m)]
    for m in FALLBACK_CHAIN + ("openrouter/free",):
        if is_free_model(m) and m not in free:
            free.append(m)
    return free


class VoiceBrain:
    """Process-wide. The inhale is cached because computing it costs 3-7 s
    (projection checks, a domain classifier, a 25 MB queue parse) and its
    content changes on the scale of minutes, not turns."""

    def __init__(self, inhale_fn: Optional[Callable[[], str]] = None,
                 history_fn: Optional[Callable[[str, str], List[Dict[str, str]]]] = None,
                 stream_fn: Optional[Callable[..., AsyncIterator[str]]] = None,
                 chain: Optional[List[str]] = None) -> None:
        self._inhale_fn = inhale_fn or _default_inhale
        self._history_fn = history_fn or _default_history
        self._stream_fn = stream_fn
        self._chain = chain
        self._inhale: Optional[str] = None
        self._inhale_at = 0.0
        self._lock = threading.Lock()
        self._refreshing = False
        self.redacted: List[str] = []

    def warm(self) -> None:
        self.inhale_block(force=True)

    def inhale_block(self, force: bool = False) -> str:
        """Never make a turn wait on a refresh. Measured 2026-09-27 the inhale
        takes 12-20 s in a cold process, so a stale block is served at once and
        refreshed in the background; a turn blocks only when there is none."""
        with self._lock:
            have = self._inhale is not None
            stale = not have or time.monotonic() - self._inhale_at >= INHALE_TTL_S
            if have and stale and not force and not self._refreshing:
                self._refreshing = True
                threading.Thread(target=self._refresh, daemon=True, name="inhale-refresh").start()
            if have and not force:
                return self._inhale or ""
        self._refresh()
        return self._inhale or ""

    def _refresh(self) -> None:
        try:
            block = self._inhale_fn()
        except Exception:                                   # noqa: BLE001
            block = None
        with self._lock:
            if block is not None or self._inhale is None:
                self._inhale = block or ""
            self._inhale_at = time.monotonic()
            self._refreshing = False

    def prompt(self, question: str, session_id: str) -> List[Dict[str, str]]:
        from jarvis_core.agent.mind import JARVIS_PSYCHE_PROMPT
        system = JARVIS_PSYCHE_PROMPT + "\n\n" + VOICE_REGISTER
        inhale = self.inhale_block()
        if inhale:
            system += "\n\n" + inhale
        messages = [{"role": "system", "content": system}]
        for turn in self._history_fn(session_id, question):
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": self._redact(turn["content"])})
        messages.append({"role": "user", "content": self._redact(question)})
        return messages

    def _redact(self, text: str) -> str:
        from jarvis_core.brain.outbound_policy import redact_outbound
        verdict = redact_outbound(text)
        self.redacted.extend(verdict.removed)
        return verdict.text

    async def respond(self, question: str, session_id: str,
                      cancel: Optional[asyncio.Event] = None,
                      free_only: bool = False) -> AsyncIterator[Dict[str, Any]]:
        """Stream one answer. HEDGED: if the leading model has produced no
        token within HEDGE_S, the next model in the chain starts in parallel
        and whichever speaks first wins; the loser is cancelled. Measured
        2026-09-27, one provider queue alone took 8.9 s to a first token while
        the same model normally answered in 0.3-2 s — hedging caps that tail
        at roughly HEDGE_S plus the second model's TTFT."""
        from jarvis_core.brain.llm_client import StreamRefused, stream_chat
        stream = self._stream_fn or stream_chat
        chain = list(self._chain or load_chain())
        if free_only:
            chain = free_chain(chain)
        messages = self.prompt(question, session_id)
        t0 = time.perf_counter()
        events: "asyncio.Queue[tuple]" = asyncio.Queue()
        tasks: Dict[int, asyncio.Task] = {}
        held: Dict[int, str] = {}
        alive: set = set()
        dead: set = set()
        errors: List[str] = []
        winner: Optional[int] = None
        parts: List[str] = []
        launched = 0

        async def pump(i: int, model: str) -> None:
            try:
                async for piece in stream(model, messages, max_tokens=MAX_TOKENS):
                    await events.put((i, "piece", piece))
                await events.put((i, "end", None))
            except asyncio.CancelledError:
                raise
            except StreamRefused as e:
                await events.put((i, "refused", str(e)))
            except Exception as e:                          # noqa: BLE001
                await events.put((i, "refused", f"{type(e).__name__}: {e}"))

        def launch() -> bool:
            nonlocal launched
            if launched >= len(chain):
                return False
            i = launched
            launched += 1
            held[i] = ""
            alive.add(i)
            tasks[i] = asyncio.create_task(pump(i, chain[i]))
            return True

        def stop_all(keep: Optional[int] = None) -> None:
            for i, t in tasks.items():
                if i != keep and not t.done():
                    t.cancel()

        def ttft() -> float:
            return round(time.perf_counter() - t0, 3)

        launch()
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    yield {"type": "cancelled"}
                    return
                can_hedge = (winner is None and launched < len(chain)
                             and chain[launched] not in LAST_RESORT)
                try:
                    i, kind, val = await asyncio.wait_for(events.get(), HEDGE_S if can_hedge else 60.0)
                except asyncio.TimeoutError:
                    if can_hedge:
                        launch()
                        continue
                    yield {"type": "error", "error": "voice model stopped responding"}
                    return
                if (winner is not None and i != winner) or i in dead:
                    continue
                if kind == "refused":
                    if winner == i:
                        yield {"type": "error", "error": f"{chain[i]} stopped mid-answer: {val}"}
                        return
                    alive.discard(i)
                    errors.append(f"{chain[i]}: {val}")
                    if not alive and not launch():
                        yield {"type": "error",
                               "error": "every voice model refused: " + " | ".join(errors)}
                        return
                    continue
                if winner is None:
                    if kind == "piece":
                        held[i] += val
                    probe = held[i].lstrip()
                    if kind == "piece" and len(probe) < len(SENTINEL) and SENTINEL.startswith(probe):
                        continue
                    if kind == "piece" and _maybe_verdict(probe) and not _CLASSIFIER_VERDICT.match(probe):
                        continue
                    if probe.startswith(SENTINEL):
                        stop_all()
                        yield {"type": "deep", "model": chain[i], "ttft": ttft()}
                        return
                    if _CLASSIFIER_VERDICT.match(probe):
                        # A guard model's label, not an answer: a refusal.
                        tasks[i].cancel()
                        dead.add(i)
                        alive.discard(i)
                        errors.append(f"{chain[i]}: replied with a safety-classifier label")
                        if not alive and not launch():
                            yield {"type": "error",
                                   "error": "every voice model refused: " + " | ".join(errors)}
                            return
                        continue
                    if not probe:
                        if kind == "end":
                            alive.discard(i)
                            errors.append(f"{chain[i]}: empty reply")
                            if not alive and not launch():
                                yield {"type": "error",
                                       "error": "every voice model refused: " + " | ".join(errors)}
                                return
                        continue
                    winner = i
                    stop_all(keep=i)
                    yield {"type": "first", "model": chain[i], "ttft": ttft(), "hedged": launched > 1}
                    parts.append(probe)
                    yield {"type": "token", "text": probe}
                    if kind == "end":
                        break
                    continue
                if kind == "piece":
                    parts.append(val)
                    yield {"type": "token", "text": val}
                elif kind == "end":
                    break
        finally:
            stop_all()
        yield {"type": "done", "model": chain[winner], "answer": "".join(parts).strip(),
               "total": round(time.perf_counter() - t0, 3)}


# Which inhale sections a SPOKEN turn gets — each one WHOLE. The full inhale is
# written for an agent about to use tools: routing guidance, repo anatomy,
# projection integrity. Measured 2026-09-27, handing all of it to the voice
# model made JARVIS answer "Hi" with "Projection integrity warning: memory
# index lagging by 53 entries". What a spoken reply needs is who the owner is,
# what they have been doing, what is next, and what time it is. Choosing
# sections is selection; the per-section char caps that used to sit here were
# cuts and are gone (owner directive 2026-09-28: no truncation anywhere).
VOICE_SECTIONS = (
    "Cognitive profile (standing model of your owner)",
    "People and circumstances in your owner's life",
    "Pipeline health",
    "Next pending task",
    "Recent cross-chat activity",
    "Temporal",
)


def _default_inhale() -> str:
    from jarvis_core.brain.context_injector import ContextInjector, ProviderSpec, default_providers
    # Ordered static -> volatile. Providers cache a prompt PREFIX, so the
    # clock ("Temporal") goes last: first, it would change the prefix on every
    # refresh and no turn would ever hit the cache.
    by_name = {spec.name: spec for spec in default_providers()}
    return ContextInjector([by_name[n] for n in VOICE_SECTIONS if n in by_name]).inhale().block


def _default_history(session_id: str, question: str) -> List[Dict[str, str]]:
    from jarvis_core.brain.conversation import ConversationStore
    return ConversationStore().load_context(session_id, question)


def persist_turn(question: str, answer: str, session_id: str, model: str,
                 conv_store: Any = None, queue_path: Optional[Path] = None) -> Dict[str, bool]:
    """Leave behind exactly what the full path leaves behind."""
    from jarvis_core.agent.capture import (QUEUE_PATH, append_observation,
                                           build_observation, strip_harness_blocks)
    from jarvis_core.brain.conversation import ConversationStore, resolve_terminal_session
    out = {"captured": False, "persisted": False}
    resolve_terminal_session(explicit=session_id)
    question = strip_harness_blocks(question)
    try:
        obs = build_observation(event={"session_id": session_id},
                                turn={"user_text": question, "assistant_summary": answer, "model": model},
                                cwd=os.getcwd(), host="jarvis")
        if obs is not None:
            obs["chat_label"] = "voice-ask"
            append_observation(obs, queue_path or QUEUE_PATH)
            out["captured"] = True
    except Exception:                                       # noqa: BLE001
        pass
    if answer.strip():
        store = conv_store or ConversationStore()
        store.append_turn(session_id, "user", question)
        store.append_turn(session_id, "assistant", answer)
        out["persisted"] = True
    return out


BRAIN = VoiceBrain()


# =============================================================================
# Self-test — hermetic unless --live
# =============================================================================

def _run_self_test() -> int:
    passed = failed = 0

    def check(label: str, got: Any, want: Any) -> None:
        nonlocal passed, failed
        ok = got == want
        passed, failed = passed + ok, failed + (not ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        got {got!r} want {want!r}"))

    from jarvis_core.brain.llm_client import StreamRefused

    def scripted(replies: Dict[str, Any]):
        async def fake(model, messages, max_tokens=0):
            r = replies[model]
            if isinstance(r, Exception):
                raise r
            for piece in r:
                yield piece
        return fake

    def run(brain: VoiceBrain, q: str = "hi") -> List[Dict[str, Any]]:
        async def go():
            return [e async for e in brain.respond(q, "conv-web-test")]
        return asyncio.run(go())

    base = dict(inhale_fn=lambda: "## profile\nthe owner", history_fn=lambda s, q: [])
    print("=" * 70)
    print("  voice_path self-test")
    print("=" * 70)

    ev = run(VoiceBrain(**base, chain=["a"], stream_fn=scripted({"a": ["Good ", "evening, sir."]})))
    check("P1 a normal reply streams tokens then done",
          [e["type"] for e in ev], ["first", "token", "token", "done"])
    check("P2 done carries the whole answer", ev[-1]["answer"], "Good evening, sir.")

    ev = run(VoiceBrain(**base, chain=["a"], stream_fn=scripted({"a": ["<<DE", "EP>>"]})))
    check("P3 a sentinel split across tokens escalates and speaks nothing", [e["type"] for e in ev], ["deep"])

    ev = run(VoiceBrain(**base, chain=["a", "b"],
                        stream_fn=scripted({"a": StreamRefused(402, "no credit"), "b": ["Done, sir."]})))
    check("P4 a 402 before the first token fails over to the next model",
          (ev[0]["type"], ev[0]["model"], ev[-1]["answer"]), ("first", "b", "Done, sir."))

    ev = run(VoiceBrain(**base, chain=["a"], stream_fn=scripted({"a": ["<", "3 you too, sir."]})))
    check("P5 text that merely STARTS like the sentinel is not held forever",
          ev[-1].get("answer"), "<3 you too, sir.")

    ev = run(VoiceBrain(**base, chain=["a", "b"],
                        stream_fn=scripted({"a": StreamRefused(429, "busy"), "b": StreamRefused(500, "down")})))
    check("P6 when every model refuses, one error names them all",
          (ev[-1]["type"], "a:" in ev[-1]["error"] and "b:" in ev[-1]["error"]), ("error", True))

    reasons = {f"m{i}": StreamRefused(503, f"reason-{i} " + "x" * 300) for i in range(4)}
    ev = run(VoiceBrain(**base, chain=list(reasons), stream_fn=scripted(reasons)))
    check("P17 the all-refused error carries every reason whole",
          all(f"reason-{i} " + "x" * 300 in ev[-1]["error"] for i in range(4)), True)

    seen: List[str] = []

    async def recording(model, messages, max_tokens=0):
        seen.append(model)
        yield "Here, sir."

    async def go_free():
        brain = VoiceBrain(**base, chain=["paid/a", "paid/b", "x/y:free"], stream_fn=recording)
        return [e async for e in brain.respond("hi", "conv-web-test", free_only=True)]
    ev = asyncio.run(go_free())
    check("P13 FREE MODELS mode never launches a paid model",
          (all(is_free_model(m) for m in seen), ev[0]["model"]), (True, "x/y:free"))
    ev = run(VoiceBrain(**base, chain=["guard", "b"],
                        stream_fn=scripted({"guard": ["User", " Safety", ": safe"], "b": ["Evening, sir."]})))
    check("P15 a safety-classifier label is rejected and the next model answers",
          (ev[0]["model"], ev[-1]["answer"]), ("b", "Evening, sir."))
    ev = run(VoiceBrain(**base, chain=["a"], stream_fn=scripted({"a": ["Safe", " travels, sir."]})))
    check("P16 an answer that merely starts like a label still streams", ev[-1]["answer"], "Safe travels, sir.")
    check("P14 free_chain is never empty, even for an all-paid chain",
          bool(free_chain(["paid/a"])) and all(is_free_model(m) for m in free_chain(["paid/a"])), True)

    def staggered(delays: Dict[str, float], replies: Dict[str, List[str]]):
        async def fake(model, messages, max_tokens=0):
            await asyncio.sleep(delays[model])
            for piece in replies[model]:
                yield piece
        return fake
    # Patch THIS module's global: under `python -m` the module runs as
    # __main__, so importing it by name would patch a second copy.
    g = globals()
    g["HEDGE_S"] = 0.2
    try:
        t = time.perf_counter()
        ev = run(VoiceBrain(**base, chain=["slow", "fast"], stream_fn=staggered(
            {"slow": 3.0, "fast": 0.05}, {"slow": ["late."], "fast": ["Here, sir."]})))
        took = time.perf_counter() - t
    finally:
        g["HEDGE_S"] = 1.2
    check("P12 a stalled leading model is hedged: the second model wins, well before the first would",
          (ev[0]["model"], ev[-1]["answer"], took < 1.5), ("fast", "Here, sir.", True))

    b = VoiceBrain(inhale_fn=lambda: "INHALE", history_fn=lambda s, q: [
        {"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"},
        {"role": "system", "content": "not a turn"}])
    msgs = b.prompt("now", "s")
    check("P7 prompt = persona + register + inhale, then history, then question",
          ([m["role"] for m in msgs], "INHALE" in msgs[0]["content"], SENTINEL in msgs[0]["content"]),
          (["system", "user", "assistant", "user"], True, True))

    calls = {"n": 0}

    def counting() -> str:
        calls["n"] += 1
        return "x"
    c = VoiceBrain(inhale_fn=counting, history_fn=lambda s, q: [])
    c.prompt("a", "s"); c.prompt("b", "s")
    check("P8 the inhale is computed once, not per turn", calls["n"], 1)

    gate = threading.Event()
    def slow() -> str:
        gate.wait(5)
        return "NEW"
    d = VoiceBrain(inhale_fn=lambda: "OLD", history_fn=lambda s, q: [])
    d.inhale_block()
    d._inhale_fn, d._inhale_at = slow, 0.0
    t = time.perf_counter(); got = d.inhale_block(); waited = time.perf_counter() - t
    gate.set()
    check("P11 a stale inhale is served at once while it refreshes in the background",
          (got, waited < 0.5), ("OLD", True))

    import tempfile
    from jarvis_core.brain.conversation import ConversationStore
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(conv_dir=Path(tmp) / "conv")
        q = Path(tmp) / "queue.jsonl"
        import jarvis_core.brain.conversation as conv_mod
        real_state = conv_mod._SESSION_STATE
        conv_mod._SESSION_STATE = Path(tmp) / "state.json"
        try:
            res = persist_turn("Hi, JARVIS.", "Good evening, sir.", "conv-web-t", "m",
                               conv_store=store, queue_path=q)
        finally:
            conv_mod._SESSION_STATE = real_state
        rows = [json.loads(x) for x in q.read_text(encoding="utf-8").splitlines() if x.strip()]
        turns = store.load_recent("conv-web-t")
        check("P9 persistence writes one capture row and two turns",
              (res, len(rows), [t["role"] for t in turns]),
              ({"captured": True, "persisted": True}, 1, ["user", "assistant"]))
        check("P10 the capture row is labelled as a voice turn", rows[0].get("chat_label"), "voice-ask")

    print("-" * 70)
    print(f"  {passed} passed, {failed} failed")
    print("=" * 70)
    return 1 if failed else 0


async def _live(question: str) -> None:
    t = time.perf_counter()
    BRAIN.warm()
    print(f"  inhale warm: {time.perf_counter() - t:.2f}s")
    async for ev in BRAIN.respond(question, "conv-web-livetest"):
        if ev["type"] == "token":
            print(ev["text"], end="", flush=True)
        else:
            print(f"\n  [{ev['type']}] " + json.dumps({k: v for k, v in ev.items() if k not in ('type', 'answer')}))


if __name__ == "__main__":
    if "--live" in sys.argv:
        asyncio.run(_live(sys.argv[-1]))
        sys.exit(0)
    sys.exit(_run_self_test())

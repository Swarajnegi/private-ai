"""
live_voice.py — one hands-free conversation over a WebSocket.

LAYER: Body (Voice I/O)

Route: WS /v1/voice/live?token=<hearth token>   (loopback only)

=============================================================================
THE BIG PICTURE
=============================================================================

The previous UI did a turn as three HTTP round trips — upload a WAV, POST
/v1/ask, POST each chunk for synthesis — and closed the microphone for the
whole of it. Every hop reloaded a model or reopened a connection.

Here one socket stays open for the whole conversation. The browser streams
raw microphone PCM up; the server does everything else in one place:

    PCM16 16 kHz  ->  StreamingVAD  ->  Whisper  ->  voice fast path
                                                        |  tokens
                   <- PCM16 24 kHz  <-  Kokoro  <-  SentenceChunker

and the microphone NEVER closes, because people do not talk in tidy turns.

=============================================================================
WHAT HAPPENS WHEN THE USER KEEPS TALKING (the reason this file exists)
=============================================================================

The VAD is fed continuously and every event is routed by what JARVIS is
doing at that moment:

    PENDING   an utterance has ended, speculative transcription is running
              or the commit grace is ticking. More speech (sustained, so a
              cough does not count) cancels the commit; when it ends, its
              audio is APPENDED and the whole buffer is re-transcribed —
              Whisper is more accurate on full context than on stitched text.
              A transcript that ends mid-thought ("...and", "so", a comma)
              waits 1.5 s instead of 0.25 s before committing.

    THINKING  the question is committed and the brain is streaming, but no
              audio has played. Sustained speech CANCELS the answer — it has
              not been spoken or persisted, so nothing is lost — and the new
              speech is merged with the old into one question.

    SPEAKING  JARVIS is talking. Sustained speech stops playback at once
              (barge-in, with a raised VAD threshold so JARVIS's own voice in
              the room does not trigger it). The answer already given is
              persisted; what the user says becomes the next turn.

    DEEP      a tool-using answer is running in the full orchestrator, which
              cannot be interrupted mid-run; new speech is held and becomes
              the next turn when it finishes.

=============================================================================
PROTOCOL
=============================================================================

client -> server
    binary                           PCM16 mono 16 kHz microphone frames
    {"type": "hello", "session", "voice", "hands_free", "speak", "ephemeral"}
                                     ephemeral: persist and capture NOTHING — for
                                     scripts/verify_voice_live.py, whose scripted
                                     prompts would otherwise enter the training corpus
                                     as if the owner had said them (found 2026-09-27)
    {"type": "text", "question"}     a typed turn, spoken back if voice is on
    {"type": "interrupt"}            stop speaking now
    {"type": "config", ...}          same keys as hello

server -> client
    {"type": "state", "state": waking|idle|listening|transcribing|thinking|speaking}
    {"type": "ready", "engine": {...}}
    {"type": "partial", "text"}      a speculative transcript, not yet committed
    {"type": "final", "text"}        the committed question
    {"type": "retract"}              the running answer was cancelled to merge
    {"type": "token", "text"}        answer text as it streams
    {"type": "log", "line"}          deep-path narration
    {"type": "answer", "text", "path", "model", "payload"?}
    {"type": "audio_start", "rate"} / binary PCM16 / {"type": "audio_end"}
    {"type": "stop_audio"}           barge-in: flush local playback now
    {"type": "error", "error"}
=============================================================================
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

import numpy as np

from jarvis_core.serve.speech import (ENGINE, STT_RATE, SentenceChunker, StreamingVAD, TTS_RATE,
                                      TTS_VOICE, TTS_VOICES, log_latency, strip_for_speech)

Receive = Callable[[], Awaitable[Dict[str, Any]]]
Send = Callable[[Dict[str, Any]], Awaitable[None]]

DEEP_ACK = "One moment, sir."
BUSY_LINE = "One moment, sir. I'm still on the previous question."
COMMIT_GRACE_S = 0.25
INCOMPLETE_GRACE_S = 1.5
LISTEN_THRESHOLD = 0.5
SPEAKING_THRESHOLD = 0.8          # JARVIS's own voice leaks past echo cancellation at low levels
JOIN_GAP = np.zeros(int(0.25 * STT_RATE), dtype=np.float32)

_TRAILING = re.compile(
    r"(?:\b(?:and|but|or|so|because|if|then|the|a|an|to|of|for|with|um|uh|like|which|that|"
    r"when|while|also|plus|is|are|was|my|your)|,|\.\.\.|…|-)\s*[.?!]?\s*$", re.IGNORECASE)


def looks_incomplete(text: str) -> bool:
    """Whisper closes almost every clip with a full stop, so the WORD before it
    is what shows the speaker was mid-thought."""
    return bool(_TRAILING.search(text.strip()))


class LiveSession:
    def __init__(self, hearth: Any, send: Send, brain: Any = None, engine: Any = None) -> None:
        from jarvis_core.brain.voice_path import BRAIN
        self.hearth = hearth
        self._send_raw = send
        self._send_lock = asyncio.Lock()
        self.brain = brain or BRAIN
        self.engine = engine or ENGINE
        self.session = ""
        self.voice = TTS_VOICE
        self.hands_free = True
        self.speak = True
        self.free_only = False
        self.ephemeral = False
        self.state = "idle"
        self.closed = False
        self.vad: Optional[StreamingVAD] = None
        self.stop_audio = asyncio.Event()
        # the utterance being assembled before commit
        self.pending_audio: Optional[np.ndarray] = None
        self.pending_task: Optional[asyncio.Task] = None
        self.pending_t0 = 0.0
        # the committed turn
        self.turn: Optional[asyncio.Task] = None
        self.turn_audio: Optional[np.ndarray] = None
        self.turn_cancel: Optional[asyncio.Event] = None
        self.turn_path = "fast"
        self.turn_speaking = False
        self.merge_next = False
        self.merging = False          # between a cancelled answer and its merged resubmit
        self.queued: List[np.ndarray] = []

    # ---- transport -------------------------------------------------------

    async def send(self, obj: Dict[str, Any]) -> None:
        await self._emit({"type": "websocket.send", "text": json.dumps(obj, ensure_ascii=False)})

    async def send_audio(self, pcm: bytes) -> None:
        await self._emit({"type": "websocket.send", "bytes": pcm})

    async def _emit(self, message: Dict[str, Any]) -> None:
        # A client that leaves mid-turn must not abort the turn: the answer
        # still has to be persisted, or the interview loses that exchange.
        if self.closed:
            return
        async with self._send_lock:
            try:
                await self._send_raw(message)
            except Exception:                               # noqa: BLE001
                self.closed = True

    async def set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            await self.send({"type": "state", "state": state})

    def _busy(self) -> bool:
        return self.turn is not None and not self.turn.done()

    async def _rest_state(self) -> None:
        await self.set_state("listening" if self.hands_free else "idle")

    # ---- inbound ---------------------------------------------------------

    async def on_text(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        kind = msg.get("type")
        if kind in ("hello", "config"):
            if isinstance(msg.get("session"), str) and msg["session"].strip():
                self.session = msg["session"].strip()
            if msg.get("voice") in TTS_VOICES:
                self.voice = msg["voice"]
            if "hands_free" in msg:
                self.hands_free = bool(msg["hands_free"])
            if "speak" in msg:
                self.speak = bool(msg["speak"])
            if "free_only" in msg:
                self.free_only = bool(msg["free_only"])
            if kind == "hello" and msg.get("ephemeral"):
                self.ephemeral = True               # hello only: a later config cannot switch it off
            if not self._busy() and self.pending_task is None:
                await self._rest_state()
        elif kind == "text":
            question = str(msg.get("question") or "").strip()
            if question and not self._busy():
                self.turn_audio = None
                self.turn = asyncio.create_task(self.run_turn(question, t_heard=time.perf_counter()))
        elif kind == "interrupt":
            self.stop_audio.set()

    async def on_audio(self, pcm: bytes) -> None:
        if not self.hands_free or self.vad is None:
            return
        self.vad.threshold = SPEAKING_THRESHOLD if self.turn_speaking else LISTEN_THRESHOLD
        for ev in self.vad.feed(pcm):
            if ev.kind == "sustained":
                await self._on_sustained()
            elif ev.kind == "utterance" and ev.audio is not None:
                await self._on_utterance(ev.audio)

    async def _on_sustained(self) -> None:
        """The user is really speaking. What that means depends on JARVIS."""
        if self.pending_task is not None and not self.pending_task.done():
            self.pending_task.cancel()                     # continuation: don't commit yet
            self.pending_task = None
            await self.set_state("listening")
            return
        if not self._busy():
            return
        if self.turn_speaking:
            self.stop_audio.set()                          # barge-in
            await self.send({"type": "stop_audio"})
            return
        if self.turn_path == "fast" and self.turn_cancel is not None and self.turn_audio is not None:
            self.merge_next = True                         # cancel the unspoken answer
            self.turn_cancel.set()

    async def _on_utterance(self, audio: np.ndarray) -> None:
        if self._busy() or self.merging:
            self.queued.append(audio)                      # merge, barge-in or deep: picked up later
            return
        if self.pending_audio is not None:
            audio = np.concatenate([self.pending_audio, JOIN_GAP, audio])
        else:
            self.pending_t0 = time.perf_counter()
        self._start_pending(audio)

    def _start_pending(self, audio: np.ndarray) -> None:
        self.pending_audio = audio
        if self.pending_task is not None and not self.pending_task.done():
            self.pending_task.cancel()
        self.pending_task = asyncio.create_task(self._pending(audio))

    async def _pending(self, audio: np.ndarray) -> None:
        """Speculatively transcribe, wait the grace, then commit."""
        await self.set_state("transcribing")
        try:
            text = await asyncio.to_thread(self.engine.transcribe, audio)
        except asyncio.CancelledError:
            raise
        except Exception as e:                              # noqa: BLE001
            await self.send({"type": "error", "error": f"transcription failed: {e}"})
            self.pending_audio, self.pending_task = None, None
            await self._rest_state()
            return
        t_stt = time.perf_counter()
        if not text or len(text.strip(" .,!?")) < 2:
            self.pending_audio, self.pending_task = None, None
            await self._rest_state()
            return
        await self.send({"type": "partial", "text": text})
        await asyncio.sleep(INCOMPLETE_GRACE_S if looks_incomplete(text) else COMMIT_GRACE_S)
        # Committed: from here, more speech becomes a merge or a new turn.
        t_heard = self.pending_t0
        self.pending_audio, self.pending_task = None, None
        await self.send({"type": "final", "text": text})
        self.turn_audio = audio
        self.turn = asyncio.create_task(self.run_turn(
            text, t_heard=t_heard, t_stt=t_stt, audio_s=round(audio.shape[0] / STT_RATE, 2)))

    # ---- a turn ----------------------------------------------------------

    async def run_turn(self, question: str, t_heard: float, t_stt: Optional[float] = None,
                       audio_s: Optional[float] = None) -> None:
        from jarvis_core.brain.voice_path import persist_turn
        timing: Dict[str, Any] = {"session": self.session, "chars_in": len(question), "audio_s": audio_s,
                                  "stt_s": None if t_stt is None else round(t_stt - t_heard, 3)}
        self.stop_audio.clear()
        self.turn_cancel = asyncio.Event()
        self.turn_path, self.turn_speaking, self.merge_next = "fast", False, False
        if not self.session:
            self.session = f"conv-web-{uuid.uuid4()}"
            await self.send({"type": "session", "session": self.session})
        if self.hearth._slot.locked():
            await self._speak_line(BUSY_LINE, timing, t_heard)
            await self._after_turn()
            return
        await self.set_state("thinking")
        speaker = _Speaker(self, timing, t_heard)
        chunker = SentenceChunker()
        answer, model, cancelled = "", "", False
        async with self.hearth._slot:
            async for ev in self.brain.respond(question, self.session, cancel=self.turn_cancel,
                                                free_only=self.free_only):
                if ev["type"] == "cancelled":
                    cancelled = True
                    break
                if ev["type"] == "first":
                    timing["first_token_s"] = round(time.perf_counter() - t_heard, 3)
                    model = ev["model"]
                elif ev["type"] == "token":
                    await self.send({"type": "token", "text": ev["text"]})
                    for sentence in chunker.push(ev["text"]):
                        speaker.say(sentence)
                elif ev["type"] == "done":
                    answer, model = ev["answer"], ev["model"]
                elif ev["type"] == "deep":
                    self.turn_path, model = "deep", ev["model"]
                    speaker.say(DEEP_ACK)
                    answer = await self._deep(question, speaker)
                    break
                elif ev["type"] == "error":
                    await self.send({"type": "error", "error": ev["error"]})
                    speaker.say("I've lost the connection to my models, sir.")
                    break
            if not cancelled:
                for sentence in chunker.flush():
                    speaker.say(sentence)
        if cancelled:
            # The user spoke over an answer that had not been voiced yet.
            # Nothing was spoken or persisted; take their new words with the old.
            speaker.abandon()
            await speaker.finish()
            await self.send({"type": "retract"})
            timing.update(path="merged", total_s=round(time.perf_counter() - t_heard, 3))
            await self._log(timing)
            base = self.turn_audio
            self.merging = True
            self.turn = None
            try:
                await self._merge_and_resubmit(base)
            finally:
                self.merging = False
            return
        if self.turn_path == "fast" and answer:
            await self.send({"type": "answer", "text": answer, "path": "fast", "model": model})
        await speaker.finish()
        timing.update(path=self.turn_path, model=model, chars_out=len(answer),
                      barged_in=self.stop_audio.is_set(), total_s=round(time.perf_counter() - t_heard, 3))
        if self.turn_path == "fast" and answer and not self.ephemeral:
            timing.update(await asyncio.to_thread(persist_turn, question, answer, self.session, model))
        await self._log(timing)
        await self._after_turn()

    async def _merge_and_resubmit(self, base: Optional[np.ndarray]) -> None:
        """Old question audio + everything said since -> one new pending utterance.
        The interrupting speech may still be in progress: wait for it to end."""
        deadline = time.perf_counter() + 8.0
        while time.perf_counter() < deadline and (not self.queued or (self.vad and self.vad.speaking)):
            await asyncio.sleep(0.05)
        audio = base if base is not None else np.zeros(0, dtype=np.float32)
        for a in self.queued:
            audio = np.concatenate([audio, JOIN_GAP, a])
        self.queued = []
        self.pending_audio = None
        self.pending_t0 = time.perf_counter()
        self._start_pending(audio)

    async def _after_turn(self) -> None:
        self.turn_speaking = False
        self.turn = None
        if self.queued:
            audio = self.queued[0]
            for a in self.queued[1:]:
                audio = np.concatenate([audio, JOIN_GAP, a])
            self.queued = []
            self.pending_t0 = time.perf_counter()
            self._start_pending(audio)
        else:
            await self._rest_state()

    async def _log(self, timing: Dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(log_latency, timing)
        except Exception:                                   # noqa: BLE001
            pass

    async def _deep(self, question: str, speaker: "_Speaker") -> str:
        async def emit(event: str, data: Dict[str, Any]) -> None:
            if event == "log":
                await self.send({"type": "log", "line": data.get("line", "")})
        payload = await self.hearth.run_ask(question, emit, session=self.session,
                                            capture=False if self.ephemeral else None,
                                            free_only=self.free_only)
        self.hearth.requests_served += 1
        text = str(payload.get("answer") or "")
        await self.send({"type": "answer", "text": text, "path": "deep", "payload": payload})
        if not payload.get("ok", True) or not text:
            speaker.say("That one didn't come together, sir. The details are on screen.")
            return text
        chunker = SentenceChunker()
        for s in chunker.push(strip_for_speech(text)) + chunker.flush():
            speaker.say(s)
        return text

    async def _speak_line(self, line: str, timing: Dict[str, Any], t0: float) -> None:
        sp = _Speaker(self, timing, t0)
        sp.say(line)
        await sp.finish()


class _Speaker:
    """Synthesizes queued sentences in order, sending audio as each is ready.
    Runs concurrently with generation, so sentence N plays while N+1 streams."""

    def __init__(self, live: LiveSession, timing: Dict[str, Any], t0: float) -> None:
        self.live, self.timing, self.t0 = live, timing, t0
        self.queue: "asyncio.Queue[Optional[str]]" = asyncio.Queue()
        self.started = False
        self.abandoned = False
        self.task = asyncio.create_task(self._run())

    def say(self, sentence: str) -> None:
        text = strip_for_speech(sentence)
        if text and self.live.speak and not self.abandoned:
            self.queue.put_nowait(text)

    def abandon(self) -> None:
        self.abandoned = True

    async def finish(self) -> None:
        self.queue.put_nowait(None)
        await self.task

    async def _run(self) -> None:
        live = self.live
        while True:
            sentence = await self.queue.get()
            if sentence is None:
                break
            if live.stop_audio.is_set() or self.abandoned:
                continue
            try:
                chunks = await asyncio.to_thread(lambda: list(live.engine.synthesize(sentence, live.voice)))
            except Exception as e:                          # noqa: BLE001
                await live.send({"type": "error", "error": f"speech failed: {e}"})
                continue
            if live.stop_audio.is_set() or self.abandoned:
                continue
            if not self.started:
                self.started = True
                live.turn_speaking = True
                self.timing["first_audio_s"] = round(time.perf_counter() - self.t0, 3)
                await live.set_state("speaking")
                await live.send({"type": "audio_start", "rate": TTS_RATE})
            for pcm in chunks:
                if live.stop_audio.is_set():
                    break
                await live.send_audio(pcm)
        if self.started:
            await live.send({"type": "audio_end"})


async def _prewarm_connection() -> None:
    import os
    try:
        from jarvis_core.brain.llm_client import _stream_client
        key = os.environ.get("OPENROUTER_API_KEY", "")
        await _stream_client().get("https://openrouter.ai/api/v1/key",
                                   headers={"Authorization": f"Bearer {key}"}, timeout=10)
    except Exception:                                       # noqa: BLE001
        pass


async def handle(hearth: Any, scope: Dict[str, Any], receive: Receive, send: Send) -> None:
    """Serve one WebSocket connection until the client leaves."""
    first = await receive()
    if first.get("type") != "websocket.connect":
        return
    await send({"type": "websocket.accept"})
    live = LiveSession(hearth, send)
    # Open the provider connection now, while the user is still deciding what
    # to say: the first turn otherwise pays a TLS handshake (measured +1.5 s).
    asyncio.create_task(_prewarm_connection())
    if not ENGINE.state.warm:
        await live.set_state("waking")
        await asyncio.to_thread(ENGINE.warm)
    live.vad = StreamingVAD()
    await live.send({"type": "ready", "engine": ENGINE.status()})
    await live._rest_state()
    try:
        while True:
            msg = await receive()
            if msg["type"] == "websocket.disconnect":
                live.closed = True
                break
            if msg.get("bytes"):
                await live.on_audio(msg["bytes"])
            elif msg.get("text"):
                await live.on_text(msg["text"])
    finally:
        live.stop_audio.set()
        for task in (live.pending_task, live.turn):
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=60)
                except Exception:                           # noqa: BLE001
                    pass


# =============================================================================
# Self-test — hermetic: fake engine, brain and hearth; nothing is persisted
# =============================================================================

def _run_self_test() -> int:
    g = globals()
    # Real commit grace (0.25 s): a shorter one made L1 commit and fully answer
    # before the continuation began, which is correct behaviour for a long pause
    # but not the case under test. Only the incomplete-grace is shortened.
    g["COMMIT_GRACE_S"], g["INCOMPLETE_GRACE_S"] = 0.25, 0.35
    passed = failed = 0

    def check(label: str, got: Any, want: Any) -> None:
        nonlocal passed, failed
        ok = got == want
        passed, failed = passed + ok, failed + (not ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        got {got!r}\n        want {want!r}"))

    SR = STT_RATE

    class FakeEngine:
        """The transcript is keyed on how much speech the buffer holds, so a
        merged buffer is distinguishable from either half on its own."""
        def __init__(self, texts: Dict[int, str]):
            self.texts = texts

        def transcribe(self, audio: np.ndarray) -> str:
            voiced = int(round(float((np.abs(audio) > 0.1).sum()) / SR * 10))   # tenths of a second
            return self.texts[min(self.texts, key=lambda k: abs(k - voiced))]

        def synthesize(self, text: str, voice: str = ""):
            yield bytes(4800)

    class FakeBrain:
        def __init__(self, delay: float, reply: str = "Done, sir."):
            self.delay, self.reply, self.questions = delay, reply, []

        async def respond(self, question, session, cancel=None, free_only=False):
            self.questions.append(question)
            t = 0.0
            while t < self.delay:
                if cancel is not None and cancel.is_set():
                    yield {"type": "cancelled"}
                    return
                await asyncio.sleep(0.02)
                t += 0.02
            yield {"type": "first", "model": "m", "ttft": self.delay}
            for w in self.reply.split(" "):
                if cancel is not None and cancel.is_set():
                    yield {"type": "cancelled"}
                    return
                yield {"type": "token", "text": w + " "}
            yield {"type": "done", "model": "m", "answer": self.reply}

    class FakeHearth:
        def __init__(self):
            self._slot = asyncio.Semaphore(1)
            self.requests_served = 0

    persisted: List[str] = []
    import jarvis_core.brain.voice_path as vp
    real_persist, real_log = vp.persist_turn, g["log_latency"]
    vp.persist_turn = lambda q, a, s, m: persisted.append(q) or {"captured": True, "persisted": True}
    g["log_latency"] = lambda row: None

    def energy(frame: np.ndarray) -> float:
        return 1.0 if float(np.abs(frame).mean()) > 0.1 else 0.0

    def pcm(seconds: float, loud: bool) -> bytes:
        return np.full(int(SR * seconds), 8000 if loud else 0, dtype=np.int16).tobytes()

    async def speak(live: "LiveSession", segments: List[tuple]) -> None:
        """Feed (seconds, loud) segments in 32 ms frames, about 4x real time."""
        for secs, loud in segments:
            data = pcm(secs, loud)
            for i in range(0, len(data), 1024):
                await live.on_audio(data[i:i + 1024])
                await asyncio.sleep(0.008)

    def session(engine: Any, brain: Any):
        sent: List[Any] = []

        async def send(msg: Dict[str, Any]) -> None:
            sent.append(json.loads(msg["text"]) if "text" in msg else ("audio", len(msg["bytes"])))
        live = LiveSession(FakeHearth(), send, brain=brain, engine=engine)
        live.vad = StreamingVAD(prob_fn=energy)
        live.session = "conv-web-selftest"
        return live, sent

    async def settle(live: "LiveSession", timeout: float = 6.0) -> None:
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < timeout:
            idle = ((live.pending_task is None or live.pending_task.done())
                    and not live._busy() and not live.merging)
            if idle and live.state in ("listening", "idle"):
                return
            await asyncio.sleep(0.05)

    async def wait_state(live: "LiveSession", state: str, timeout: float = 4.0) -> None:
        t0 = time.perf_counter()
        while live.state != state and time.perf_counter() - t0 < timeout:
            await asyncio.sleep(0.02)

    def finals(sent: List[Any]) -> List[str]:
        return [m["text"] for m in sent if isinstance(m, dict) and m.get("type") == "final"]

    def count(sent: List[Any], kind: str) -> int:
        return sum(1 for m in sent if isinstance(m, dict) and m.get("type") == kind)

    print("=" * 70)
    print("  live_voice self-test")
    print("=" * 70)

    async def l1() -> None:
        live, sent = session(FakeEngine({6: "Open the lab.", 14: "Open the lab and dim the lights."}),
                             FakeBrain(0.05))
        await speak(live, [(0.6, True), (0.6, False)])
        await speak(live, [(0.8, True), (0.7, False)])      # keeps going before the commit
        await settle(live)
        check("L1 speech before commit is appended and re-transcribed as ONE question",
              finals(sent), ["Open the lab and dim the lights."])

    async def l2() -> None:
        live, sent = session(FakeEngine({6: "Remind me to call mum and."}), FakeBrain(0.05))
        await speak(live, [(0.6, True), (0.6, False)])
        t = time.perf_counter()
        while not finals(sent) and time.perf_counter() - t < 3:
            await asyncio.sleep(0.02)
        check("L2 a transcript ending mid-thought waits the longer grace before committing",
              time.perf_counter() - t >= 0.3, True)
        await settle(live)

    async def l3() -> None:
        brain = FakeBrain(1.2)
        live, sent = session(FakeEngine({6: "What's the weather.",
                                         13: "What's the weather in Mumbai tomorrow."}), brain)
        await speak(live, [(0.6, True), (0.6, False)])
        await wait_state(live, "thinking")
        await speak(live, [(0.7, True), (0.7, False)])      # talks over the thinking
        await settle(live)
        check("L3 speaking during THINKING cancels the unspoken answer (one retract)", count(sent, "retract"), 1)
        check("L3b ...and the merged question is what gets answered",
              brain.questions[-1], "What's the weather in Mumbai tomorrow.")
        check("L3c ...and only the merged turn is persisted",
              persisted[-1:], ["What's the weather in Mumbai tomorrow."])

    async def l4() -> None:
        engine = FakeEngine({6: "Tell me a story.", 7: "Stop, that's enough."})

        def slow_synth(text: str, voice: str = ""):
            time.sleep(0.25)
            yield bytes(4800)
        engine.synthesize = slow_synth
        brain = FakeBrain(0.02, reply="Once upon a time. There was a lab. It was very quiet. The end.")
        live, sent = session(engine, brain)
        await speak(live, [(0.6, True), (0.6, False)])
        await wait_state(live, "speaking")
        await speak(live, [(0.7, True), (0.7, False)])      # barge in
        await settle(live, timeout=8)
        check("L4 speaking over JARVIS stops playback (stop_audio sent)", count(sent, "stop_audio") >= 1, True)
        check("L4b ...and the interruption becomes the NEXT question", brain.questions[-1], "Stop, that's enough.")

    async def l5() -> None:
        live, sent = session(FakeEngine({6: "Hello there."}), FakeBrain(0.6))
        await speak(live, [(0.6, True), (0.6, False)])
        await wait_state(live, "thinking")
        await speak(live, [(0.15, True), (0.6, False)])     # a cough
        await settle(live)
        check("L5 a cough during THINKING does not cancel the answer", count(sent, "retract"), 0)

    async def l6() -> None:
        long_answer = " ".join(f"Point {i} of the deep answer is spoken aloud." for i in range(60))

        class DeepHearth(FakeHearth):
            async def run_ask(self, question, emit, **kwargs):
                return {"ok": True, "answer": long_answer}

        class Recorder:
            def __init__(self):
                self.lines: List[str] = []

            def say(self, line: str) -> None:
                self.lines.append(line)
        sent: List[Any] = []

        async def send(msg: Dict[str, Any]) -> None:
            sent.append(msg)
        live = LiveSession(DeepHearth(), send, brain=FakeBrain(0.0), engine=FakeEngine({6: "x"}))
        rec = Recorder()
        await live._deep("explain everything", rec)
        spoken = " ".join(rec.lines)
        check("L6 a long deep answer is SPOKEN whole, not cut at 700 chars",
              len(long_answer) > 2000 and "Point 59 of the deep answer" in spoken
              and "rest is on screen" not in spoken, True)

    try:
        for case in (l1, l2, l3, l4, l5, l6):
            asyncio.run(case())
    finally:
        vp.persist_turn, g["log_latency"] = real_persist, real_log
    print("-" * 70)
    print(f"  {passed} passed, {failed} failed")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_run_self_test())

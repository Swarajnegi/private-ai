"""
speech.py — JARVIS's ears and voice, resident on the GPU.

LAYER: Body (Voice I/O)

Run with:
    PYTHONPATH=js-development python -m jarvis_core.serve.speech            # hermetic self-test
    PYTHONPATH=js-development python -m jarvis_core.serve.speech --live     # also loads the models

=============================================================================
THE BIG PICTURE
=============================================================================

The voice path this replaces (serve/voice.py) spawned a fresh whisper.cpp
process and a fresh Piper process for EVERY request, reloading each model
from disk every time. On this laptop that was ~25 s of speech-to-text plus
~25 s of text-to-speech per turn — most of the "2-3 minutes for Hi, JARVIS"
the user measured on 2026-09-26.

Here both models load ONCE, into the hearth process, and stay resident:

    faster-whisper small  CUDA int8_float16   1.2 s utterance -> 0.52 s
    Kokoro-82M bm_george  CUDA                6.5 s of speech  -> 0.37 s
    VRAM for both                              ~1.1 GB (measured 2026-09-27)

=============================================================================
THE LOAD-ORDER RULE (measured, not assumed — do not "tidy" it)
=============================================================================

ctranslate2 4.8.2 bundles only the cuDNN 9.10 DISPATCHER; torch 2.5.1+cu121
ships the full cuDNN 9.1 set. Whichever cudnn64_9.dll loads first owns that
name for the whole process. Measured both orders on 2026-09-27:

    ctranslate2 first  -> "Could not load symbol cudnnGetLibConfig", crash
    torch first        -> Whisper on CUDA works AND torch cuDNN convs work

So _init_torch_cuda() MUST run before faster_whisper is imported. Kokoro's
decoder uses cuDNN convolutions, which is why the other order is not an
option — it would break the voice to fix the ears.

=============================================================================
THE FLOW
=============================================================================

STEP 1: warm() initialises torch on CUDA, then loads Whisper, then Kokoro,
        running one throwaway inference each so the first real turn pays no
        kernel-compile cost. Any engine that fails falls back to CPU.
        |
STEP 2: StreamingVAD.feed() consumes 16 kHz PCM16 frames and emits an
        utterance once speech is followed by `end_silence_ms` of silence —
        Silero VAD, the same ONNX model faster-whisper ships, run
        statefully frame by frame (faster-whisper's own wrapper is
        batch-only and resets its state every call).
        |
STEP 3: transcribe() turns an utterance into text; synthesize() yields
        24 kHz PCM16 per sentence so playback can start on the first one.
        |
STEP 4: SentenceChunker turns a stream of LLM tokens into speakable
        sentences, so TTS never waits for the whole answer.
=============================================================================
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jarvis_core.config import DATA_ROOT  # noqa: E402

STT_MODEL = os.environ.get("JARVIS_STT_MODEL", "small")
# Chosen by the owner 2026-09-28 from a side-by-side of the four British male
# voices (artifacts/voice-samples/compare), heard at 1.05x.
TTS_VOICE = os.environ.get("JARVIS_TTS_VOICE", "bm_lewis")
TTS_SPEED = float(os.environ.get("JARVIS_TTS_SPEED", "1.05"))
TTS_VOICES = ("bm_george", "bm_fable", "bm_lewis", "bm_daniel")
TTS_RATE = 24000
STT_RATE = 16000
LATENCY_LOG = Path(DATA_ROOT) / "voice_latency.jsonl"
_IST = timezone(timedelta(hours=5, minutes=30))


def _init_torch_cuda() -> bool:
    """Claim cuDNN for torch before ctranslate2 loads. See THE LOAD-ORDER RULE."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.zeros(1, device="cuda")
            return True
    except Exception:
        pass
    return False


# =============================================================================
# Part 1: THE ENGINE — resident STT + TTS
# =============================================================================

@dataclass
class EngineState:
    stt_device: str = "unloaded"
    tts_device: str = "unloaded"
    warm: bool = False
    warm_seconds: Optional[float] = None
    error: Optional[str] = None


class SpeechEngine:
    """Process-wide. STT and TTS have separate locks so JARVIS can hear
    while it speaks — the prerequisite for barge-in."""

    def __init__(self) -> None:
        self.state = EngineState()
        self._stt: Any = None
        self._stt_cpu: Any = None
        self._tts: Any = None
        self._stt_lock = threading.Lock()
        self._tts_lock = threading.Lock()
        self._warm_lock = threading.Lock()

    def warm(self) -> EngineState:
        with self._warm_lock:
            if self.state.warm:
                return self.state
            t0 = time.perf_counter()
            cuda = _init_torch_cuda()
            try:
                self._load_stt(cuda)
            except Exception as e:                          # noqa: BLE001
                self.state.error = f"stt: {type(e).__name__}: {e}"
            try:
                self._load_tts(cuda)
            except Exception as e:                          # noqa: BLE001
                self.state.error = f"tts: {type(e).__name__}: {e}"
            self.state.warm = self._stt is not None and self._tts is not None
            self.state.warm_seconds = round(time.perf_counter() - t0, 2)
            return self.state

    def _load_stt(self, cuda: bool) -> None:
        from faster_whisper import WhisperModel
        if cuda:
            try:
                model = WhisperModel(STT_MODEL, device="cuda", compute_type="int8_float16")
                list(model.transcribe(np.zeros(STT_RATE, dtype=np.float32),
                                      language="en", beam_size=1)[0])
                self._stt, self.state.stt_device = model, "cuda"
                return
            except Exception:                               # noqa: BLE001
                pass
        model = WhisperModel(STT_MODEL, device="cpu", compute_type="int8")
        self._stt, self.state.stt_device = model, "cpu"

    def _load_tts(self, cuda: bool) -> None:
        from kokoro import KPipeline
        device = "cuda" if cuda else "cpu"
        pipe = KPipeline(lang_code="b", device=device, repo_id="hexgrad/Kokoro-82M")
        for _ in pipe("Ready.", voice=TTS_VOICE):
            pass
        self._tts, self.state.tts_device = pipe, device

    def transcribe(self, audio: np.ndarray) -> str:
        """16 kHz mono float32 in [-1, 1] -> text."""
        if self._stt is None:
            self.warm()
        if self._stt is None:
            raise RuntimeError(self.state.error or "speech-to-text unavailable")
        with self._stt_lock:
            try:
                return self._run_stt(self._stt, audio)
            except RuntimeError as e:
                # Measured 2026-09-27: a CUDA OOM (another process took VRAM)
                # left ctranslate2 reporting "invalid device ordinal" for the
                # next call. Losing the turn is worse than a slower transcript,
                # so a CUDA fault drops this one utterance to a CPU model.
                if self.state.stt_device != "cuda" or "cuda" not in str(e).lower():
                    raise
                if self._stt_cpu is None:
                    from faster_whisper import WhisperModel
                    self._stt_cpu = WhisperModel(STT_MODEL, device="cpu", compute_type="int8")
                self.state.error = f"stt cuda fault, used cpu once: {e}"
                return self._run_stt(self._stt_cpu, audio)

    @staticmethod
    def _run_stt(model: Any, audio: np.ndarray) -> str:
        # initial_prompt biases spelling: without it "Hi, JARVIS" came back as
        # "Hi, J.R.VIS." (measured 2026-09-27).
        segments, _ = model.transcribe(audio, language="en", beam_size=1,
                                       condition_on_previous_text=False,
                                       initial_prompt="A conversation with JARVIS.")
        return " ".join(seg.text.strip() for seg in segments).strip()

    def synthesize(self, text: str, voice: str = TTS_VOICE) -> Iterator[bytes]:
        """Text -> 24 kHz mono PCM16, one chunk per sentence Kokoro produces."""
        if self._tts is None:
            self.warm()
        if self._tts is None:
            raise RuntimeError(self.state.error or "text-to-speech unavailable")
        if voice not in TTS_VOICES:
            voice = TTS_VOICE
        with self._tts_lock:
            for _gs, _ps, audio in self._tts(text, voice=voice, speed=TTS_SPEED):
                arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
                yield (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

    def status(self) -> Dict[str, Any]:
        s = self.state
        return {"warm": s.warm, "stt": s.stt_device, "tts": s.tts_device,
                "stt_model": STT_MODEL, "voice": TTS_VOICE, "voices": list(TTS_VOICES),
                "warm_seconds": s.warm_seconds, "error": s.error}


ENGINE = SpeechEngine()


# =============================================================================
# Part 2: STREAMING VAD — Silero, run statefully frame by frame
# =============================================================================

_FRAME = 512          # 32 ms at 16 kHz — the size Silero v6 was trained on
_CONTEXT = 64


class _Silero:
    def __init__(self) -> None:
        import onnxruntime
        from faster_whisper.utils import get_assets_path
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.session = onnxruntime.InferenceSession(
            os.path.join(get_assets_path(), "silero_vad_v6.onnx"),
            providers=["CPUExecutionProvider"], sess_options=opts)
        self.reset()

    def reset(self) -> None:
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros((1, _CONTEXT), dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.context, frame.reshape(1, _FRAME)], axis=1)
        out, self.h, self.c = self.session.run(None, {"input": x, "h": self.h, "c": self.c})
        self.context = frame.reshape(1, _FRAME)[:, -_CONTEXT:]
        return float(np.asarray(out).reshape(-1)[0])


@dataclass
class VadEvent:
    kind: str                     # "speech_start" | "sustained" | "utterance"
    audio: Optional[np.ndarray] = None
    speech_ms: int = 0


@dataclass
class StreamingVAD:
    """Feed PCM16 bytes; get an utterance once speech is followed by silence.

    `prob_fn` is injectable so the self-test runs without the ONNX model."""

    end_silence_ms: int = 500
    min_speech_ms: int = 200
    # "sustained" fires once per utterance after this much voiced audio — the
    # signal that the user is really speaking, as opposed to a cough or a
    # click. Barge-in and continuation both key on it, never on speech_start.
    sustain_ms: int = 300
    preroll_ms: int = 300
    threshold: float = 0.5
    prob_fn: Any = None
    _buf: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    _utt: List[np.ndarray] = field(default_factory=list)
    _pre: List[np.ndarray] = field(default_factory=list)
    _speaking: bool = False
    _voiced_ms: int = 0
    _silent_ms: int = 0
    _sustained: bool = False

    def __post_init__(self) -> None:
        if self.prob_fn is None:
            self.prob_fn = _Silero().prob

    @property
    def speaking(self) -> bool:
        return self._speaking

    def feed(self, pcm16: bytes) -> Iterator[VadEvent]:
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        self._buf = np.concatenate([self._buf, samples])
        frame_ms = _FRAME * 1000 // STT_RATE
        while self._buf.shape[0] >= _FRAME:
            frame, self._buf = self._buf[:_FRAME], self._buf[_FRAME:]
            voiced = self.prob_fn(frame) >= self.threshold
            if not self._speaking:
                self._pre.append(frame)
                self._pre = self._pre[-max(1, self.preroll_ms // frame_ms):]
                if voiced:
                    self._speaking, self._voiced_ms, self._silent_ms = True, frame_ms, 0
                    self._sustained = False
                    self._utt = list(self._pre)
                    yield VadEvent("speech_start")
                continue
            self._utt.append(frame)
            if voiced:
                self._voiced_ms += frame_ms
                self._silent_ms = 0
                if not self._sustained and self._voiced_ms >= self.sustain_ms:
                    self._sustained = True
                    yield VadEvent("sustained", speech_ms=self._voiced_ms)
            else:
                self._silent_ms += frame_ms
                if self._silent_ms >= self.end_silence_ms:
                    speech_ms = self._voiced_ms
                    audio = np.concatenate(self._utt)
                    self._speaking, self._utt, self._pre = False, [], []
                    if speech_ms >= self.min_speech_ms:
                        yield VadEvent("utterance", audio=audio, speech_ms=speech_ms)


# =============================================================================
# Part 3: SENTENCE CHUNKER — LLM tokens in, speakable sentences out
# =============================================================================

_SENTENCE_END = re.compile(r"([.!?…]+[\"')\]]*)(\s+|$)")
_SOFT_BREAK = re.compile(r"[,;:—–]\s")


class SentenceChunker:
    """Emit a sentence as soon as it is complete. A long clause with no full
    stop is released at a soft break so TTS never idles behind one run-on."""

    def __init__(self, soft_limit: int = 160, first_soft_limit: int = 40) -> None:
        # The FIRST chunk is released at the first clause break past
        # first_soft_limit chars: time-to-first-audio is set by how long the
        # opening chunk takes to arrive, and "Project timeline intact, sir," is
        # speakable long before its sentence ends.
        self._buf = ""
        self._soft = soft_limit
        self._first_soft = first_soft_limit
        self._emitted = False

    def push(self, token: str) -> List[str]:
        self._buf += token
        out: List[str] = []
        while True:
            m = _SENTENCE_END.search(self._buf)
            if m and m.end(1) < len(self._buf):
                out.append(self._buf[: m.end(1)].strip())
                self._buf = self._buf[m.end():]
                continue
            limit = self._soft if self._emitted else self._first_soft
            if len(self._buf) > limit:
                soft = None
                for s in _SOFT_BREAK.finditer(self._buf):
                    soft = s
                if soft:
                    out.append(self._buf[: soft.start() + 1].strip())
                    self._buf = self._buf[soft.end():]
                    continue
            break
        out = [s for s in out if s]
        if out:
            self._emitted = True
        return out

    def flush(self) -> List[str]:
        rest, self._buf = self._buf.strip(), ""
        return [rest] if rest else []


def strip_for_speech(text: str) -> str:
    """Markdown is for eyes. Remove what a voice would read aloud literally."""
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s*[#>*\-+]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~]{1,3}", "", text)
    return re.sub(r"\s+", " ", text).strip()


# =============================================================================
# Part 3b: HTTP VOICE — for clients that are not the live socket
# =============================================================================

def http_capabilities() -> Dict[str, Any]:
    """Engine status for GET /v1/voice/capabilities. Never loads a model."""
    return {"ok": True, "local": True, **ENGINE.status()}


def http_voice(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /v1/voice/transcribe {audio: base64 WAV} -> {text}
       POST /v1/voice/synthesize {text, voice?}    -> {audio: base64 WAV 24 kHz}"""
    import base64
    import io
    import wave
    if kind == "transcribe":
        raw = payload.get("audio")
        if not isinstance(raw, str) or not raw:
            raise ValueError("field 'audio' must be a base64 WAV string")
        with wave.open(io.BytesIO(base64.b64decode(raw)), "rb") as w:
            if w.getsampwidth() != 2:
                raise ValueError("audio must be 16-bit PCM WAV")
            rate, channels = w.getframerate(), w.getnchannels()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)
        if rate != STT_RATE:
            n = int(len(pcm) * STT_RATE / rate)
            pcm = np.interp(np.linspace(0, len(pcm), n, endpoint=False), np.arange(len(pcm)), pcm).astype(np.float32)
        return {"text": ENGINE.transcribe(pcm), "local": True}
    if kind == "synthesize":
        text = strip_for_speech(str(payload.get("text") or ""))
        if not text:
            raise ValueError("field 'text' is required")
        pcm = b"".join(ENGINE.synthesize(text, str(payload.get("voice") or TTS_VOICE)))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(TTS_RATE); w.writeframes(pcm)
        return {"audio": base64.b64encode(buf.getvalue()).decode("ascii"), "local": True}
    raise ValueError(f"unknown voice operation {kind!r}")


# =============================================================================
# Part 4: LATENCY LOG — the instrument the Phase 1 gate reads
# =============================================================================

def log_latency(record: Dict[str, Any], path: Optional[Path] = None) -> None:
    """Append one turn's stage timings. Locked, and heals a torn last line."""
    from jarvis_core.locking import exclusive_lock
    target = path or LATENCY_LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": datetime.now(_IST).isoformat(timespec="milliseconds"), **record}
    with exclusive_lock(target):
        with open(target, "a+b") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    f.write(b"\n")
            f.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())


# =============================================================================
# Self-test — hermetic unless --live
# =============================================================================

def _run_self_test(live: bool = False) -> int:
    import tempfile
    passed = failed = 0

    def check(label: str, got: Any, want: Any) -> None:
        nonlocal passed, failed
        ok = got == want
        passed, failed = passed + ok, failed + (not ok)
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        got {got!r} want {want!r}"))

    print("=" * 70)
    print("  speech self-test" + (" (live)" if live else ""))
    print("=" * 70)

    def frames(ms: int, loud: bool) -> bytes:
        n = STT_RATE * ms // 1000
        return (np.full(n, 8000 if loud else 0, dtype=np.int16)).tobytes()

    energy = lambda f: 1.0 if float(np.abs(f).mean()) > 0.1 else 0.0   # noqa: E731
    vad = StreamingVAD(end_silence_ms=500, min_speech_ms=200, prob_fn=energy)
    ev = list(vad.feed(frames(300, False) + frames(600, True) + frames(700, False)))
    kinds = [e.kind for e in ev]
    check("V1 speech then silence yields speech_start, sustained, then one utterance",
          kinds, ["speech_start", "sustained", "utterance"])
    check("V2 the utterance carries the pre-roll plus the speech",
          ev[-1].audio is not None and ev[-1].audio.shape[0] > STT_RATE * 0.6, True)
    vad2 = StreamingVAD(end_silence_ms=500, min_speech_ms=200, prob_fn=energy)
    check("V3 a 64 ms click is not an utterance",
          [e.kind for e in vad2.feed(frames(64, True) + frames(700, False))], ["speech_start"])
    vad3 = StreamingVAD(end_silence_ms=500, min_speech_ms=200, prob_fn=energy)
    ev3 = list(vad3.feed(frames(400, True) + frames(300, False) + frames(400, True) + frames(600, False)))
    check("V4 a pause SHORTER than end_silence stays one utterance",
          [e.kind for e in ev3], ["speech_start", "sustained", "utterance"])
    vad4 = StreamingVAD(end_silence_ms=500, min_speech_ms=100, sustain_ms=300, prob_fn=energy)
    check("V5 speech shorter than sustain_ms never reports sustained (a cough cannot barge in)",
          [e.kind for e in vad4.feed(frames(160, True) + frames(700, False))], ["speech_start", "utterance"])

    c = SentenceChunker()
    got: List[str] = []
    for tok in ["Good ", "evening", ", sir.", " All systems", " are online.", " Shall I"]:
        got += c.push(tok)
    check("S1 sentences release as soon as they end", got, ["Good evening, sir.", "All systems are online."])
    check("S2 flush returns the unfinished tail", c.flush(), ["Shall I"])
    c2 = SentenceChunker(soft_limit=40)
    long = c2.push("this clause runs on and on without stopping, and it keeps going further ")
    check("S3 a run-on is released at a soft break", len(long) >= 1 and long[0].endswith(","), True)
    c3 = SentenceChunker()
    early = c3.push("Project timeline intact, sir, and the next pending task is fine-tuning")
    check("S5 the first chunk releases at a clause break, not the sentence end",
          early, ["Project timeline intact, sir,"])
    check("S4 markdown is stripped for speech",
          strip_for_speech("**Done.** See `hearth.py` and [docs](http://x)."), "Done. See hearth.py and docs.")

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "lat.jsonl"
        p.write_bytes(b'{"torn": tr')
        log_latency({"stage": "x"}, path=p)
        lines = p.read_text(encoding="utf-8").splitlines()
        check("L1 a torn last line is healed before appending",
              json.loads(lines[-1]).get("stage"), "x")

    if live:
        st = ENGINE.warm()
        check("E1 both engines load", st.warm, True)
        pcm = b"".join(ENGINE.synthesize("Good evening, sir. All systems are online."))
        check("E2 synthesis produces audio", len(pcm) > TTS_RATE, True)
        a24 = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        a16 = np.interp(np.linspace(0, len(a24), int(len(a24) * STT_RATE / TTS_RATE), endpoint=False),
                        np.arange(len(a24)), a24).astype(np.float32)
        t = time.perf_counter()
        text = ENGINE.transcribe(a16).lower()
        print(f"        round trip heard: {text!r} in {time.perf_counter() - t:.2f}s on {st.stt_device}")
        check("E3 the voice is intelligible to the ears", "systems" in text and "online" in text, True)
        real = StreamingVAD()
        pad = np.zeros(int(0.8 * STT_RATE), dtype=np.float32)
        stream = (np.concatenate([pad, a16, pad]) * 32767).astype(np.int16).tobytes()
        check("E4 real Silero VAD finds one utterance in synthesized speech",
              [e.kind for e in real.feed(stream)].count("utterance") >= 1, True)

    print("-" * 70)
    print(f"  {passed} passed, {failed} failed")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_self_test(live="--live" in sys.argv))

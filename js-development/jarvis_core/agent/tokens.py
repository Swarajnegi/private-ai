"""
tokens.py — one token counter, calibrated against provider ground truth.

LAYER: Agent (Memory / budget accounting)

Import with:
    from jarvis_core.agent.tokens import TokenCounter, TokenBudget, count_messages

=============================================================================
THE BIG PICTURE
=============================================================================

Until 2026-09-08 every token number in this system was `len(text) // 4`, in two
separate copies that could drift from each other:

    brain/llm_client.py:75   _CHARS_PER_TOKEN = 4   -> est_in_tokens (:225)
    agent/compact.py:73      _CHARS_PER_TOKEN = 4   -> estimate_tokens() (:77)

And nothing anywhere compared an assembled prompt against the target model's
context_length, even though that value is loaded (router.py:241) and even sorted
on (llm_client.pick_free_model). So the system could not answer the one question
that governs every paging decision: WILL THIS FIT?

WHY NOT A REAL TOKENIZER. tiktoken is not installed; transformers is, but the
catalog holds 364 models across a dozen tokenizer families, and loading a
tokenizer per model on CPU is not viable. More importantly it would be a
DIFFERENT wrong answer — OpenAI's BPE does not tokenize Gemini or Kimi text.

WHY CALIBRATION IS BETTER HERE. The provider already tells us the truth.
llm_client.py:264-266 reads usage.prompt_tokens / usage.completion_tokens from
the response body and only falls back to the estimate. Every real call is a free
labelled sample: we sent N chars, the provider counted T tokens. Feeding that
back turns a fixed guess into a per-model ratio that converges on reality — for
EVERY model in the catalog, with zero new dependencies.

The ratio file is a PROJECTION in the storage taxonomy (KB 548): derived,
disposable, regenerable by using the system. Losing it costs nothing but a few
calls of re-convergence, so it is gitignored and never synced.

HONEST LIMIT: this is an approximation and stays one. It is accurate in
aggregate, not per-string — a message of pure punctuation or CJK will be
mis-estimated even at a well-calibrated ratio. It exists to make budget and
paging decisions sound, not to replace a tokenizer.

=============================================================================
THE FLOW
=============================================================================

STEP 1: TokenCounter.count(text, model) -> len(text) / ratio_for(model),
        where ratio_for falls back DEFAULT_RATIO until calibrated.
        |
STEP 2: after a real call, llm_client hands back the truth:
        counter.observe(model, chars_sent, usage.prompt_tokens). An EWMA
        nudges that model's ratio toward the observed value.
        |
STEP 3: ratios persist to jarvis_data/token_ratios.json under flock, so the
        calibration survives across sessions and processes.
        |
STEP 4: TokenBudget(context_length, reserve_output) answers fits()/remaining()
        so the compactor and the paging policy have a real ceiling to aim at.
=============================================================================
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import DATA_ROOT
from jarvis_core.locking import exclusive_lock

# 4.0 chars/token is the industry rule of thumb for English prose and is what
# both previous estimators hardcoded. It is the STARTING point now, not the
# answer — every model moves off it as soon as real usage arrives.
DEFAULT_RATIO = 4.0

# How fast a model's ratio chases observed reality. 0.25 converges in a handful
# of calls while staying immune to one anomalous response (a huge tool result,
# a truncated reply). Deliberately not 1.0: a single sample must not define the
# ratio for every future call.
_EWMA_ALPHA = 0.25

# Guard rails. Anything outside this is a parsing bug or a provider reporting
# tokens for a different payload than we sent — clamp rather than poison the
# ratio, because a corrupted ratio silently breaks every paging decision.
_MIN_RATIO = 1.5
_MAX_RATIO = 12.0

# Below this the sample is noise: short strings round badly and a 3-token reply
# would swing the ratio wildly.
_MIN_SAMPLE_CHARS = 200

_RATIOS_PATH = Path(DATA_ROOT) / "token_ratios.json"

# Reserve for the model's own reply when asking "does the prompt fit?". A prompt
# that exactly fills the window leaves no room to answer, which is a failure
# mode indistinguishable from overflow but much more confusing.
DEFAULT_OUTPUT_RESERVE = 2048


@dataclass
class TokenCounter:
    """Chars->tokens with a per-model ratio learned from provider ground truth."""

    ratios: Dict[str, float] = field(default_factory=dict)
    path: Optional[Path] = None
    _samples: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "TokenCounter":
        """Read persisted ratios. A missing/corrupt file is normal, not an error."""
        p = Path(path) if path else _RATIOS_PATH
        ratios: Dict[str, float] = {}
        samples: Dict[str, int] = {}
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            for model, rec in (raw.get("models") or {}).items():
                r = float(rec.get("ratio", DEFAULT_RATIO))
                if _MIN_RATIO <= r <= _MAX_RATIO:
                    ratios[model] = r
                    samples[model] = int(rec.get("samples", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return cls(ratios=ratios, path=p, _samples=samples)

    def ratio_for(self, model: Optional[str]) -> float:
        if not model:
            return DEFAULT_RATIO
        return self.ratios.get(model, DEFAULT_RATIO)

    def count(self, text: Optional[str], model: Optional[str] = None) -> int:
        """Estimated tokens in one string. Never returns 0 for non-empty text."""
        if not text:
            return 0
        return max(1, int(len(text) / self.ratio_for(model)))

    def count_messages(
        self, messages: Iterable[Dict[str, Any]], model: Optional[str] = None
    ) -> int:
        return sum(self.count(str(m.get("content", "")), model) for m in messages)

    def observe(self, model: Optional[str], chars: int, actual_tokens: int) -> None:
        """Feed one provider-reported truth back into the ratio (EWMA)."""
        if not model or chars < _MIN_SAMPLE_CHARS or actual_tokens <= 0:
            return
        observed = chars / float(actual_tokens)
        if not (_MIN_RATIO <= observed <= _MAX_RATIO):
            return  # implausible: clamp by ignoring, never by poisoning
        prior = self.ratios.get(model, DEFAULT_RATIO)
        self.ratios[model] = (1 - _EWMA_ALPHA) * prior + _EWMA_ALPHA * observed
        self._samples[model] = self._samples.get(model, 0) + 1

    def save(self) -> bool:
        """Persist under flock. Failure is non-fatal — calibration is disposable."""
        p = self.path or _RATIOS_PATH
        payload = {
            "_comment": ("Derived calibration (a PROJECTION per KB 548): chars-per-token "
                         "per model, learned from provider usage.prompt_tokens. "
                         "Regenerable by using the system; safe to delete."),
            "models": {m: {"ratio": round(r, 4), "samples": self._samples.get(m, 0)}
                       for m, r in sorted(self.ratios.items())},
        }
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with exclusive_lock(p):
                with p.open("a+", encoding="utf-8") as fh:
                    fh.seek(0)
                    fh.truncate()
                    json.dump(payload, fh, ensure_ascii=False, indent=2)
                    fh.flush()
                    os.fsync(fh.fileno())
            return True
        except OSError:
            return False


@dataclass(frozen=True)
class TokenBudget:
    """The ceiling a prompt must fit under, and how much room is left.

    The first thing in this repo able to answer "will this fit?" — every paging
    and compaction decision downstream is only as sound as this object.
    """

    context_length: int
    reserve_output: int = DEFAULT_OUTPUT_RESERVE

    @property
    def usable(self) -> int:
        """Window minus room for the reply. Never negative."""
        return max(0, int(self.context_length) - int(self.reserve_output))

    def fits(self, tokens: int) -> bool:
        return int(tokens) <= self.usable

    def remaining(self, tokens: int) -> int:
        return max(0, self.usable - int(tokens))

    def overflow(self, tokens: int) -> int:
        """How many tokens must be evicted for this to fit. 0 when it already does."""
        return max(0, int(tokens) - self.usable)


_SHARED: Optional[TokenCounter] = None


def shared_counter() -> TokenCounter:
    """Process-wide counter so llm_client's observations reach compact.py's counts.

    Persists at interpreter exit. WHY atexit rather than saving on every
    observe(): every `--ask` is a fresh process, so without a flush the ratio
    would be re-learned from 4.0 on every invocation and never converge — but
    writing on each observation would fsync several times per question for a
    value that only matters at the end. One write per process is the whole cost.
    """
    global _SHARED
    if _SHARED is None:
        _SHARED = TokenCounter.load()

        import atexit

        def _flush() -> None:
            try:
                if _SHARED is not None and _SHARED.ratios:
                    _SHARED.save()
            except Exception:
                pass  # calibration is disposable; never noise up a clean exit

        atexit.register(_flush)
    return _SHARED


def count_messages(messages: Iterable[Dict[str, Any]],
                   model: Optional[str] = None) -> int:
    return shared_counter().count_messages(messages, model)


# =============================================================================
# SMOKE TESTS (offline — temp paths, no network, no writes outside tempdir)
# =============================================================================

def _run_self_test() -> None:
    import tempfile

    print("=" * 70)
    print("  tokens.py -- Smoke Tests")
    print("=" * 70)
    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        nonlocal passed
        if cond:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed.append(name)
            print(f"  FAIL  {name}  {hint}")

    c = TokenCounter()
    check("T1 uncalibrated model uses the 4.0 default",
          c.count("x" * 400) == 100, c.count("x" * 400))
    check("T2 empty text is 0 tokens", c.count("") == 0 and c.count(None) == 0)
    check("T3 non-empty text is never 0", c.count("hi") >= 1)

    # T4-T6 -- calibration. Provider says 400 chars was 200 tokens => ratio 2.0.
    c.observe("m1", 400, 200)
    r1 = c.ratio_for("m1")
    check("T4 one sample moves the ratio toward truth (4.0 -> 2.0)",
          2.0 < r1 < 4.0, f"ratio={r1}")
    for _ in range(20):
        c.observe("m1", 400, 200)
    r2 = c.ratio_for("m1")
    check("T5 repeated samples converge on the observed ratio",
          abs(r2 - 2.0) < 0.05, f"ratio={r2}")
    check("T6 calibration is PER-MODEL, not global",
          c.ratio_for("m2") == DEFAULT_RATIO, c.ratio_for("m2"))

    # T7-T9 -- the guard rails. A poisoned ratio silently breaks all paging.
    before = c.ratio_for("m1")
    c.observe("m1", 400, 1)            # implausible 400 chars/token
    check("T7 implausible sample is ignored, not absorbed",
          c.ratio_for("m1") == before, c.ratio_for("m1"))
    c.observe("m3", 10, 5)             # too short to be signal
    check("T8 sub-threshold sample is ignored",
          c.ratio_for("m3") == DEFAULT_RATIO)
    c.observe(None, 4000, 1000)
    check("T9 observe(None) is a no-op, not a crash", True)

    # T10-T11 -- persistence round-trip.
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ratios.json"
        c.path = p
        check("T10 save() succeeds", c.save() is True)
        back = TokenCounter.load(p)
        # Tolerance is 1e-3, not exact equality: save() rounds to 4dp on purpose
        # so the file stays human-readable. Max round-trip error is 5e-5, which
        # is ~0.001 tokens on a 100-token string — far below the noise floor of
        # a chars-per-token approximation.
        check("T11 ratios survive a round-trip (within save()'s 4dp rounding)",
              abs(back.ratio_for("m1") - c.ratio_for("m1")) < 1e-3,
              f"{back.ratio_for('m1')} vs {c.ratio_for('m1')}")
        check("T11b samples count survives too",
              back._samples.get("m1", 0) == c._samples.get("m1", 0),
              f"{back._samples.get('m1')} vs {c._samples.get('m1')}")

    missing = TokenCounter.load(Path("/nonexistent-dir/ratios.json"))
    check("T12 missing file degrades to defaults, never raises",
          missing.ratio_for("anything") == DEFAULT_RATIO)

    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "corrupt.json"
        bad.write_text("{not json at all", encoding="utf-8")
        check("T13 corrupt file degrades to defaults",
              TokenCounter.load(bad).ratio_for("m1") == DEFAULT_RATIO)

    msgs = [{"role": "system", "content": "a" * 400},
            {"role": "user", "content": "b" * 400}]
    check("T14 count_messages sums across the list",
          TokenCounter().count_messages(msgs) == 200,
          TokenCounter().count_messages(msgs))

    # T15-T19 -- the budget object.
    b = TokenBudget(context_length=10_000, reserve_output=2_000)
    check("T15 usable = window - output reserve", b.usable == 8_000)
    check("T16 fits() at the exact boundary is True", b.fits(8_000))
    check("T17 one token past the boundary does not fit", not b.fits(8_001))
    check("T18 remaining() reports real headroom", b.remaining(6_000) == 2_000)
    check("T19 overflow() says how much must be evicted",
          b.overflow(9_500) == 1_500 and b.overflow(100) == 0)
    check("T20 reserve larger than window clamps to 0, not negative",
          TokenBudget(context_length=100, reserve_output=999).usable == 0)

    print("-" * 70)
    print(f"  {passed} passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()

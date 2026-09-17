#!/usr/bin/env python3
"""
curator.py — the agent in the conversation decides what a turn was FOR.

LAYER: Agent (capture stream)

Run with:
    python3 -m jarvis_core.agent.curator        # smoke tests (offline, injected)

=============================================================================
THE BIG PICTURE
=============================================================================

Until now nothing decided what a captured turn was ABOUT or where it belonged.
Measured 2026-09-14, and it is worse than it sounds:

  * `engineer_corpus` and `personalization_corpus` read the SAME
    `observation_queue.jsonl`. Every turn went into BOTH. The only difference
    was which half of the exchange each took — engineer kept
    "USER: … ASSISTANT: …", personalization kept the user's half. There was no
    routing decision at all, per prompt or otherwise.
  * `guess_domain()` in capture.py is a keyword matcher whose output feeds the
    digest's day-grouping and routes nothing.
  * `domain_labels.jsonl`, whose own source calls it THE AUTHORITATIVE LABEL,
    was six days stale, covered 583 of 989 turns, and was referenced by no
    corpus builder.

So the only thing standing between a three-word "continue" and the training
corpus was a character-count floor.

=============================================================================
WHY AN AGENT AND NOT A BETTER CLASSIFIER
=============================================================================

`relabel_domains.py` labelled 314 of 583 turns `unknown`. That looks like a
broken classifier and it is not — scored against its 28-turn gold set it gets
89%, above its 80% bar. It is ABSTAINING, correctly, and its own header
predicted exactly this and prescribed the cure:

    "A great many turns genuinely carry no domain in isolation — 'Convert these
     other two also', 'skip the learning for now', pasted stdout, and follow-ups
     whose subject sits in the PREVIOUS turn. No classifier reading one turn
     alone can label those... the fix is to classify a turn WITH its session
     neighbours — not to lower the threshold."

All three of its gold-set misses are that shape. "skip the learning for now,
let's start building" has no domain on its own; it has an obvious one if you
saw the turn before it.

The agent handling the conversation already holds that context. It does not
need to reconstruct it, and it is the only participant that knows what the
user's prompt was REPLYING to. That is the whole argument for putting the
judgement here instead of in another offline pass.

=============================================================================
WHY THIS RUNS AUTOMATICALLY AND NOT BY AGENT DISCIPLINE
=============================================================================

The tempting design is "the agent calls a tool to annotate each turn." This
repository has decisive evidence against it: Antigravity's capture depends on
the user typing `/memory`, and it has produced **zero records in months**. The
hearth was started by hand once and was found dead three days later. Anything
that must be REMEMBERED every turn returns nothing.

So the curator is driven by the Stop hook and the hearth's clock, not by an
agent choosing to invoke it. `complete_fn` is injected, which is what lets the
same organ be driven by Claude Code's hook, by Codex's ingester, by
Antigravity, or by JARVIS itself answering through `--ask`. Same contract as
`capture.py`'s `build_observation` — core organ, thin per-host adapter.

=============================================================================
WHY VERDICTS ARE APPENDED AND NEVER EDITED
=============================================================================

The user's requirement is that any agent can review whether JARVIS routed a
turn correctly. That needs the original judgement to survive being overruled,
so `turn_curation.jsonl` is an append-only EVENT log folded on read: the newest
verdict for a (ts, session_id) wins, and every earlier one stays legible with
its author. A reviewer appends; nobody rewrites. Same shape Codex used for
`scripts/commitments.py`, and the same reason.

The embedding label is carried alongside the agent's verdict rather than
replaced by it, so disagreement between a context-free classifier and a
context-having agent is a QUERY, not a thing someone has to notice.

=============================================================================
THE FLOW
=============================================================================

STEP 1: `TurnContext` gathers the turn plus its preceding session neighbours —
        the context the offline classifier structurally cannot have.
        |
STEP 2: `build_prompt` renders one compact classification request. Compact
        matters: this runs on every turn forever, so the neighbour window and
        each excerpt are capped.
        |
STEP 3: `parse_verdict` reads strict JSON and REJECTS anything it cannot
        validate against the known vocabularies, rather than coercing. A
        guessed label is the failure mode this whole module exists to end.
        |
STEP 4: `curate` returns a `Curation`, which the caller appends. `None` means
        the model ANSWERED and the answer was unusable — leave that turn
        uncurated, because an absent verdict is recoverable and a fabricated
        one is not. A model that could not be REACHED raises instead; the two
        are different problems and only the caller can decide between skipping
        one turn and stopping the batch.
=============================================================================
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "TurnContext", "Curation", "build_prompt", "parse_verdict", "curate",
    "CORPORA", "DOMAINS", "NOT_TRAINABLE", "fold_events", "load_routing", "routes_to",
]

# The corpora a turn can be routed into. "none" is a real destination and the
# most common correct one — "continue", "go", "hi" belong nowhere.
CORPORA: Tuple[str, ...] = ("engineer", "personalization", "none")
NOT_TRAINABLE = "none"

# Matches agent/domain_classifier.py's prototype labels exactly, plus its
# abstention. Divergence here would make the agent verdict and the embedding
# label incomparable, which would defeat the review path.
DOMAINS: Tuple[str, ...] = ("jarvis-build", "data-engineering", "ai-ml", "finance", "unknown")

_MAX_NEIGHBOURS = 3
_MAX_NEIGHBOUR_CHARS = 400
_MAX_TURN_CHARS = 2400


@dataclass(frozen=True)
class TurnContext:
    """One turn plus the conversation it sat in."""
    ts: str
    session_id: str
    user_text: str
    assistant_summary: str = ""
    neighbours: Tuple[str, ...] = ()      # preceding user turns, oldest first
    chat_label: str = ""


@dataclass(frozen=True)
class Curation:
    """One agent's judgement about one turn. Append-only; never edited."""
    ts: str
    session_id: str
    corpora: Tuple[str, ...]
    domain: str
    trainable: bool
    responds_to: str          # what the user's prompt was replying to
    rationale: str
    curated_by: str           # which agent/model produced this verdict
    confidence: float
    embedding_label: str = ""
    embedding_score: float = 0.0
    curated_at: str = ""

    def to_record(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "session_id": self.session_id,
            "corpora": list(self.corpora),
            "domain": self.domain,
            "trainable": self.trainable,
            "responds_to": self.responds_to,
            "rationale": self.rationale,
            "curated_by": self.curated_by,
            "confidence": self.confidence,
            "embedding_label": self.embedding_label,
            "embedding_score": self.embedding_score,
            "curated_at": self.curated_at,
        }

    @property
    def disagrees_with_embedding(self) -> bool:
        """True when the context-having agent and the context-free classifier differ.

        `unknown` from the embedding side is ABSTENTION, not a competing
        answer, so it is never a disagreement — treating it as one would flag
        half the corpus and train everyone to ignore the flag.
        """
        if not self.embedding_label or self.embedding_label == "unknown":
            return False
        return self.embedding_label != self.domain


_PROMPT = """\
You are curating one captured turn for JARVIS's training corpus. You have the \
conversation it came from, which an offline classifier does not.

Decide FOUR things and answer with JSON only.

1. `corpora` — where this turn's content belongs. A list, any of:
     "engineer"        — technical reasoning, architecture, code, data work.
     "personalization" — how the user thinks, decides, writes, what they want,
                         their constraints, preferences, self-assessments.
     "none"            — carries no durable signal. Acknowledgements ("ok",
                         "continue", "go ahead"), pure task commands with no
                         reasoning, pasted machine output, greetings.
   Both real corpora may apply. If "none" applies, it is the ONLY entry.

2. `domain` — exactly one of: {domains}.
   Use the CONVERSATION to resolve follow-ups. "skip the learning for now"
   has no domain alone; with the preceding turns it usually does. Answer
   "unknown" only when the context genuinely does not settle it.

3. `responds_to` — one sentence: what the user's message was replying to or
   building on. This is the context an offline pass cannot recover. If the
   turn opens a topic, say so.

4. `trainable` — true only if a model should learn from this EXCHANGE.
   Judge the pair, not the user's half alone. A short, precisely-steered
   question that draws out a substantial technical answer IS a high-value
   pair — the value sits in the answer, and the question is what elicited it.
   "explain again but keep watermark at 3 and 4 minutes and the interval delay
   at 2" carries no standalone reasoning and is trainable, because what came
   back was a full numerical derivation.
   Otherwise most turns in a working session are false. Be strict: a corpus of
   200 real turns beats 2000 padded ones.

Also give `confidence` (0.0-1.0) and a one-line `rationale`.

CONVERSATION SO FAR (oldest first):
{neighbours}

THE TURN TO CURATE
user: {user_text}
assistant (summary): {assistant_summary}

Answer with JSON only, no prose, no code fence:
{{"corpora": [...], "domain": "...", "responds_to": "...", "trainable": true|false, "confidence": 0.0, "rationale": "..."}}"""


def build_prompt(ctx: TurnContext) -> str:
    """Render the curation request. Capped — this runs on every turn, forever."""
    if ctx.neighbours:
        window = ctx.neighbours[-_MAX_NEIGHBOURS:]
        neighbours = "\n".join(
            f"  [{i + 1}] {n[:_MAX_NEIGHBOUR_CHARS]}" for i, n in enumerate(window))
    else:
        neighbours = "  (this is the first turn in the session)"
    return _PROMPT.format(
        domains=", ".join(f'"{d}"' for d in DOMAINS),
        neighbours=neighbours,
        user_text=ctx.user_text[:_MAX_TURN_CHARS],
        assistant_summary=ctx.assistant_summary[:_MAX_NEIGHBOUR_CHARS],
    )


_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_BRACES = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
    """Models fence JSON even when told not to. Strip, then fall back to braces."""
    for candidate in (m.group(1) for m in _FENCE.finditer(raw)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass
    m = _BRACES.search(raw)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def parse_verdict(raw: str, ctx: TurnContext, curated_by: str,
                  curated_at: str = "") -> Optional[Curation]:
    """Strict parse. Returns None rather than coercing an invalid answer.

    REJECTING BEATS REPAIRING HERE. This module exists because a keyword
    matcher quietly emitted a plausible-looking label for 309 turns it had no
    evidence about. Silently mapping an unrecognised domain onto the nearest
    known one would rebuild that failure with a bigger model behind it.
    """
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return None

    raw_corpora = data.get("corpora")
    if isinstance(raw_corpora, str):
        raw_corpora = [raw_corpora]
    if not isinstance(raw_corpora, list) or not raw_corpora:
        return None
    corpora = tuple(dict.fromkeys(str(c).strip().lower() for c in raw_corpora))
    if any(c not in CORPORA for c in corpora):
        return None
    if NOT_TRAINABLE in corpora and len(corpora) > 1:
        return None            # "none" is exclusive by definition

    domain = str(data.get("domain", "")).strip().lower()
    if domain not in DOMAINS:
        return None

    trainable = data.get("trainable")
    if not isinstance(trainable, bool):
        return None
    if trainable and corpora == (NOT_TRAINABLE,):
        return None            # "trainable but belongs nowhere" is incoherent

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None
    confidence = min(1.0, max(0.0, confidence))

    return Curation(
        ts=ctx.ts,
        session_id=ctx.session_id,
        corpora=corpora,
        domain=domain,
        trainable=trainable,
        responds_to=str(data.get("responds_to", "")).strip()[:400],
        rationale=str(data.get("rationale", "")).strip()[:300],
        curated_by=curated_by,
        confidence=confidence,
        curated_at=curated_at,
    )


def curate(ctx: TurnContext, complete_fn: Callable[[str], str], curated_by: str,
           curated_at: str = "") -> Optional[Curation]:
    """Ask the injected model to curate one turn. None when the ANSWER is unusable.

    `complete_fn` is the seam that makes this host-independent: Claude Code's
    hook, Codex's ingester, Antigravity and JARVIS each pass their own.

    TRANSPORT ERRORS PROPAGATE — they are deliberately NOT caught here, and the
    first version of this function was wrong to catch them. It returned None on
    any exception, so the caller reported every failure as "UNPARSEABLE". On
    2026-09-15 that turned an HTTP 402 (OpenRouter credits exhausted) into three
    lines claiming the model had produced unreadable output, which points at the
    prompt instead of at the bill — the exact class of confidently-wrong message
    this repo keeps finding.

    The two failures need different handling and only the caller can choose: a
    bad answer means skip this turn and continue; an unreachable model means
    stop, because the next 900 turns will fail identically.
    """
    raw = complete_fn(build_prompt(ctx))
    if not raw:
        return None
    return parse_verdict(raw, ctx, curated_by=curated_by, curated_at=curated_at)


def load_routing(path: Optional[Any] = None) -> Dict[Tuple[str, str], Tuple[str, ...]]:
    """{(ts, session_id): corpora} from the curation log, newest verdict winning.

    Returned to the corpus builders, which is the whole point of the module:
    before this, both builders read the same queue and every turn went into
    BOTH corpora because nothing had ever decided otherwise.

    An ABSENT key is not "route nowhere" — it is "nobody has looked yet", and
    the builders must treat it as such. Defaulting an uncurated turn to
    exclusion would silently collapse the corpus to whatever the backlog had
    reached, which is the kind of quiet, plausible-looking wrongness this
    module was written to stop.
    """
    import json as _json
    from pathlib import Path as _Path
    if path is None:
        from jarvis_core.config import DATA_ROOT
        path = _Path(DATA_ROOT) / "turn_curation.jsonl"
    records: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(_json.loads(line))
                except ValueError:
                    continue
    except (OSError, FileNotFoundError):
        return {}
    return {
        key: tuple(rec.get("corpora", ()))
        for key, rec in fold_events(records).items()
    }


def routes_to(corpus: str, key: Tuple[str, str],
              routing: Dict[Tuple[str, str], Tuple[str, ...]]) -> bool:
    """Should this turn go into `corpus`? Uncurated turns are admitted."""
    corpora = routing.get(key)
    if corpora is None:
        return True
    return corpus in corpora


def fold_events(records: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Newest verdict per (ts, session_id) wins; earlier ones stay in the log.

    Order of the file is authoritative rather than `curated_at`, because a
    reviewer correcting a verdict seconds later must win over one stamped by a
    machine whose clock is off — and every writer appends.

    KNOWN PROPERTY, cross-machine. `turn_curation.jsonl` is tracked and
    `.gitattributes` gives every `*.jsonl` `merge=union`, so two laptops can
    curate independently and the verdicts concatenate rather than conflict.
    What union does NOT preserve is global chronology: if both machines curate
    the SAME turn, the winner after a merge is whichever line sorts last in the
    merged file, not whichever was written later. That is deliberate and
    harmless — both are genuine verdicts from agents that had context, and
    picking either is defensible. It would NOT be harmless if this file held
    facts instead of judgements, which is why the queue itself is never
    written here.
    """
    folded: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rec in records:
        key = (str(rec.get("ts", "")), str(rec.get("session_id", "")))
        folded[key] = rec
    return folded


# =============================================================================
# Smoke tests — offline, model injected. No network.
# =============================================================================

def _smoke() -> int:
    passed: List[str] = []
    failed: List[str] = []

    def check(name: str, got, want) -> None:
        (passed if got == want else failed).append(
            name if got == want else f"{name}: got {got!r}, want {want!r}")

    ctx = TurnContext(
        ts="2026-09-14T10:00:00+05:30", session_id="s1",
        user_text="skip the learning for now, let's start building",
        assistant_summary="Moving to the build phase.",
        neighbours=("I want to learn how ChromaDB indexes embeddings before we wire it in.",
                    "That makes sense, but the roadmap says Stage 2.5 is already closed."))

    prompt = build_prompt(ctx)
    check("T1 prompt carries the neighbours", "ChromaDB indexes embeddings" in prompt, True)
    check("T2 prompt carries the turn", "skip the learning for now" in prompt, True)
    check("T3 prompt names every domain", all(d in prompt for d in DOMAINS), True)
    # T3b guards the fix for the one false `none` in Antigravity's a_005 audit:
    # the prompt used to ask whether the USER's half carried reasoning, so a
    # parameter-steered follow-up that drew out a full derivation was dropped.
    check("T3b prompt tells the model to judge the EXCHANGE, not the user half",
          "learn from this EXCHANGE" in prompt and "sits in the answer" in prompt, True)

    check("T4 first-turn prompt says so",
          "first turn in the session" in build_prompt(
              TurnContext(ts="t", session_id="s", user_text="hello there")), True)

    good = ('{"corpora": ["engineer"], "domain": "jarvis-build", '
            '"responds_to": "a plan to study ChromaDB before wiring it in", '
            '"trainable": true, "confidence": 0.8, "rationale": "a real build decision"}')
    v = parse_verdict(good, ctx, curated_by="claude")
    check("T5 valid verdict parses", v is not None, True)
    check("T6 domain resolved from context", v.domain, "jarvis-build")
    check("T7 corpora parsed", v.corpora, ("engineer",))
    check("T8 responds_to captured", "ChromaDB" in v.responds_to, True)

    check("T9 fenced JSON still parses",
          parse_verdict("```json\n" + good + "\n```", ctx, "claude") is not None, True)
    check("T10 JSON with leading prose still parses",
          parse_verdict("Here is my answer:\n" + good, ctx, "claude") is not None, True)

    # Every rejection below is a real failure mode, not defensive noise.
    check("T11 unknown domain is REJECTED, never coerced",
          parse_verdict(good.replace("jarvis-build", "devops"), ctx, "claude"), None)
    check("T12 unknown corpus is rejected",
          parse_verdict(good.replace('["engineer"]', '["backend"]'), ctx, "claude"), None)
    check("T13 'none' cannot be combined with a real corpus",
          parse_verdict(good.replace('["engineer"]', '["engineer","none"]'), ctx, "claude"), None)
    check("T14 trainable-but-belongs-nowhere is incoherent and rejected",
          parse_verdict(good.replace('["engineer"]', '["none"]'), ctx, "claude"), None)
    check("T15 non-boolean trainable is rejected",
          parse_verdict(good.replace('"trainable": true', '"trainable": "yes"'), ctx, "claude"),
          None)
    check("T16 empty corpora is rejected",
          parse_verdict(good.replace('["engineer"]', '[]'), ctx, "claude"), None)
    check("T17 garbage is rejected", parse_verdict("I could not decide.", ctx, "claude"), None)
    check("T18 empty string is rejected", parse_verdict("", ctx, "claude"), None)

    check("T19 a bare 'none' verdict is valid",
          parse_verdict('{"corpora":["none"],"domain":"unknown","responds_to":"an ack",'
                        '"trainable":false,"confidence":0.95,"rationale":"acknowledgement"}',
                        ctx, "claude").corpora, ("none",))
    check("T20 confidence is clamped",
          parse_verdict(good.replace("0.8", "4.2"), ctx, "claude").confidence, 1.0)
    check("T21 both corpora at once is valid",
          parse_verdict(good.replace('["engineer"]', '["engineer","personalization"]'),
                        ctx, "claude").corpora, ("engineer", "personalization"))
    check("T22 duplicate corpora collapse",
          parse_verdict(good.replace('["engineer"]', '["engineer","engineer"]'),
                        ctx, "claude").corpora, ("engineer",))

    # T23 asserts the OPPOSITE of what it used to. A transport error must reach
    # the caller so it can tell "bad answer" from "no model", instead of being
    # flattened into the same None as unparseable output.
    raised = False
    try:
        curate(ctx, lambda _p: (_ for _ in ()).throw(RuntimeError("HTTP 402")), "claude")
    except RuntimeError as exc:
        raised = "402" in str(exc)
    check("T23 a transport error PROPAGATES rather than looking unparseable", raised, True)
    check("T24 curate() returns None on an empty completion",
          curate(ctx, lambda _p: "", "claude"), None)
    check("T25 curate() passes the verdict through",
          curate(ctx, lambda _p: good, "codex").curated_by, "codex")

    dis = Curation(ts="t", session_id="s", corpora=("engineer",), domain="jarvis-build",
                   trainable=True, responds_to="", rationale="", curated_by="claude",
                   confidence=0.9, embedding_label="ai-ml", embedding_score=0.5)
    check("T26 real disagreement is flagged", dis.disagrees_with_embedding, True)
    agree = Curation(ts="t", session_id="s", corpora=("engineer",), domain="ai-ml",
                     trainable=True, responds_to="", rationale="", curated_by="claude",
                     confidence=0.9, embedding_label="ai-ml", embedding_score=0.5)
    check("T27 agreement is not flagged", agree.disagrees_with_embedding, False)
    abstained = Curation(ts="t", session_id="s", corpora=("engineer",), domain="jarvis-build",
                         trainable=True, responds_to="", rationale="", curated_by="claude",
                         confidence=0.9, embedding_label="unknown", embedding_score=0.1)
    check("T28 embedding ABSTENTION is not a disagreement",
          abstained.disagrees_with_embedding, False)

    folded = fold_events([
        {"ts": "t1", "session_id": "s", "domain": "ai-ml", "curated_by": "jarvis"},
        {"ts": "t1", "session_id": "s", "domain": "jarvis-build", "curated_by": "claude"},
        {"ts": "t2", "session_id": "s", "domain": "finance", "curated_by": "jarvis"},
    ])
    check("T29 a review overrides the original", folded[("t1", "s")]["domain"], "jarvis-build")
    check("T30 the reviewer is recorded", folded[("t1", "s")]["curated_by"], "claude")
    check("T31 untouched verdicts survive folding", folded[("t2", "s")]["domain"], "finance")
    check("T32 fold keeps one entry per turn", len(folded), 2)

    routing = {("t1", "s"): ("engineer",), ("t2", "s"): ("none",),
               ("t3", "s"): ("engineer", "personalization")}
    check("T34 routed turn goes to its corpus", routes_to("engineer", ("t1", "s"), routing), True)
    check("T35 ...and not to the other", routes_to("personalization", ("t1", "s"), routing), False)
    check("T36 a 'none' verdict routes nowhere",
          routes_to("engineer", ("t2", "s"), routing), False)
    check("T37 a both-verdict routes to both",
          all(routes_to(c, ("t3", "s"), routing) for c in ("engineer", "personalization")), True)
    check("T38 an UNCURATED turn is admitted, not dropped",
          routes_to("engineer", ("never-seen", "s"), routing), True)

    long_ctx = TurnContext(ts="t", session_id="s", user_text="x" * 9000,
                           neighbours=tuple("n" * 2000 for _ in range(12)))
    p = build_prompt(long_ctx)
    check("T33 prompt stays bounded on a huge turn", len(p) < 6000, True)

    print("=" * 70)
    print("  curator smoke tests")
    print("=" * 70)
    for line in passed:
        print(f"  PASS  {line}")
    for line in failed:
        print(f"  FAIL  {line}")
    print("-" * 70)
    print(f"  {len(passed)} passed, {len(failed)} failed")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_smoke())

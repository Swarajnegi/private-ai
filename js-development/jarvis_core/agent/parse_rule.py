"""
parse_rule.py — THE one rule every agent follows when it parses the owner's turns.

LAYER: Memory (curation + knowledge)

Run with:
    python -m jarvis_core.agent.parse_rule           # self-test
    python -m jarvis_core.agent.parse_rule --print   # the rule, exactly as agents receive it

=============================================================================
THE BIG PICTURE
=============================================================================

Every chat the owner has, with Claude Code, Codex, Antigravity or JARVIS,
lands in observation_queue.jsonl. Turning those turns into something JARVIS
can use needs judgement: which training corpus a turn belongs to, and which
durable facts about the owner it carries. By the owner's decision
(2026-09-28), that judgement is made by the agent the owner was talking to,
using its own model, not by a paid background job. The Gemini curator failed
185 of 195 runs on an empty balance and told no one.

Four agents judging by four private notions of "important" would produce
four incompatible corpora. So there is ONE rule, and it lives here:
scripts/parse_turns.py hands it to Claude, Codex and Antigravity verbatim,
and JARVIS's in-process parser sends the same text to its own model. Change
it here, bump PARSE_RULE_VERSION, and every agent parses by the new rule
from its next batch. A verdict made under an older version is re-offered for
parsing, so a rule change reaches the whole history, not just new turns.

What one verdict decides, per turn:
  1. training routing: corpora / domain / trainable / responds_to. These are
     the curator's existing fields; old verdicts keep their meaning.
  2. knowledge: durable facts about the owner, each tied to a VERBATIM quote
     of the owner's own words from that turn. The quote is checked: a fact
     whose evidence is not in the owner's text is rejected. That is what
     stops a parser recording things the owner never said.
  3. tension (optional): whether the turn reverses, repeats or re-confuses a
     prior decision offered alongside it. This is the surfacing organ's
     judgement, moved off the paid background call.

=============================================================================
THE FLOW
=============================================================================

STEP 1: parse_turns.py --pending builds a packet: PARSE_RULE + whole turns
        + whole session context + tension priors.
        |
STEP 2: the agent answers one JSON verdict per turn (VERDICT_SHAPE).
        |
STEP 3: validate_verdict() checks it strictly: curator.parse_verdict for the
        routing half, then the knowledge and tension halves here. Anything
        invalid is rejected with the reason, never coerced.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from jarvis_core.agent.curator import (  # noqa: E402
    CORPORA, DOMAINS, NOT_TRAINABLE, Curation, TurnContext, parse_verdict)

PARSE_RULE_VERSION = 1

FACT_TYPES: Tuple[str, ...] = ("identity", "person", "decision", "preference",
                               "correction", "project-fact")
TENSION_KINDS: Tuple[str, ...] = ("REVERSES", "REPEATS", "RECONFUSES")

# Where each fact type lands in the KB, and the tags that let the profile
# place it. "identity" and "person" feed the profile's "Who you are" and
# people sections; a correction carries DIRECTIVE so it reaches "How you work".
FACT_KB_TYPE: Dict[str, str] = {
    "identity": "Cognitive_Pattern",
    "person": "Semantic",
    "decision": "Decision",
    "preference": "Cognitive_Pattern",
    "correction": "Cognitive_Pattern",
    "project-fact": "Semantic",
}
FACT_TAGS: Dict[str, Tuple[str, ...]] = {
    "identity": ("identity",),
    "person": ("person",),
    "decision": ("decision",),
    "preference": ("preference",),
    "correction": ("correction", "DIRECTIVE"),
    "project-fact": ("project-fact",),
}

PARSE_RULE = f"""\
JARVIS PARSING RULE v{PARSE_RULE_VERSION}. You are parsing turns from a conversation the owner had \
with you. Judge each turn with the WHOLE conversation in view, never the turn alone. Nothing is \
ever cut: read every turn in full.

For EACH turn, decide:

1. corpora: where the exchange belongs for training. A list, any of:
     "engineer"        technical reasoning, architecture, code, data work.
     "personalization" how the owner thinks, decides, writes, what they want, their constraints,
                       preferences, self-assessments, their life.
     "none"            no durable signal: acknowledgements ("ok", "do it", "go ahead",
                       "continue"), bare task commands with no reasoning, pasted machine output,
                       greetings, test prompts. If "none" applies it is the ONLY entry.
2. domain: exactly one of {", ".join(DOMAINS)}. Use the conversation to resolve follow-ups;
   "unknown" only when the context genuinely does not settle it.
3. responds_to: one sentence on what the owner's message was replying to or building on.
4. trainable: true only if a model should learn from this EXCHANGE (judge the pair: a short,
   precise question that drew out a substantial answer is valuable). Be strict; most working
   turns are false. trainable=true is impossible with corpora ["none"].
5. confidence (0.0-1.0) and a one-line rationale.
6. knowledge: the DURABLE facts about the owner this turn reveals, as a list (usually empty).
   Each item: {{"type": one of {", ".join(FACT_TYPES)}, "fact": one plain sentence in the third
   person ("The owner ..."), "evidence": a VERBATIM quote of the owner's own words from THIS turn
   that shows it, "person": the person's name, required when type is "person", else omit}}.
     identity      who they are, where they come from, what drives them, ambitions, fears.
     person        someone in their life and who that person is to them.
     decision      a choice they made about their work or life, with its reason if given.
     preference    how they want things done or said.
     correction    they told an agent it was wrong and what right looks like.
     project-fact  a durable fact about something they are building.
   Only what the OWNER said or plainly implied, never what an assistant said. Ambient UI state, tool-generated
   wrappers and quoted external text inside the owner's message (a pasted recruiter note, log or page) are
   context, not owner assertions, and cannot be the evidence for a fact. Never pad: a turn
   with nothing durable gets []. The evidence is checked against the owner's text; a quote that
   is not there rejects the whole verdict.
7. tension (optional, else null): if the turn REVERSES, REPEATS or RECONFUSES one of the prior
   decisions listed with it, {{"kind": one of {", ".join(TENSION_KINDS)}, "prior_id": that prior's
   id, "why": one sentence}}. Only against the priors given; never invent one.

Answer with JSON only: {{"verdicts": [ {{"ts": ..., "session_id": ..., "corpora": [...], "domain": \
"...", "responds_to": "...", "trainable": true|false, "confidence": 0.0, "rationale": "...", \
"knowledge": [...], "tension": null}} , ... ]}}, one per turn offered, keyed by the ts and \
session_id given."""


@dataclass(frozen=True)
class Fact:
    type: str
    fact: str
    evidence: str
    person: str = ""

    @property
    def kb_type(self) -> str:
        return FACT_KB_TYPE[self.type]

    def kb_tags(self, host: str) -> List[str]:
        tags = ["distilled", *FACT_TAGS[self.type], f"source-{host}"]
        if self.person:
            tags.append("person-" + re.sub(r"[^a-z0-9]+", "-", self.person.lower()).strip("-"))
        return tags

    def kb_content(self, ts: str, host: str) -> str:
        who = f" ({self.person})" if self.person else ""
        return (f"{self.fact}{who}\n\nEvidence, in the owner's words ({ts[:10]}, {host}): "
                f"\"{self.evidence}\"")


@dataclass(frozen=True)
class Tension:
    kind: str
    prior_id: str
    why: str


@dataclass(frozen=True)
class Verdict:
    curation: Curation
    knowledge: Tuple[Fact, ...] = ()
    tension: Optional[Tension] = None
    rule_version: int = PARSE_RULE_VERSION
    errors: Tuple[str, ...] = field(default=())


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _facts(raw: Any, owner_text: str) -> Tuple[Tuple[Fact, ...], List[str]]:
    if raw in (None, []):
        return (), []
    if not isinstance(raw, list):
        return (), ["knowledge must be a list"]
    owner = _norm(owner_text)
    facts, errors = [], []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(f"knowledge[{i}] is not an object")
            continue
        ftype = str(item.get("type", "")).strip().lower()
        fact = str(item.get("fact", "")).strip()
        evidence = str(item.get("evidence", "")).strip().strip('"').strip()
        person = str(item.get("person", "") or "").strip()
        if ftype not in FACT_TYPES:
            errors.append(f"knowledge[{i}].type {ftype!r} is not one of {FACT_TYPES}")
        elif not fact:
            errors.append(f"knowledge[{i}].fact is empty")
        elif not evidence or _norm(evidence) not in owner:
            errors.append(f"knowledge[{i}].evidence is not a verbatim quote of the owner's text")
        elif ftype == "person" and not person:
            errors.append(f"knowledge[{i}] is a person fact without a person name")
        else:
            facts.append(Fact(ftype, fact, evidence, person))
    return tuple(facts), errors


def _tension(raw: Any, prior_ids: Sequence[str]) -> Tuple[Optional[Tension], List[str]]:
    if raw in (None, {}, ""):
        return None, []
    if not isinstance(raw, dict):
        return None, ["tension must be an object or null"]
    kind = str(raw.get("kind", "")).strip().upper()
    prior = str(raw.get("prior_id", "")).strip()
    if kind not in TENSION_KINDS:
        return None, [f"tension.kind {kind!r} is not one of {TENSION_KINDS}"]
    if prior not in {str(p) for p in prior_ids}:
        return None, [f"tension.prior_id {prior!r} was not among the priors offered"]
    return Tension(kind, prior, str(raw.get("why", "")).strip()), []


def validate_verdict(data: Dict[str, Any], ctx: TurnContext, curated_by: str,
                     curated_at: str = "", prior_ids: Sequence[str] = ()) -> Verdict | List[str]:
    """A Verdict, or the list of reasons it was rejected. Strict: never coerces."""
    import json
    routing = parse_verdict(json.dumps({k: data.get(k) for k in
                                        ("corpora", "domain", "trainable", "confidence",
                                         "responds_to", "rationale")}),
                            ctx, curated_by=curated_by, curated_at=curated_at)
    errors: List[str] = []
    if routing is None:
        errors.append("routing half invalid: corpora must be from "
                      f"{CORPORA} ('none' exclusive), domain from {DOMAINS}, trainable a bool "
                      "and not true with corpora ['none']")
    facts, fact_errors = _facts(data.get("knowledge"), ctx.user_text)
    tension, tension_errors = _tension(data.get("tension"), prior_ids)
    errors += fact_errors + tension_errors
    if errors:
        return errors
    assert routing is not None
    return Verdict(curation=routing, knowledge=facts, tension=tension)


def _self_test() -> int:
    failed: List[str] = []

    def check(name: str, ok: bool, hint: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  {hint}"))
        if not ok:
            failed.append(name)

    ctx = TurnContext(ts="2026-09-14T13:07:00+05:30", session_id="s",
                      user_text="I'm from Uttarakhand, the pahadi gene. My girlfriend Shubha, I call her Tobu.")
    good = {"corpora": ["personalization"], "domain": "unknown", "trainable": True, "confidence": 0.9,
            "responds_to": "Q1", "rationale": "self-description",
            "knowledge": [{"type": "identity", "fact": "The owner is from Uttarakhand.",
                           "evidence": "I'm from Uttarakhand"},
                          {"type": "person", "fact": "The owner's girlfriend is Shubha, called Tobu.",
                           "evidence": "My girlfriend Shubha, I call her Tobu.", "person": "Shubha"}],
            "tension": None}
    v = validate_verdict(good, ctx, "claude/test")
    check("T1 a well-formed verdict validates", isinstance(v, Verdict), str(v))
    check("T2 facts carry KB type and tags",
          isinstance(v, Verdict) and v.knowledge[1].kb_type == "Semantic"
          and "person-shubha" in v.knowledge[1].kb_tags("claude"), str(v))
    bad = dict(good, knowledge=[{"type": "identity", "fact": "The owner lives in Sweden.",
                                 "evidence": "I live in Sweden"}])
    check("T3 evidence not in the owner's words rejects the verdict",
          isinstance(validate_verdict(bad, ctx, "x"), list))
    trivial = TurnContext(ts="t", session_id="s", user_text="do it")
    none_v = {"corpora": ["none"], "domain": "unknown", "trainable": False, "confidence": 0.9,
              "responds_to": "prior plan", "rationale": "ack", "knowledge": [], "tension": None}
    check("T4 a trivial turn: none, no knowledge", isinstance(validate_verdict(none_v, trivial, "x"), Verdict))
    check("T5 trainable with corpora none is rejected",
          isinstance(validate_verdict(dict(none_v, trainable=True), trivial, "x"), list))
    tens = dict(good, tension={"kind": "REVERSES", "prior_id": "429", "why": "reverses July call"})
    check("T6 tension against an offered prior validates",
          isinstance(validate_verdict(tens, ctx, "x", prior_ids=["429"]), Verdict))
    check("T7 tension against a prior not offered is rejected",
          isinstance(validate_verdict(tens, ctx, "x", prior_ids=["1"]), list))
    check("T8 the rule carries its version and every fact type",
          f"v{PARSE_RULE_VERSION}" in PARSE_RULE and all(t in PARSE_RULE for t in FACT_TYPES))
    print(f"  {8 - len(failed)}/8 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--print" in sys.argv:
        print(PARSE_RULE)
        sys.exit(0)
    sys.exit(_self_test())

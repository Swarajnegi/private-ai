#!/usr/bin/env python3
"""
build_sft_pairs.py — turn prose that is already question-shaped into SFT pairs.

LAYER: Tools (corpus assembly — the transform half of Stage 5.1.2 / 5.2.2)

Run with:
    python3 scripts/build_sft_pairs.py --dry-run    # counts + samples, writes nothing
    python3 scripts/build_sft_pairs.py              # writes sft_pairs.jsonl + heldout
    python3 scripts/build_sft_pairs.py --report     # summarise what already exists

=============================================================================
THE BIG PICTURE
=============================================================================

`js-learning/stage_5_specialists/SFT_SPEC.md` decided the format, the targets and
the sources on 2026-08-26, and then nothing built them: `sft_pairs.jsonl` did not
exist. An external review on 2026-09-09 measured the consequence — 100% of ~1.29 M
training tokens are raw `{"text": ...}`, so a QLoRA run would push the adapter
toward "continue this document" and away from "answer this person".

THE KEY INSIGHT IS THE SPEC'S, AND IT IS WHY THIS IS CHEAP: these pairs are
TRANSFORMED, NOT AUTHORED. `### heading` + body already IS question + answer. A
bolded lesson already IS the answer to an unasked question. The work is parsing,
not writing, so nothing here invents content the user did not produce.

=============================================================================
THE TRAP THIS FILE EXISTS TO NOT SPRING
=============================================================================

SFT_SPEC.md §5 warned, in 2026-08-26:

    "Do NOT build personalization pairs where the assistant side is MY writing.
     KB Cognitive_Pattern entries are observations ABOUT the user, authored by
     me. Training on them teaches the adapter to describe the user in the third
     person, not to be them."

The warning was scoped to pairs, and the RAW corpus walked into it anyway:
measured 2026-09-10, 101 of 246 `kb_identity`/`kb_judgment` records (41%) carry
third-person assistant voice ("PATTERN: ...", "the user prefixed it").

The obvious fix — purge them — is WRONG, and that is the whole design of the
`kb_verbatim` extractor below. 54% of those records EMBED a quoted utterance of
the user's own, and some of it is the best voice material in the repository:

    KB 499: "I know not the journey, nor my destination. What I know is how I
             wanna feel throughout and at the end."

Purging deletes that. So instead the record is SPLIT along the grammatical seam:

    my third-person framing  -> the USER turn   (context; loss-masked, unlearned)
    the user's quoted words  -> the ASSISTANT turn (the target; learned)

Right content, wrong form — so change the form. A pair is emitted ONLY when a
verbatim quote is actually present; no quote, no pair, never a paraphrase.

=============================================================================
THE FLOW
=============================================================================

STEP 1: Each extractor yields SFTPair objects from one source, carrying the
        source_path that makes every pair traceable (spec §2).
        |
STEP 2: The quality gate drops pairs whose answer states a conclusion with no
        mechanism — spec §4: "the answer must contain the REASON, not just the
        fact", because a fact-only answer trains the thing the user rejects.
        |
STEP 3: Dedup on a normalised prefix key; overlapping sources collide by design.
        |
STEP 4: Carve a ~10% held-out slice BEFORE writing (spec §7/§8.3), so Stage 5.3
        has something honest to measure against.
        |
STEP 5: Report filled-vs-target per bucket. Shortfalls are printed, never
        padded — a fabricated pair is worse than a missing one.
=============================================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.agent.provenance import ECHO_CEILING, EchoIndex  # noqa: E402
from jarvis_core.config import DATA_ROOT, JARVIS_ROOT, KB_PATH  # noqa: E402
from jarvis_core.specialists.text_hygiene import (  # noqa: E402
    MACHINE_TEXT, OWNER_PROSE, classify,
)

CORPUS_ROOT = Path(DATA_ROOT) / "training_corpus"
OUT_PATH = CORPUS_ROOT / "sft_pairs.jsonl"
HELDOUT_PATH = CORPUS_ROOT / "sft_pairs_heldout.jsonl"

_DE_LESSONS = Path(JARVIS_ROOT) / "knowledge" / "Data Engineering" / "Data_Engineering_Lessons.md"
_CLIENT_WORK = Path(JARVIS_ROOT) / "client_work"
_JARVIS_CORE = Path(JARVIS_ROOT) / "js-development" / "jarvis_core"
_LITERATURE = Path(JARVIS_ROOT) / "knowledge" / "literature"
_EXPERIENCE_MAP = Path(DATA_ROOT) / "experience_map.md"

# Spec §3. Deliberately at the low end of useful: the first run is a measurement.
TARGETS = {"engineer": 400, "personalization": 200}
HELDOUT_FRACTION = 0.10
_HELDOUT_SEED = 20260910          # fixed: the split must be reproducible across runs

_MIN_ANSWER_CHARS = 120
_MIN_VOICE_CHARS = 60      # a real utterance, not a fragment — voice runs shorter
_MIN_QUESTION_CHARS = 15
_MAX_ANSWER_CHARS = 6000

# Spec §4's bar is "the answer must contain the REASON, not just the fact".
#
# MY FIRST IMPLEMENTATION OF THIS WAS WRONG, AND WRONG IN THE EXACT WAY THIS
# REPO SPENT TODAY FIXING ELSEWHERE. It matched a list of connective words
# (because/since/reason/...) and rejected 106 of 152 curated DE lessons. Every
# sampled reject carried plain mechanism -- "guarantees they'll drift apart",
# "nobody does", "is a future regression", and one that literally opened
# "Reasons:" (which the regex missed anyway, because \breason\b does not match
# the plural). Rationale has an UNBOUNDED vocabulary; matching keywords against
# an unbounded space is the same defect as `nse` inside "respo-nse-" in
# capture.py, and it fails the same silent way.
#
# So the gate is STRUCTURAL instead. These sources are hand-written LESSON
# files: by construction each section already is a lesson with its reason. What
# genuinely does not belong is a stub, a reference table, or a bare name list.
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_MIN_SENTENCES = 2


def _looks_like_reference_table(text: str) -> bool:
    """True when the body is mostly a table or a bare list, not prose."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return True
    table_rows = len(_TABLE_ROW.findall(text))
    return table_rows >= max(3, len(lines) * 0.6)


@dataclass
class SFTPair:
    """One training pair. `messages` is the spec's format; the rest is traceability."""
    user: str
    assistant: str
    bucket: str                    # "engineer" | "personalization"
    source_type: str
    source_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> Dict[str, Any]:
        return {
            "messages": [
                {"role": "user", "content": self.user},
                {"role": "assistant", "content": self.assistant},
            ],
            "source_type": self.source_type,
            "source_path": self.source_path,
            "metadata": {"bucket": self.bucket, **self.metadata},
        }

    @property
    def cluster_key(self) -> str:
        """Normalised prefix key — overlapping sources collide by design (spec §7)."""
        basis = re.sub(r"\W+", " ", self.assistant.lower()).strip()[:220]
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


# =============================================================================
# Part 1: QUALITY GATE
# =============================================================================

def passes_quality(pair: SFTPair) -> Tuple[bool, str]:
    """(keep, reason-if-dropped). The gate is the spec's, not taste."""
    a, q = pair.assistant.strip(), pair.user.strip()
    if len(q) < _MIN_QUESTION_CHARS:
        return False, "question too short"
    # Defence in depth, added after q_003 (2026-09-11). The extractor that
    # produced the corrupted pairs now filters at source, but a target made of
    # machine text is wrong from EVERY source, so the check also lives here
    # where no future extractor can route around it. Only MACHINE_TEXT is
    # enforced globally: DIRECTIVE is a judgement about voice that is correct
    # for personalization targets and meaningless for an engineer lesson.
    verdict, reason = classify(a)
    if verdict == MACHINE_TEXT:
        return False, f"assistant target is machine text — {reason}"
    floor = _MIN_ANSWER_CHARS if pair.bucket == "engineer" else _MIN_VOICE_CHARS
    if len(a) < floor:
        return False, "answer too short"
    if len(a) > _MAX_ANSWER_CHARS:
        return False, "answer too long (likely an unsplit section)"
    if _looks_like_reference_table(a):
        return False, "body is a reference table, not reasoning"
    # The sentence floor is a MECHANISM proxy, so it belongs to engineer pairs
    # only. A personalization pair's target is VOICE: "I know not the journey,
    # nor my destination" is one clause and is exactly the material wanted.
    # Applying a mechanism test to voice deleted 36 good pairs on the first try.
    if pair.bucket == "engineer":
        if a.count(".") + a.count("!") + a.count("?") < _MIN_SENTENCES:
            return False, "single-clause answer — no room for a mechanism"
    return True, ""


# =============================================================================
# Part 2: ENGINEER EXTRACTORS (spec §4 — transformed, not authored)
# =============================================================================

def _split_md_sections(text: str, level: str = "### ") -> Iterator[Tuple[str, str]]:
    """(heading, body) for each section at the given heading level."""
    lines = text.splitlines()
    heading: Optional[str] = None
    body: List[str] = []
    for line in lines:
        if line.startswith(level):
            if heading is not None:
                yield heading, "\n".join(body).strip()
            heading, body = line[len(level):].strip(), []
        elif heading is not None:
            if line.startswith("## ") or line.startswith("# "):
                yield heading, "\n".join(body).strip()
                heading, body = None, []
            else:
                body.append(line)
    if heading is not None:
        yield heading, "\n".join(body).strip()


# q_003 issue 3: 254 of 324 engineer pairs opened with the SAME seven words, so
# the prompt distribution was a single template rather than a distribution. The
# rotation is keyed on a hash of the heading, not on a counter or RNG, so a
# given lesson always draws the same phrasing across machines and re-runs —
# reproducibility matters more here than novelty.
_QUESTION_TEMPLATES = (
    "What do I need to know about {h}?",
    "Walk me through {h}.",
    "Explain {h} — what actually happens, and why?",
    "What's the practical lesson on {h}?",
    "Tell me what matters about {h}.",
    "{H} — what should I keep in mind here?",
    "Why does {h} bite people, and what do I do about it?",
)


def _decapitalise(h: str) -> str:
    """Lowercase a leading ordinary word; leave acronyms alone.

    `"CSV Ingestion..."[0].lower() + [1:]` yields "cSV Ingestion", which is how
    q_003 came to quote a question about "cSV Ingestion Makes Everything
    STRING". An all-caps opening run is an acronym, not a capitalised sentence.
    """
    first = h.split(" ", 1)[0]
    if len(first) > 1 and first[:2].isupper():
        return h
    return h[0].lower() + h[1:]


def _as_question(heading: str) -> str:
    """A heading is an answer's title; make it the question it answers."""
    h = heading.strip().rstrip(".:").lstrip("#").strip()
    h = re.sub(r"^\d+[\.\)]\s*", "", h)
    if not h:
        return ""
    if h.endswith("?"):
        return h
    if re.match(r"^(how|why|what|when|where|which|who)\b", h, re.IGNORECASE):
        return h + "?"
    slot = int(hashlib.sha256(h.encode("utf-8")).hexdigest(), 16) % len(_QUESTION_TEMPLATES)
    lowered = _decapitalise(h)
    return _QUESTION_TEMPLATES[slot].format(h=lowered, H=h)


def extract_de_lessons() -> Iterator[SFTPair]:
    """`### lesson` -> question; body -> answer. Nearly 1:1 (spec §4)."""
    try:
        text = _DE_LESSONS.read_text(encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return
    for i, (heading, body) in enumerate(_split_md_sections(text)):
        if not body:
            continue
        yield SFTPair(
            user=_as_question(heading), assistant=body.strip(),
            bucket="engineer", source_type="sft_engineer",
            source_path=f"Data_Engineering_Lessons.md#{i}:{heading[:48]}",
            metadata={"origin": "transformed", "domain": "data_engineering"})


_BULLET_START = re.compile(r"^\s*[-*]\s+\*\*")
_BULLET_LESSON = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*[.:—-]?\s*(.*)$", re.DOTALL)
# A bolded run that is only a date is a journal header, not a lesson.
_DATE_ONLY = re.compile(r"^(?:\w{3,9}\s+\d{1,2}|\d{4}-\d{2}-\d{2})\s*$")


def _iter_bulleted_lessons(text: str) -> Iterator[Tuple[str, str]]:
    """(bolded claim, continuation) for each `- **claim** body` bullet.

    Two structural facts about this file, both learned by getting it wrong:
    it is a bulleted list rather than a heading tree (154 bolded lessons against
    6 `###` headings, so reading it as sections found 6), and MANY bolded claims
    WRAP ACROSS LINES -- the `**` opens on one line and closes two lines later.
    A per-line regex matched 93 of 154. So logical bullets are reassembled first,
    then matched.
    """
    blocks: List[str] = []
    current: List[str] = []
    for line in text.splitlines():
        if _BULLET_START.match(line):
            if current:
                blocks.append(" ".join(current))
            current = [line.strip()]
        elif current:
            if not line.strip() or line.startswith("#"):
                blocks.append(" ".join(current))
                current = []
            else:
                current.append(line.strip())
    if current:
        blocks.append(" ".join(current))

    for block in blocks:
        m = _BULLET_LESSON.match(block)
        if not m:
            continue
        claim, rest = m.group(1).strip(), m.group(2).strip()
        if _DATE_ONLY.match(claim):
            continue
        yield claim, rest


def extract_session_learnings() -> Iterator[SFTPair]:
    """A bolded claim IS an answer; the question is what it answers (spec §4)."""
    for path in sorted(_CLIENT_WORK.glob("*/SESSION_LEARNINGS.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        project = path.parent.name
        for i, (claim, body) in enumerate(_iter_bulleted_lessons(text)):
            yield SFTPair(
                user=_as_question(claim), assistant=f"{claim} {body}".strip(),
                bucket="engineer", source_type="sft_engineer",
                source_path=f"{project}/SESSION_LEARNINGS.md#{i}:{claim[:48]}",
                metadata={"origin": "transformed", "domain": "client_engineering"})


def extract_big_picture() -> Iterator[SFTPair]:
    """A module's THE BIG PICTURE section already explains why it exists (spec §4)."""
    for path in sorted(_JARVIS_CORE.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"THE BIG PICTURE\s*\n=+\s*\n(.*?)(?:\n=+\s*\n|\n\"\"\")",
                      text, re.DOTALL)
        if not m:
            continue
        body = m.group(1).strip()
        rel = path.relative_to(JARVIS_ROOT).as_posix()
        yield SFTPair(
            user=f"Why does {path.stem}.py exist in JARVIS, and what problem does it solve?",
            assistant=body, bucket="engineer", source_type="sft_engineer",
            source_path=f"{rel}#big_picture",
            metadata={"origin": "transformed", "domain": "jarvis_architecture"})


# =============================================================================
# Part 3: PERSONALIZATION EXTRACTORS (spec §5 — the assistant side must be THEIRS)
# =============================================================================

# An ATTRIBUTED quote: a marker naming the user's speech, then the quoted run.
#
# THE FIRST VERSION OF THIS WAS BADLY WRONG and produced 112 junk pairs that all
# passed the quality gate. It accepted any quoted-looking span, so the APOSTROPHE
# in "generator's yield" opened a quote and the pair began mid-word: "s yield
# (loading current document)". Worse, the captured text was technical KB prose,
# not the user's voice at all -- the exact opposite of what this extractor is for.
# The tell was in the report and I nearly missed it: 124 found, ZERO dropped.
#
# Requiring attribution collapses it to 12 entries. Twelve real utterances beat a
# hundred fabricated ones, and the honest count is the point of this whole file.
_ATTRIBUTED_QUOTE = re.compile(
    r"(?:VERBATIM|verbatim|user said|their words|user asked|user directed|"
    r"user wrote|in their own words|user's words)\s*[:\-—]?\s*"
    r"['\"“]((?:[^'\"”]|'(?=[a-z])){40,1200})", re.IGNORECASE)

# WAS 320, lowered to 150 on 2026-09-14. The old floor was doing filtering work
# that the filter could not do: with only an offset-zero word list guarding the
# extractor, length was the crude proxy for "probably a real turn". Now that
# `text_hygiene` rejects machine text on form and `provenance` rejects pasted
# replies on fact, length can go back to meaning what it says — long enough to
# carry a thought. Measured: 37 surviving turns at 320, 58 at 150, with the
# same two gates applied, so the floor alone was suppressing 21 clean pairs.
_MIN_EXPLANATION_CHARS = 150


# FIVE TEMPLATES OVER ~60 PAIRS MADE COLLISION STRUCTURAL, not accidental:
# check_pipeline flagged one prompt on 13 different answers. One input mapped
# to thirteen different targets teaches the model nothing about which to
# produce. Fourteen templates puts the expected reuse at ~4, under the bar.
#
# This is a mitigation, not a cure. The real fix is a prompt that was actually
# asked, which is what `extract_ui_sessions` provides — and why that extractor
# is registered ahead of this one.
_EXPLANATION_PROMPTS = (
    "Explain your own thinking on this, in your own words and at the length it deserves.",
    "What's your actual position here? Say it the way you'd say it, not the tidy version.",
    "Talk this through the way you'd talk it through out loud.",
    "Give me your reasoning on this — the whole shape of it, not a summary.",
    "How do you actually see this? Use your own words.",
    "Set out your thinking here, at whatever length it actually needs.",
    "What's the reasoning behind your view on this?",
    "Say what you actually think about this, not the diplomatic version.",
    "Walk me through how you arrived at this.",
    "What matters to you about this, and why?",
    "Lay out your position and the reasoning under it.",
    "How would you explain your thinking here to someone who disagreed?",
    "What's your read on this, in full?",
    "Put your own reasoning on this into words.",
)


def extract_user_explanations() -> Iterator[SFTPair]:
    """Long turns where the user EXPLAINS rather than asks (spec §5, 60 pairs).

    THE FILTER HERE WAS THE SUBJECT OF q_003 AND IT WAS BADLY INSUFFICIENT.
    It excluded interrogative and imperative openers by matching a word list at
    OFFSET ZERO, which meant "add a checklist" was caught and "also add a
    checklist" was not. Worse, it never asked whether the text was the user's
    PROSE at all: `user_text` is named for where text arrived, not who wrote it,
    so pasted shell transcripts, IDE context blocks and `<task-notification>`
    envelopes all became assistant targets. Measured against the 41 pairs this
    produced: 30 were corrupt.

    The judgement now lives in `specialists/text_hygiene.py`, which matches
    machine FORMS (closed grammars) rather than marker strings, and grades mood
    by a first/second-person ratio rather than a verb list. Validated at 41/41
    against the hand-labelled rows from that audit.
    """
    queue = Path(DATA_ROOT) / "observation_queue.jsonl"
    try:
        handle = queue.open("r", encoding="utf-8")
    except (OSError, FileNotFoundError):
        return
    records: List[Dict[str, Any]] = []
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # THE ONE PLACE THIS FILE MATERIALISES A SOURCE, and the reason is the echo
    # check rather than convenience: scoring a turn against EARLIER replies
    # requires timestamp order, and the queue is not guaranteed to be in it —
    # a backfilling adapter writes each turn's own timestamp, not ingestion
    # time (capture.py's `ts` note). Bounded by the capture queue, which is
    # append-only and currently ~1k records, so this is a real exception to the
    # lazy-pipeline rule and not a quiet erosion of it.
    records.sort(key=lambda r: str(r.get("ts", "")))
    echo = EchoIndex()

    for rec in records:
        text = str(rec.get("user_text", "")).strip()
        echoed = echo.add_turn(text, str(rec.get("assistant_summary", "")))
        if classify(text, min_chars=_MIN_EXPLANATION_CHARS)[0] != OWNER_PROSE:
            continue
        if text.count("?") > 2:          # mostly an interrogation, not a position
            continue
        if echoed > ECHO_CEILING:
            continue
        ts = str(rec.get("ts", ""))
        slot = int(hashlib.sha256(ts.encode("utf-8")).hexdigest(), 16)
        yield SFTPair(
            user=_EXPLANATION_PROMPTS[slot % len(_EXPLANATION_PROMPTS)],
            assistant=text[:_MAX_ANSWER_CHARS],
            bucket="personalization", source_type="sft_personalization",
            source_path=f"observation_queue.jsonl#{ts}",
            metadata={"origin": "authored_by_user", "form": "explanation",
                      "echo_fraction": round(echoed, 3)})


def extract_kb_verbatim() -> Iterator[SFTPair]:
    """The extraction that replaces the purge. See this module's header."""
    try:
        handle = Path(KB_PATH).open("r", encoding="utf-8")
    except (OSError, FileNotFoundError):
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = str(entry.get("content", ""))
            m = _ATTRIBUTED_QUOTE.search(content)
            if not m:
                continue
            quote = m.group(1).strip()
            framing = content[:m.start()].strip()
            if len(framing) < 40:
                continue
            eid = entry.get("id")
            ref = eid if isinstance(eid, int) else f"ts:{str(entry.get('timestamp',''))[:19]}"
            yield SFTPair(
                user=(f"Here is a situation from my own history. Respond the way I "
                      f"actually responded, in my own words.\n\n{framing[:1200]}"),
                assistant=quote,
                bucket="personalization", source_type="sft_personalization",
                source_path=f"kb#{ref}#verbatim",
                metadata={"origin": "extracted_verbatim", "kb_type": entry.get("type")})


_CONVERSATIONS = Path(DATA_ROOT) / "conversations"

# The UI writes `**Question 3:** …` after its acknowledgement of the previous
# answer. The acknowledgement is JARVIS's prose and must not become the prompt.
_QUESTION_MARKER = re.compile(r"\*\*Question\s*\d+\s*[:.]?\*\*\s*(.+?)\s*$", re.DOTALL)
# A prompt is a QUESTION, not a document. Without this the extractor also pairs
# "here is a 2,679-char status dump" with whatever the user typed next.
_MAX_QUESTION_CHARS = 600


def _extract_question(assistant_text: str) -> str:
    """The question JARVIS actually asked, or "" when the turn asked nothing."""
    marked = _QUESTION_MARKER.search(assistant_text)
    if marked:
        question = marked.group(1).strip()
    else:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", assistant_text) if p.strip()]
        question = paragraphs[-1] if paragraphs else ""
        if not question.rstrip().endswith("?"):
            return ""
    return question if 0 < len(question) <= _MAX_QUESTION_CHARS else ""


def extract_ui_sessions() -> Iterator[SFTPair]:
    """(the question JARVIS asked) -> (the user's answer). Spec §5's ideal shape.

    THE USER IS CURRENTLY ANSWERING 45 PERSONALIZATION QUESTIONS THROUGH THE
    JARVIS UI, and before this extractor existed those answers reached the
    corpus only through `extract_user_explanations`, which reads the capture
    queue and attaches the synthetic prompt "Explain your own thinking on
    this…". That threw away the better half of every pair: a deliberate Q&A
    session is ALREADY (prompt, target), with a real question and a real answer
    in the user's own voice. Nothing else in this file gets to start from that.

    Two gates, and both earn their place:
      * the prompt must parse as a QUESTION, which is what stops this pairing a
        long status answer with whatever the user happened to type next;
      * the answer must pass `text_hygiene` as owner prose, which is what drops
        the session's protocol-setting opener ("Alright Jarvis, ask me these
        questions one by one…") as the vocative directive it is.

    THE FLOOR IS `_MIN_VOICE_CHARS`, NOT `_MIN_EXPLANATION_CHARS`. The 150-char
    floor on the queue path is a proxy for substance, needed only because that
    path has no real prompt to judge the answer against. Here there is one, so
    a short answer is still a whole pair — "I was saying I'm calculative even
    when I shouldn't be" is 94 characters, is a genuine reply to a genuine
    question, and was being discarded as `too_thin`.
    """
    if not _CONVERSATIONS.is_dir():
        return
    for path in sorted(_CONVERSATIONS.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        turns: List[Dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                turns.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        for i in range(len(turns) - 1):
            if turns[i].get("role") != "assistant" or turns[i + 1].get("role") != "user":
                continue
            question = _extract_question(str(turns[i].get("content", "")))
            if not question:
                continue
            answer = str(turns[i + 1].get("content", "")).strip()
            if classify(answer, min_chars=_MIN_VOICE_CHARS)[0] != OWNER_PROSE:
                continue
            yield SFTPair(
                user=question,
                assistant=answer[:_MAX_ANSWER_CHARS],
                bucket="personalization", source_type="sft_personalization",
                source_path=f"conversations/{path.name}#turn{i + 1}",
                metadata={"origin": "authored_by_user", "form": "interview",
                          "ts": str(turns[i + 1].get("ts", ""))})


_MIN_PARAGRAPH_CHARS = 250


def extract_literature() -> Iterator[SFTPair]:
    """The published essays — the purest voice material available (spec §5).

    Emitted at TWO granularities, and the reason is that a whole `## ` section
    and one paragraph inside it teach different things. The section teaches how
    the user structures an argument; the paragraph teaches cadence at the scale
    the adapter actually generates at. Section-level alone yielded 18 pairs
    from the richest voice material in the repository, while 39 paragraphs of
    it sat unused.

    Overlap between the two levels is real and is handled where every other
    overlap in this file is handled — `cluster_key` dedups on the ANSWER, so a
    single-paragraph section collides with itself exactly once and the longer
    form wins. The two Napoleon files are near-duplicates of each other and
    collapse the same way; that is the dedup doing its job, not a bug.
    """
    if not _LITERATURE.exists():
        return
    for path in sorted(_LITERATURE.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title = path.stem.replace("_", " ").replace("-", " ").strip()
        for i, (heading, body) in enumerate(_split_md_sections(text, level="## ")):
            if len(body) < _MIN_ANSWER_CHARS:
                continue
            yield SFTPair(
                user=(f"Write in my own voice about this, from '{title}': {heading}"),
                assistant=body.strip()[:_MAX_ANSWER_CHARS],
                bucket="personalization", source_type="sft_personalization",
                source_path=f"knowledge/literature/{path.name}#{i}",
                metadata={"origin": "authored_by_user", "form": "essay"})

            for j, para in enumerate(re.split(r"\n\s*\n", body)):
                para = para.strip()
                if len(para) < _MIN_PARAGRAPH_CHARS or para.startswith("#"):
                    continue
                yield SFTPair(
                    user=(f"In my own voice, on '{heading}' from '{title}' — "
                          f"take the thought further."),
                    assistant=para[:_MAX_ANSWER_CHARS],
                    bucket="personalization", source_type="sft_personalization",
                    source_path=f"knowledge/literature/{path.name}#{i}p{j}",
                    metadata={"origin": "authored_by_user", "form": "essay_paragraph"})


def extract_experience_map() -> Iterator[SFTPair]:
    """Filled Notes cells are literally (prompt -> the user's own answer)."""
    try:
        text = _EXPERIENCE_MAP.read_text(encoding="utf-8", errors="replace")
    except (OSError, FileNotFoundError):
        return
    for i, raw in enumerate(text.splitlines()):
        if not raw.strip().startswith("|"):
            continue
        cells = [c.strip() for c in raw.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        subject, note = cells[0], cells[-1]
        # The user's own prose lives in the Notes column; guesses are marked and skipped.
        #
        # THE FLOOR WAS `_MIN_ANSWER_CHARS` (120) AND THAT WAS THE WRONG
        # CONSTANT — it is the ENGINEER floor, sized for a lesson that must
        # carry a mechanism. This bucket is voice, and `passes_quality` already
        # applies `_MIN_VOICE_CHARS` to it for exactly the reason recorded
        # there: an honest experience boundary is short by nature. "Haven't
        # gotten any situation where I would try out kafka or event hubs" is
        # 70 characters and is precisely the material that stops the adapter
        # claiming experience the user does not have. 79 such rows were being
        # dropped by a threshold borrowed from the other bucket.
        if "GUESS:" in note or len(note) < _MIN_VOICE_CHARS or "---" in subject:
            continue
        subject = re.sub(r"\*+", "", subject).strip()
        if not subject or subject.lower() in ("#", "project", "technology", "scenario"):
            continue
        yield SFTPair(
            user=f"What is your actual experience with {subject}? Be honest about the limits.",
            assistant=note, bucket="personalization", source_type="sft_personalization",
            source_path=f"experience_map.md#L{i + 1}",
            metadata={"origin": "authored_by_user", "form": "self_assessment"})


# =============================================================================
# Part 4: ASSEMBLY
# =============================================================================

EXTRACTORS = (
    ("de_lessons", extract_de_lessons),
    ("session_learnings", extract_session_learnings),
    ("big_picture", extract_big_picture),
    ("kb_verbatim", extract_kb_verbatim),
    # BEFORE user_explanations, and the order is load-bearing. Dedup is global
    # and keyed on the ANSWER (`SFTPair.cluster_key`), so the first extractor to
    # emit a given answer wins. Both of these see the same UI turns — this one
    # carries the question JARVIS actually asked, the other substitutes a
    # generic prompt. Swap the order and every interview pair silently loses
    # its real question to a synthetic one.
    ("ui_sessions", extract_ui_sessions),
    ("user_explanations", extract_user_explanations),
    ("literature", extract_literature),
    ("experience_map", extract_experience_map),
)


def build() -> Tuple[List[SFTPair], Dict[str, Dict[str, int]]]:
    """(kept pairs, per-extractor stats). Dedup is global across sources."""
    kept: List[SFTPair] = []
    seen: set = set()
    stats: Dict[str, Dict[str, int]] = {}
    for name, fn in EXTRACTORS:
        s = {"found": 0, "dropped_quality": 0, "dropped_dup": 0, "kept": 0}
        for pair in fn():
            s["found"] += 1
            ok, _ = passes_quality(pair)
            if not ok:
                s["dropped_quality"] += 1
                continue
            key = pair.cluster_key
            if key in seen:
                s["dropped_dup"] += 1
                continue
            seen.add(key)
            kept.append(pair)
            s["kept"] += 1
        stats[name] = s
    return kept, stats


def carve_heldout(pairs: List[SFTPair]) -> Tuple[List[SFTPair], List[SFTPair]]:
    """Stratified ~10% held-out slice, carved BEFORE training (spec §7/§8.3).

    Stratified by bucket so the eval set cannot end up all-engineer, and seeded
    so the split is identical on both machines and across re-runs.
    """
    rng = random.Random(_HELDOUT_SEED)
    train: List[SFTPair] = []
    held: List[SFTPair] = []
    for bucket in ("engineer", "personalization"):
        group = [p for p in pairs if p.bucket == bucket]
        rng.shuffle(group)
        cut = int(len(group) * HELDOUT_FRACTION)
        held.extend(group[:cut])
        train.extend(group[cut:])
    return train, held


def write_jsonl(pairs: List[SFTPair], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for p in pairs:
            fh.write(json.dumps(p.to_record(), ensure_ascii=False) + "\n")
    tmp.replace(path)


def report(pairs: List[SFTPair], stats: Dict[str, Dict[str, int]]) -> None:
    print("=" * 74)
    print("  SFT pair extraction")
    print("=" * 74)
    print(f"  {'extractor':<20} {'found':>7} {'quality':>8} {'dup':>6} {'kept':>7}")
    print("  " + "-" * 51)
    for name, s in stats.items():
        print(f"  {name:<20} {s['found']:>7} {s['dropped_quality']:>8} "
              f"{s['dropped_dup']:>6} {s['kept']:>7}")
    print()
    for bucket, target in TARGETS.items():
        got = sum(1 for p in pairs if p.bucket == bucket)
        pct = got / target if target else 0
        flag = "OK" if got >= target * 0.9 else "SHORT"
        print(f"  {bucket:<18} {got:>5} / {target}   ({pct:.0%})  {flag}")
    total = len(pairs)
    chars = sum(len(p.user) + len(p.assistant) for p in pairs)
    print(f"  {'TOTAL':<18} {total:>5} pairs, ~{chars:,} chars, ~{chars // 4:,} tokens")
    print()
    short = [b for b, t in TARGETS.items()
             if sum(1 for p in pairs if p.bucket == b) < t * 0.9]
    if short:
        print(f"  SHORTFALL in: {', '.join(short)}.")
        print("  Not padded. The spec's remaining sources for these are")
        print("  decision-explanation sessions (spec §6) and hand-authored pairs —")
        print("  both require the user, and a fabricated pair is worse than a missing one.")
    print("=" * 74)


def main() -> int:
    p = argparse.ArgumentParser(description="Build SFT pairs from already-question-shaped prose.")
    p.add_argument("--dry-run", action="store_true", help="counts + samples, write nothing")
    p.add_argument("--report", action="store_true", help="summarise the existing sft_pairs.jsonl")
    p.add_argument("--samples", type=int, default=0, help="print N sample pairs per bucket")
    args = p.parse_args()

    if args.report:
        if not OUT_PATH.exists():
            print(f"no {OUT_PATH.name} yet — run without --report to build it")
            return 1
        recs = [json.loads(l) for l in OUT_PATH.open(encoding="utf-8") if l.strip()]
        from collections import Counter
        print(f"{len(recs)} pairs in {OUT_PATH.name}")
        for k, v in Counter(r["metadata"].get("bucket") for r in recs).most_common():
            print(f"  {k:<20} {v}")
        return 0

    pairs, stats = build()
    report(pairs, stats)

    if args.samples:
        for bucket in TARGETS:
            print(f"\n--- sample {bucket} pairs ---")
            for pair in [x for x in pairs if x.bucket == bucket][:args.samples]:
                print(f"\n  [{pair.source_path}]")
                print(f"  USER      : {pair.user[:220]}")
                print(f"  ASSISTANT : {pair.assistant[:260]}")

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return 0

    train, held = carve_heldout(pairs)
    write_jsonl(train, OUT_PATH)
    write_jsonl(held, HELDOUT_PATH)
    print(f"\n  wrote {len(train)} -> {OUT_PATH.name}")
    print(f"  wrote {len(held)} -> {HELDOUT_PATH.name}  (held out BEFORE training, seed "
          f"{_HELDOUT_SEED} so the split is reproducible)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

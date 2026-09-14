#!/usr/bin/env python3
"""
text_hygiene.py — did the OWNER write this, or did a machine emit it?

LAYER: Specialists (Corpus Assembly)

Run with:
    python3 -m jarvis_core.specialists.text_hygiene      # smoke tests

=============================================================================
THE BIG PICTURE
=============================================================================

`observation_queue.jsonl`'s `user_text` field is named for where the text
ARRIVED, not for who WROTE it. Everything the user submits lands there: prose
they typed, yes — but also terminal transcripts they pasted, IDE context the
editor injected, `<task-notification>` blocks, slash-command templates, and
job descriptions copied off LinkedIn.

That distinction did not matter while the corpus was raw `{"text": ...}`
pretraining blobs. It became load-bearing the moment `build_sft_pairs.py`
started using `user_text` as an ASSISTANT TARGET — because with loss masking
on assistant tokens, a pasted shell transcript in the target teaches the
adapter to emit `swara_unix@HRM5472-NEW:~/work/JARVIS$` when asked to reason.

Antigravity's q_003 audit (2026-09-11) caught this. Measured against the 41
explanation-form pairs then in `sft_pairs.jsonl`, only 11 were the owner's
own reasoning. The other 30 were machine text or instructions aimed at the
assistant.

=============================================================================
WHY THIS IS FORM-MATCHING AND NOT A BLOCKLIST
=============================================================================

The obvious fix — and the one q_003 proposed — is to reject on marker strings:
`swara_unix@`, `(.venv)`, `<task-notification>`. That is a blocklist over an
OPEN set, and this repository has now been burned by exactly that shape three
times:

  * `capture.py` matched `nse` and hit the middle of "respo-NSE-"
  * `build_sft_pairs.passes_quality` matched connective words to detect
    rationale and rejected 106 of 152 good lessons (see that file's header)
  * `reconcile_codex_memory.py` approximated five known placeholder strings
    with a regex and missed two of them (KB 584)

A blocklist here breaks on the first new hostname, the first `zsh` prompt, the
first envelope tag a vendor renames. So the gate matches FORMS instead, and the
distinction that makes this safe rather than clever is:

    A shell prompt, an XML envelope, a Python traceback, a markdown table row,
    a progress bar and a URL are CLOSED GRAMMARS. They have specifications.
    Matching them is recognition, not guessing.

    "Trivial", "administrative", "rationale" and "instruction" are OPEN
    VOCABULARIES. Matching those with patterns is the defect above.

Where an open vocabulary is genuinely unavoidable — telling an instruction from
an explanation — this uses a GRAMMATICAL ratio (first person vs second person,
terminal mood) rather than a verb list, because pronouns are a closed class and
verbs are not.

=============================================================================
THE FLOW
=============================================================================

STEP 1: `machine_line_fraction` classifies each LINE against the closed
        grammars above. Density, not presence — quoting one command inside a
        paragraph of reasoning is normal and must survive.
        |
STEP 2: Whole-text envelope checks: a document pasted whole announces itself
        (leading markdown heading, a tag that opens and closes the text,
        non-web link schemes from IDE plugin pickers).
        |
STEP 3: Mood: a turn that names the assistant in the vocative, or ends on a
        question, or is grammatically second-person, is the user DIRECTING
        rather than explaining. Its text cannot serve as an assistant target.
        |
STEP 4: `classify` returns a verdict plus the reason, so every rejection is
        reportable and the caller never has to guess why a record vanished.
=============================================================================
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

__all__ = [
    "classify",
    "is_owner_prose",
    "machine_line_fraction",
    "OWNER_PROSE",
    "MACHINE_TEXT",
    "DIRECTIVE",
    "TOO_THIN",
]

OWNER_PROSE = "owner_prose"
MACHINE_TEXT = "machine_text"
DIRECTIVE = "directive"
TOO_THIN = "too_thin"

# Closed grammars. Each has a specification somewhere outside this repo; none
# is a guess about what "machine output usually looks like".
_MACHINE_LINE_FORMS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("shell_prompt", re.compile(r"^\(?[\w.+-]*\)?\s*[\w.-]+@[\w.-]+:\S*\s*[$#]")),
    # The POSIX prompt above was the only one until 2026-09-14, when the corpus
    # grew its first Windows-side turns and six PowerShell transcripts walked
    # straight through. Codex and Antigravity both run on the Windows laptop, so
    # this is now the more likely of the two.
    ("powershell_prompt", re.compile(r"^\s*(?:PS\s+)?[A-Za-z]:\\\S*>|^\s*>\s+>")),
    ("windows_banner", re.compile(r"^\s*(?:Windows PowerShell|Copyright \(C\) Microsoft)")),
    # Source code pasted for review. Each alternative is a Python/JS statement
    # form, not a guess about what code "looks like".
    ("source_statement", re.compile(
        r"^\s*(?:import|from)\s+[\w.]+|"
        r"^\s*(?:def|class)\s+\w+|"
        r"^\s*(?:return|yield|raise|elif|else|try|except|finally|with|while|for|if)\b[^.!?]*:\s*$|"
        r"^\s*[\w.\[\]\"']+\s*=\s*\S|"
        r"^\s*[\)\]\}],?;?\s*$")),
    ("markup_line", re.compile(r"^\s*</?[A-Za-z][\w:.-]*(?:\s[^>]*)?/?>\s*$")),
    ("traceback", re.compile(r'^Traceback \(most recent call last\)|^\s+File "[^"]+", line \d+')),
    ("log_level", re.compile(r"^\s*(?:WARNING|ERROR|INFO|DEBUG|CRITICAL|Warning|Error)\b\s*:")),
    ("progress_bar", re.compile(r"\d+%\|[^|]*\||\d+(?:\.\d+)?it/s\]")),
    ("repl_sigil", re.compile(r"^\s*(?:\$|>>>|\.\.\.)\s")),
    ("command_invocation", re.compile(
        r"^\s*(?:python3?|pip3?|git|npm|npx|node|bash|sh|cd|export|source|sudo|"
        r"curl|wget|docker|make|pytest|ls|cat|grep)\s+\S")),
    ("bare_flag", re.compile(r"^\s*--[\w-]+[= ]")),
    ("table_row", re.compile(r"^\s*\|.*\|\s*$")),
    ("bare_url", re.compile(r"^\s*https?://\S+\s*$")),
    ("key_value_log", re.compile(r"^\s*\[[\w.:+-]+\]\s+\w+")),
)

# A leading markdown heading means a DOCUMENT was pasted. People do not open a
# typed chat turn with `## `.
_LEADING_HEADING = re.compile(r"^\s*#{1,6}\s+\S")

# A tag that opens the text and closes somewhere inside it is an envelope the
# toolchain wrapped around content — not something a person typed.
_ENVELOPE_OPEN = re.compile(r"^\s*<([A-Za-z][\w:.-]*)\s*>")

# Markdown links whose scheme is NOT the web are emitted by IDE/plugin pickers
# (`plugin://…`, `C:\…`), never typed as prose.
_NON_WEB_LINK = re.compile(r"\]\((?:(?!https?:)[A-Za-z][\w+.-]*://|[A-Za-z]:\\)")

# Pronouns are a CLOSED class, which is what makes this ratio legitimate where a
# verb list would not be.
_FIRST_PERSON = re.compile(r"\b(?:i|me|my|mine|myself|i'?m|i'?ve|i'?d|i'?ll)\b", re.IGNORECASE)
_SECOND_PERSON = re.compile(r"\b(?:you|your|yours|yourself|you'?re|you'?ve|you'?ll)\b",
                            re.IGNORECASE)

# Naming the assistant in the vocative: the turn is addressed TO it.
_VOCATIVE_ADDRESSEE = re.compile(
    r"^\W{0,4}(?:hey|hi|hello|ok(?:ay)?|so|yo|alright|right|now)?[\s,]{0,3}"
    r"\b(?:jarvis|claude|codex|antigravity)\b[\s,.:!]", re.IGNORECASE)

# Opening on a long quoted run means the user is REACTING to pasted material.
# Such a turn is often mixed — assistant prose quoted at the head, the user's
# own voice at the tail — and the tail is genuinely good. It is dropped anyway:
# splitting on the closing quote would salvage it, but a target whose first
# sentence belongs to someone else teaches the wrong opening, and the spec's
# standing rule is that a missing pair beats a contaminated one.
_QUOTED_OPENING = re.compile(r'^["“][^"”]{120,}["”]', re.DOTALL)

# ---------------------------------------------------------------------------
# THE ONE BOUNDED HEURISTIC IN THIS MODULE, LABELLED AS SUCH.
#
# Everything above matches a closed grammar. Imperative mood does not have one
# without a part-of-speech tagger, because English imperatives are bare verbs
# and the verb lexicon is open. So this is an explicit, finite list of the
# directive openers actually OBSERVED in this corpus — it will miss new ones,
# and that is a known limit rather than a claim.
#
# The real defect it repairs is not the list but the ANCHORING: the original
# `_NOT_EXPLANATORY` in build_sft_pairs.py matched only at offset 0, so any
# prefix at all defeated it. "add a checklist" was caught; "also add a
# checklist" and "1. add a checklist" sailed through. A leading list marker or
# discourse particle is now consumed before the verb is tested.
# ---------------------------------------------------------------------------
_IMPERATIVE_OPENER = re.compile(
    r"^\W{0,3}"
    r"(?:\d+[.)]\s*)?"                                     # "1. " list marker
    r"(?:(?:also|and|so|then|now|ok(?:ay)?|alright|right|plus|"
    r"first|next|finally|please|just|fine)[\s,]+)*"        # discourse particles
    r"\b(?:explain|tell|give|show|build|make|create|write|add|fix|run|go|"
    r"forget|let'?s|lets|read|check|update|remove|delete|change|use|put|take|"
    r"keep|start|stop|continue|do|don'?t|generate|implement|refactor|review|"
    r"list|find|search|look|open|close|send|push|commit|merge|install)\b",
    re.IGNORECASE)

# Wh-words and auxiliaries ARE a closed class in English — unlike the verb list
# above, this one is complete. A turn that opens by asking is a question.
_INTERROGATIVE_OPENER = re.compile(
    r"^\W{0,3}(?:\d+[.)]\s*)?"
    r"(?:(?:also|and|so|then|now|ok(?:ay)?|alright|right|hey|but)[\s,]+)*"
    r"\b(?:what|how|why|when|where|which|who|whose|whom|"
    r"is|are|was|were|am|do|does|did|can|could|shall|should|will|would|may|might|must|have|has|had)"
    r"\b\s+\w", re.IGNORECASE)

# ---------------------------------------------------------------------------
# DECISIVE vs DENSITY — the distinction that "density, not presence" got wrong.
#
# Density alone failed on a real row: a 90-line pasted terminal session scored
# 0.07 because 84 of its lines were the MODEL's prose reply. The prompts were a
# rounding error in their own transcript.
#
# The repair is that these forms are not evidence to be weighed, they are proof.
# There is no way for a line beginning `user@host:~$` or `PS C:\>` to appear in
# prose someone typed; it can only have been pasted. The density rule stays for
# forms that DO occur legitimately — a table in a design note, a command named
# on its own line — where one occurrence must not condemn the whole turn.
# ---------------------------------------------------------------------------
_DECISIVE_FORMS = frozenset({
    "shell_prompt", "powershell_prompt", "windows_banner", "traceback", "progress_bar",
})

_MACHINE_LINE_CEILING = 0.10
_MIN_FIRST_PERSON = 2
# A turn that lands on a question but carries many declarative sentences first
# is still the user's position with a question appended. Only a turn that is
# MOSTLY setup for its question is a question turn.
_MIN_DECLARATIVES_TO_OUTWEIGH_QUESTION = 5


def machine_line_fraction(text: str) -> Tuple[float, Dict[str, int]]:
    """(fraction of non-blank lines matching a machine grammar, per-form counts)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return 1.0, {}
    counts: Dict[str, int] = {}
    hits = 0
    for line in lines:
        for name, pattern in _MACHINE_LINE_FORMS:
            if pattern.search(line):
                counts[name] = counts.get(name, 0) + 1
                hits += 1
                break
    return hits / len(lines), counts


def _ends_on_question(text: str) -> bool:
    """True when the turn's final sentence is interrogative."""
    tail = text.rstrip()[-400:]
    for char in reversed(tail):
        if char in ".!?":
            return char == "?"
        if not char.isspace() and char not in "\"')]}»”’*_`":
            return False
    return False


def _is_question_turn(text: str) -> bool:
    """A turn whose PURPOSE is to ask: it ends on a question and says little else."""
    if not _ends_on_question(text):
        return False
    declaratives = text.count(".") + text.count("!")
    return declaratives < _MIN_DECLARATIVES_TO_OUTWEIGH_QUESTION


def classify(text: str, min_chars: int = 0) -> Tuple[str, str]:
    """(verdict, reason). Verdict is one of the four module constants."""
    stripped = text.strip()
    if len(stripped) < min_chars:
        return TOO_THIN, f"under {min_chars} chars"
    if not stripped:
        return TOO_THIN, "empty"

    fraction, counts = machine_line_fraction(stripped)
    decisive = sorted(_DECISIVE_FORMS.intersection(counts))
    if decisive:
        return MACHINE_TEXT, f"contains {counts[decisive[0]]}x {decisive[0]} — a pasted transcript"
    if fraction > _MACHINE_LINE_CEILING:
        worst = max(counts, key=counts.get) if counts else "machine_line"
        return MACHINE_TEXT, f"{fraction:.0%} machine lines (mostly {worst})"

    if _LEADING_HEADING.match(stripped):
        return MACHINE_TEXT, "opens with a markdown heading — a pasted document"

    envelope = _ENVELOPE_OPEN.match(stripped)
    if envelope and f"</{envelope.group(1)}>" in stripped:
        return MACHINE_TEXT, f"wrapped in a <{envelope.group(1)}> envelope"

    if _NON_WEB_LINK.search(stripped):
        return MACHINE_TEXT, "contains an IDE/plugin link, not typed prose"

    if _QUOTED_OPENING.match(stripped):
        return MACHINE_TEXT, "opens by quoting pasted material"

    if _VOCATIVE_ADDRESSEE.match(stripped):
        return DIRECTIVE, "addresses the assistant by name"

    if _IMPERATIVE_OPENER.match(stripped):
        return DIRECTIVE, "opens in the imperative — an instruction, not a position"

    if _INTERROGATIVE_OPENER.match(stripped):
        return DIRECTIVE, "opens by asking — a question, not a position"

    first = len(_FIRST_PERSON.findall(stripped))
    second = len(_SECOND_PERSON.findall(stripped))
    if first < _MIN_FIRST_PERSON:
        return DIRECTIVE, f"only {first} first-person token(s) — not the user's own position"
    if second > first:
        return DIRECTIVE, f"second person ({second}) outweighs first ({first}) — an instruction"

    if _is_question_turn(stripped):
        return DIRECTIVE, "ends on a question with little else — asking, not explaining"

    return OWNER_PROSE, ""


def is_owner_prose(text: str, min_chars: int = 0) -> bool:
    """True when the text is safe to use as an ASSISTANT TARGET in the user's voice."""
    return classify(text, min_chars=min_chars)[0] == OWNER_PROSE


def corpus_admits(text: str, min_chars: int = 100) -> Tuple[bool, str]:
    """(keep, reason-if-dropped) for a RAW corpus record — a weaker bar than a pair.

    DIRECTIVE is deliberately admitted here and rejected for SFT targets, and
    the asymmetry is the point. "just store it, make this permanent" is an
    instruction, so it cannot be an assistant target — but it is unmistakably
    how this user writes, which is exactly what a voice corpus is for. Only
    text the user did not compose is wrong at both bars.
    """
    verdict, reason = classify(text, min_chars=min_chars)
    if verdict in (MACHINE_TEXT, TOO_THIN):
        return False, reason
    return True, ""


# =============================================================================
# Smoke tests — the fixture is REAL data, hand-labelled from the q_003 audit.
# =============================================================================

def _smoke() -> int:
    """Every case below is a verbatim prefix of a row that reached sft_pairs.jsonl."""
    passed: List[str] = []
    failed: List[str] = []

    def check(name: str, got, want) -> None:
        (passed if got == want else failed).append(
            f"{name}: got {got!r}, want {want!r}" if got != want else name)

    machine = [
        ("T1 shell transcript",
         "swara_unix@HRM5472-NEW:~/work/JARVIS$  source /home/swara_unix/work/JARVIS/"
         ".venv/bin/activate\n(.venv) swara_unix@HRM5472-NEW:~/work/JARVIS$ python3 "
         "js-development/jarvis_core/brain/orchestrator.py --new\nI think this is fine"),
        ("T2 task-notification envelope",
         "<task-notification>\n<task-id>w19fqc91s</task-id>\n<output-file>/tmp/x</output-file>\n"
         "</task-notification>"),
        ("T3 ide_opened_file envelope",
         "<ide_opened_file>The user opened the file /home/swara_unix/work/JARVIS/SDP_Syntax.py "
         "in the IDE. This may or may not be related to my current task.</ide_opened_file>"),
        ("T4 pasted IDE context document",
         "# Context from my IDE setup:\n\n## Active file: dadfinanceapp/.gitignore\n\n"
         "## Open tabs:\n- .gitignore: dadfinanceapp/.gitignore\nI want to know about my app"),
        ("T5 pasted AGENTS.md",
         "# AGENTS.md instructions for E:\\J.A.R.V.I.S\n\n<INSTRUCTIONS>\n"
         "# JARVIS — Codex Operating Context\nI am reading my own file here</INSTRUCTIONS>"),
        ("T6 markdown table paste",
         "| workflow_name | source_system | status |\n| --- | --- | --- |\n"
         "| wf_1 | system_a | ok |\n| wf_2 | system_b | ok |\nI need my table explained"),
        ("T7 plugin-picker markup",
         "[@Taste](plugin://engineering-suite-taste@openai-curated-remote) I want my UI "
         "to look like the reference I gave you, and I think my taste is decent here"),
        ("T8 HF warning + progress bar",
         "Warning: You are sending unauthenticated requests to the HF Hub.\n"
         "Loading weights: 100%|##########| 103/103 [00:00<00:00, 1909.01it/s]\n"
         "I ran my index and it worked"),
        ("T9 bare url",
         "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fwww.databricks.com%2Fblog\n"
         "I want my summary of this"),
    ]
    for name, text in machine:
        check(name, classify(text)[0], MACHINE_TEXT)

    directive = [
        ("T10 vocative — hey Jarvis",
         "hey Jarvis, I just learnt some things in my current BUPA project which i need "
         "you to add in my data engg project learnings like you did for my previous one"),
        ("T11 vocative — Hey, jarvis.",
         "Hey, jarvis.\nRead this. I am specifically concerned with the pre-req section. "
         "Out of everything you know from my SDP project, what pre-reqs did I miss"),
        ("T12 no first person at all",
         "1. The Hearth (jarvis_core/serve/) is an always-on ASGI daemon that owns state "
         "and handles background memory consolidation on a fixed schedule for the system."),
        ("T13 second person outweighs first",
         "Fine do one thing, include all this too in the doc so both codex and antigravity "
         "can read it independently, and make sure you tell them what you expect from you."),
        ("T14 ends on a question",
         "forget this. If I head into an interview with companies like Atlassian and they "
         "ask me in their systems design round about warehousing, what should I say?"),
        ("T15 job description paste — no first person",
         "Required Skills\n1-4 years of experience in Data Engineering.\nStrong hands-on "
         "experience with Databricks Notebooks.\nProficiency in Python for data processing."),
        # T26-T28 are the anchoring bug: each was defeated by a leading prefix.
        ("T26 imperative behind a discourse particle",
         "also add that each roadmap html must have a checklist for individual topics "
         "that I can check off indicating that I'm confident about that topic."),
        ("T27 imperative behind a list marker",
         "1. explain this more, briefly then build\n2. i dont work on the personal laptop "
         "for the last 8 weeks so dont worry about my setup there"),
        ("T28 bare imperative opener",
         "go through the entire jarvis repo and plan out how the application connectivity "
         "part will work. I mean the way all the claude code chats are linked to my repo."),
    ]
    for name, text in directive:
        check(name, classify(text)[0], DIRECTIVE)

    owner = [
        ("T16 voice — what pulls me",
         "nope, none of these pull me. What pulls me is how one man holds so much weight "
         "that it shifts and moves empires, how one man's ambition could shape history."),
        ("T17 autobiography",
         "I was placed from campus hiring right (feb, 2025), but from the 10 people who "
         "got recruited, me and one of my friends who live with me now got interviewed."),
        ("T18 aspiration",
         "nice, i am both excited and nervous just thinking about the day when my final "
         "jarvis is finally implemented everywhere. I open my phone in the morning and it "
         "already knows what I need."),
        ("T19 position with reasoning",
         "I believe we must train the main model, the orchestrator, on my personal data "
         "and on my cognitive profile. The orchestrator is a router for sure but it is "
         "also the thing I actually talk to."),
        ("T20 correction with reasoning",
         "no, these fixes are also focused on narrow problem solving, we need a solution "
         "that will generally make jarvis smarter for any kind of messy workspace I throw "
         "at it, not just the one I showed you."),
        ("T21 one quoted command inside reasoning survives",
         "I ran `python3 scripts/index_memory.py` last night and I think the result tells "
         "me my assumption was wrong. My mental model had the index rebuilding itself."),
    ]
    for name, text in owner:
        check(name, classify(text)[0], OWNER_PROSE)

    # T29 is the rule that cost two good pairs before it was bounded: a long
    # reasoning turn that happens to END on a question is still reasoning.
    check("T29 long reasoning ending on a question survives",
          classify(
              "nice, i am both excited and nervous thinking about the day my jarvis is "
              "implemented everywhere. I open my phone and it already knows my day. "
              "I have wanted this since I was a kid. My own version of it, anyway. "
              "I think the hard part is the ambient bit, not the model. "
              "Does that match how you see my roadmap?")[0], OWNER_PROSE)
    check("T30 short setup for a question is a question turn",
          classify("forget this. If I head into an interview and they ask me about "
                   "warehousing in my systems design round, what should I say?")[0], DIRECTIVE)
    check("T31 turn opening on quoted material",
          classify('"Say you ask the future Electrician specialist for the current-limiting '
                   'resistor value for a laser diode. The formula it learned is real and '
                   'correct." and that is the bit I keep coming back to, because my whole '
                   'point is that it still does not know my diode.')[0], MACHINE_TEXT)
    # T32 is the density bug, locked down. This is a real shape: a pasted
    # session whose prompts are outnumbered ~15:1 by the model's own reply.
    _diluted = ("PS E:\\J.A.R.V.I.S> .\\.venv\\Scripts\\python.exe scripts\\jarvis_client.py\n"
                + "\n".join(f"This is line {n} of a long prose answer about my project "
                            f"and what I asked it to do." for n in range(40)))
    check("T32 one prompt in a diluted transcript is still decisive",
          classify(_diluted)[0], MACHINE_TEXT)
    check("T33 posix prompt is decisive too",
          classify("swara_unix@box:~/work$ ls\n"
                   + "\n".join(f"I wrote line {n} about my own reasoning here."
                               for n in range(40)))[0], MACHINE_TEXT)
    check("T22 min_chars floor", classify("I am short and mine.", min_chars=320)[0], TOO_THIN)
    frac, counts = machine_line_fraction("hello there\nswara_unix@box:~$ ls\nmore prose here")
    check("T23 fraction is density not presence", round(frac, 2), 0.33)
    check("T24 form is named", "shell_prompt" in counts, True)
    check("T25 empty text is not owner prose", is_owner_prose(""), False)

    print("=" * 70)
    print("  text_hygiene smoke tests")
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

"""
episode_index.py — the episode INDEX over the verbatim store (Context Store, Layer 1).

LAYER: Memory (Context Store — retrieval projection)

Import with:
    from jarvis_core.memory.episode_index import (
        EpisodeIndex, SearchResult, parse_time_range, TimeRange,
        queue_to_turn, backfill_provenance, fact_source_fields, EMBEDDERS,
    )

Run with:
    cd js-development && PYTHONPATH=. python -m jarvis_core.memory.episode_index   # hermetic self-test

=============================================================================
THE BIG PICTURE
=============================================================================

Layer 0 (memory/episode_store.py) keeps every session verbatim. Nothing can
FIND anything in it: 72K events, 520 MB of text. This module is the finding
half, and it is a PROJECTION — rebuildable from the store, the KB and a few
canon files, never tracked (the FTS file is gitignored; the vectors live in
the machine-local chromadb/).

What a retrieval unit is, and why:

  exchange     one per owner turn: the owner's message(s) + every assistant
               message and reasoning block + a compact list of the tool calls
               in between (name + input). An answer is only meaningful next
               to the question that produced it, so they are one unit.
  tool_call    a tool input too long to list inline (a Write of a whole file)
               — the exchange names it and points here.
  tool_result  every tool output, whole.
  compaction   the host's compaction summaries / replacement histories.
  kb / doc     KB entries, and sections of the canon files (personal_life.md,
               cognitive_profile.md, the rules, the finance strategy), so
               recall covers FACTS as well as episodes.
  queue        capture rows whose session is not in this machine's store
               (the other laptop's sessions, until its shards arrive).

NOTHING IS CUT. A unit longer than the embedder's window is split into
overlapping windows by the embedder's OWN tokenizer (character offsets from
the token stream), so every character sits in at least one window and no
window is ever silently truncated by the model. Role=system bookkeeping
events (token reminders, tool listings, session meta) are not indexed; that
is a stated selection, counted in status(), and every such event stays in
the store.

Each unit carries a CONTEXTUAL PREFIX (Anthropic's contextual retrieval)
before it is embedded: host, date, session title / chat label, the parse
rule's responds_to for the turn, and the distilled KB facts whose evidence
quote came from that turn. No LLM call is needed: all of it already exists.

Search = RRF(dense, FTS5 bm25, and both again restricted to the query's time
range when one is parsed) -> optional cross-encoder rerank -> neighbours.
Results are pointers (unit_id + store turn ids); read_unit() returns a unit
whole and episode_store.read_turn() pages any single event — results never
carry cut text.

=============================================================================
THE FLOW
=============================================================================

STEP 1: build(): load context maps once (queue rows, folded curation,
        distilled-fact provenance).
        |
STEP 2: per source (episode file / KB / canon file / queue rows): skip when
        its signature is unchanged; else derive its units, window them,
        diff against the FTS table by sha, embed only new/changed windows,
        delete vanished ones. Chroma writes take the shared
        .chroma_write.lock (memory/store.py) — the hearth reads the same DB.
        |
STEP 3: search(): time parse -> dense + FTS (+ time-restricted twins) ->
        RRF -> rerank -> neighbours -> SearchResult pointers.
=============================================================================
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import (Any, Callable, Dict, Iterable, Iterator, List, Optional, Protocol,
                    Sequence, Set, Tuple)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety
from jarvis_core.config import DATA_ROOT, DB_ROOT, JARVIS_ROOT, KB_PATH  # noqa: E402
from jarvis_core.locking import exclusive_lock  # noqa: E402
from jarvis_core.memory.episode_store import (  # noqa: E402
    STORE_ROOT, _append_healed, _dumps_line, _loads, episode_id, now_ist, safe_session)

_IST = timezone(timedelta(hours=5, minutes=30))

COLLECTION = "episodes"
FTS_PATH = STORE_ROOT / "episodes_fts.sqlite3"
PROVENANCE_PATH = Path(DATA_ROOT) / "fact_provenance.jsonl"
QUEUE_PATH = Path(DATA_ROOT) / "observation_queue.jsonl"
CURATION_PATH = Path(DATA_ROOT) / "turn_curation.jsonl"
CHROMA_WRITE_LOCK = Path(DB_ROOT).parent / ".chroma_write.lock"   # the same lock memory/store.py takes
DOC_FILES: Tuple[str, ...] = (
    "jarvis_data/personal_life.md",
    "jarvis_data/cognitive_profile.md",
    ".agent/rules/CLAUDE.md",
    ".agent/rules/JARVIS_ENDGAME.md",
    "knowledge/Finance/strategy.md",
)
SOURCES = ("exchange", "tool_call", "tool_result", "compaction", "kb", "doc", "queue")
CORE_SOURCES = ("exchange", "compaction", "kb", "doc", "queue")

INLINE_TOOL_CHARS = 600          # longer tool inputs become their own tool_call unit
PREFIX_FACT_TOKENS = 96          # facts in a prefix beyond this are counted, not listed
RRF_K = 60
_QUERY_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="episode-query")
_EMBED_BATCH = 32
_UPSERT_BATCH = 1000


# =============================================================================
# Part 1: EMBEDDERS (picked by measurement — see scripts/index_episodes.py)
# =============================================================================

@dataclass(frozen=True)
class EmbedderSpec:
    name: str
    model: str
    max_tokens: int
    query_prefix: str = ""
    doc_prefix: str = ""
    trust_remote_code: bool = False
    overlap: int = 64


EMBEDDERS: Dict[str, EmbedderSpec] = {
    "minilm": EmbedderSpec("minilm", "sentence-transformers/all-MiniLM-L6-v2", 256, overlap=40),
    "bge-small": EmbedderSpec("bge-small", "BAAI/bge-small-en-v1.5", 512,
                              query_prefix="Represent this sentence for searching relevant passages: "),
    "bge-base": EmbedderSpec("bge-base", "BAAI/bge-base-en-v1.5", 512,
                             query_prefix="Represent this sentence for searching relevant passages: "),
    "nomic": EmbedderSpec("nomic", "nomic-ai/nomic-embed-text-v1.5", 512,
                          query_prefix="search_query: ", doc_prefix="search_document: ",
                          trust_remote_code=True),
    # Gated on HF (401 without a token, measured 2026-09-29) — kept so a
    # machine with a token can measure it with the same harness.
    "embeddinggemma": EmbedderSpec("embeddinggemma", "google/embeddinggemma-300m", 512,
                                   query_prefix="task: search result | query: ",
                                   doc_prefix="title: none | text: "),
}
DEFAULT_EMBEDDER = os.environ.get("JARVIS_EPISODE_EMBEDDER", "nomic")


class Tokenizer(Protocol):
    def __call__(self, text: str, **kw: Any) -> Dict[str, Any]: ...


class Embedder:
    """Lazy tokenizer + lazy SentenceTransformer. Nothing touches the GPU until encode()."""

    def __init__(self, spec: EmbedderSpec, device: Optional[str] = None) -> None:
        self.spec = spec
        self._device = device
        self._tok: Any = None
        self._model: Any = None
        self.overflow = 0

    @property
    def tokenizer(self) -> Any:
        if self._tok is None:
            import logging
            from transformers import AutoTokenizer
            logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)
            self._tok = AutoTokenizer.from_pretrained(self.spec.model,
                                                      trust_remote_code=self.spec.trust_remote_code)
            self._tok.model_max_length = 10 ** 9     # we window; never let it warn or cut
        return self._tok

    def count(self, text: str) -> int:
        return len(self.tokenizer(text, add_special_tokens=False)["input_ids"])

    def _load(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            device = self._device or ("cuda" if torch.cuda.is_available() else "cpu")
            self._model = SentenceTransformer(self.spec.model, device=device,
                                              trust_remote_code=self.spec.trust_remote_code)
            self._model.max_seq_length = self.spec.max_tokens
        return self._model

    def _encode(self, texts: List[str]) -> Any:
        import numpy as np
        model = self._load()
        lens = self.tokenizer(texts, add_special_tokens=True)["input_ids"]
        self.overflow += sum(len(x) > self.spec.max_tokens for x in lens)
        vecs = model.encode(texts, batch_size=_EMBED_BATCH, normalize_embeddings=True,
                            convert_to_numpy=True, show_progress_bar=False)
        return np.asarray(vecs, dtype="float32")

    def encode_docs(self, texts: List[str]) -> Any:
        return self._encode([self.spec.doc_prefix + t for t in texts])

    def encode_query(self, text: str) -> Any:
        return self._encode([self.spec.query_prefix + text])[0]

    def vram_peak_mb(self) -> Optional[int]:
        try:
            import torch
            return int(torch.cuda.max_memory_allocated() // 2 ** 20) if torch.cuda.is_available() else None
        except Exception:                                   # noqa: BLE001
            return None


def token_windows(text: str, budget: int, overlap: int, tok: Any) -> List[Tuple[int, int]]:
    """Character spans of overlapping token windows that together cover ALL of text.

    Window k spans from the first char of its first token to the first char of
    the next window's... end token, so whitespace between tokens is never lost;
    the first window starts at 0 and the last ends at len(text)."""
    if not text:
        return []
    offs = tok(text, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"]
    n = len(offs)
    if n <= budget:
        return [(0, len(text))]
    stride = max(1, budget - max(0, min(overlap, budget // 2)))
    spans: List[Tuple[int, int]] = []
    i = 0
    while True:
        j = min(n, i + budget)
        start = 0 if i == 0 else offs[i][0]
        end = len(text) if j >= n else offs[j][0]
        spans.append((start, end))
        if j >= n:
            return spans
        i += stride


# =============================================================================
# Part 2: TEMPORAL PARSING (deterministic)
# =============================================================================

@dataclass(frozen=True)
class TimeRange:
    start: Optional[datetime]      # inclusive; None = open
    end: Optional[datetime]        # exclusive; None = open
    phrase: str = ""

    def bounds(self) -> Tuple[float, float]:
        return (self.start.timestamp() if self.start else -1e18,
                self.end.timestamp() if self.end else 1e18)

    def contains(self, t0: Optional[float], t1: Optional[float]) -> bool:
        if t0 is None or t1 is None:
            return False
        lo, hi = self.bounds()
        return t1 >= lo and t0 < hi


_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9
_MONTH_RX = "|".join(sorted(_MONTHS, key=len, reverse=True))
# "may"/"march" are also words; accept them bare only with a date-ish neighbour.
_AMBIGUOUS = {"may", "mar", "march", "jun", "jan", "dec", "sep", "aug"}
_ORD = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
        "last": -1, "final": -1}
_UNITS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "fortnight": 14, "month": 30, "months": 30,
          "year": 365, "years": 365}
_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "couple of": 2, "few": 3}


def _day(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=_IST)


def _month_span(y: int, m: int) -> Tuple[datetime, datetime]:
    start = _day(y, m, 1)
    end = _day(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return start, end


def _year_for(m: int, d: int, year: Optional[str], now: datetime) -> int:
    if year:
        return int(year)
    y = now.year
    try:
        if _day(y, m, min(d, 28)) > now:
            y -= 1
    except ValueError:
        pass
    return y


def _qualifier(prefix: str, start: datetime, end: datetime, phrase: str) -> TimeRange:
    p = prefix.strip().lower()
    if p in ("since", "after", "from"):
        return TimeRange(start if p == "since" or p == "from" else end, None, phrase)
    if p in ("before", "until", "till", "prior to"):
        return TimeRange(None, start if p in ("before", "prior to") else end, phrase)
    return TimeRange(start, end, phrase)


_QUAL = r"(?:(since|after|before|until|till|prior to|from|in|during|on|of|by)\s+)?"


def parse_time_range(text: str, now: Optional[datetime] = None,
                     resolver: Optional[Callable[[str], Optional[datetime]]] = None) -> Optional[TimeRange]:
    """The date range a question refers to, or None. Deterministic; `now` anchors relatives.

    `resolver(event_phrase) -> datetime` anchors "before/after <event>" (e.g.
    "before the interview"); without one such phrases yield None.
    """
    now = (now or datetime.now(_IST)).astimezone(_IST)
    s = " " + text.lower().replace("’", "'") + " "
    today = _day(now.year, now.month, now.day)

    m = re.search(_QUAL + r"(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        start = _day(int(m.group(2)), int(m.group(3)), int(m.group(4)))
        return _qualifier(m.group(1) or "", start, start + timedelta(days=1), m.group(0).strip())

    m = re.search(_QUAL + r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MONTH_RX + r")\b\.?,?(?:\s+(\d{4}))?", s)
    if not m:
        m2 = re.search(_QUAL + r"(" + _MONTH_RX + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!:)(?:,?\s+(\d{4}))?", s)
        if m2 and not (m2.group(3) and int(m2.group(3)) > 31):
            mo, d, yr = _MONTHS[m2.group(2)], int(m2.group(3)), m2.group(4)
            if 1 <= d <= 31:
                start = _day(_year_for(mo, d, yr, now), mo, min(d, calendar.monthrange(_year_for(mo, d, yr, now), mo)[1]))
                return _qualifier(m2.group(1) or "", start, start + timedelta(days=1), m2.group(0).strip())
    if m:
        d, mo, yr = int(m.group(2)), _MONTHS[m.group(3)], m.group(4)
        if 1 <= d <= 31:
            y = _year_for(mo, d, yr, now)
            start = _day(y, mo, min(d, calendar.monthrange(y, mo)[1]))
            return _qualifier(m.group(1) or "", start, start + timedelta(days=1), m.group(0).strip())

    m = re.search(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|last|final)\s+week\s+of\s+("
                  + _MONTH_RX + r")\b(?:\s+(\d{4}))?", s)
    if m:
        mo = _MONTHS[m.group(2)]
        y = _year_for(mo, 1, m.group(3), now)
        ms, me = _month_span(y, mo)
        k = _ORD[m.group(1)]
        if k < 0:
            return TimeRange(me - timedelta(days=7), me, m.group(0).strip())
        start = ms + timedelta(days=7 * k)
        return TimeRange(start, min(me, start + timedelta(days=7)), m.group(0).strip())

    m = re.search(_QUAL + r"(early|mid|middle of|late|end of|start of|beginning of)[\s-]+("
                  + _MONTH_RX + r")\b(?:\s+(\d{4}))?", s)
    if m:
        mo = _MONTHS[m.group(3)]
        y = _year_for(mo, 1, m.group(4), now)
        ms, me = _month_span(y, mo)
        part = m.group(2)
        if part in ("early", "start of", "beginning of"):
            a, b = ms, ms + timedelta(days=10)
        elif part in ("mid", "middle of"):
            a, b = ms + timedelta(days=10), ms + timedelta(days=20)
        else:
            a, b = ms + timedelta(days=20), me
        return _qualifier(m.group(1) or "", a, b, m.group(0).strip())

    for m in re.finditer(_QUAL + r"(" + _MONTH_RX + r")\b\.?(?:\s+(\d{4}))?", s):
        word, yr, qual = m.group(2), m.group(3), m.group(1)
        if word in _AMBIGUOUS and not (yr or qual in ("in", "during", "since", "after", "before", "of", "until")):
            continue
        mo = _MONTHS[word]
        y = int(yr) if yr else (now.year if mo <= now.month else now.year - 1)
        a, b = _month_span(y, mo)
        return _qualifier(qual or "", a, b, m.group(0).strip())

    rel = [
        (r"\b(this|earlier this) (morning|afternoon|evening)\b|\btonight\b|\btoday\b",
         lambda mm: (today, today + timedelta(days=1))),
        (r"\blast night\b", lambda mm: (today - timedelta(hours=6), today + timedelta(hours=6))),
        (r"\byesterday\b", lambda mm: (today - timedelta(days=1), today)),
        (r"\b(the )?day before yesterday\b", lambda mm: (today - timedelta(days=2), today - timedelta(days=1))),
        (r"\bthis week\b", lambda mm: (today - timedelta(days=today.weekday()), now + timedelta(seconds=1))),
        (r"\blast week\b|\bprevious week\b",
         lambda mm: (today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday()))),
        (r"\bthis month\b", lambda mm: (_day(now.year, now.month, 1), now + timedelta(seconds=1))),
        (r"\blast month\b|\bprevious month\b",
         lambda mm: _month_span(now.year - (now.month == 1), 12 if now.month == 1 else now.month - 1)),
        (r"\bthis year\b", lambda mm: (_day(now.year, 1, 1), now + timedelta(seconds=1))),
        (r"\blast year\b", lambda mm: (_day(now.year - 1, 1, 1), _day(now.year, 1, 1))),
        (r"\brecently\b|\blately\b|\bthese days\b", lambda mm: (now - timedelta(days=14), now + timedelta(seconds=1))),
    ]
    m = re.search(r"\b(?:in the |over the |during the )?(?:past|last|previous)\s+(\d+|a|an|one|two|three|four|five|six|"
                  r"seven|eight|nine|ten|couple of|few)\s+(days?|weeks?|months?|years?|fortnight)\b", s)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM[m.group(1)]
        return TimeRange(now - timedelta(days=n * _UNITS[m.group(2)]), now + timedelta(seconds=1), m.group(0).strip())
    m = re.search(r"\b(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple of|few)\s+"
                  r"(days?|weeks?|months?|years?)\s+ago\b", s)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _NUM[m.group(1)]
        unit = _UNITS[m.group(2)]
        center = today - timedelta(days=n * unit)
        half = timedelta(days=max(1, unit) / 2) if unit > 1 else timedelta(0)
        return TimeRange(center - half, center + timedelta(days=1) + half, m.group(0).strip())
    for rx, span in rel:
        mm = re.search(rx, s)
        if mm:
            a, b = span(mm)
            return TimeRange(a, b, mm.group(0).strip())

    m = re.search(r"\b(?:in|during|of)\s+(20\d{2})\b", s)
    if m:
        y = int(m.group(1))
        return TimeRange(_day(y, 1, 1), _day(y + 1, 1, 1), m.group(0).strip())

    m = re.search(r"\b(before|after|since|prior to)\s+(?:the|my|our|that)\s+([a-z][a-z0-9 \-]{2,40}?)(?:[?.!,]|\s+(?:and|but|when|with|did|was|i)\b|\s*$)", s)
    if m and resolver is not None:
        anchor = resolver(m.group(2).strip())
        if anchor is not None:
            anchor = anchor.astimezone(_IST)
            if m.group(1) in ("before", "prior to"):
                return TimeRange(None, anchor, m.group(0).strip())
            return TimeRange(anchor, None, m.group(0).strip())
    return None


# =============================================================================
# Part 3: SMALL READERS + THE QUEUE -> STORE TURN MAPPING
# =============================================================================

def _jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    try:
        fh = Path(path).open("rb")
    except OSError:
        return
    with fh:
        for raw in fh:
            rec = _loads(raw)
            if rec is not None:
                yield rec


def _epoch(ts: Any) -> Optional[float]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_IST)
        return dt.timestamp()
    except ValueError:
        return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()


def _episode_files(store_root: Path) -> Iterator[Tuple[str, str, Path]]:
    """(host, stem, path) for every stored episode file."""
    base = store_root / "episodes"
    if not base.exists():
        return
    for hdir in sorted(p for p in base.iterdir() if p.is_dir()):
        for path in sorted(hdir.glob("*.jsonl")):
            yield hdir.name, path.stem, path


def _user_events(path: Path) -> List[Dict[str, Any]]:
    out = []
    for rec in _jsonl(path):
        if rec.get("role") == "user":
            out.append({"id": rec["id"], "ts": rec.get("ts"), "t": _epoch(rec.get("ts")),
                        "norm": _norm(rec.get("content") or ""), "n": rec.get("n")})
    return out


def match_queue_row(user_events: Sequence[Dict[str, Any]], ts: str,
                    user_text: Optional[str] = None) -> Optional[str]:
    """The store user event a capture row (ts, user_text) was written for.

    The queue stamps a row when the turn ENDS; the store stamps the owner's
    message when it was SENT, so the match is the owner message at or before
    the row's ts. Text decides first (the queue's copy may be redacted or, for
    old rows, capped, so the comparison is on the leading 200 chars); the
    nearest earlier message decides when text cannot."""
    qt = _epoch(ts)
    if qt is None or not user_events:
        return None
    want = _norm(user_text or "")[:200]
    earlier = [e for e in user_events if e["t"] is not None and e["t"] <= qt + 120]
    if want:
        hits = [e for e in earlier if e["norm"][:200] == want or (len(want) > 30 and want in e["norm"])]
        if not hits:
            hits = [e for e in user_events if e["norm"][:200] == want]
        if hits:
            return max(hits, key=lambda e: e["t"] or 0)["id"]
    if earlier:
        return max(earlier, key=lambda e: e["t"])["id"]
    return None


class _SessionFinder:
    """session_id -> stored episode files, and cached user events per file."""

    def __init__(self, store_root: Path) -> None:
        self.store_root = store_root
        self._by_session: Optional[Dict[str, List[Path]]] = None
        self._events: Dict[Path, List[Dict[str, Any]]] = {}

    def files(self, session_id: str) -> List[Path]:
        if self._by_session is None:
            self._by_session = {}
            for _, stem, path in _episode_files(self.store_root):
                self._by_session.setdefault(stem, []).append(path)
        return self._by_session.get(safe_session(session_id), [])

    def has(self, session_id: str) -> bool:
        return bool(self.files(session_id))

    def user_events(self, path: Path) -> List[Dict[str, Any]]:
        if path not in self._events:
            self._events[path] = _user_events(path)
        return self._events[path]

    def turn_for(self, ts: str, session_id: str, user_text: Optional[str] = None) -> Optional[str]:
        for path in self.files(session_id):
            tid = match_queue_row(self.user_events(path), ts, user_text)
            if tid:
                return tid
        return None


def queue_to_turn(ts: str, session_id: str, user_text: Optional[str] = None,
                  root: Optional[Path] = None) -> Optional[str]:
    """Map a capture-queue turn key (ts, session_id) to its store turn id, or None."""
    return _SessionFinder(Path(root) if root else STORE_ROOT).turn_for(ts, session_id, user_text)


# =============================================================================
# Part 4: FACT PROVENANCE (facts -> the turns they came from, two timelines)
# =============================================================================

_EVIDENCE = re.compile(r"Evidence, in the owner's words \((\d{4}-\d{2}-\d{2}), ([a-z]+)\): \"(.*)\"\s*$", re.S)


def fact_source_fields(ts: str, session_id: str, user_text: str = "",
                       root: Optional[Path] = None, recorded_at: Optional[str] = None) -> Dict[str, Any]:
    """The structured provenance a NEW fact carries into its KB entry.

    valid_from = when it became true (the turn it was said in); valid_to stays
    null until a contradiction closes it; recorded_at = when JARVIS learned it.
    source_turn is None when this machine's store does not hold the session
    yet — source_queue always identifies the turn, and backfill_provenance()
    resolves it later."""
    return {
        "source_turn": queue_to_turn(ts, session_id, user_text, root),
        "source_queue": f"queue:{ts}|{session_id}",
        "valid_from": ts,
        "valid_to": None,
        "recorded_at": recorded_at or datetime.now(_IST).isoformat(timespec="seconds"),
    }


def _kb_ref(entry: Dict[str, Any], line_no: int) -> str:
    return f"kb:{entry['id']}" if entry.get("id") is not None else f"kb:line{line_no}"


def _iter_kb(kb_path: Path) -> Iterator[Tuple[int, Dict[str, Any]]]:
    """(1-based line, entry) — kb:line<N> in the recall eval counts lines from 1."""
    try:
        fh = Path(kb_path).open("r", encoding="utf-8")
    except OSError:
        return
    with fh:
        for line_no, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if isinstance(entry, dict):
                yield line_no, entry


def load_provenance(kb_path: Path = KB_PATH, prov_path: Path = PROVENANCE_PATH) -> Dict[str, Dict[str, Any]]:
    """kb ref -> provenance. Fields on the KB entry win; the side file fills the rest (newest row wins)."""
    out: Dict[str, Dict[str, Any]] = {}
    for rec in _jsonl(prov_path):
        if rec.get("kb"):
            out[str(rec["kb"])] = {**out.get(str(rec["kb"]), {}), **rec}
    for line_no, e in _iter_kb(kb_path):
        if e.get("source_turn") or e.get("source_queue"):
            ref = _kb_ref(e, line_no)
            out[ref] = {**out.get(ref, {}), **{k: e.get(k) for k in
                        ("source_turn", "source_queue", "valid_from", "valid_to", "recorded_at") if k in e},
                        "kb": ref}
    return out


def backfill_provenance(kb_path: Path = KB_PATH, prov_path: Path = PROVENANCE_PATH,
                        queue_path: Path = QUEUE_PATH, store_root: Optional[Path] = None,
                        dry_run: bool = False) -> Dict[str, int]:
    """Locate the source turn of every `distilled` KB fact that lacks one.

    Appends to fact_provenance.jsonl rather than rewriting KB lines: the KB is
    append-only and union-merged across laptops, so an in-place edit would
    leave BOTH versions of the line after the other machine's merge — a
    duplicate id. The side file is append-only, tracked, union-merged, and
    folded newest-wins by load_provenance()."""
    finder = _SessionFinder(Path(store_root) if store_root else STORE_ROOT)
    known = load_provenance(kb_path, prov_path)
    queue_rows = [r for r in _jsonl(queue_path) if r.get("ts") and r.get("session_id")]
    stats = {"distilled": 0, "already": 0, "resolved": 0, "queue_only": 0, "unlocated": 0}
    new_rows: List[Dict[str, Any]] = []
    for line_no, e in _iter_kb(kb_path):
        if "distilled" not in (e.get("tags") or []):
            continue
        stats["distilled"] += 1
        ref = _kb_ref(e, line_no)
        prev = known.get(ref, {})
        if prev.get("source_turn"):
            stats["already"] += 1
            continue
        m = _EVIDENCE.search(str(e.get("content") or ""))
        if not m:
            stats["unlocated"] += 1
            continue
        day, quote = m.group(1), _norm(m.group(3))
        rows = [r for r in queue_rows if str(r["ts"]).startswith(day) and quote in _norm(r.get("user_text") or "")]
        if not rows:
            rows = [r for r in queue_rows if quote in _norm(r.get("user_text") or "")]
        if not rows:
            stats["unlocated"] += 1
            continue
        row = rows[0]
        tid = finder.turn_for(str(row["ts"]), str(row["session_id"]), str(row.get("user_text") or ""))
        if tid is None and prev.get("source_queue"):
            stats["queue_only"] += 1
            continue
        stats["resolved" if tid else "queue_only"] += 1
        new_rows.append({"kb": ref, "source_turn": tid, "source_queue": f"queue:{row['ts']}|{row['session_id']}",
                         "valid_from": str(row["ts"]), "valid_to": None,
                         "recorded_at": str(e.get("timestamp") or ""), "method": "evidence-quote",
                         "at": now_ist()})
    if new_rows and not dry_run:
        with exclusive_lock(prov_path):
            _append_healed(prov_path, b"".join(_dumps_line(r) for r in new_rows))
    return stats


# =============================================================================
# Part 5: UNITS
# =============================================================================

@dataclass(frozen=True)
class Unit:
    unit_id: str
    source: str                   # one of SOURCES
    source_key: str               # what it was derived from (episode id / kb / file / queue)
    host: str
    episode: str
    session_id: str
    seq: int                      # exchange ordinal, or the event n for tool units
    part: int
    parts: int
    turn_ids: Tuple[str, ...]
    ts_start: str
    ts_end: str
    roles: Tuple[str, ...]
    prefix: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.prefix}\n{self.body}" if self.prefix else self.body

    @property
    def sha(self) -> str:
        return _sha(self.text)


@dataclass
class _Ctx:
    """Everything a prefix needs, loaded once per build."""
    titles: Dict[str, str] = field(default_factory=dict)                   # episode -> title
    labels: Dict[str, str] = field(default_factory=dict)                   # session -> chat label
    queue: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)   # session -> rows
    curation: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict)  # session -> (ts, responds_to)
    facts_by_turn: Dict[str, List[str]] = field(default_factory=dict)      # store turn id -> fact sentences
    facts_by_queue: Dict[str, List[str]] = field(default_factory=dict)     # queue key -> fact sentences

    def session_fingerprint(self, session_id: str, turn_ids_prefix: str) -> str:
        cur = self.curation.get(session_id, [])
        facts = sorted(k for k in self.facts_by_turn if k.startswith(turn_ids_prefix))
        return _sha(json.dumps([cur, facts, self.labels.get(session_id, "")], ensure_ascii=False))[:12]


def _fact_sentence(content: str) -> str:
    return str(content).split("\n\nEvidence,", 1)[0].strip()


def load_context(store_root: Path, kb_path: Path, queue_path: Path, curation_path: Path,
                 prov_path: Path) -> _Ctx:
    ctx = _Ctx()
    for rec in _jsonl(store_root / "manifest.jsonl"):
        if rec.get("t") == "session" and rec.get("title"):
            ctx.titles[str(rec["episode"])] = str(rec["title"])
    for row in _jsonl(queue_path):
        sid = str(row.get("session_id") or "")
        if not sid:
            continue
        ctx.queue.setdefault(sid, []).append(row)
        if row.get("chat_label") and not re.fullmatch(r"rollout-.*|[0-9a-f-]{36}", str(row["chat_label"])):
            ctx.labels.setdefault(sid, str(row["chat_label"]))
    folded: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rec in _jsonl(curation_path):
        folded[(str(rec.get("ts", "")), str(rec.get("session_id", "")))] = rec
    for (ts, sid), rec in folded.items():
        if rec.get("responds_to"):
            ctx.curation.setdefault(sid, []).append((ts, str(rec["responds_to"])))
    prov = load_provenance(kb_path, prov_path)
    for line_no, e in _iter_kb(kb_path):
        if "distilled" not in (e.get("tags") or []):
            continue
        p = prov.get(_kb_ref(e, line_no), {})
        sentence = _fact_sentence(e.get("content") or "")
        if p.get("source_turn"):
            ctx.facts_by_turn.setdefault(str(p["source_turn"]), []).append(sentence)
        if p.get("source_queue"):
            ctx.facts_by_queue.setdefault(str(p["source_queue"]), []).append(sentence)
    return ctx


def _render_tool_input(rec: Dict[str, Any]) -> Tuple[str, str]:
    """(tool name, its whole input as text)."""
    tool = rec.get("tool") or {}
    name = str(tool.get("name") or rec.get("kind") or "tool")
    content = str(rec.get("content") or "")
    if not content and tool.get("input") is not None:
        inp = tool["input"]
        content = inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False)
    return name, content


def _short_args(text: str) -> str:
    try:
        obj = json.loads(text)
    except ValueError:
        return ""
    if not isinstance(obj, dict):
        return ""
    keep = {k: v for k, v in obj.items() if isinstance(v, (int, float, bool))
            or (isinstance(v, str) and len(v) <= 200)}
    return json.dumps(keep, ensure_ascii=False) if keep else ""


def _compaction_text(content: str) -> str:
    """The readable text of a compaction record (codex replacement histories are
    JSON; their encrypted blobs and inline image bytes are not text)."""
    head, _, body = content.partition("\n")
    if head.strip() != "[replacement_history]":
        return content
    try:
        items = json.loads(body)
    except ValueError:
        return content
    lines = ["[replacement_history]"]
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or it.get("type") == "compaction" or "encrypted_content" in it:
            continue
        role = str(it.get("role") or it.get("type") or "")
        cont = it.get("content")
        parts: List[str] = []
        if isinstance(cont, str):
            parts.append(cont)
        for blk in cont if isinstance(cont, list) else []:
            if isinstance(blk, dict):
                if isinstance(blk.get("text"), str):
                    parts.append(blk["text"])
                elif "image" in str(blk.get("type", "")):
                    parts.append("[image]")
        if parts:
            lines.append(f"[{role}] " + "\n".join(parts))
    return "\n".join(lines)


def _date(ts: str) -> str:
    return str(ts or "")[:10]


def episode_raw_units(records: Iterable[Dict[str, Any]], host: str, session_id: str,
                      ctx: _Ctx, stats: Optional[Dict[str, int]] = None) -> Iterator[Dict[str, Any]]:
    """Un-windowed units of one episode, in order. Generator: an episode can be 150 MB."""
    ep = episode_id(host, session_id)
    title = ctx.titles.get(ep, "")
    label = ctx.labels.get(session_id.split(".agent-")[0], "")
    cur_rows = sorted(ctx.curation.get(session_id.split(".agent-")[0], []))
    head_bits = [host, title and f"session: {title}", label and label != title and f"chat: {label}"]
    stats = stats if stats is not None else {}
    calls: Dict[str, Tuple[str, str]] = {}
    ex: Optional[Dict[str, Any]] = None
    seq = 0

    def open_exchange(rec: Dict[str, Any]) -> Dict[str, Any]:
        return {"lines": [], "turn_ids": [], "ts": [], "roles": set(), "first_n": rec.get("n", 0),
                "owner_ids": [], "owner_ts": ""}

    def close(e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        nonlocal seq
        if not e["lines"]:
            return None
        facts: List[str] = []
        for tid in e["owner_ids"]:
            facts.extend(ctx.facts_by_turn.get(tid, []))
        responds = ""
        ots = _epoch(e["owner_ts"])
        if ots is not None:
            for qts, rt in cur_rows:
                qt = _epoch(qts)
                if qt is not None and ots - 5 <= qt <= ots + 6 * 3600:
                    responds = rt
                    break
        unit = {"source": "exchange", "seq": seq, "turn_ids": e["turn_ids"], "ts": e["ts"],
                "roles": sorted(e["roles"]), "body": "\n".join(e["lines"]),
                "head": [*head_bits, _date(e["ts"][0] if e["ts"] else "")],
                "responds_to": responds, "facts": facts, "key": f"x{e['first_n']}"}
        seq += 1
        return unit

    for rec in records:
        role = rec.get("role")
        n = rec.get("n", 0)
        tid = str(rec.get("id"))
        ts = str(rec.get("ts") or "")
        if role == "system":
            stats["system_events_skipped"] = stats.get("system_events_skipped", 0) + 1
            stats["system_chars_skipped"] = stats.get("system_chars_skipped", 0) + len(rec.get("content") or "")
            continue
        if role == "user":
            if ex is not None and ex["roles"] - {"user"}:
                done = close(ex)
                if done:
                    yield done
                ex = None
            if ex is None:
                ex = open_exchange(rec)
                ex["owner_ts"] = ts
            text = str(rec.get("content") or "")
            if rec.get("media"):
                text += ("\n" if text else "") + "[media] " + " ".join(map(str, rec["media"]))
            ex["lines"].append(f"[owner] {text}")
            ex["owner_ids"].append(tid)
        elif role in ("assistant", "thinking"):
            text = str(rec.get("content") or "")
            if not text.strip():
                continue
            ex = ex or open_exchange(rec)
            ex["lines"].append(f"[{'assistant' if role == 'assistant' else 'reasoning'}] {text}")
        elif role == "tool_call":
            name, inp = _render_tool_input(rec)
            tool = rec.get("tool") or {}
            for k in ("id", "call_id", "use_id"):
                if tool.get(k):
                    calls[str(tool[k])] = (name, inp if len(inp) <= 200 else "")
            ex = ex or open_exchange(rec)
            if len(inp) <= INLINE_TOOL_CHARS:
                ex["lines"].append(f"[tool] {name} {inp}".rstrip())
            else:
                args = _short_args(inp)
                ex["lines"].append(f"[tool] {name} {args} [full input: {len(inp)} chars, unit {ep}|c{n}]".replace("  ", " "))
                yield {"source": "tool_call", "seq": n, "turn_ids": [tid], "ts": [ts], "roles": ["tool_call"],
                       "body": inp, "head": [*head_bits, _date(ts), f"tool input: {name}"],
                       "responds_to": "", "facts": [], "key": f"c{n}"}
        elif role == "tool_result":
            tool = rec.get("tool") or {}
            text = str(rec.get("content") or "")
            if rec.get("stub"):
                st = rec["stub"]
                text += f"\n[held locally by {st.get('held_by')}: {st.get('bytes')} bytes, sha256 {st.get('sha256')}]"
            if rec.get("media"):
                text += "\n[media] " + " ".join(map(str, rec["media"]))
            if not text.strip():
                continue
            cname, cin = calls.get(str(tool.get("use_id") or tool.get("call_id") or tool.get("id") or ""),
                                   (str(tool.get("name") or rec.get("kind") or "tool"), ""))
            about = f"output of {cname}" + (f" {cin}" if cin else "")
            yield {"source": "tool_result", "seq": n, "turn_ids": [tid], "ts": [ts], "roles": ["tool_result"],
                   "body": text, "head": [*head_bits, _date(ts), about], "responds_to": "", "facts": [],
                   "key": f"r{n}"}
            continue
        elif role == "compaction":
            text = _compaction_text(str(rec.get("content") or ""))
            if text.strip():
                yield {"source": "compaction", "seq": n, "turn_ids": [tid], "ts": [ts], "roles": ["compaction"],
                       "body": text, "head": [*head_bits, _date(ts), f"compaction ({rec.get('kind')})"],
                       "responds_to": "", "facts": [], "key": f"p{n}"}
            continue
        else:
            continue
        ex["turn_ids"].append(tid)
        if ts:
            ex["ts"].append(ts)
        ex["roles"].add(role)
    if ex is not None:
        done = close(ex)
        if done:
            yield done


def kb_raw_units(kb_path: Path) -> Iterator[Dict[str, Any]]:
    for line_no, e in _iter_kb(kb_path):
        content = str(e.get("content") or "")
        if not content.strip():
            continue
        ref = _kb_ref(e, line_no)
        tags = ", ".join(map(str, e.get("tags") or []))
        yield {"source": "kb", "seq": line_no, "turn_ids": [ref], "ts": [str(e.get("timestamp") or "")],
               "roles": ["kb"], "body": content,
               "head": [f"KB {e.get('type', '')}", f"recorded {_date(str(e.get('timestamp') or ''))}",
                        tags and f"tags: {tags}"],
               "responds_to": "", "facts": [], "key": ref}


def doc_raw_units(rel_path: str, root: Path) -> Iterator[Dict[str, Any]]:
    path = root / rel_path
    try:
        text = path.read_text(encoding="utf-8")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, _IST).isoformat(timespec="seconds")
    except OSError:
        return
    sections: List[Tuple[str, str]] = []
    heading, buf = "(top)", []
    for line in text.splitlines(keepends=True):
        if re.match(r"^#{1,3} ", line) and buf:
            sections.append((heading, "".join(buf)))
            buf = []
        if re.match(r"^#{1,3} ", line):
            heading = line.strip("# \n")
        buf.append(line)
    if buf:
        sections.append((heading, "".join(buf)))
    for i, (h, body) in enumerate(sections):
        if body.strip():
            yield {"source": "doc", "seq": i, "turn_ids": [f"file:{rel_path}"], "ts": [mtime], "roles": ["doc"],
                   "body": body, "head": [f"file {rel_path}", f"section: {h}"], "responds_to": "",
                   "facts": [], "key": f"s{i}"}


def queue_raw_units(rows: Sequence[Dict[str, Any]], ctx: _Ctx) -> Iterator[Dict[str, Any]]:
    for row in rows:
        ts, sid = str(row.get("ts")), str(row.get("session_id"))
        key = f"queue:{ts}|{sid}"
        body = f"[owner] {row.get('user_text') or ''}"
        if row.get("assistant_summary"):
            body += f"\n[assistant] {row['assistant_summary']}"
        responds = next((rt for qts, rt in ctx.curation.get(sid, []) if qts == ts), "")
        yield {"source": "queue", "seq": 0, "turn_ids": [key], "ts": [ts], "roles": ["user", "assistant"],
               "body": body, "head": [str(row.get("host") or "capture"), ctx.labels.get(sid, "") and
                                      f"chat: {ctx.labels.get(sid)}", _date(ts), f"machine {row.get('machine', '')}"],
               "responds_to": responds, "facts": ctx.facts_by_queue.get(key, []), "key": key}


def _prefix(raw: Dict[str, Any], counter: Callable[[str], int]) -> str:
    bits = [b for b in raw["head"] if b]
    head = "[" + " · ".join(bits) + "]"
    extra: List[str] = []
    if raw.get("responds_to"):
        extra.append(f"responds to: {raw['responds_to']}")
    facts = list(dict.fromkeys(raw.get("facts") or []))
    listed, used = [], 0
    for f in facts:
        cost = counter(f)
        if used + cost > PREFIX_FACT_TOKENS and listed:
            break
        listed.append(f)
        used += cost
    if listed:
        more = len(facts) - len(listed)
        extra.append("facts: " + " | ".join(listed) + (f" (+{more} more facts)" if more else ""))
    return " ".join([head, *extra])


def window_units(raw: Dict[str, Any], source_key: str, host: str, episode: str, session_id: str,
                 emb: "Embedder | Any") -> List[Unit]:
    """Split one raw unit into windows that fit the embedder with its prefix; nothing dropped."""
    spec = emb.spec
    prefix = _prefix(raw, emb.count)
    reserve = emb.count(spec.doc_prefix + prefix + "\n") + 2 + 4
    if reserve > spec.max_tokens // 2:
        # Prefix metadata (never the content) yields to the body: drop the
        # responds_to/facts, then all but host and date, so no window overflows.
        prefix = _prefix({**raw, "responds_to": "", "facts": []}, emb.count)
        reserve = emb.count(spec.doc_prefix + prefix + "\n") + 2 + 4
        if reserve > spec.max_tokens // 2:
            prefix = "[" + " · ".join(b for b in raw["head"][:1] + [_date((raw["ts"] or [""])[0])] if b) + "]"
            reserve = emb.count(spec.doc_prefix + prefix + "\n") + 2 + 4
    budget = max(8, spec.max_tokens - reserve)
    spans = token_windows(raw["body"], budget, spec.overlap, emb.tokenizer)
    ts = [t for t in raw["ts"] if t] or [""]
    out = []
    base = f"{episode or source_key}|{raw['key']}"
    for k, (a, b) in enumerate(spans):
        out.append(Unit(unit_id=f"{base}|w{k}", source=raw["source"], source_key=source_key, host=host,
                        episode=episode, session_id=session_id, seq=int(raw["seq"]), part=k, parts=len(spans),
                        turn_ids=tuple(raw["turn_ids"]), ts_start=min(ts), ts_end=max(ts),
                        roles=tuple(raw["roles"]), prefix=prefix, body=raw["body"][a:b]))
    return out


# =============================================================================
# Part 6: VECTOR BACKENDS (Chroma for the real index; numpy for tests/measurement)
# =============================================================================

class VectorBackend(Protocol):
    def meta(self) -> Dict[str, Any]: ...
    def upsert(self, ids: List[str], vecs: Any, metas: List[Dict[str, Any]]) -> None: ...
    def delete(self, ids: List[str]) -> None: ...
    def query(self, vec: Any, n: int, where: Optional[Dict[str, Any]]) -> List[Tuple[str, float]]: ...
    def count(self) -> int: ...
    def reset(self, meta: Dict[str, Any]) -> None: ...


class EmbedderMismatch(RuntimeError):
    pass


class ChromaBackend:
    """The `episodes` collection in the shared chromadb/, reached through
    get_chroma_client (HttpClient to the supervised server, else sole-owner
    direct). Writes also take memory/store.py's .chroma_write.lock as belt and braces."""

    def __init__(self, db_path: Path = DB_ROOT, name: str = COLLECTION) -> None:
        from jarvis_core.memory.chroma_access import get_chroma_client
        self.client = get_chroma_client(Path(db_path))
        self.name = name
        self.lock = Path(db_path).parent / ".chroma_write.lock"
        self._col: Any = None

    def _collection(self, meta: Optional[Dict[str, Any]] = None) -> Any:
        if self._col is None:
            try:
                self._col = self.client.get_collection(self.name, embedding_function=None)
            except Exception:                              # noqa: BLE001 — absent
                if meta is None:
                    return None
                with exclusive_lock(self.lock):
                    self._col = self.client.get_or_create_collection(
                        self.name, embedding_function=None, metadata={**meta, "hnsw:space": "cosine"})
        return self._col

    def meta(self) -> Dict[str, Any]:
        col = self._collection()
        return dict(col.metadata or {}) if col is not None else {}

    def reset(self, meta: Dict[str, Any]) -> None:
        with exclusive_lock(self.lock):
            try:
                self.client.delete_collection(self.name)
            except Exception:                              # noqa: BLE001
                pass
            self._col = self.client.create_collection(self.name, embedding_function=None,
                                                      metadata={**meta, "hnsw:space": "cosine"})

    def upsert(self, ids: List[str], vecs: Any, metas: List[Dict[str, Any]]) -> None:
        col = self._collection({})
        for i in range(0, len(ids), _UPSERT_BATCH):
            with exclusive_lock(self.lock):
                col.upsert(ids=ids[i:i + _UPSERT_BATCH], embeddings=vecs[i:i + _UPSERT_BATCH].tolist(),
                           metadatas=metas[i:i + _UPSERT_BATCH])

    def delete(self, ids: List[str]) -> None:
        col = self._collection()
        if col is None:
            return
        for i in range(0, len(ids), _UPSERT_BATCH):
            with exclusive_lock(self.lock):
                col.delete(ids=ids[i:i + _UPSERT_BATCH])

    def query(self, vec: Any, n: int, where: Optional[Dict[str, Any]]) -> List[Tuple[str, float]]:
        col = self._collection()
        if col is None or n <= 0:
            return []
        res = col.query(query_embeddings=[list(map(float, vec))], n_results=n, where=where or None,
                        include=["distances"])
        return list(zip(res["ids"][0], res["distances"][0]))

    def count(self) -> int:
        col = self._collection()
        return col.count() if col is not None else 0


class NumpyBackend:
    """Brute-force cosine in memory, persisted to one .npz. For the self-test and
    for measuring embedder candidates without touching the shared chromadb/."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self.ids: List[str] = []
        self.vecs: Dict[str, Any] = {}
        self.metas: Dict[str, Dict[str, Any]] = {}
        self._meta: Dict[str, Any] = {}
        self._mat: Any = None
        if path and Path(path).exists():
            import numpy as np
            data = np.load(path, allow_pickle=True)
            self._meta = json.loads(str(data["meta"]))
            for i, v, m in zip(data["ids"], data["vecs"], data["metas"]):
                self.vecs[str(i)] = v
                self.metas[str(i)] = json.loads(str(m))

    def meta(self) -> Dict[str, Any]:
        return dict(self._meta)

    def reset(self, meta: Dict[str, Any]) -> None:
        self.vecs, self.metas, self._meta, self._mat = {}, {}, dict(meta), None

    def upsert(self, ids: List[str], vecs: Any, metas: List[Dict[str, Any]]) -> None:
        if not self._meta:
            self._meta = {"created": now_ist()}
        for i, v, m in zip(ids, vecs, metas):
            self.vecs[i], self.metas[i] = v, m
        self._mat = None

    def delete(self, ids: List[str]) -> None:
        for i in ids:
            self.vecs.pop(i, None)
            self.metas.pop(i, None)
        self._mat = None

    def set_meta(self, meta: Dict[str, Any]) -> None:
        self._meta.update(meta)

    def _matrix(self) -> Tuple[List[str], Any]:
        import numpy as np
        if self._mat is None:
            self.ids = list(self.vecs)
            self._mat = np.stack([self.vecs[i] for i in self.ids]) if self.ids else np.zeros((0, 1), "float32")
        return self.ids, self._mat

    @staticmethod
    def _passes(m: Dict[str, Any], where: Optional[Dict[str, Any]]) -> bool:
        if not where:
            return True
        clauses = where.get("$and", [where])
        for c in clauses:
            for k, cond in c.items():
                v = m.get(k)
                for op, arg in cond.items():
                    if v is None:
                        return False
                    if (op == "$gte" and not v >= arg) or (op == "$lte" and not v <= arg) or \
                       (op == "$lt" and not v < arg) or (op == "$in" and v not in arg):
                        return False
        return True

    def query(self, vec: Any, n: int, where: Optional[Dict[str, Any]]) -> List[Tuple[str, float]]:
        import numpy as np
        ids, mat = self._matrix()
        if not ids or n <= 0:
            return []
        sims = mat @ np.asarray(vec, dtype="float32")
        order = np.argsort(-sims)
        out = []
        for j in order:
            if self._passes(self.metas[ids[j]], where):
                out.append((ids[j], float(1.0 - sims[j])))
                if len(out) >= n:
                    break
        return out

    def count(self) -> int:
        return len(self.vecs)

    def save(self) -> None:
        if not self.path:
            return
        import numpy as np
        ids = list(self.vecs)
        np.savez(self.path, ids=np.array(ids, dtype=object),
                 vecs=np.stack([self.vecs[i] for i in ids]) if ids else np.zeros((0, 1), "float32"),
                 metas=np.array([json.dumps(self.metas[i]) for i in ids], dtype=object),
                 meta=json.dumps(self._meta))


# =============================================================================
# Part 7: THE INDEX
# =============================================================================

_SCHEMA = """
CREATE TABLE IF NOT EXISTS units(
  rid INTEGER PRIMARY KEY, unit_id TEXT UNIQUE NOT NULL, source TEXT, source_key TEXT,
  host TEXT, episode TEXT, session_id TEXT, seq INTEGER, part INTEGER, parts INTEGER,
  turn_ids TEXT, ts_start TEXT, ts_end TEXT, t0 REAL, t1 REAL, roles TEXT,
  prefix TEXT, body TEXT, sha TEXT);
CREATE INDEX IF NOT EXISTS units_by_key ON units(source_key);
CREATE INDEX IF NOT EXISTS units_by_ep ON units(episode, source, seq);
CREATE TABLE IF NOT EXISTS sources(key TEXT PRIMARY KEY, sig TEXT, units INTEGER, at TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS units_fts USING fts5(
  prefix, body, content='', contentless_delete=1, tokenize='porter unicode61');
"""

_STOP = set("""a an and are as at be been but by can could did do does doing done for from had has have
how i if in into is it its just me my of on or our so than that the their them then there these they
this those to was we were what when where which who whom why will with would you your yours about
tell said say ever still now any all get got""".split())


def fts_query(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9_]+", text.lower()) if len(w) > 1 and w not in _STOP]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


@dataclass(frozen=True)
class SearchResult:
    unit_id: str
    source: str
    host: str
    episode: str
    session_id: str
    turn_ids: Tuple[str, ...]
    ts_start: str
    ts_end: str
    part: int
    parts: int
    score: float
    ranks: Dict[str, int]
    in_time_range: bool
    neighbours: Tuple[str, ...] = ()
    signals: Dict[str, float] = field(default_factory=dict)


class EpisodeIndex:
    """FTS5 (units + bm25) and a vector backend over the same units."""

    def __init__(self, fts_path: Path = FTS_PATH, backend: Optional[VectorBackend] = None,
                 embedder: Optional[Any] = None, store_root: Path = STORE_ROOT,
                 kb_path: Path = KB_PATH, queue_path: Path = QUEUE_PATH,
                 curation_path: Path = CURATION_PATH, prov_path: Path = PROVENANCE_PATH,
                 doc_root: Path = JARVIS_ROOT, doc_files: Sequence[str] = DOC_FILES,
                 sources: Sequence[str] = SOURCES, dense_sources: Sequence[str] = CORE_SOURCES,
                 vector_seed: Optional[Tuple[Path, Path]] = None,
                 rerank_device: Optional[str] = None) -> None:
        self.fts_path = Path(fts_path)
        self.rerank_device = rerank_device
        self.dense_sources = tuple(dense_sources)
        self._seed_paths = vector_seed
        self._seed: Optional[Dict[str, Tuple[str, Any]]] = None
        self.embedder = embedder or Embedder(EMBEDDERS[DEFAULT_EMBEDDER])
        self._backend = backend
        self.store_root = Path(store_root)
        self.kb_path, self.queue_path = Path(kb_path), Path(queue_path)
        self.curation_path, self.prov_path = Path(curation_path), Path(prov_path)
        self.doc_root, self.doc_files = Path(doc_root), tuple(doc_files)
        self.sources = tuple(sources)
        self._db: Optional[sqlite3.Connection] = None
        self._reranker: Any = None
        self._vocab_n: Optional[int] = None

    # ---- plumbing -------------------------------------------------------

    @property
    def backend(self) -> VectorBackend:
        if self._backend is None:
            self._backend = ChromaBackend()
        return self._backend

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self.fts_path.parent.mkdir(parents=True, exist_ok=True)
            # The voice path calls recall from a worker thread; every search
            # takes the router's lock, so one connection is never used at once.
            self._db = sqlite3.connect(str(self.fts_path), timeout=60, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> "EpisodeIndex":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _meta_get(self, key: str) -> Optional[str]:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _meta_set(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value))

    def _expected_meta(self) -> Dict[str, Any]:
        spec = self.embedder.spec
        return {"embedder": spec.model, "embedder_name": spec.name, "max_tokens": spec.max_tokens}

    def check_embedder(self) -> None:
        """Refuse to mix vector spaces: the collection and the FTS both record their model."""
        want = self.embedder.spec.model
        have = self.backend.meta().get("embedder") or self._meta_get("embedder")
        if have and have != want:
            raise EmbedderMismatch(f"index '{COLLECTION}' was built with {have}; this process "
                                   f"embeds with {want}. Rebuild (--rebuild) or set "
                                   f"JARVIS_EPISODE_EMBEDDER to the building model.")

    # ---- building -------------------------------------------------------

    def rebuild_reset(self) -> None:
        self.db.executescript("DROP TABLE IF EXISTS units; DROP TABLE IF EXISTS sources; "
                              "DROP TABLE IF EXISTS meta; DROP TABLE IF EXISTS units_fts;")
        self.db.executescript(_SCHEMA)
        self.backend.reset({**self._expected_meta(), "built": now_ist()})
        for k, v in self._expected_meta().items():
            self._meta_set(k, str(v))
        self.db.commit()

    def _source_units(self, kind: str, ctx: _Ctx, finder: _SessionFinder,
                      stats: Dict[str, int]) -> Iterator[Tuple[str, str, Callable[[], Iterator[Unit]]]]:
        """(source_key, signature, lazy unit generator) for every source of this kind."""
        emb = self.embedder
        if kind == "episodes":
            for host, stem, path in _episode_files(self.store_root):
                ep = episode_id(host, stem)
                size = path.stat().st_size
                sig = f"{size}:{ctx.session_fingerprint(stem.split('.agent-')[0], f'turn:{host}:{stem}:')}"

                def gen(host=host, stem=stem, path=path, ep=ep) -> Iterator[Unit]:
                    for raw in episode_raw_units(_jsonl(path), host, stem, ctx, stats):
                        if raw["source"] in self.sources:
                            yield from window_units(raw, ep, host, ep, stem, emb)
                yield ep, sig, gen
        elif kind == "kb" and "kb" in self.sources:
            st = self.kb_path.stat() if self.kb_path.exists() else None
            sig = f"{st.st_size}:{st.st_mtime_ns}" if st else "absent"

            def gen_kb() -> Iterator[Unit]:
                for raw in kb_raw_units(self.kb_path):
                    yield from window_units(raw, "kb", "kb", "", "", emb)
            yield "kb", sig, gen_kb
        elif kind == "docs" and "doc" in self.sources:
            for rel in self.doc_files:
                p = self.doc_root / rel
                sig = _sha(p.read_text(encoding="utf-8")) if p.exists() else "absent"

                def gen_doc(rel=rel) -> Iterator[Unit]:
                    for raw in doc_raw_units(rel, self.doc_root):
                        yield from window_units(raw, f"file:{rel}", "doc", "", "", emb)
                yield f"file:{rel}", sig, gen_doc
        elif kind == "queue" and "queue" in self.sources:
            rows = [r for sid, rs in ctx.queue.items() if not finder.has(sid) for r in rs
                    if str(r.get("user_text") or "").strip() or r.get("assistant_summary")]
            seen: Set[str] = set()
            uniq = []
            for r in rows:
                k = f"{r.get('ts')}|{r.get('session_id')}"
                if k not in seen:
                    seen.add(k)
                    uniq.append(r)
            sig = _sha(json.dumps(sorted(seen)) + json.dumps(sorted(ctx.facts_by_queue)) +
                       json.dumps(sorted(ctx.curation.items())))

            def gen_q() -> Iterator[Unit]:
                for raw in queue_raw_units(uniq, ctx):
                    yield from window_units(raw, "queue", raw["head"][0] or "capture", "", "", emb)
            yield "queue", sig, gen_q

    def _seeded(self, u: Unit) -> Optional[Any]:
        """A vector another build of the SAME model already computed for this exact
        text (unit id and sha both match), so a rebuild does not re-embed it."""
        if self._seed_paths is None:
            return None
        if self._seed is None:
            import numpy as np
            fts_p, npz_p = self._seed_paths
            self._seed = {}
            data = np.load(npz_p, allow_pickle=True)
            vecs = {str(i): v for i, v in zip(data["ids"], data["vecs"])}
            spec_model = json.loads(str(data["meta"])).get("embedder")
            if spec_model == self.embedder.spec.model:
                con = sqlite3.connect(str(fts_p))
                for uid, sha in con.execute("SELECT unit_id, sha FROM units"):
                    if uid in vecs:
                        self._seed[uid] = (sha, vecs[uid])
                con.close()
        hit = self._seed.get(u.unit_id)
        return hit[1] if hit and hit[0] == u.sha else None

    def _sync_source(self, key: str, units: Iterator[Unit], stats: Dict[str, int]) -> None:
        """Diff one source's units against the table by sha; embed only what changed."""
        old = {r[0]: (r[1], r[2]) for r in
               self.db.execute("SELECT unit_id, sha, rid FROM units WHERE source_key=?", (key,))}
        keep: Set[str] = set()
        pending: List[Unit] = []

        def flush() -> None:
            if not pending:
                return
            dense = [u for u in pending if u.source in self.dense_sources]
            if dense:
                import numpy as np
                have = [self._seeded(u) for u in dense]
                todo = [u for u, v in zip(dense, have) if v is None]
                fresh = iter(self.embedder.encode_docs([u.text for u in todo])) if todo else iter(())
                vecs = np.stack([v if v is not None else next(fresh) for v in have])
                metas = [{"source": u.source, "host": u.host, "episode": u.episode, "session_id": u.session_id,
                          "t0": _epoch(u.ts_start) or 0.0, "t1": _epoch(u.ts_end) or 0.0,
                          "has_ts": bool(u.ts_start)} for u in dense]
                self.backend.upsert([u.unit_id for u in dense], vecs, metas)
                stats["seeded"] = stats.get("seeded", 0) + len(dense) - len(todo)
                stats["embedded_dense"] = stats.get("embedded_dense", 0) + len(todo)
            for u in pending:
                prev = old.get(u.unit_id)
                if prev:
                    self.db.execute("DELETE FROM units_fts WHERE rowid=?", (prev[1],))
                    self.db.execute("DELETE FROM units WHERE rid=?", (prev[1],))
                cur = self.db.execute(
                    "INSERT INTO units(unit_id, source, source_key, host, episode, session_id, seq, part, parts,"
                    " turn_ids, ts_start, ts_end, t0, t1, roles, prefix, body, sha)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (u.unit_id, u.source, u.source_key, u.host, u.episode, u.session_id, u.seq, u.part, u.parts,
                     json.dumps(u.turn_ids), u.ts_start, u.ts_end, _epoch(u.ts_start), _epoch(u.ts_end),
                     ",".join(u.roles), u.prefix, u.body, u.sha))
                self.db.execute("INSERT INTO units_fts(rowid, prefix, body) VALUES(?,?,?)",
                                (cur.lastrowid, u.prefix, u.body))
            stats["embedded"] = stats.get("embedded", 0) + len(pending)
            stats["embedded_chars"] = stats.get("embedded_chars", 0) + sum(len(u.text) for u in pending)
            pending.clear()
            self.db.commit()

        for u in units:
            keep.add(u.unit_id)
            prev = old.get(u.unit_id)
            if prev and prev[0] == u.sha:
                stats["unchanged"] = stats.get("unchanged", 0) + 1
                continue
            pending.append(u)
            if len(pending) >= 256:
                flush()
        flush()
        gone = [uid for uid in old if uid not in keep]
        if gone:
            self.backend.delete(gone)
            for uid in gone:
                self.db.execute("DELETE FROM units_fts WHERE rowid=?", (old[uid][1],))
                self.db.execute("DELETE FROM units WHERE rid=?", (old[uid][1],))
            stats["deleted"] = stats.get("deleted", 0) + len(gone)

    def build(self, rebuild: bool = False, kinds: Sequence[str] = ("episodes", "kb", "docs", "queue"),
              log: Callable[[str], None] = print, limit_sources: Optional[int] = None) -> Dict[str, Any]:
        """Incremental by default: a source whose signature is unchanged is not read."""
        t_start = time.perf_counter()
        if rebuild:
            self.rebuild_reset()
        else:
            self.check_embedder()
            if not self.backend.meta().get("embedder"):
                if isinstance(self.backend, NumpyBackend):
                    self.backend.set_meta(self._expected_meta())
                else:
                    self.backend.reset({**self._expected_meta(), "built": now_ist()})
            for k, v in self._expected_meta().items():
                self._meta_set(k, str(v))
        stats: Dict[str, Any] = {}
        ctx = load_context(self.store_root, self.kb_path, self.queue_path, self.curation_path, self.prov_path)
        finder = _SessionFinder(self.store_root)
        live_keys: Set[str] = set()
        done = 0
        for kind in kinds:
            for key, sig, gen in self._source_units(kind, ctx, finder, stats):
                live_keys.add(key)
                row = self.db.execute("SELECT sig FROM sources WHERE key=?", (key,)).fetchone()
                if row and row[0] == sig:
                    stats["sources_unchanged"] = stats.get("sources_unchanged", 0) + 1
                    continue
                if limit_sources is not None and done >= limit_sources:
                    continue
                t0 = time.perf_counter()
                before = stats.get("embedded", 0)
                self._sync_source(key, gen(), stats)
                n = self.db.execute("SELECT COUNT(*) FROM units WHERE source_key=?", (key,)).fetchone()[0]
                self.db.execute("INSERT OR REPLACE INTO sources(key, sig, units, at) VALUES(?,?,?,?)",
                                (key, sig, n, now_ist()))
                self.db.commit()
                done += 1
                stats["sources_synced"] = stats.get("sources_synced", 0) + 1
                log(f"  {key}: {n} units ({stats.get('embedded', 0) - before} embedded, "
                    f"{time.perf_counter() - t0:.1f}s)")
        if limit_sources is None:
            stale = [r[0] for r in self.db.execute("SELECT key FROM sources") if r[0] not in live_keys]
            for key in stale:
                self._sync_source(key, iter(()), stats)
                self.db.execute("DELETE FROM sources WHERE key=?", (key,))
            self.db.commit()
        self._meta_set("updated", now_ist())
        self.db.commit()
        if isinstance(self.backend, NumpyBackend):
            self.backend.save()
        stats["seconds"] = round(time.perf_counter() - t_start, 1)
        stats["overflow_windows"] = getattr(self.embedder, "overflow", 0)
        return stats

    # ---- reading --------------------------------------------------------

    def _row(self, unit_id: str) -> Optional[sqlite3.Row]:
        self.db.row_factory = sqlite3.Row
        try:
            return self.db.execute("SELECT * FROM units WHERE unit_id=?", (unit_id,)).fetchone()
        finally:
            self.db.row_factory = None

    def read_unit(self, unit_id: str) -> Optional[Dict[str, Any]]:
        """A unit whole: its prefix, its full body window, and which window of how many."""
        r = self._row(unit_id)
        if r is None:
            return None
        d = dict(r)
        d["turn_ids"] = json.loads(d["turn_ids"])
        d["text"] = f"{d['prefix']}\n{d['body']}" if d["prefix"] else d["body"]
        return d

    def unit_windows(self, unit_id: str) -> List[str]:
        """Every window id of the unit this window belongs to, in order."""
        base = unit_id.rsplit("|w", 1)[0]
        return [r[0] for r in self.db.execute(
            "SELECT unit_id FROM units WHERE unit_id LIKE ? ORDER BY part", (base.replace("%", r"\%") + "|w%",))]

    def status(self) -> Dict[str, Any]:
        by = dict(self.db.execute("SELECT source, COUNT(*) FROM units GROUP BY source").fetchall())
        chars = self.db.execute("SELECT COALESCE(SUM(LENGTH(body)),0) FROM units").fetchone()[0]
        return {"units": sum(by.values()), "by_source": by, "body_chars": chars,
                "sources": self.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                "vectors": self.backend.count(), "embedder": self._meta_get("embedder"),
                "updated": self._meta_get("updated"),
                "fts_bytes": self.fts_path.stat().st_size if self.fts_path.exists() else 0}

    # ---- search ---------------------------------------------------------

    def _where(self, rng: Optional[TimeRange], hosts: Optional[Sequence[str]],
               sources: Optional[Sequence[str]]) -> Optional[Dict[str, Any]]:
        clauses: List[Dict[str, Any]] = []
        if rng is not None:
            lo, hi = rng.bounds()
            clauses += [{"t1": {"$gte": lo}}, {"t0": {"$lt": hi}}, {"has_ts": {"$in": [True]}}]
        if hosts:
            clauses.append({"host": {"$in": list(hosts)}})
        if sources:
            clauses.append({"source": {"$in": list(sources)}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}

    def doc_freq(self, word: str) -> float:
        """Fraction of indexed units containing this word (its stem, approximately).
        Read from the FTS5 vocabulary table, so it costs a point lookup."""
        if self._vocab_n is None:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.units_vocab "
                            "USING fts5vocab('main', 'units_fts', 'row')")
            self._vocab_n = max(1, self.db.execute("SELECT COUNT(*) FROM units").fetchone()[0])
        w = word.lower()
        best = 0
        for cand in {w, w[:-1], w[:-2], w[:-3]}:
            if len(cand) < 2:
                continue
            row = self.db.execute("SELECT doc FROM units_vocab WHERE term=?", (cand,)).fetchone()
            if row:
                best = max(best, int(row[0]))
        return best / self._vocab_n

    def unit_parts(self, unit_id: str) -> List[Dict[str, Any]]:
        """Every window of the unit this window belongs to, in order (rows as dicts)."""
        r = self._row(unit_id)
        if r is None:
            return []
        base = unit_id.rsplit("|w", 1)[0]
        if r["episode"]:
            cur = self.db.execute("SELECT unit_id, part, parts, prefix, body FROM units "
                                  "WHERE episode=? AND source=? AND seq=? ORDER BY part",
                                  (r["episode"], r["source"], r["seq"]))
        else:
            cur = self.db.execute("SELECT unit_id, part, parts, prefix, body FROM units "
                                  "WHERE source_key=? AND seq=? ORDER BY part", (r["source_key"], r["seq"]))
        out = [dict(zip(("unit_id", "part", "parts", "prefix", "body"), x)) for x in cur
               if x[0].rsplit("|w", 1)[0] == base]
        return out or [{"unit_id": unit_id, "part": r["part"], "parts": r["parts"],
                        "prefix": r["prefix"], "body": r["body"]}]

    def _fts(self, query: str, n: int, rng: Optional[TimeRange], hosts: Optional[Sequence[str]],
             sources: Optional[Sequence[str]], df_max: float = 0.0) -> List[str]:
        q = fts_query(query)
        if q and df_max > 0:
            words = [w.strip('"') for w in q.split(" OR ")]
            kept = [w for w in words if self.doc_freq(w) <= df_max]
            if kept:
                q = " OR ".join(f'"{w}"' for w in kept)
        if not q:
            return []
        sql = ("SELECT u.unit_id FROM units_fts f JOIN units u ON u.rid = f.rowid "
               "WHERE units_fts MATCH ?")
        args: List[Any] = [q]
        if rng is not None:
            lo, hi = rng.bounds()
            sql += " AND u.t1 >= ? AND u.t0 < ?"
            args += [lo, hi]
        if hosts:
            sql += f" AND u.host IN ({','.join('?' * len(hosts))})"
            args += list(hosts)
        if sources:
            sql += f" AND u.source IN ({','.join('?' * len(sources))})"
            args += list(sources)
        sql += " ORDER BY bm25(units_fts, 0.5, 1.0) LIMIT ?"
        args.append(n)
        try:
            return [r[0] for r in self.db.execute(sql, args)]
        except sqlite3.OperationalError:
            return []

    def _anchor(self, phrase: str) -> Optional[datetime]:
        """'before the interview' -> the date of the best KB hit for 'interview'."""
        hits = self._fts(phrase, 1, None, None, ("kb",))
        r = self._row(hits[0]) if hits else None
        t = _epoch(r["ts_start"]) if r is not None else None
        return datetime.fromtimestamp(t, _IST) if t else None

    def reranker(self) -> Any:
        if self._reranker is None:
            from jarvis_core.memory.rerank import CrossEncoderReranker
            self._reranker = CrossEncoderReranker(device=self.rerank_device)
        return self._reranker

    def search(self, query: str, k: int = 10, time_range: Optional[TimeRange] = None,
               hosts: Optional[Sequence[str]] = None, sources: Optional[Sequence[str]] = None,
               rerank: bool = True, neighbours: int = 1, now: Optional[datetime] = None,
               fetch_k: int = 50, rerank_k: int = 30, time_mode: str = "boost",
               rerank_blend: bool = True, tool_weight: float = 0.3,
               exclude_sessions: Sequence[str] = (),
               factor: Optional[Callable[[sqlite3.Row], float]] = None,
               fts_df_max: float = 0.0, dense_k: Optional[int] = None) -> List[SearchResult]:
        """Hybrid recall. time_mode: 'boost' fuses time-restricted twins into RRF;
        'filter' returns only units inside the range. exclude_sessions drops units
        whose session id starts with any prefix (before the rerank, so they never
        spend a rerank slot); factor(row) multiplies a candidate's fused score
        (a demotion in (0, 1]). Both act on the fused top pool. Each result
        carries the raw signals its rank came from (dense cosine similarity,
        cross-encoder logit) so a caller can judge confidence, not just order.
        fts_df_max > 0 drops keyword terms present in more than that fraction
        of units (they match everything and cost most of the query); dense_k
        sets how many vectors the dense lane fetches."""
        self.check_embedder()
        rng = time_range if time_range is not None else parse_time_range(query, now, self._anchor)
        # Encoding the query (torch, releases the GIL) overlaps with the keyword
        # lanes (sqlite, releases it too): the dense lane is the only consumer.
        qfut = _QUERY_POOL.submit(self.embedder.encode_query, query)
        lists: Dict[str, List[str]] = {}
        weights: Dict[str, float] = {}
        dsim: Dict[str, float] = {}

        def dense(where: Optional[Dict[str, Any]]) -> List[str]:
            ids: List[str] = []
            for uid, dist in self.backend.query(qfut.result(), dense_k or fetch_k, where):
                ids.append(uid)
                dsim[uid] = max(dsim.get(uid, -1.0), 1.0 - float(dist))
            return ids

        allowed = list(sources) if sources else list(SOURCES)
        lane_core = [x for x in allowed if x in self.dense_sources]
        lane_tool = [x for x in allowed if x not in self.dense_sources]
        # Keyword-only units (raw tool output: 225 MB of logs and file dumps)
        # match almost any query on some rare word. They get their own FTS lane
        # at tool_weight so they can surface when they are THE answer, without
        # crowding the exchange that produced or used them.
        if not lane_core:                       # only keyword-only sources asked for: full weight
            lane_core, lane_tool, tool_weight = lane_tool, [], 1.0
        sources = lane_core
        # Only the dense sources have vectors, so when the lane covers all of them
        # the metadata filter on source is redundant and only slows the HNSW query.
        dsrc = None if set(self.dense_sources) <= set(lane_core) else lane_core
        has_dense = any(x in self.dense_sources for x in lane_core)
        if time_mode == "filter" and rng is not None:
            lists["fts"] = self._fts(query, fetch_k, rng, hosts, sources, fts_df_max)
            lists["dense"] = dense(self._where(rng, hosts, dsrc)) if has_dense else []
        else:
            lists["fts"] = self._fts(query, fetch_k, None, hosts, sources, fts_df_max)
            if rng is not None:
                lists["fts_t"] = self._fts(query, fetch_k, rng, hosts, sources, fts_df_max)
            lists["dense"] = dense(self._where(None, hosts, dsrc)) if has_dense else []
            if rng is not None and lists["dense"]:
                lists["dense_t"] = dense(self._where(rng, hosts, dsrc))
        if lane_tool and tool_weight > 0:
            lists["fts_tool"] = self._fts(query, fetch_k, rng if time_mode == "filter" else None, hosts, lane_tool,
                                          fts_df_max)
            weights["fts_tool"] = tool_weight
        fused: Dict[str, float] = {}
        ranks: Dict[str, Dict[str, int]] = {}
        for name, ids in lists.items():
            for r, uid in enumerate(ids):
                fused[uid] = fused.get(uid, 0.0) + weights.get(name, 1.0) / (RRF_K + r)
                ranks.setdefault(uid, {})[name] = r
        order = sorted(fused, key=lambda u: -fused[u])
        seen_rows: Dict[str, Any] = {}
        if exclude_sessions or factor is not None:
            prefixes = tuple(exclude_sessions)
            pool = order[:max(3 * max(k, rerank_k), 90)]
            for uid in pool:
                r = self._row(uid)
                seen_rows[uid] = r
                if r is None or (prefixes and str(r["session_id"]).startswith(prefixes)):
                    fused.pop(uid, None)
                elif factor is not None:
                    fused[uid] *= factor(r)
                    if fused[uid] <= 0.0:
                        fused.pop(uid, None)
            order = sorted((u for u in pool if u in fused), key=lambda u: -fused[u])
        rows = {uid: (seen_rows[uid] if uid in seen_rows else self._row(uid))
                for uid in order[:max(k, rerank_k if rerank else k)]}
        rows = {u: r for u, r in rows.items() if r is not None}
        cand = [u for u in order if u in rows]
        scores = {u: fused[u] for u in cand}
        ce_raw: Dict[str, float] = {}
        if rerank and cand:
            head = cand[:rerank_k]
            ce = self.reranker().rerank(query, [f"{rows[u]['prefix']}\n{rows[u]['body']}" for u in head],
                                        chunk_ids=head, k=len(head))
            ce_raw = {h.chunk_id: float(h.score) for h in ce}
            if rerank_blend:
                # The cross-encoder is a passage ranker trained on web text; on
                # conversation units it is right often but not always. Blending
                # its rank with the hybrid rank keeps a strong first-stage hit
                # from being demoted by one model's opinion.
                ce_rank = {h.chunk_id: r for r, h in enumerate(ce)}
                for r, u in enumerate(head):
                    scores[u] = 1.0 / (RRF_K + ce_rank[u]) + 1.0 / (RRF_K + r)
                    if rng is not None and TimeRange.contains(rng, rows[u]["t0"], rows[u]["t1"]):
                        scores[u] += 1.0 / (RRF_K * 4)
            else:
                for h in ce:
                    bonus = 1.0 if rng is not None and TimeRange.contains(rng, rows[h.chunk_id]["t0"], rows[h.chunk_id]["t1"]) else 0.0
                    scores[h.chunk_id] = h.score + bonus + 1e-3 * scores[h.chunk_id]
            cand = sorted(head, key=lambda u: -scores[u]) + cand[rerank_k:]
        out: List[SearchResult] = []
        for uid in cand[:k]:
            r = rows[uid]
            nbrs: Tuple[str, ...] = ()
            if neighbours and r["source"] == "exchange" and r["episode"]:
                nbrs = tuple(x[0] for x in self.db.execute(
                    "SELECT unit_id FROM units WHERE episode=? AND source='exchange' AND part=0 "
                    "AND seq BETWEEN ? AND ? AND seq != ? ORDER BY seq",
                    (r["episode"], r["seq"] - neighbours, r["seq"] + neighbours, r["seq"])))
            out.append(SearchResult(
                unit_id=uid, source=r["source"], host=r["host"], episode=r["episode"], session_id=r["session_id"],
                turn_ids=tuple(json.loads(r["turn_ids"])), ts_start=r["ts_start"], ts_end=r["ts_end"],
                part=r["part"], parts=r["parts"], score=round(scores[uid], 5), ranks=ranks.get(uid, {}),
                in_time_range=bool(rng and rng.contains(r["t0"], r["t1"])), neighbours=nbrs,
                signals={name: v for name, v in (("dense_sim", dsim.get(uid)), ("ce", ce_raw.get(uid)),
                                                  ("fused", fused.get(uid))) if v is not None}))
        return out


# =============================================================================
# SMOKE TESTS (temp dirs, fake tokenizer + embedder: hermetic, no model download)
# =============================================================================

class _FakeTok:
    """Whitespace tokenizer with offsets — enough to test windowing exactly."""

    def __call__(self, text: Any, add_special_tokens: bool = False, return_offsets_mapping: bool = False,
                 **kw: Any) -> Dict[str, Any]:
        if isinstance(text, list):
            return {"input_ids": [self(t, add_special_tokens)["input_ids"] for t in text]}
        offs = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        extra = 2 if add_special_tokens else 0
        out: Dict[str, Any] = {"input_ids": list(range(len(offs) + extra))}
        if return_offsets_mapping:
            out["offset_mapping"] = offs
        return out


class _FakeEmbedder:
    def __init__(self, max_tokens: int = 40) -> None:
        self.spec = EmbedderSpec("fake", "fake/hash-bow", max_tokens, overlap=5)
        self.tokenizer = _FakeTok()
        self.overflow = 0

    def count(self, text: str) -> int:
        return len(self.tokenizer(text)["input_ids"])

    def _vec(self, text: str) -> Any:
        import numpy as np
        v = np.zeros(64, dtype="float32")
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
        return v / (np.linalg.norm(v) or 1.0)

    def encode_docs(self, texts: List[str]) -> Any:
        import numpy as np
        self.overflow += sum(self.count(t) + 2 > self.spec.max_tokens for t in texts)
        return np.stack([self._vec(t) for t in texts])

    def encode_query(self, text: str) -> Any:
        return self._vec(text)


def _run_self_test() -> None:
    import tempfile
    from jarvis_core.memory.episode_store import EpisodeStore

    print("=" * 70)
    print("  episode_index.py -- Smoke Tests")
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

    now = datetime(2026, 9, 28, 21, 0, tzinfo=_IST)

    def rng(q: str, **kw: Any) -> Optional[Tuple[str, str]]:
        r = parse_time_range(q, now, **kw)
        if r is None:
            return None
        return (r.start.date().isoformat() if r.start else "-", r.end.date().isoformat() if r.end else "-")

    check("P1 'first week of September'", rng("What was I working on in the first week of September?")
          == ("2026-09-01", "2026-09-08"), str(rng("first week of September")))
    check("P2 'on 3 June 2026'", rng("What was I doing on 3 June 2026?") == ("2026-06-03", "2026-06-04"))
    check("P3 'in September' (whole month)", rng("what did I say in September") == ("2026-09-01", "2026-10-01"))
    check("P4 'last week' = previous Mon..Mon (now is a Monday)", rng("what did we do last week") == ("2026-09-21", "2026-09-28"),
          str(rng("last week")))
    check("P5 'this morning' = today", rng("Why couldn't you tell me who Tobu was this morning?")
          == ("2026-09-28", "2026-09-29"))
    check("P6 'early June' = 1-10 June", rng("For the interview I prepared for in early June") ==
          ("2026-06-01", "2026-06-11"), str(rng("in early June")))
    check("P7 'yesterday'", rng("what happened yesterday") == ("2026-09-27", "2026-09-28"))
    check("P8 a month after now resolves to last year", rng("in December") == ("2025-12-01", "2026-01-01"))
    check("P9 'may' as a verb is not a month", rng("I may switch jobs") is None)
    check("P10 'in May 2026'", rng("in May 2026") == ("2026-05-01", "2026-06-01"))
    check("P11 'since August' is open-ended", rng("since August") == ("2026-08-01", "-"))
    check("P12 no time expression -> None", rng("Who is Tobu?") is None)
    check("P13 'before the interview' uses the resolver",
          rng("what was I nervous about before the interview?",
              resolver=lambda p: datetime(2026, 6, 3, tzinfo=_IST) if "interview" in p else None)
          == ("-", "2026-06-03"))
    check("P14 ...and without one yields None", rng("before the interview") is None)
    check("P15 '3 days ago'", rng("what did I say 3 days ago") == ("2026-09-25", "2026-09-26"))
    check("P16 'past two weeks'", rng("over the past two weeks") == ("2026-09-14", "2026-09-28"))
    check("P17 ISO date", rng("on 2026-09-03") == ("2026-09-03", "2026-09-04"))
    check("P18 'Sept 14th'", rng("what did I answer on Sept 14th") == ("2026-09-14", "2026-09-15"))

    tok = _FakeTok()
    text = " ".join(f"w{i}" for i in range(103))
    spans = token_windows(text, 20, 5, tok)
    covered = set()
    for a, b in spans:
        covered.update(range(a, b))
    check("W1 windows cover every character", covered == set(range(len(text))) and spans[0][0] == 0
          and spans[-1][1] == len(text), str(spans))
    check("W2 every window fits the budget", all(len(tok(text[a:b])["input_ids"]) <= 20 for a, b in spans))
    check("W3 consecutive windows overlap", all(spans[i + 1][0] < spans[i][1] for i in range(len(spans) - 1)))

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        root = d / "cs"
        s = EpisodeStore(root=root, machine="alpha", write_shards=False)

        def ev(k: str, role: str, content: str, ts: str, **kw: Any) -> Dict[str, Any]:
            return {"key": k, "ts": ts, "role": role, "content": content, **kw}
        big_output = "\n".join(f"line {i} of the build log for the uttarakhand farm planner" for i in range(60))
        big_write = json.dumps({"file_path": "notes.md", "content": " ".join(f"tok{i}" for i in range(200))})
        s.append("claude", "sess-a", [
            ev("0", "system", "token reminder", "2026-09-01T10:00:00+05:30"),
            ev("1", "user", "My girlfriend Shubha, I call her Tobu.", "2026-09-01T10:00:01+05:30"),
            ev("2", "thinking", "The owner shares a person.", "2026-09-01T10:00:02+05:30"),
            ev("3", "assistant", "Noted: Tobu is Shubha.", "2026-09-01T10:00:03+05:30"),
            ev("4", "tool_call", '{"command": "ls"}', "2026-09-01T10:00:04+05:30",
               tool={"name": "Bash", "id": "t1", "input": {"command": "ls"}}),
            ev("5", "tool_result", big_output, "2026-09-01T10:00:05+05:30", tool={"name": "Bash", "use_id": "t1"}),
            ev("6", "tool_call", big_write, "2026-09-01T10:00:06+05:30",
               tool={"name": "Write", "id": "t2"}),
            ev("7", "user", "Which voice now? Lewis.", "2026-09-05T09:00:00+05:30"),
            ev("8", "assistant", "Switched to Lewis.", "2026-09-05T09:00:05+05:30"),
            ev("9", "user", "and the gpu plan", "2026-09-06T09:00:00+05:30"),
            ev("10", "assistant", "No local GPU purchase.", "2026-09-06T09:00:05+05:30"),
        ])
        s.append("codex", "sess-b", [
            ev("0", "user", "Summarise the Databricks exam attempt.", "2026-06-10T10:00:00+05:30"),
            ev("1", "assistant", "You attempted the Databricks Data Engineer Professional exam.", "2026-06-10T10:00:10+05:30"),
            ev("2", "compaction", "[replacement_history]\n" + json.dumps(
                [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "exam recap"},
                                                                  {"type": "input_image", "image_url": "data:x"}]},
                 {"type": "compaction", "encrypted_content": "gAAAA"}]), "2026-06-10T11:00:00+05:30"),
        ])
        queue = d / "q.jsonl"
        qrows = [
            {"ts": "2026-09-01T10:01:00+05:30", "session_id": "sess-a", "host": "claude", "chat_label": "JARVIS",
             "user_text": "My girlfriend Shubha, I call her Tobu.", "assistant_summary": "Noted."},
            {"ts": "2026-08-16T20:10:17+05:30", "session_id": "other-laptop", "host": "claude",
             "user_text": "My elder sister is a Business Analyst at ADP.", "assistant_summary": "Got it.",
             "machine": "HRM"},
        ]
        queue.write_text("".join(json.dumps(r) + "\n" for r in qrows), encoding="utf-8")
        cur = d / "c.jsonl"
        cur.write_text(json.dumps({"ts": qrows[0]["ts"], "session_id": "sess-a",
                                   "responds_to": "the owner introducing people"}) + "\n", encoding="utf-8")
        kb = d / "kb.jsonl"
        kb_rows = [
            {"timestamp": "2026-04-17T10:00:00+05:30", "type": "Episodic", "tags": ["identity"],
             "content": "First production project: Apollo Dynamics 365 Gen2 pipeline."},
            {"id": 801, "timestamp": "2026-09-28T18:00:00+05:30", "type": "Semantic",
             "tags": ["distilled", "person", "source-claude", "person-shubha"],
             "content": "The owner's girlfriend is Shubha, called Tobu. (Shubha)\n\nEvidence, in the owner's "
                        "words (2026-09-01, claude): \"My girlfriend Shubha, I call her Tobu.\""},
            {"id": 802, "timestamp": "2026-09-28T18:00:00+05:30", "type": "Semantic",
             "tags": ["distilled", "person", "source-claude"],
             "content": "The owner's sister is a BA.\n\nEvidence, in the owner's words (2026-08-16, claude): "
                        "\"My elder sister is a Business Analyst at ADP.\""},
        ]
        kb.write_text("".join(json.dumps(r) + "\n" for r in kb_rows), encoding="utf-8")
        docs = d / "repo"
        (docs / "jarvis_data").mkdir(parents=True)
        (docs / "jarvis_data" / "personal_life.md").write_text(
            "# Personal Life\n\n## Family\nParents live in Raigad.\n\n## Fitness\nBench 90 kg.\n", encoding="utf-8")
        prov = d / "prov.jsonl"

        tid = queue_to_turn(qrows[0]["ts"], "sess-a", qrows[0]["user_text"], root=root)
        check("M1 a queue row maps to the owner message it was written for", tid == "turn:claude:sess-a:1", str(tid))
        check("M2 a session absent from the store maps to None",
              queue_to_turn(qrows[1]["ts"], "other-laptop", root=root) is None)
        fields = fact_source_fields(qrows[0]["ts"], "sess-a", qrows[0]["user_text"], root=root)
        check("M3 new-fact fields: source_turn + two timelines",
              fields["source_turn"] == tid and fields["valid_from"] == qrows[0]["ts"]
              and fields["valid_to"] is None and fields["recorded_at"], str(fields))

        bst = backfill_provenance(kb, prov, queue, root)
        pv = load_provenance(kb, prov)
        check("M4 backfill resolves a distilled fact to its store turn",
              pv.get("kb:801", {}).get("source_turn") == "turn:claude:sess-a:1", str(pv))
        check("M5 ...and records queue-only provenance when the store lacks the session",
              pv.get("kb:802", {}).get("source_queue", "").startswith("queue:2026-08-16")
              and not pv["kb:802"].get("source_turn"), str(bst))
        size = prov.stat().st_size
        backfill_provenance(kb, prov, queue, root)
        check("M6 re-running backfill appends nothing", prov.stat().st_size == size)

        emb = _FakeEmbedder(max_tokens=80)
        backend = NumpyBackend(d / "vec.npz")
        idx = EpisodeIndex(fts_path=d / "fts.sqlite3", backend=backend, embedder=emb, store_root=root,
                           kb_path=kb, queue_path=queue, curation_path=cur, prov_path=prov,
                           doc_root=docs, doc_files=("jarvis_data/personal_life.md",))
        st1 = idx.build(rebuild=True, log=lambda s: None)
        stat = idx.status()
        check("I1 every source kind is indexed", {"exchange", "tool_result", "tool_call", "compaction",
                                                  "kb", "doc", "queue"} <= set(stat["by_source"]), str(stat))
        check("I2 no window overflows the embedder", st1["overflow_windows"] == 0, str(st1))
        check("I3 system events are skipped and counted", st1.get("system_events_skipped") == 1, str(st1))
        x0 = idx.read_unit("ep:claude:sess-a|x1|w0")
        check("I4 an exchange holds owner + reasoning + assistant + compact tool list",
              x0 is not None and "[owner] My girlfriend" in x0["text"] and "[reasoning]" in x0["text"]
              and "[tool] Bash" in x0["text"], str(x0 and x0["text"]))
        check("I5 the prefix carries host, date, chat label, responds_to and the distilled fact",
              x0 is not None and "claude" in x0["prefix"] and "2026-09-01" in x0["prefix"]
              and "chat: JARVIS" in x0["prefix"] and "introducing people" in x0["prefix"]
              and "girlfriend is Shubha" in x0["prefix"], str(x0 and x0["prefix"]))
        long_tool = idx.unit_windows("ep:claude:sess-a|r5|w0")
        bodies = [idx.read_unit(u)["body"] for u in long_tool]
        check("I6 a long tool output is windowed; the windows run start to end and overlap",
              len(bodies) > 1 and all(b in big_output for b in bodies) and big_output.startswith(bodies[0])
              and big_output.endswith(bodies[-1])
              and all(bodies[i + 1][:12] in bodies[i] for i in range(len(bodies) - 1)), str(len(bodies)))
        wid = "ep:claude:sess-a|c6|w0"
        check("I7 a long tool input is its own unit and the exchange points to it",
              idx.read_unit(wid) is not None and "unit ep:claude:sess-a|c6" in "".join(
                  idx.read_unit(u)["text"] for u in idx.unit_windows("ep:claude:sess-a|x1|w0")))
        comp = idx.read_unit("ep:codex:sess-b|p2|w0")
        check("I8 compaction text is extracted (no encrypted blob, image as a marker)",
              comp is not None and "exam recap" in comp["body"] and "gAAAA" not in comp["body"]
              and "[image]" in comp["body"], str(comp and comp["body"]))
        q = idx.read_unit("queue|queue:2026-08-16T20:10:17+05:30|other-laptop|w0")
        check("I9 a capture row whose session is not in the store is its own unit, with its fact",
              q is not None and "Business Analyst" in q["body"] and "sister is a BA" in q["prefix"], str(q))
        check("I10 KB rows without an id are kb:line<N> (1-based)",
              idx.read_unit("kb|kb:line1|w0") is not None)

        res = idx.search("who is Tobu girlfriend", k=5, rerank=False, now=now)
        check("S1 hybrid search finds the exchange", any(r.unit_id.startswith("ep:claude:sess-a|x1") for r in res),
              str([r.unit_id for r in res]))
        top = next(r for r in res if r.unit_id.startswith("ep:claude:sess-a|x1"))
        check("S2 results are pointers: store turn ids + ranks, neighbours for exchanges",
              "turn:claude:sess-a:1" in top.turn_ids and top.ranks and top.neighbours
              == ("ep:claude:sess-a|x7|w0",), str(top))
        res_t = idx.search("what did I decide about the voice in the first week of September", k=3,
                           rerank=False, now=now, time_mode="filter")
        check("S3 time filter keeps only in-range units",
              res_t and all(r.in_time_range for r in res_t) and all(r.ts_start >= "2026-09-01" for r in res_t),
              str([(r.unit_id, r.ts_start) for r in res_t]))
        check("S4 host filter", all(r.host == "codex" for r in idx.search("exam", k=5, hosts=["codex"],
                                                                          rerank=False, now=now)))

        st2 = idx.build(log=lambda s: None)
        check("I11 an unchanged rebuild embeds nothing", st2.get("embedded", 0) == 0
              and st2.get("sources_synced", 0) == 0, str(st2))
        s.append("claude", "sess-a", [ev("11", "user", "one more question about Raigad",
                                         "2026-09-07T09:00:00+05:30"),
                                      ev("12", "assistant", "Your parents live there.", "2026-09-07T09:00:05+05:30")])
        st3 = idx.build(log=lambda s: None)
        check("I12 an appended exchange is embedded incrementally; the rest is unchanged",
              st3.get("embedded", 0) == 1 and st3.get("unchanged", 0) > 3 and st3.get("sources_synced") == 1,
              str(st3))
        other = EpisodeIndex(fts_path=d / "fts.sqlite3", backend=backend,
                             embedder=type("E", (), {"spec": EmbedderSpec("x", "other/model", 40)})(),
                             store_root=root)
        try:
            other.check_embedder()
            check("I13 querying with a different embedder is refused", False)
        except EmbedderMismatch:
            check("I13 querying with a different embedder is refused", True)
        other.close()
        n_vec, n_units = idx.status()["vectors"], idx.status()["units"]
        tr = idx.status()["by_source"].get("tool_result", 0) + idx.status()["by_source"].get("tool_call", 0)
        check("I14 tool units are keyword-only by default (no vectors), everything else is dense",
              tr > 0 and n_vec == n_units - tr, f"{n_vec} vectors, {n_units} units, {tr} tool units")
        hit = idx.search("build log uttarakhand farm planner line 57", k=20, rerank=False, now=now)
        only = idx.search("build log uttarakhand farm planner line 57", k=3, rerank=False, now=now,
                          sources=["tool_result"])
        check("I15 keyword-only tool output surfaces in the default lane and alone when asked for",
              any(r.source == "tool_result" and "fts_tool" in r.ranks for r in hit)
              and only and all(r.source == "tool_result" for r in only), str([(r.unit_id, r.ranks) for r in hit]))
        idx.close()

        # a rebuild in a scratch index re-uses vectors computed for identical text
        class _Counting(_FakeEmbedder):
            calls = 0

            def encode_docs(self, texts: List[str]) -> Any:
                type(self).calls += len(texts)
                return super().encode_docs(texts)
        backend.save()
        cemb = _Counting(max_tokens=80)
        seeded = EpisodeIndex(fts_path=d / "fts2.sqlite3", backend=NumpyBackend(), embedder=cemb,
                              store_root=root, kb_path=kb, queue_path=queue, curation_path=cur,
                              prov_path=prov, doc_root=docs, doc_files=("jarvis_data/personal_life.md",),
                              vector_seed=(d / "fts.sqlite3", d / "vec.npz"))
        st4 = seeded.build(rebuild=True, log=lambda s: None)
        check("I16 a rebuild takes identical-text vectors from the seed and embeds nothing",
              _Counting.calls == 0 and st4.get("seeded", 0) > 5, f"{_Counting.calls} embedded, {st4}")
        seeded.close()

    total = passed + len(failed)
    print("-" * 70)
    print(f"  {passed}/{total} passed")
    for name in failed:
        print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    _run_self_test()

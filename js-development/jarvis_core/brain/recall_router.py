"""
recall_router.py — the standing core plus per-question recall (Context Store, Layer 2).

LAYER: Brain (Cognitive Control Loop — what the prompt carries, and what it fetches)

Import with:
    from jarvis_core.brain.recall_router import RecallRouter, get_router, standing_core

Run with:
    cd js-development && PYTHONPATH=. python -m jarvis_core.brain.recall_router --self-test
    cd js-development && PYTHONPATH=. python -m jarvis_core.brain.recall_router --core
    cd js-development && PYTHONPATH=. python -m jarvis_core.brain.recall_router --ask "who is Tobu"

=============================================================================
THE BIG PICTURE
=============================================================================

Every turn used to carry the whole 674K-char cognitive profile, about 168K
tokens, 84% of the free model's window, and the model answered from it with
64.1% accuracy on the owner's own recall questions (scripts/eval_recall.py):
long context rots. This module splits the prompt in two.

  The STANDING CORE (always loaded, cached). The profile's identity, people and
  recent-corrections sections, whole; the personal-life file; the next task;
  pipeline health; the clock. About 15K tokens. It holds who the owner is. The
  rest of the profile ("How you work", "Other observed patterns", ...) is
  derived from the knowledge base, and the knowledge base is indexed, so recall
  reaches it when a question needs it.

  PER-QUESTION RECALL (this module's router). The question goes to the episode
  index (hybrid dense + keyword, cross-encoder rerank, time hints), the current
  session is excluded (it is already in the history), units that are only
  discussion ABOUT the memory system are demoted, and the survivors are read
  WHOLE in rank order until the token budget is spent. What does not fit is
  named by id so the reasoning loop can open it (agent/tools/recall.py).
  Nothing shown is ever cut: a unit is inlined whole, or (when one unit alone
  is bigger than the budget allows) its matching window is inlined and labelled
  as window k of n, or it is only named.

No LLM call happens on this path. When nothing scores high enough the block
says so out loud ("No stored memory matched this question") so the model can
answer "I don't have that" instead of guessing.

=============================================================================
THE FLOW
=============================================================================

STEP 1: plan_queries(): the question, plus deterministic sub-queries when it
        enumerates ("X, Y and Z"). A second pass reuses entities found in the
        first pass's best hits (Personalized-PageRank's poor cousin, no graph).
        |
STEP 2: EpisodeIndex.search() per query: excludes the current session and any
        unit that quotes the eval harness, multiplies meta-discussion units by
        a demotion factor, rerank on the fused head. Time hints are parsed by
        the index from the question itself.
        |
STEP 3: fuse the passes by weighted reciprocal rank; take confidence from the
        question's own pass (cross-encoder logit, dense similarity).
        |
STEP 4: fit the token budget by reading whole units in rank order; neighbours
        of the top hits after the primary hits; the rest become handles.
        |
STEP 5: render the block (or the explicit abstention block).
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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety

from jarvis_core.config import DATA_ROOT  # noqa: E402

_IST = timezone(timedelta(hours=5, minutes=30))

CHARS_PER_TOKEN = 3.6            # conservative; the profile measured 3.9 (655K chars = 168K tokens)
CORE_TOKEN_TARGET = 15_000
DEFAULT_BUDGET_TOKENS = 8_000
ITEM_SHARE = 0.4                 # one unit above this share of the budget is windowed, not inlined
RRF_K = 60

# Text that belongs to the measurement harness, not to the owner's life. A unit
# that quotes it (a tool result holding recall_eval.jsonl, an assistant message
# listing gold answers) would let the eval read its own answer key.
CONTAMINATION_MARKERS = ("recall_eval", "gold_answer", "required_facts", "eval_recall", "eval_c002")


def contamination_markers() -> Tuple[str, ...]:
    """The static markers plus the c002 canaries, which are generated per install."""
    from jarvis_core.specialists.eval_exclusions import load_registry
    return CONTAMINATION_MARKERS + tuple(c.lower() for c in load_registry().canaries)

# Vocabulary of talking ABOUT the memory system. Sessions dense in it are
# usually the owner and an agent debugging recall ("why did you not know Tobu"),
# and their text outranks the original statement because it repeats the same
# names many times. Demotion is skipped when the question is itself about the
# memory system.
_META = re.compile(
    r"\b(recall\w*|retriev\w*|rerank\w*|embedd?\w*|episode\w*|context store|eval\w*|ablation|"
    r"abstention|benchmark\w*|latenc\w+|chroma\w*|bm25|fts5?|vector\w*|reindex\w*|inhale|"
    r"standing core|memory contract|hallucinat\w*|prompt tokens|first token)\b", re.I)
META_UNIT_MIN_HITS = 3
META_QUESTION_MIN_HITS = 2

_SPLIT = re.compile(r",\s*(?:and\s+)?|;\s*|\s+and\s+|\s+as well as\s+|\s+versus\s+|\s+vs\.?\s+|\s+or\s+", re.I)
_STOP = frozenset("""a an and are as at be been but by can could did do does doing done for from had has have how
i if in into is it its just me my of on or our so than that the their them then there these they this those to was
we were what when where which who whom why will with would you your yours about tell""".split())
_CAP_STOP = frozenset("""The This That These Those What Why How When Where Which Who And But For With From Not Also
Here There Yes Yeah Okay User Owner Assistant Claude JARVIS Jarvis Codex Sir Now Then Just Some Any All One Two
Its And Are Was Were Can Could Would Should Will Did Does Has Have Had You Your Our Their Them Then Let Use Using
Note Done Today Tomorrow Yesterday Monday Tuesday Wednesday Thursday Friday Saturday Sunday Please Thanks""".split())
_CAPS = re.compile(r"\b[A-Z][A-Za-z0-9_\-]{2,}\b")
_MULTI_CUES = re.compile(
    r"\b(all|every|both|over time|so far|history|timeline|what have|have i|how many|tell me about|"
    r"across|which (?:models|companies|pieces|tools)|what did i (?:say|tell)|what came out|what happened)\b", re.I)


# =============================================================================
# Part 1: THE STANDING CORE
# =============================================================================

@dataclass(frozen=True)
class CoreReport:
    block: str
    section_chars: Dict[str, int]
    chars: int
    tokens_est: int
    over_target: bool


def standing_core(injector_factory: Optional[Callable[[], Any]] = None) -> CoreReport:
    """The always-loaded block and what each section costs. Sections are whole."""
    from jarvis_core.brain.context_injector import CORE_SECTIONS, ContextInjector, default_providers
    by_name = {s.name: s for s in default_providers(core=True)}
    specs = [by_name[n] for n in CORE_SECTIONS if n in by_name]
    sizes: Dict[str, int] = {}
    for spec in specs:
        try:
            sizes[spec.name] = len(spec.provider() or "")
        except Exception:                                    # noqa: BLE001 — reported as 0, never raised
            sizes[spec.name] = 0
    injector = injector_factory() if injector_factory else ContextInjector(specs)
    block = injector.inhale().block
    tokens = int(len(block) / CHARS_PER_TOKEN)
    return CoreReport(block=block, section_chars=sizes, chars=len(block), tokens_est=tokens,
                      over_target=tokens > CORE_TOKEN_TARGET)


# =============================================================================
# Part 2: RESULT CONTRACTS
# =============================================================================

@dataclass(frozen=True)
class RecallItem:
    ref: str                  # what the model can open: the first store turn id, else the unit id
    unit_id: str
    source: str
    host: str
    ts: str
    chars: int                # size of the whole unit (an estimate for a handle)
    shown: str                # full | window | neighbour | handle
    score: float
    text: str                 # "" for a handle
    turns: Tuple[str, ...] = ()   # every store turn / kb / file id the unit covers


@dataclass(frozen=True)
class RecallResult:
    block: str
    items: Tuple[RecallItem, ...]
    ranked: Tuple[str, ...]                     # every candidate unit id, best first, before the budget
    ranked_turns: Tuple[Tuple[str, ...], ...]   # their store turn ids
    confidence: Dict[str, float]
    abstained: bool
    searched: int
    queries: Tuple[str, ...]
    timings: Dict[str, float]
    error: str = ""                                 # set when the search itself could not run

    @property
    def context_ids(self) -> List[str]:
        return [t for i in self.items if i.shown != "handle" for t in (i.turns or (i.ref,))]

    @property
    def shown_chars(self) -> int:
        return sum(len(i.text) for i in self.items)


@dataclass
class RecallConfig:
    rerank: bool = True
    rerank_k: int = 20
    fetch_k: int = 60
    dense_k: int = 40
    fts_df_max: float = 0.05
    pool_k: int = 12                 # candidates kept after fusion
    second_pass: str = "auto"        # never | auto (multi-session cues) | always
    sub_queries: int = 3
    tool_lane: bool = False
    meta_weight: float = 0.6
    # Calibrated on the 78-question set with the voice preset: abstaining when the
    # best cross-encoder logit < 0 AND the best dense similarity < 0.61 catches 5 of
    # 13 abstention questions and none of the 65 answerable ones. The rest of the
    # abstention questions are about a topic that IS in memory (the sister exists,
    # her name does not): only the model reading the passages can decline those.
    abstain_ce: float = 0.0
    abstain_dense: float = 0.61
    neighbours: int = 3              # neighbour units for the top N hits, budget permitting
    # A question that asks for several things across sessions ("what have I told you
    # about...", "X and Y") needs a wider net than a single-fact lookup; when its
    # wording says so, this preset replaces the fast one for that question only.
    multi: Optional["RecallConfig"] = None


DEEP = RecallConfig(rerank_k=30, fetch_k=80, dense_k=60, second_pass="auto", sub_queries=3)
VOICE = RecallConfig(rerank_k=12, fetch_k=40, dense_k=30, second_pass="never", sub_queries=0, multi=DEEP)


# =============================================================================
# Part 3: PURE HELPERS (no index needed)
# =============================================================================

def content_words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9_]+", text.lower()) if len(w) > 2 and w not in _STOP]


def plan_queries(question: str, max_subs: int = 3) -> List[str]:
    """Sub-queries from an enumerating question: 'X, Y and Z' -> X, Y, Z (each with
    at least two content words). Empty when the question is a single ask."""
    parts = [p.strip(" ?.!") for p in _SPLIT.split(question)]
    parts = [p for p in parts if len(content_words(p)) >= 2]
    return parts[:max_subs] if len(parts) >= 2 else []


def looks_multi(question: str) -> bool:
    return bool(_MULTI_CUES.search(question)) or len(plan_queries(question)) >= 2


def meta_hits(text: str) -> int:
    return len({m.group(0).lower() for m in _META.finditer(text)})


def merge_windows(a: str, b: str) -> str:
    """Join two consecutive overlapping windows of one unit without repeating the
    overlap: the longest tail of `a` that is also the head of `b` is written once."""
    probe = b[:16]
    lo = max(0, len(a) - 6000)
    pos = a.find(probe, lo)
    while pos != -1:
        if b.startswith(a[pos:]):
            return a + b[len(a) - pos:]
        pos = a.find(probe, pos + 1)
    return a + "\n" + b


def entity_terms(texts: Sequence[str], question: str, df: Callable[[str], float],
                 limit: int = 3, rare_below: float = 0.02) -> List[str]:
    """Names and terms that recur across the best hits but are not in the question."""
    asked = set(content_words(question))
    counts: Dict[str, int] = {}
    for t in texts:
        for w in {m.group(0) for m in _CAPS.finditer(t)}:
            if w in _CAP_STOP or w.lower() in asked or w.lower() in _STOP:
                continue
            counts[w] = counts.get(w, 0) + 1
    ranked = sorted((w for w, c in counts.items() if c >= 2), key=lambda w: (-counts[w], w))
    out: List[str] = []
    for w in ranked:
        if df(w.lower()) <= rare_below:
            out.append(w)
        if len(out) >= limit:
            break
    return out


def fuse(passes: Sequence[Tuple[float, Sequence[str]]]) -> List[str]:
    """Weighted reciprocal-rank fusion of ranked id lists."""
    score: Dict[str, float] = {}
    for weight, ids in passes:
        for rank, uid in enumerate(ids):
            score[uid] = score.get(uid, 0.0) + weight / (RRF_K + rank)
    return sorted(score, key=lambda u: -score[u])


def est_tokens(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN)


# =============================================================================
# Part 4: THE ROUTER
# =============================================================================

class RecallRouter:
    """One warm EpisodeIndex, one lock. Query encoding runs on CPU (about 100 ms)
    so the GPU stays with the hearth's speech models."""

    def __init__(self, index: Optional[Any] = None, config: Optional[RecallConfig] = None,
                 exclude_sessions: Sequence[str] = (), device: str = "cpu",
                 rerank_device: Optional[str] = None,
                 now_fn: Optional[Callable[[], datetime]] = None) -> None:
        self._index = index
        self._device = device                 # query encoder: CPU (about 100 ms) keeps VRAM for the speech models
        self._rerank_device = rerank_device   # cross-encoder: auto (GPU when present); on CPU it is ~10x slower
        self.config = config or DEEP
        self.exclude_sessions = tuple(exclude_sessions)
        self._now = now_fn or (lambda: datetime.now(_IST))
        self._lock = threading.RLock()
        self._session_share: Dict[str, Tuple[int, float]] = {}
        self._shares_loaded = False
        self._searched: Optional[int] = None

    # ---- plumbing -------------------------------------------------------

    @property
    def index(self) -> Any:
        if self._index is None:
            from jarvis_core.memory import episode_index as ei
            self._index = ei.EpisodeIndex(embedder=ei.Embedder(ei.EMBEDDERS[ei.DEFAULT_EMBEDDER],
                                                               device=self._device),
                                          rerank_device=self._rerank_device)
        return self._index

    def warm(self) -> Dict[str, float]:
        """Load the query encoder, the reranker, the vocabulary and page the FTS
        index in, so the first spoken question pays none of it (measured 25-30 s)."""
        t0 = time.perf_counter()
        with self._lock:
            self.index.check_embedder()
            self.ensure_shares()
            self.recall("warm up the memory index", session_id="__warm__",
                        config=RecallConfig(**{**self.config.__dict__, "second_pass": "never"}),
                        budget_tokens=500)
        return {"warm_s": round(time.perf_counter() - t0, 2)}

    def searched_sources(self) -> int:
        if self._searched is None:
            try:
                self._searched = int(self.index.status()["sources"])
            except Exception:                                # noqa: BLE001
                self._searched = 0
        return self._searched

    # ---- demotion -------------------------------------------------------

    def _load_shares(self) -> None:
        db = self.index.db
        db.execute("CREATE TABLE IF NOT EXISTS session_meta(episode TEXT PRIMARY KEY, n INTEGER, share REAL)")
        self._session_share = {e: (n, s) for e, n, s in db.execute("SELECT episode, n, share FROM session_meta")}
        self._shares_loaded = True

    def _compute_share(self, episode: str) -> Tuple[int, float]:
        hot = total = 0
        for (body,) in self.index.db.execute(
                "SELECT body FROM units WHERE episode=? AND source='exchange' AND part=0", (episode,)):
            total += 1
            hot += meta_hits(body) >= META_UNIT_MIN_HITS
        return total, (hot / total if total else 0.0)

    def ensure_shares(self) -> int:
        """Score every session that is new or whose exchange count moved by more than 20%.
        Persisted in the index database so a restart pays it once, not per query."""
        if not self._shares_loaded:
            self._load_shares()
        db = self.index.db
        counts = dict(db.execute("SELECT episode, COUNT(*) FROM units WHERE source='exchange' AND part=0 "
                                 "AND episode != '' GROUP BY episode"))
        stale = [e for e, n in counts.items()
                 if e not in self._session_share or abs(self._session_share[e][0] - n) > max(2, 0.2 * self._session_share[e][0])]
        for e in stale:
            n, share = self._compute_share(e)
            self._session_share[e] = (n, share)
            db.execute("INSERT OR REPLACE INTO session_meta(episode, n, share) VALUES (?, ?, ?)", (e, n, share))
        if stale:
            db.commit()
        return len(stale)

    def _share(self, episode: str) -> float:
        """Fraction of a session's exchanges that are dense in memory-system talk."""
        if not episode:
            return 0.0
        if not self._shares_loaded:
            self._load_shares()
        cached = self._session_share.get(episode)
        if cached is not None:
            return cached[1]
        n, share = self._compute_share(episode)
        self._session_share[episode] = (n, share)
        self.index.db.execute("INSERT OR REPLACE INTO session_meta(episode, n, share) VALUES (?, ?, ?)",
                              (episode, n, share))
        self.index.db.commit()
        return share

    def _factor(self, question: str, weight: float) -> Callable[[Any], float]:
        asked_meta = meta_hits(question) >= META_QUESTION_MIN_HITS
        eval_q = question.lower()
        markers = contamination_markers()

        def factor(row: Any) -> float:
            text = f"{row['prefix']}\n{row['body']}".lower()
            if any(m in text and m not in eval_q for m in markers):
                return 0.0
            if asked_meta or weight <= 0:
                return 1.0
            unit_meta = min(1.0, meta_hits(text) / 5.0)
            return max(0.05, 1.0 - weight * (0.5 * self._share(row["episode"]) + 0.5 * unit_meta))
        return factor

    # ---- reading --------------------------------------------------------

    def read_unit_whole(self, unit_id: str) -> Tuple[str, int]:
        """(prefix + the unit's whole body, number of windows). Windows overlap; the
        overlap is removed so the text is the unit exactly once."""
        parts = self.index.unit_parts(unit_id)
        if not parts:
            return "", 0
        body = parts[0]["body"]
        for p in parts[1:]:
            body = merge_windows(body, p["body"])
        prefix = parts[0]["prefix"]
        return (f"{prefix}\n{body}" if prefix else body), len(parts)

    # ---- the pipeline ---------------------------------------------------

    def _search(self, query: str, cfg: RecallConfig, exclude: Sequence[str], factor: Callable[[Any], float],
                sources: Optional[Sequence[str]], time_range: Any, hosts: Optional[Sequence[str]],
                rerank: bool, time_mode: str = "boost") -> List[Any]:
        return self.index.search(
            query, k=cfg.pool_k, time_range=time_range, hosts=hosts, sources=sources, rerank=rerank,
            time_mode=time_mode,
            rerank_k=cfg.rerank_k, fetch_k=cfg.fetch_k, dense_k=cfg.dense_k, fts_df_max=cfg.fts_df_max,
            neighbours=1, now=self._now(), exclude_sessions=exclude, factor=factor)

    def recall(self, question: str, session_id: str = "", budget_tokens: int = DEFAULT_BUDGET_TOKENS,
               time_range: Any = None, hosts: Optional[Sequence[str]] = None,
               config: Optional[RecallConfig] = None, openable: bool = True,
               time_mode: str = "boost") -> RecallResult:
        cfg = config or self.config
        if cfg.multi is not None and looks_multi(question):
            cfg = cfg.multi
        timings: Dict[str, float] = {}
        t_all = time.perf_counter()
        exclude = tuple(x for x in (session_id, *self.exclude_sessions) if x)
        with self._lock:
            from jarvis_core.memory import episode_index as ei
            sources = None if cfg.tool_lane else list(ei.CORE_SOURCES)
            factor = self._factor(question, cfg.meta_weight)

            t = time.perf_counter()
            try:
                for attempt in (0, 1):
                    try:
                        if self.index.backend.count() == 0:
                            raise RuntimeError("the vector index is empty (rebuild it: "
                                               "python scripts/index_episodes.py --rebuild)")
                        first = self._search(question, cfg, exclude, factor, sources, time_range, hosts, cfg.rerank, time_mode)
                        break
                    except Exception:                       # noqa: BLE001 — another process may be compacting the store
                        if attempt:
                            raise
                        time.sleep(0.7)
            except Exception as e:                          # noqa: BLE001 — a dead index must be said, never silent
                timings["total"] = round(time.perf_counter() - t_all, 3)
                return RecallResult(
                    block=(f"RECALLED MEMORY: the memory search could not run just now ({type(e).__name__}: {e}). "
                           f"Answer only from the standing context above; if it does not hold the fact, tell the "
                           f"owner plainly that your memory search is unavailable rather than guessing."),
                    items=(), ranked=(), ranked_turns=(), confidence={}, abstained=False, searched=0,
                    queries=(question,), timings=timings, error=f"{type(e).__name__}: {e}")
            timings["search"] = round(time.perf_counter() - t, 3)
            passes: List[Tuple[float, List[str]]] = [(1.0, [r.unit_id for r in first])]
            by_id = {r.unit_id: r for r in first}
            queries = [question]

            t = time.perf_counter()
            subs = plan_queries(question, cfg.sub_queries) if cfg.sub_queries else []
            for sq in subs:
                res = self._search(sq, cfg, exclude, factor, sources, time_range, hosts, False, time_mode)
                passes.append((0.7, [r.unit_id for r in res]))
                by_id.update({r.unit_id: by_id.get(r.unit_id, r) for r in res})
                queries.append(sq)
            run_second = cfg.second_pass == "always" or (cfg.second_pass == "auto" and looks_multi(question))
            if run_second and first:
                texts = []
                for r in first[:5]:
                    row = self.index._row(r.unit_id)
                    if row is not None:
                        texts.append(f"{row['prefix']}\n{row['body']}")
                ents = entity_terms(texts, question, self.index.doc_freq)
                if ents:
                    q2 = " ".join(ents) + " " + " ".join(content_words(question)[:6])
                    res = self._search(q2, cfg, exclude, factor, sources, time_range, hosts, False, time_mode)
                    passes.append((0.5, [r.unit_id for r in res]))
                    by_id.update({r.unit_id: by_id.get(r.unit_id, r) for r in res})
                    queries.append(q2)
            timings["extra_passes"] = round(time.perf_counter() - t, 3)

            ranked = fuse(passes)[:cfg.pool_k] if len(passes) > 1 else [r.unit_id for r in first]
            conf = self._confidence(first)
            abstained = bool(not first) or self._abstain(conf, cfg)

            t = time.perf_counter()
            items = [] if abstained else self._fit(ranked, by_id, budget_tokens, cfg)
            timings["read"] = round(time.perf_counter() - t, 3)
            block = self._render(items, abstained, budget_tokens, openable)
            timings["total"] = round(time.perf_counter() - t_all, 3)
            return RecallResult(
                block=block, items=tuple(items), ranked=tuple(ranked),
                ranked_turns=tuple(by_id[u].turn_ids if u in by_id else () for u in ranked),
                confidence=conf, abstained=abstained, searched=self.searched_sources(),
                queries=tuple(queries), timings=timings)

    @staticmethod
    def _confidence(results: Sequence[Any]) -> Dict[str, float]:
        ce = [r.signals["ce"] for r in results if "ce" in r.signals]
        dense = [r.signals["dense_sim"] for r in results if "dense_sim" in r.signals]
        return {"ce_top": max(ce) if ce else float("nan"), "dense_top": max(dense) if dense else float("nan"),
                "n": float(len(results))}

    @staticmethod
    def _abstain(conf: Dict[str, float], cfg: RecallConfig) -> bool:
        ce, dense = conf["ce_top"], conf["dense_top"]
        weak_ce = ce != ce or ce < cfg.abstain_ce            # NaN (no rerank ran) counts as weak
        weak_dense = dense != dense or dense < cfg.abstain_dense
        return weak_ce and weak_dense

    def _fit(self, ranked: Sequence[str], by_id: Dict[str, Any], budget_tokens: int,
             cfg: RecallConfig) -> List[RecallItem]:
        budget = int(budget_tokens * CHARS_PER_TOKEN)
        cap = int(budget * ITEM_SHARE)
        used = 0
        items: List[RecallItem] = []
        done: set = set()

        def base(uid: str) -> str:
            return uid.rsplit("|w", 1)[0]

        def place(uid: str, score: float, shown_as: str) -> None:
            nonlocal used
            b = base(uid)
            if b in done:
                return
            done.add(b)
            row = self.index._row(uid)
            if row is None:
                return
            turn_ids = json.loads(row["turn_ids"])
            ref = turn_ids[0] if turn_ids else uid
            # Windows of one unit are about the same length, so parts x this window
            # sizes the unit without reading the rest of it (an estimate: it is only
            # used to skip reading what cannot fit, and to size a handle).
            est = row["parts"] * len(row["body"]) + len(row["prefix"])
            head = dict(unit_id=uid, source=row["source"], host=row["host"], ts=row["ts_start"] or "",
                        chars=est, score=score, ref=ref, turns=tuple(turn_ids))
            if used + 160 >= budget:
                items.append(RecallItem(shown="handle", text="", **head))
                return
            parts = row["parts"]
            if est <= 2 * cap:
                whole, parts = self.read_unit_whole(uid)
                head["chars"] = len(whole)
                if len(whole) <= cap and used + len(whole) + 160 <= budget:
                    used += len(whole) + 160
                    items.append(RecallItem(shown=shown_as, text=whole, **head))
                    return
            if parts > 1 and shown_as == "full":
                hit = self.index.read_unit(uid)
                win = hit["text"] if hit else ""
                if win and len(win) + 160 <= min(cap, budget - used):
                    used += len(win) + 160
                    items.append(RecallItem(shown="window", text=f"(window {row['part'] + 1} of {row['parts']} "
                                                                 f"of this unit)\n{win}", **head))
                    return
            items.append(RecallItem(shown="handle", text="", **head))

        for rank, uid in enumerate(ranked):
            place(uid, 1.0 / (RRF_K + rank), "full")
        for uid in ranked[:cfg.neighbours]:
            row = self.index._row(uid)
            if row is None or row["source"] != "exchange" or not row["episode"]:
                continue
            for (nid,) in self.index.db.execute(
                    "SELECT unit_id FROM units WHERE episode=? AND source='exchange' AND part=0 "
                    "AND seq BETWEEN ? AND ? AND seq != ? ORDER BY seq",
                    (row["episode"], row["seq"] - 1, row["seq"] + 1, row["seq"])):
                place(nid, 0.0, "neighbour")
        return items

    def _render(self, items: Sequence[RecallItem], abstained: bool, budget_tokens: int, openable: bool) -> str:
        n = self.searched_sources()
        if abstained:
            return (f"RECALLED MEMORY: No stored memory matched this question (searched {n:,} sources: every "
                    f"conversation, knowledge-base entry and note on record). Nothing beyond the standing "
                    f"context above was found. If the answer is not in that context, tell the owner you "
                    f"do not have it; do not guess and do not fill in from general knowledge.")
        shown = [i for i in items if i.shown != "handle"]
        handles = [i for i in items if i.shown == "handle"]
        if not shown and not handles:
            return ""
        lines = [f"RECALLED MEMORY: passages retrieved for this question from the owner's own stored history "
                 f"(searched {n:,} sources; best match first; each carries its date and host). Where two "
                 f"passages disagree, the newer one is current. If none of them holds the fact asked for and "
                 f"the standing context above does not either, say you do not have it; do not guess."]
        for k, it in enumerate(shown, 1):
            tag = "adjacent to a match" if it.shown == "neighbour" else it.source
            lines.append(f"--- [{k}] {tag} | {it.ts[:10] or 'undated'} | {it.host} | id {it.ref}\n{it.text}")
        if handles:
            names = "; ".join(f"{h.ref} (about {h.chars:,} chars)" for h in handles)
            lines.append(("Also matched but too large for this budget, open by id with episode_read: "
                          if openable else "Also matched but not shown here: ") + names)
        return "\n\n".join(lines)


_ROUTER: Optional[RecallRouter] = None
_ROUTER_LOCK = threading.Lock()


def get_router() -> RecallRouter:
    """The process-wide router (one warm index)."""
    global _ROUTER
    with _ROUTER_LOCK:
        if _ROUTER is None:
            _ROUTER = RecallRouter()
        return _ROUTER


# =============================================================================
# SMOKE TESTS (hermetic: temp store, fake embedder, numpy vectors — no models, no network)
# =============================================================================

def _run_self_test() -> None:
    import tempfile
    from jarvis_core.memory import episode_index as ei
    from jarvis_core.memory.episode_store import EpisodeStore

    print("=" * 70)
    print("  recall_router.py -- Smoke Tests")
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

    check("H1 plan_queries splits an enumeration",
          plan_queries("Which voice and which model did we pick for the hearth, and the GPU plan") == [
              "Which voice", "which model did we pick for the hearth", "the GPU plan"][:3]
          or len(plan_queries("Which voice and which model did we pick for the hearth, and the GPU plan")) >= 2)
    check("H2 a single ask yields no sub-queries", plan_queries("Who is Tobu?") == [])
    check("H3 'why' alone is not a sub-query", plan_queries("What did I decide about the roster, and why?") == [])
    check("H4 looks_multi on aggregation cues",
          looks_multi("What have I told you about how I am socially?") and not looks_multi("Who is Tobu?"))
    a = "x" * 300 + "the quick brown fox jumps over the lazy dog and keeps running far away"
    b = "the quick brown fox jumps over the lazy dog and keeps running far away, then rests"
    m = merge_windows(a, b)
    check("H5 merge_windows removes the overlap once", m == a + ", then rests", m[-40:])
    check("H6 merge_windows keeps both when nothing overlaps", merge_windows("aaa", "bbb") == "aaa\nbbb")
    check("H7 fuse ranks a unit found by two passes above one found by one",
          fuse([(1.0, ["a", "b"]), (0.7, ["c", "b"])])[0] == "b")
    check("H8 meta_hits counts distinct markers",
          meta_hits("recall and retrieval and rerank and recall") == 3 and meta_hits("who is Tobu") == 0)
    ents = entity_terms(["Shubha works with Tobu at Celebal", "Tobu and Shubha plan Uttarakhand"],
                        "who is Tobu", lambda w: 0.001)
    check("H9 entity_terms returns names recurring across hits, not the asked one",
          "Shubha" in ents and "Tobu" not in ents, str(ents))

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        root = d / "cs"
        s = EpisodeStore(root=root, machine="alpha", write_shards=False)

        def ev(k: str, role: str, content: str, ts: str) -> Dict[str, Any]:
            return {"key": k, "ts": ts, "role": role, "content": content}
        long_answer = " ".join(f"detail{i} about the specialist roster" for i in range(400))
        s.append("claude", "sess-a", [
            ev("1", "user", "My girlfriend Shubha, I call her Tobu.", "2026-09-01T10:00:01+05:30"),
            ev("2", "assistant", "Noted: Tobu is Shubha.", "2026-09-01T10:00:03+05:30"),
            ev("3", "user", "Which voice now? Lewis.", "2026-09-05T09:00:00+05:30"),
            ev("4", "assistant", "Switched to Lewis.", "2026-09-05T09:00:05+05:30"),
            ev("5", "user", "what did we decide about the specialist roster", "2026-09-06T09:00:00+05:30"),
            ev("6", "assistant", long_answer, "2026-09-06T09:00:05+05:30"),
        ])
        s.append("claude", "sess-meta", [
            ev("1", "user", "why did recall retrieval not know Tobu, check the eval embedding rerank",
               "2026-09-20T10:00:00+05:30"),
            ev("2", "assistant", "recall eval: Tobu retrieval failed, embedding rerank ablation vector latency",
               "2026-09-20T10:00:05+05:30"),
        ])
        queue, cur, kb = d / "q.jsonl", d / "c.jsonl", d / "kb.jsonl"
        queue.write_text("", encoding="utf-8")
        cur.write_text("", encoding="utf-8")
        kb.write_text(json.dumps({"id": 801, "timestamp": "2026-09-28T18:00:00+05:30", "type": "Semantic",
                                  "tags": ["person"], "content": "The owner's girlfriend is Shubha, called Tobu."})
                      + "\n", encoding="utf-8")
        docs = d / "repo"
        (docs / "jarvis_data").mkdir(parents=True)
        (docs / "jarvis_data" / "personal_life.md").write_text("# P\n\n## Family\nParents live in Raigad.\n",
                                                                encoding="utf-8")
        emb = ei._FakeEmbedder(max_tokens=400)
        idx = ei.EpisodeIndex(fts_path=d / "fts.sqlite3", backend=ei.NumpyBackend(d / "vec.npz"), embedder=emb,
                              store_root=root, kb_path=kb, queue_path=queue, curation_path=cur,
                              prov_path=d / "prov.jsonl", doc_root=docs,
                              doc_files=("jarvis_data/personal_life.md",))
        idx.build(rebuild=True, log=lambda s_: None)
        cfg = RecallConfig(rerank=False, abstain_dense=0.3, abstain_ce=-99.0, meta_weight=0.9,
                           second_pass="never", sub_queries=0)
        router = RecallRouter(index=idx, config=cfg, now_fn=lambda: datetime(2026, 9, 28, 21, 0, tzinfo=_IST))

        r = router.recall("who is Tobu girlfriend Shubha", session_id="")
        check("R1 a matching question returns items and no abstention", r.items and not r.abstained, str(r.confidence))
        check("R2 block names date, host and an openable id",
              "| 2026-09-01 | claude | id turn:claude:sess-a:" in r.block or "| 2026-09-28 |" in r.block, r.block[:400])
        check("R3 the current session is excluded",
              all("sess-a" not in i.ref for i in router.recall("who is Tobu girlfriend Shubha",
                                                                 session_id="sess-a").items))
        r_meta = router.recall("who is Tobu girlfriend", session_id="")
        top_refs = [i.ref for i in r_meta.items if i.shown == "full"][:2]
        check("R4 memory-system chatter is demoted below the original statement",
              top_refs and "sess-meta" not in top_refs[0], str(top_refs))
        r_off = RecallRouter(index=idx, config=RecallConfig(**{**cfg.__dict__, "meta_weight": 0.0}),
                             now_fn=router._now).recall("who is Tobu girlfriend", session_id="")
        check("R5 the demotion weight is a switch (0 = off)", bool(r_off.items))
        r_ab = RecallRouter(index=idx, config=RecallConfig(**{**cfg.__dict__, "abstain_dense": 0.999}),
                            now_fn=router._now).recall("zxqv blorptastic nonexistent", session_id="")
        check("R6 nothing matching -> explicit abstention block",
              r_ab.abstained and "No stored memory matched this question" in r_ab.block, r_ab.block[:200])
        small = router.recall("what did we decide about the specialist roster", session_id="", budget_tokens=200)
        big_items = [i for i in small.items if i.chars > 1500]
        check("R7 a unit too big for the budget is never inlined cut: window or handle only",
              all(i.shown in ("window", "handle") for i in big_items) and
              all(len(i.text) == 0 or i.shown == "window" for i in big_items), str([(i.shown, i.chars) for i in small.items]))
        big = router.recall("what did we decide about the specialist roster", session_id="", budget_tokens=20_000)
        whole = [i for i in big.items if i.chars > 1500 and i.shown == "full"]
        check("R8 with room the whole unit is inlined, byte for byte",
              bool(whole) and long_answer in whole[0].text, str([(i.shown, i.chars) for i in big.items]))
        harness = router._factor("q", 0.5)
        check("R9 units quoting the eval harness are dropped",
              harness({"prefix": "", "body": "gold_answer: Tobu is Shubha", "episode": ""}) == 0.0)
        check("R10 a memory-system question keeps meta units",
              router._factor("why did recall retrieval fail", 0.9)(
                  {"prefix": "", "body": "recall retrieval embedding rerank", "episode": "ep:claude:sess-meta"}) == 1.0)
        idx.close()

    class _DeadIndex:
        class backend:
            @staticmethod
            def count() -> int:
                return 0
    dead = RecallRouter(index=_DeadIndex(), config=cfg).recall("who is Tobu", session_id="")
    check("R11 an empty or failing index is reported in the block, never a silent miss",
          dead.error and "memory search could not run" in dead.block and not dead.abstained, dead.block[:200])

    print("-" * 70)
    print(f"  {passed}/{passed + len(failed)} passed")
    if failed:
        print("  FAILED: " + ", ".join(failed))
    print("=" * 70)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--core", action="store_true", help="print the standing core's per-section sizes")
    ap.add_argument("--ask", default="", help="run recall for a question and print the block (nothing is persisted)")
    ap.add_argument("--voice", action="store_true", help="use the fast voice preset for --ask")
    args = ap.parse_args()
    if args.self_test or not (args.core or args.ask):
        _run_self_test()
    if args.core:
        rep = standing_core()
        print(json.dumps({"chars": rep.chars, "tokens_est": rep.tokens_est, "target": CORE_TOKEN_TARGET,
                          "over_target": rep.over_target, "sections": rep.section_chars}, indent=2))
    if args.ask:
        router = RecallRouter(config=VOICE if args.voice else DEEP)
        res = router.recall(args.ask, session_id="recall-cli-ephemeral")
        print(res.block)
        print(json.dumps({"timings": res.timings, "confidence": res.confidence, "abstained": res.abstained,
                          "queries": list(res.queries)}, indent=2, default=str))

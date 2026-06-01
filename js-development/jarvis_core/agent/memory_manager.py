"""
memory_manager.py

JARVIS Agent Layer (Memory): MemGPT-style three-tier memory manager.
Stage 3.5.5 (foundation) + Stage 3.5.2 + Stage 3.5.3 (wiring via react.py).

LAYER: Memory (orchestration)

Import with:
    from jarvis_core.agent.memory_manager import (
        MemoryManager, MemoryItem, TierLevel, MemoryNotFoundError,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

Without a MemoryManager:
    -> The agent has 18 callable memory tools (memory_semantic_search,
       memory_hybrid_search, memory_unified_retrieve, ...) that are stateless
       single-collection retrieval primitives. There's no tier semantics:
       everything lives in one ChromaDB namespace forever, never promoted to
       fast context, never evicted, never tagged with recency / hotness.
    -> 3.5.6 heartbeat-driven consolidation has nothing to call: it would
       need to invent its own demote/promote API per-write.
    -> 3.5.9 /compact has no place to write the summary boundary -- it would
       have to bypass memory entirely and edit the LLM message list directly.

With MemoryManager (MemGPT-style hot/warm/cold hierarchy):
    -> HOT  : in-memory capacity-bounded LRU (default 32 items). Fastest;
              survives only inside a MemoryManager instance lifetime.
    -> WARM : pinned in a ChromaDB collection with metadata.tier="warm".
              Semantic retrieval via JarvisMemoryStore.query_collection.
    -> COLD : same ChromaDB collection, metadata.tier="cold". Same API as
              WARM but caller intent is "archived / rarely-touched". The
              physical separation is a metadata filter, not a separate db.
    -> Self-editing API: add / promote / demote / evict / clear -- the
       methods that the 3.5.7 consolidation agent and the LLM itself
       (via a memory_self_edit tool, lands next wave) will call.
    -> Retrieval merges across all three tiers with tier-weighted scoring:
       HOT items get a +0.2 score bonus to surface recent context first,
       WARM keeps ChromaDB similarity score, COLD gets -0.1 penalty so
       fresh material wins when scores are close. Merged, deduped, top-k.

=============================================================================
THE FLOW (Step by Step Execution Order)
=============================================================================

STEP 1: Caller constructs MemoryManager with an opened JarvisMemoryStore.
        |
        v
STEP 2: New observations / user messages get added via add(content, tier=HOT)
        from the ReActLoop or the heartbeat consolidation agent.
        |
        v
STEP 3: HOT hits its capacity cap. _evict_hot_if_full auto-demotes the
        oldest item to WARM (write to Chroma with metadata.tier=warm).
        The promote/demote API is the explicit-edit version of the same.
        |
        v
STEP 4: Each agent turn: ReActLoop calls memory_manager.retrieve(user_query)
        before iteration 0. The manager queries each tier, merges, dedupes,
        and returns the top-k MemoryItem dataclasses. The loop prepends them
        as a system-suffix message so the LLM sees relevant context.
        |
        v
STEP 5: Stage 3.5.7 heartbeat consolidation agent writes Cognitive_Pattern
        summaries to WARM with metadata.tier="warm" + tag heartbeat-emitted.
        kb_compact.py already exempts heartbeat-emitted from displacement
        (Stage 2.5.8 closure).

=============================================================================

Prep for Stage 3.5.6 (heartbeat) + 3.5.7 (consolidator) + 3.5.9 (/compact):
all three call back into this manager via the same add/promote/retrieve API
shipped here. memory_manager.py is the API surface they share.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Set


# =============================================================================
# Part 1: TIER + ITEM TYPES
# =============================================================================

class TierLevel(str, Enum):
    """Memory hierarchy levels (MemGPT-style)."""
    HOT = "hot"      # in-memory LRU
    WARM = "warm"    # ChromaDB, recently consulted
    COLD = "cold"    # ChromaDB, archived

    @property
    def is_persistent(self) -> bool:
        """True if the tier survives MemoryManager instance lifetime."""
        return self in (TierLevel.WARM, TierLevel.COLD)


@dataclass(frozen=True)
class MemoryItem:
    """One unit of memory at some tier.

    Fields:
        item_id:    Short unique id; primary key across all tiers.
        content:    Raw text body (what the LLM reads when this item surfaces).
        metadata:   Free-form dict; reserved keys -- tier, created_at, updated_at.
        tier:       Current tier of this item at the time of retrieval/snapshot.
        score:      Retrieval relevance score; None outside of retrieve() results.
    """
    item_id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    tier: TierLevel = TierLevel.HOT
    score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "content": self.content,
            "metadata": dict(self.metadata),
            "tier": self.tier.value,
            "score": self.score,
        }


# =============================================================================
# Part 2: EXCEPTIONS
# =============================================================================

class MemoryNotFoundError(Exception):
    """Raised when a promote/demote/evict targets an unknown item_id."""


class TierTransitionError(Exception):
    """Raised when promote/demote is illegal (e.g., promote(HOT) has no hotter)."""


# =============================================================================
# Part 3: HELPERS
# =============================================================================

_IST = timezone(timedelta(hours=5, minutes=30))


def _ist_now_iso() -> str:
    return datetime.now(_IST).isoformat()


def _short_id(prefix: str = "mem") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _hotter_than(t: TierLevel) -> Optional[TierLevel]:
    if t == TierLevel.COLD:
        return TierLevel.WARM
    if t == TierLevel.WARM:
        return TierLevel.HOT
    return None  # HOT has nothing hotter


def _colder_than(t: TierLevel) -> Optional[TierLevel]:
    if t == TierLevel.HOT:
        return TierLevel.WARM
    if t == TierLevel.WARM:
        return TierLevel.COLD
    return None  # COLD has nothing colder


# =============================================================================
# Part 4: MEMORY MANAGER
# =============================================================================

class MemoryManager:
    """MemGPT-style three-tier memory manager.

    Concurrency: a single asyncio.Lock guards HOT mutations AND tier
    transitions. WARM/COLD reads (the Chroma query path) don't take the
    lock since Chroma is process-safe and only single-writer matters here.

    Persistence: HOT lives in this instance's memory only. WARM + COLD
    share a ChromaDB collection (default name "memory_manager"); the tier
    distinction is the metadata field 'tier'. Restart drops HOT; WARM/COLD
    survive via the Chroma persistence layer.
    """

    DEFAULT_COLLECTION = "memory_manager"
    HOT_SCORE_BONUS = 0.2
    COLD_SCORE_PENALTY = 0.1

    def __init__(
        self,
        store: Optional[Any] = None,
        hot_capacity: int = 32,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        if hot_capacity < 1:
            raise ValueError(f"hot_capacity must be >= 1, got {hot_capacity}")
        self._store = store
        self._hot_capacity = hot_capacity
        self._collection_name = collection_name
        # Ordered so we know which HOT item is oldest (insertion order)
        self._hot: "OrderedDict[str, MemoryItem]" = OrderedDict()
        self._lock = asyncio.Lock()

    # ---- Self-editing API ----------------------------------------------

    async def add(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        tier: TierLevel = TierLevel.HOT,
        item_id: Optional[str] = None,
    ) -> str:
        """Insert new memory at the given tier. Returns the item_id.

        If `item_id` is omitted, a short UUID is generated. Duplicate ids
        are allowed only when the existing entry is replaced (overwrites
        in HOT, upserts in Chroma for WARM/COLD).
        """
        if not isinstance(content, str) or not content.strip():
            raise ValueError("MemoryManager.add: content must be a non-empty string")
        meta = dict(metadata or {})
        now = _ist_now_iso()
        meta.setdefault("created_at", now)
        meta["updated_at"] = now
        meta["tier"] = tier.value
        iid = item_id or _short_id()

        async with self._lock:
            # Cross-tier id collision: the docstring promises "Duplicate ids
            # are allowed only when the existing entry is replaced". Enforce
            # that across tiers: if `iid` already lives in a different tier,
            # remove the old copy first so the new write is a real REPLACE
            # rather than a silent duplicate spanning two tiers.
            if tier == TierLevel.HOT:
                # New target is HOT -> if iid is in WARM/COLD persistent, drop it.
                self._delete_persistent(iid)
            else:
                # New target is persistent -> if iid is in HOT, drop it.
                self._hot.pop(iid, None)

            if tier == TierLevel.HOT:
                self._hot[iid] = MemoryItem(
                    item_id=iid, content=content, metadata=meta, tier=tier
                )
                # Re-position to mark as freshest in LRU
                self._hot.move_to_end(iid)
                await self._evict_hot_if_full_locked()
            else:
                # WARM / COLD: write through to ChromaDB.
                self._write_persistent(iid, content, meta)
        return iid

    async def promote(self, item_id: str) -> TierLevel:
        """Move item to the next-hotter tier. Returns the new tier.

        COLD -> WARM, WARM -> HOT. Already-HOT items raise TierTransitionError.
        """
        async with self._lock:
            item = self._lookup_locked(item_id)
            target = _hotter_than(item.tier)
            if target is None:
                raise TierTransitionError(
                    f"Item '{item_id}' is already HOT; cannot promote further."
                )
            await self._move_locked(item, target)
            return target

    async def demote(self, item_id: str) -> TierLevel:
        """Move item to the next-colder tier. Returns the new tier."""
        async with self._lock:
            item = self._lookup_locked(item_id)
            target = _colder_than(item.tier)
            if target is None:
                raise TierTransitionError(
                    f"Item '{item_id}' is already COLD; cannot demote further."
                )
            await self._move_locked(item, target)
            return target

    async def evict(self, item_id: str) -> bool:
        """Hard-delete an item from whichever tier it lives in.

        Returns True if removed, False if not found (idempotent-safe).
        Chroma's collection.delete is silent on missing ids, so we
        explicitly check via .get(ids=[...]) before deciding True/False.
        """
        async with self._lock:
            if item_id in self._hot:
                del self._hot[item_id]
                return True
            if self._store is None:
                return False
            try:
                collection = self._store._client.get_collection(  # noqa: SLF001
                    name=self._collection_name
                )
                existing = collection.get(ids=[item_id])
                if not (existing.get("ids") or []):
                    return False
                collection.delete(ids=[item_id])
                return True
            except Exception:
                return False

    def hot_items(self) -> List[MemoryItem]:
        """Snapshot of current HOT tier in insertion order (oldest first)."""
        return list(self._hot.values())

    def hot_count(self) -> int:
        return len(self._hot)

    async def clear_hot(self) -> None:
        async with self._lock:
            self._hot.clear()

    # ---- Retrieval -----------------------------------------------------

    async def retrieve(
        self,
        query: str,
        k: int = 5,
        tiers: Optional[Set[TierLevel]] = None,
    ) -> List[MemoryItem]:
        """Retrieve top-k items across the requested tiers.

        Default: all three tiers searched. HOT uses substring keyword match
        on content (fast, no embedding); WARM + COLD use ChromaDB semantic
        retrieval through self._store.query_collection. Results are merged
        with tier-weighted scores and deduped by item_id.
        """
        if not isinstance(query, str) or not query.strip():
            return []
        if k < 1:
            return []
        wanted: Set[TierLevel] = tiers or {TierLevel.HOT, TierLevel.WARM, TierLevel.COLD}

        hits: List[MemoryItem] = []

        # HOT: token-overlap scan (cheap, no embedding cost). Treats the
        # query as a bag of tokens (words >=3 chars, lowercased); ranks HOT
        # items by overlap fraction so multi-word queries don't require an
        # exact substring match. A full-substring match on the original
        # query still beats individual-token matches via the +1.0 bonus.
        if TierLevel.HOT in wanted and self._hot:
            q_lower = query.lower()
            q_tokens = {t for t in self._tokenize(q_lower) if len(t) >= 3}
            for item in self._hot.values():
                c_lower = item.content.lower()
                substring_hit = q_lower in c_lower
                c_tokens = {t for t in self._tokenize(c_lower) if len(t) >= 3}
                overlap = q_tokens & c_tokens
                if substring_hit or overlap:
                    if substring_hit:
                        base_score = 1.0
                    elif q_tokens:
                        base_score = len(overlap) / max(1, len(q_tokens))
                    else:
                        base_score = 0.0
                    hits.append(
                        MemoryItem(
                            item_id=item.item_id,
                            content=item.content,
                            metadata=dict(item.metadata),
                            tier=TierLevel.HOT,
                            score=base_score,
                        )
                    )

        # WARM + COLD: ChromaDB. We issue separate queries per tier so we
        # can apply the correct score adjustment per item without inferring
        # the tier from metadata after the fact.
        persistent_tiers = wanted & {TierLevel.WARM, TierLevel.COLD}
        if persistent_tiers and self._store is not None:
            for tier in persistent_tiers:
                try:
                    raw = self._store.query_collection(
                        collection_name=self._collection_name,
                        query_text=query,
                        n_results=k * 2,
                        where={"tier": tier.value},
                    )
                except Exception:
                    continue
                hits.extend(self._chroma_to_items(raw, tier))

        merged = self._merge_and_score(hits)
        merged.sort(key=lambda i: (i.score if i.score is not None else 0.0), reverse=True)
        return merged[:k]

    # ---- Internal helpers ----------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Cheap Unicode-aware word tokenizer.

        Uses `\\w+` (with Python 3's default re.UNICODE) so Devanagari,
        Chinese, accented Latin, etc. produce tokens instead of being
        silently stripped to empty. Applies str.casefold() (proper
        Unicode case folding) rather than .lower() so non-ASCII case
        variants (e.g., German ß, Greek sigma) compare correctly.

        Excludes the underscore so identifier-like tokens don't smear
        with surrounding text.
        """
        import re as _re
        return _re.findall(r"[^\W_]+", text.casefold(), flags=_re.UNICODE)

    def _write_persistent(
        self,
        item_id: str,
        content: str,
        metadata: Dict[str, Any],
    ) -> None:
        """Write to the WARM/COLD-backing Chroma collection. Upsert semantics."""
        if self._store is None:
            raise RuntimeError(
                "MemoryManager: store=None; cannot write persistent tiers (WARM/COLD)."
            )
        # Sanitize metadata: Chroma requires scalar values only.
        sanitized: Dict[str, Any] = {}
        for k, v in metadata.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                sanitized[k] = v
            else:
                sanitized[k] = str(v)
        self._store.ingest_documents(
            collection_name=self._collection_name,
            documents=[content],
            metadatas=[sanitized],
            ids=[item_id],
        )

    def _delete_persistent(self, item_id: str) -> None:
        """Hard-delete from Chroma; silent on absence."""
        if self._store is None:
            return
        try:
            collection = self._store._client.get_collection(  # noqa: SLF001
                name=self._collection_name
            )
            collection.delete(ids=[item_id])
        except Exception:
            pass

    def _lookup_locked(self, item_id: str) -> MemoryItem:
        """Find an item across HOT + persistent tiers. Lock must be held."""
        if item_id in self._hot:
            return self._hot[item_id]

        if self._store is not None:
            try:
                collection = self._store._client.get_collection(  # noqa: SLF001
                    name=self._collection_name
                )
                got = collection.get(ids=[item_id], include=["documents", "metadatas"])
                ids_ = got.get("ids") or []
                if ids_:
                    docs = got.get("documents") or []
                    metas = got.get("metadatas") or []
                    meta = dict(metas[0]) if metas else {}
                    tier_str = meta.get("tier", TierLevel.WARM.value)
                    tier = TierLevel(tier_str) if tier_str in {t.value for t in TierLevel} else TierLevel.WARM
                    return MemoryItem(
                        item_id=item_id,
                        content=docs[0] if docs else "",
                        metadata=meta,
                        tier=tier,
                    )
            except Exception:
                pass
        raise MemoryNotFoundError(f"MemoryManager: no item with id '{item_id}'")

    async def _move_locked(self, item: MemoryItem, target: TierLevel) -> None:
        """Transition an item between tiers. Lock must be held."""
        new_meta = dict(item.metadata)
        new_meta["tier"] = target.value
        new_meta["updated_at"] = _ist_now_iso()

        # 1. Remove from current tier
        if item.tier == TierLevel.HOT:
            self._hot.pop(item.item_id, None)
        else:
            self._delete_persistent(item.item_id)

        # 2. Add to target tier
        if target == TierLevel.HOT:
            self._hot[item.item_id] = MemoryItem(
                item_id=item.item_id,
                content=item.content,
                metadata=new_meta,
                tier=TierLevel.HOT,
            )
            self._hot.move_to_end(item.item_id)
            await self._evict_hot_if_full_locked()
        else:
            self._write_persistent(item.item_id, item.content, new_meta)

    async def _evict_hot_if_full_locked(self) -> None:
        """When HOT exceeds capacity, auto-demote the oldest item to WARM.

        Lock must be held. If the store is missing, the oldest item is
        simply dropped (the manager warns via metadata but does not block).
        """
        while len(self._hot) > self._hot_capacity:
            iid, item = self._hot.popitem(last=False)  # oldest
            if self._store is not None:
                meta = dict(item.metadata)
                meta["tier"] = TierLevel.WARM.value
                meta["auto_demoted_at"] = _ist_now_iso()
                meta["updated_at"] = meta["auto_demoted_at"]
                try:
                    self._write_persistent(iid, item.content, meta)
                except Exception:
                    pass  # store error; item is lost rather than poisoning HOT

    def _chroma_to_items(
        self,
        raw: Dict[str, Any],
        tier: TierLevel,
    ) -> List[MemoryItem]:
        """Convert a ChromaDB query result into MemoryItem instances."""
        if not raw or not raw.get("ids"):
            return []
        ids = raw["ids"][0]
        docs = raw["documents"][0]
        metas = raw["metadatas"][0]
        dists = raw["distances"][0]
        items: List[MemoryItem] = []
        for i, iid in enumerate(ids):
            score = max(0.0, 1.0 - float(dists[i]))  # convert distance to similarity
            items.append(
                MemoryItem(
                    item_id=iid,
                    content=docs[i] if i < len(docs) else "",
                    metadata=dict(metas[i] or {}),
                    tier=tier,
                    score=score,
                )
            )
        return items

    def _merge_and_score(
        self,
        items: Iterable[MemoryItem],
    ) -> List[MemoryItem]:
        """Dedup by item_id (keep highest-scored copy), then apply tier weights."""
        best: Dict[str, MemoryItem] = {}
        for it in items:
            current = best.get(it.item_id)
            if current is None or (it.score or 0) > (current.score or 0):
                best[it.item_id] = it
        out: List[MemoryItem] = []
        for it in best.values():
            base = it.score if it.score is not None else 0.0
            if it.tier == TierLevel.HOT:
                adjusted = base + self.HOT_SCORE_BONUS
            elif it.tier == TierLevel.COLD:
                adjusted = base - self.COLD_SCORE_PENALTY
            else:
                adjusted = base
            out.append(
                MemoryItem(
                    item_id=it.item_id,
                    content=it.content,
                    metadata=dict(it.metadata),
                    tier=it.tier,
                    score=adjusted,
                )
            )
        return out


# =============================================================================
# MAIN ENTRY POINT  +  SMOKE TESTS  (no real ChromaDB needed; mock store)
# =============================================================================

if __name__ == "__main__":

    print("=" * 70)
    print("  memory_manager.py -- Smoke Tests (Stage 3.5.5)")
    print("=" * 70)

    passed = 0
    failed: List[str] = []

    def check(name: str, cond: bool, hint: str = "") -> None:
        global passed
        if cond:
            passed += 1
        else:
            failed.append(f"FAIL: {name}" + (f" ({hint})" if hint else ""))

    # ---- Mock store that mimics JarvisMemoryStore's relevant surface --------

    class _MockCollection:
        def __init__(self) -> None:
            self._docs: Dict[str, Dict[str, Any]] = {}

        def get(self, ids: List[str] = None, include: List[str] = None) -> Dict[str, Any]:
            ids = ids or list(self._docs.keys())
            present = [iid for iid in ids if iid in self._docs]
            return {
                "ids": present,
                "documents": [self._docs[iid]["content"] for iid in present],
                "metadatas": [dict(self._docs[iid]["meta"]) for iid in present],
            }

        def delete(self, ids: List[str]) -> None:
            for iid in ids:
                self._docs.pop(iid, None)

        def query(self, **kwargs: Any) -> Dict[str, Any]:
            n = kwargs.get("n_results", 5)
            where = kwargs.get("where", {}) or {}
            results = []
            for iid, item in self._docs.items():
                if not all(item["meta"].get(k) == v for k, v in where.items()):
                    continue
                # Mock score: rank by inserted order
                results.append((iid, item))
            results = results[:n]
            return {
                "ids":        [[r[0] for r in results]],
                "documents":  [[r[1]["content"] for r in results]],
                "metadatas":  [[dict(r[1]["meta"]) for r in results]],
                "distances":  [[0.1 * i for i in range(len(results))]],
            }

        def count(self) -> int:
            return len(self._docs)

    class _MockClient:
        def __init__(self) -> None:
            self._collection = _MockCollection()
        def get_collection(self, name: str) -> _MockCollection:
            return self._collection
        def get_or_create_collection(self, name: str) -> _MockCollection:
            return self._collection

    class _MockStore:
        def __init__(self) -> None:
            self._client = _MockClient()

        def ingest_documents(
            self, collection_name: str, documents: List[str],
            metadatas: List[Dict[str, Any]] = None, ids: List[str] = None,
        ) -> int:
            for iid, doc, meta in zip(ids or [], documents, metadatas or []):
                self._client._collection._docs[iid] = {  # noqa: SLF001
                    "content": doc, "meta": dict(meta)
                }
            return len(documents)

        def query_collection(
            self, collection_name: str, query_text: str,
            n_results: int = 5, where: Dict[str, Any] = None,
        ) -> Dict[str, Any]:
            return self._client._collection.query(  # noqa: SLF001
                n_results=n_results, where=where
            )

    async def smoke() -> None:
        store = _MockStore()
        mm = MemoryManager(store=store, hot_capacity=3)

        # ---- T1: Add to HOT ---------------------------------------------
        iid1 = await mm.add("first hot fact", tier=TierLevel.HOT)
        check("T1a add HOT returns id", isinstance(iid1, str) and iid1.startswith("mem_"))
        check("T1b HOT count == 1", mm.hot_count() == 1)
        snap = mm.hot_items()
        check("T1c HOT snapshot has the item", len(snap) == 1 and snap[0].content == "first hot fact")

        # ---- T2: HOT capacity LRU + auto-demote -----------------------
        await mm.add("second", tier=TierLevel.HOT)
        await mm.add("third", tier=TierLevel.HOT)
        check("T2a HOT count at capacity", mm.hot_count() == 3)
        # 4th add must auto-demote the oldest (iid1) to WARM
        iid4 = await mm.add("fourth", tier=TierLevel.HOT)
        check("T2b HOT still at capacity after overflow", mm.hot_count() == 3)
        check("T2c oldest item evicted from HOT", iid1 not in {i.item_id for i in mm.hot_items()})

        # The auto-demoted item must now live in WARM
        warm_search = await mm.retrieve("first", k=5, tiers={TierLevel.WARM})
        check("T2d auto-demoted item lives in WARM",
              any(it.item_id == iid1 for it in warm_search),
              hint=str([it.item_id for it in warm_search]))
        check("T2e auto-demoted item now has tier=WARM",
              all(it.tier == TierLevel.WARM for it in warm_search))

        # ---- T3: Explicit add to WARM ---------------------------------
        iid_warm = await mm.add("a warm preference", tier=TierLevel.WARM)
        warm_items = await mm.retrieve("warm preference", k=5, tiers={TierLevel.WARM})
        check("T3a warm add visible",
              any(it.item_id == iid_warm for it in warm_items))

        # ---- T4: Promote WARM -> HOT ----------------------------------
        new_tier = await mm.promote(iid_warm)
        check("T4a promote returns HOT", new_tier == TierLevel.HOT)
        check("T4b item now lives in HOT",
              iid_warm in {i.item_id for i in mm.hot_items()})

        # ---- T5: Demote HOT -> WARM -----------------------------------
        new_tier = await mm.demote(iid_warm)
        check("T5a demote returns WARM", new_tier == TierLevel.WARM)
        check("T5b item no longer in HOT",
              iid_warm not in {i.item_id for i in mm.hot_items()})

        # ---- T6: Demote WARM -> COLD ----------------------------------
        new_tier = await mm.demote(iid_warm)
        check("T6 demote WARM->COLD", new_tier == TierLevel.COLD)

        # ---- T7: Promote at HOT raises -------------------------------
        # Add a fresh HOT item, try to promote (already HOT)
        iid_hot = await mm.add("already hot", tier=TierLevel.HOT)
        try:
            await mm.promote(iid_hot)
            check("T7 promote HOT raises", False, hint="no error")
        except TierTransitionError:
            check("T7 promote HOT raises", True)

        # ---- T8: Demote at COLD raises -------------------------------
        try:
            await mm.demote(iid_warm)  # already COLD from T6
            check("T8 demote COLD raises", False, hint="no error")
        except TierTransitionError:
            check("T8 demote COLD raises", True)

        # ---- T9: Promote/demote on unknown id ------------------------
        try:
            await mm.promote("does-not-exist")
            check("T9 promote unknown raises", False)
        except MemoryNotFoundError:
            check("T9 promote unknown raises", True)

        # ---- T10: Evict from HOT -------------------------------------
        removed = await mm.evict(iid_hot)
        check("T10a evict HOT returns True", removed is True)
        check("T10b item gone from HOT", iid_hot not in {i.item_id for i in mm.hot_items()})

        # ---- T11: Evict non-existent ---------------------------------
        removed2 = await mm.evict("never-was")
        check("T11 evict unknown returns False", removed2 is False)

        # ---- T12: Tier-weighted retrieval merge ----------------------
        # Build a fresh manager, add the same content to all 3 tiers under
        # different ids. retrieve() should rank HOT > WARM > COLD.
        store2 = _MockStore()
        mm2 = MemoryManager(store=store2, hot_capacity=10)
        h = await mm2.add("apple pie recipe", tier=TierLevel.HOT)
        w = await mm2.add("apple pie recipe", tier=TierLevel.WARM)
        c = await mm2.add("apple pie recipe", tier=TierLevel.COLD)
        results = await mm2.retrieve("apple", k=3)
        tiers_in_order = [r.tier for r in results]
        check("T12a 3 tiers returned", len(results) == 3,
              hint=str([(r.item_id, r.tier.value, r.score) for r in results]))
        check("T12b first result is HOT", tiers_in_order[0] == TierLevel.HOT)
        check("T12c last result is COLD", tiers_in_order[-1] == TierLevel.COLD)

        # ---- T13: Empty query returns [] -----------------------------
        empty_results = await mm2.retrieve("", k=5)
        check("T13 empty query -> []", empty_results == [])

        # ---- T14: k=0 returns [] -------------------------------------
        zero_results = await mm2.retrieve("apple", k=0)
        check("T14 k=0 -> []", zero_results == [])

        # ---- T15: Tier filter -----------------------------------------
        only_hot = await mm2.retrieve("apple", k=5, tiers={TierLevel.HOT})
        check("T15a only HOT in filter", len(only_hot) == 1 and only_hot[0].tier == TierLevel.HOT)
        only_persist = await mm2.retrieve("apple", k=5, tiers={TierLevel.WARM, TierLevel.COLD})
        check("T15b persistent-only filter",
              {it.tier for it in only_persist} == {TierLevel.WARM, TierLevel.COLD})

        # ---- T16: Constructor validation -----------------------------
        try:
            MemoryManager(store=store, hot_capacity=0)
            check("T16 hot_capacity=0 rejected", False)
        except ValueError:
            check("T16 hot_capacity=0 rejected", True)

        # ---- T17: add empty content rejected -------------------------
        try:
            await mm2.add("", tier=TierLevel.HOT)
            check("T17 empty content rejected", False)
        except ValueError:
            check("T17 empty content rejected", True)
        try:
            await mm2.add("   ", tier=TierLevel.HOT)
            check("T17b whitespace-only content rejected", False)
        except ValueError:
            check("T17b whitespace-only content rejected", True)

        # ---- T18: store=None blocks WARM/COLD adds -------------------
        mm_no_store = MemoryManager(store=None)
        try:
            await mm_no_store.add("nope", tier=TierLevel.WARM)
            check("T18 WARM add without store raises", False)
        except RuntimeError:
            check("T18 WARM add without store raises", True)

        # ---- T19: HOT works without store ----------------------------
        iid_h = await mm_no_store.add("hot only no store", tier=TierLevel.HOT)
        check("T19a HOT add works without store",
              iid_h in {i.item_id for i in mm_no_store.hot_items()})

        # HOT eviction with no store just drops the oldest (no Chroma write)
        for _ in range(40):  # well over default cap of 32
            await mm_no_store.add(f"flood-{_}", tier=TierLevel.HOT)
        check("T19b HOT eviction respects capacity without store",
              mm_no_store.hot_count() <= 32)

        # ---- T20: clear_hot --------------------------------------------
        await mm2.clear_hot()
        check("T20 clear_hot empties HOT tier", mm2.hot_count() == 0)

        # ---- T21: TierLevel.is_persistent ----------------------------
        check("T21a HOT not persistent", not TierLevel.HOT.is_persistent)
        check("T21b WARM persistent", TierLevel.WARM.is_persistent)
        check("T21c COLD persistent", TierLevel.COLD.is_persistent)

        # ---- T22: MemoryItem.to_dict roundtrip ------------------------
        mi = MemoryItem(item_id="x", content="c", metadata={"k": "v"}, tier=TierLevel.WARM, score=0.7)
        d = mi.to_dict()
        check("T22 to_dict shape",
              d == {"item_id": "x", "content": "c", "metadata": {"k": "v"},
                    "tier": "warm", "score": 0.7})

        # ---- T23: metadata sanitization (non-scalar values) ----------
        # Chroma rejects dict/list metadata values. Manager must coerce to str.
        store3 = _MockStore()
        mm3 = MemoryManager(store=store3, hot_capacity=10)
        # Build complex metadata that has mixed types
        iid_complex = await mm3.add(
            "complex meta",
            metadata={"nested": {"deep": "value"}, "list_field": [1, 2, 3], "scalar": 42},
            tier=TierLevel.WARM,
        )
        # Look up the stored doc
        raw_stored = store3._client._collection._docs[iid_complex]  # noqa: SLF001
        sanitized_meta = raw_stored["meta"]
        check("T23a nested-dict coerced to string",
              isinstance(sanitized_meta["nested"], str))
        check("T23b scalar preserved",
              sanitized_meta["scalar"] == 42)

        # ---- T24: tier-only filter excludes other tiers --------------
        store4 = _MockStore()
        mm4 = MemoryManager(store=store4, hot_capacity=10)
        await mm4.add("hot one", tier=TierLevel.HOT)
        await mm4.add("warm one", tier=TierLevel.WARM)
        await mm4.add("cold one", tier=TierLevel.COLD)
        only_w = await mm4.retrieve("one", k=10, tiers={TierLevel.WARM})
        check("T24 only WARM returned",
              all(r.tier == TierLevel.WARM for r in only_w) and len(only_w) == 1,
              hint=str([(r.tier.value, r.content) for r in only_w]))

        # ---- T25: REGRESSION GUARD (M1) cross-tier id collision -----
        # Previously: add(item_id=X, tier=HOT) when X exists in WARM created
        # a HOT copy WITHOUT removing the WARM copy, leaving stale duplicates.
        store5 = _MockStore()
        mm5 = MemoryManager(store=store5, hot_capacity=10)
        # Seed WARM with an explicit id
        await mm5.add("warm version", tier=TierLevel.WARM, item_id="dup_id")
        warm_count_before = len(store5._client._collection._docs)  # noqa: SLF001
        check("T25a WARM seeded", warm_count_before == 1)

        # Now re-add the SAME id as HOT -- the WARM copy must be deleted
        await mm5.add("hot version", tier=TierLevel.HOT, item_id="dup_id")
        warm_count_after = len(store5._client._collection._docs)  # noqa: SLF001
        check("T25b WARM copy removed on HOT re-add",
              warm_count_after == 0, hint=f"docs={list(store5._client._collection._docs.keys())}")
        check("T25c HOT has the new version",
              mm5._hot.get("dup_id") is not None
              and mm5._hot["dup_id"].content == "hot version")

        # And vice versa: HOT then re-add as WARM
        await mm5.add("hot 2", tier=TierLevel.HOT, item_id="dup2")
        check("T25d HOT seeded", "dup2" in mm5._hot)
        await mm5.add("warm 2", tier=TierLevel.WARM, item_id="dup2")
        check("T25e HOT copy removed on WARM re-add",
              "dup2" not in mm5._hot)
        check("T25f WARM has the new version",
              "dup2" in store5._client._collection._docs)  # noqa: SLF001

        # ---- T26: REGRESSION GUARD (M9) Unicode tokenization -------
        # Previously: _tokenize used `[a-z0-9]+` which stripped Devanagari,
        # Chinese, accented Latin chars, silently failing HOT retrieval.
        store6 = _MockStore()
        mm6 = MemoryManager(store=store6, hot_capacity=10)
        await mm6.add("मेरा नाम जारविस है", tier=TierLevel.HOT)  # Hindi
        await mm6.add("我喜欢机器学习", tier=TierLevel.HOT)         # Chinese
        await mm6.add("café résumé naïve", tier=TierLevel.HOT)     # accented Latin
        hi_hits = await mm6.retrieve("जारविस", k=5, tiers={TierLevel.HOT})
        check("T26a Devanagari token match", len(hi_hits) >= 1,
              hint=str([h.content for h in hi_hits]))
        zh_hits = await mm6.retrieve("机器学习", k=5, tiers={TierLevel.HOT})
        check("T26b Chinese token match", len(zh_hits) >= 1,
              hint=str([h.content for h in zh_hits]))
        accented_hits = await mm6.retrieve("café", k=5, tiers={TierLevel.HOT})
        check("T26c accented Latin match", len(accented_hits) >= 1,
              hint=str([h.content for h in accented_hits]))

        # Negative case: bare ASCII query against Unicode-only content
        # should NOT match (different scripts share no tokens).
        no_match = await mm6.retrieve("apple", k=5, tiers={TierLevel.HOT})
        check("T26d ASCII query no false-positive on Unicode content",
              len(no_match) == 0)

        # ---- Report ---------------------------------------------------
        total = passed + len(failed)
        print(f"\n  Passed: {passed}/{total}")
        if failed:
            for f_ in failed:
                print(f"  {f_}")
            print("=" * 70)
            raise SystemExit(1)
        print(f"  All {total} memory_manager smoke tests passed.")
        print("=" * 70)

    asyncio.run(smoke())

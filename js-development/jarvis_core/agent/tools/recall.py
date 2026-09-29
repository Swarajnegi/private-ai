"""
recall.py — the reasoning loop's handle on the owner's whole stored history.

LAYER: Tools (Memory — model-driven recall and page-in)

Import with:
    from jarvis_core.agent.tools.recall import MemoryRecallTool, EpisodeReadTool

Run with:
    cd js-development && PYTHONPATH=. python -m jarvis_core.agent.tools.recall

=============================================================================
THE BIG PICTURE
=============================================================================

The prompt carries a small standing core; everything else the owner ever said
or did lives in the episode store (memory/episode_store.py), verbatim, and is
found through the episode index. brain/recall_router.py answers one question
in one pass. These two tools let the MODEL iterate, which multi-hop questions
need: recall, read what came back, recall again with a name it just learned.

  memory_recall(query, time_range?, host?)
      Hybrid search over every conversation, knowledge-base entry and note.
      Returns passages read whole, each with its date, host and an id, plus the
      ids of matches too large to inline.
  episode_read(id, offset, page_chars)
      Opens one id, page by page: any stored event (a 5 MB tool output
      included) or a whole retrieval unit. Every page states total_chars and
      next_offset, so nothing is ever cut, only paged.

Both are READ-ONLY by construction (they open a search index and append-only
files and write nothing), so they are safe under the permission gate.

=============================================================================
THE FLOW
=============================================================================

STEP 1: memory_recall -> RecallRouter.recall(config=DEEP, tool lane on, no
        session to exclude beyond the caller's own).
        |
STEP 2: the model reads the passages; an id it wants more of goes to
        episode_read, which pages it from the store (turn ids) or the index
        (unit ids, KB entries, notes).
=============================================================================
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # standalone-run safety

from jarvis_core.agent.tool import Tool, ToolResult

RECALL_BUDGET_TOKENS = 6_000
DEFAULT_PAGE_CHARS = 12_000
MAX_PAGE_CHARS = 48_000
_MIN_PAGE_CHARS = 1_000


class MemoryRecallInput(BaseModel):
    query: str = Field(..., description=(
        "What to remember, in the owner's own terms: a name, a topic, a decision, a phrase they used. "
        "Ask for one thing per call; call again with a name you just learned to follow a thread."))
    time_range: Optional[str] = Field(None, description=(
        "Optional natural-language period to favour: 'last week', 'in early June', 'on 3 June 2026', "
        "'September 2026'. Also parsed from the query itself when it contains one."))
    host: Optional[str] = Field(None, description=(
        "Optional: restrict to one host's sessions: claude, codex, antigravity or jarvis."))


class MemoryRecallTool(Tool):
    """Recall from the owner's whole stored history."""

    name = "memory_recall"
    description = (
        "Search EVERYTHING the owner has said or done with any agent: every conversation (Claude, Codex, "
        "Antigravity, JARVIS), every knowledge-base entry, and the notes about their life. Use it for any "
        "question about the owner's past: who someone is, what was decided and why, when something happened, "
        "what they said about a topic. Returns passages read whole, best match first, each with its date, host "
        "and id; matches too large to show come back as ids you can open with episode_read. When it says no "
        "stored memory matched, that is the answer: say you do not have it. Read-only."
    )
    input_schema = MemoryRecallInput

    def __init__(self, router: Optional[Any] = None, budget_tokens: int = RECALL_BUDGET_TOKENS,
                 session_id: str = "") -> None:
        self._router = router
        self._budget = budget_tokens
        self._session = session_id

    def is_concurrency_safe(self) -> bool:
        return True

    def _get_router(self) -> Any:
        if self._router is None:
            from jarvis_core.brain.recall_router import get_router
            self._router = get_router()
        return self._router

    async def invoke(self, tool_input: MemoryRecallInput) -> ToolResult:
        from jarvis_core.brain.recall_router import RecallConfig
        from jarvis_core.memory import episode_index as ei
        rng = None
        if tool_input.time_range:
            rng = ei.parse_time_range(tool_input.time_range)
            if rng is None:
                return ToolResult(error=f"Could not read time_range {tool_input.time_range!r}. Use a phrase like "
                                        f"'last week', 'in early June' or 'on 3 June 2026', or leave it out.")
        router = self._get_router()
        cfg = RecallConfig(**{**router.config.__dict__, "tool_lane": True})
        try:
            res = await asyncio.to_thread(
                router.recall, tool_input.query, self._session, self._budget, rng,
                [tool_input.host] if tool_input.host else None, cfg, True)
        except Exception as e:                                     # noqa: BLE001 — surfaced, never raised
            return ToolResult(error=f"recall failed: {type(e).__name__}: {e}")
        return ToolResult(output={
            "abstained": res.abstained,
            "shown": len([i for i in res.items if i.shown != "handle"]),
            "not_shown": [{"id": i.ref, "chars": i.chars, "source": i.source, "date": i.ts[:10]}
                          for i in res.items if i.shown == "handle"],
            "queries": list(res.queries),
            "recall": res.block,
        })


class EpisodeReadInput(BaseModel):
    id: str = Field(..., description=(
        "An id from memory_recall: a store turn id ('turn:claude:<session>:<n>'), an episode id "
        "('ep:claude:<session>'), a retrieval unit id ('ep:...|x12|w0'), or a knowledge-base entry "
        "('kb:<id>')."))
    offset: int = Field(0, ge=0, description="Character offset to start at. Pass back next_offset for the next page.")
    page_chars: Optional[int] = Field(None, description="Characters per page (optional).")


class EpisodeReadTool(Tool):
    """Open one stored item, page by page."""

    name = "episode_read"
    description = (
        "Read one stored item in full, page by page, by the id memory_recall gave you: a turn (any message, "
        "tool call or tool output, however large), a whole exchange, or a knowledge-base entry. Each page "
        "returns total_chars and next_offset; call again with next_offset until complete is true. Returns the "
        "exact stored text, never a summary. Read-only."
    )
    input_schema = EpisodeReadInput

    def __init__(self, router: Optional[Any] = None, page_chars: int = DEFAULT_PAGE_CHARS) -> None:
        self._router = router
        self._page = min(MAX_PAGE_CHARS, max(_MIN_PAGE_CHARS, int(page_chars)))

    def is_concurrency_safe(self) -> bool:
        return True

    def fit_pages(self, max_page_chars: int) -> None:
        self._page = min(self._page, max(_MIN_PAGE_CHARS, int(max_page_chars)))

    def _get_router(self) -> Any:
        if self._router is None:
            from jarvis_core.brain.recall_router import get_router
            self._router = get_router()
        return self._router

    def _unit_text(self, ident: str) -> Optional[str]:
        router = self._get_router()
        with router._lock:
            idx = router.index
            row = idx._row(ident)
            if row is None and ident.startswith(("kb:", "file:")):
                hit = idx.db.execute("SELECT unit_id FROM units WHERE turn_ids LIKE ? LIMIT 1",
                                     (f'%"{ident}"%',)).fetchone()
                row = idx._row(hit[0]) if hit else None
                ident = hit[0] if hit else ident
            if row is None:
                return None
            return router.read_unit_whole(ident)[0]

    async def invoke(self, tool_input: EpisodeReadInput) -> ToolResult:
        from jarvis_core.memory import episode_store as es
        ident = tool_input.id.strip()
        page = self._page if tool_input.page_chars is None else min(
            MAX_PAGE_CHARS, max(_MIN_PAGE_CHARS, int(tool_input.page_chars)))
        offset = int(tool_input.offset or 0)
        try:
            if ident.startswith("turn:"):
                out = await asyncio.to_thread(es.read_turn, ident, offset, page)
                if out.get("error"):
                    return ToolResult(error=str(out["error"]))
                return ToolResult(output=out)
            if ident.startswith("ep:") and "|" not in ident:
                events = await asyncio.to_thread(lambda: list(es.iter_episode(ident)))
                if not events:
                    return ToolResult(error=f"episode {ident!r} not found in the store")
                text = "\n\n".join(f"[{e.get('n')}] {e.get('role')} {e.get('ts')}\n{es.render_event(e)}"
                                   for e in events)
            else:
                text = await asyncio.to_thread(self._unit_text, ident)
                if text is None:
                    return ToolResult(error=f"id {ident!r} not found in the store or the index")
        except Exception as e:                                     # noqa: BLE001
            return ToolResult(error=f"read failed: {type(e).__name__}: {e}")
        total = len(text)
        if offset > total:
            return ToolResult(error=f"offset {offset} is past the end ({total} chars)")
        end = min(total, offset + page)
        return ToolResult(output={
            "id": ident, "total_chars": total, "offset": offset, "returned_chars": end - offset,
            "next_offset": None if end >= total else end, "complete": end >= total,
            "content": text[offset:end],
        })


# =============================================================================
# SMOKE TESTS (hermetic: fake router, temp store)
# =============================================================================

def _run_self_test() -> None:
    import tempfile
    from types import SimpleNamespace
    from jarvis_core.agent.tool import safe_invoke
    from jarvis_core.brain.recall_router import RecallConfig, RecallItem, RecallResult
    from jarvis_core.memory import episode_store as es

    print("=" * 70)
    print("  tools/recall.py -- Smoke Tests")
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

    seen: Dict[str, Any] = {}

    class FakeRouter:
        config = RecallConfig()

        def recall(self, question, session_id, budget, rng, hosts, cfg, openable):
            seen.update(question=question, rng=rng, hosts=hosts, tool_lane=cfg.tool_lane, openable=openable)
            item = RecallItem(ref="turn:claude:s:1", unit_id="u", source="exchange", host="claude",
                              ts="2026-09-01T10:00:00", chars=40, shown="full", score=1.0, text="Tobu is Shubha")
            big = RecallItem(ref="turn:claude:s:9", unit_id="u2", source="tool_result", host="claude",
                             ts="2026-09-02T10:00:00", chars=90000, shown="handle", score=0.5, text="")
            return RecallResult(block="RECALLED MEMORY ...", items=(item, big), ranked=("u",), ranked_turns=(),
                                confidence={}, abstained=False, searched=5, queries=(question,), timings={})

    import asyncio

    async def go() -> None:
        tool = MemoryRecallTool(router=FakeRouter())
        r = await safe_invoke(tool, {"query": "who is Tobu", "time_range": "in early June", "host": "claude"})
        check("T1 memory_recall returns passages and the not-shown ids", r.error is None
              and r.output["shown"] == 1 and r.output["not_shown"][0]["id"] == "turn:claude:s:9", str(r))
        check("T2 the tool lane is on and the ids are openable", seen["tool_lane"] and seen["openable"])
        check("T3 a time phrase is parsed and passed through", seen["rng"] is not None and seen["hosts"] == ["claude"])
        bad = await safe_invoke(tool, {"query": "x", "time_range": "gibberish period"})
        check("T4 an unreadable time_range is an error, not a silent no-filter", bad.error is not None)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            s = es.EpisodeStore(root=root, machine="alpha", write_shards=False)
            s.append("claude", "sess-r", [
                {"key": "1", "ts": "2026-09-01T10:00:01+05:30", "role": "user", "content": "hello"},
                {"key": "2", "ts": "2026-09-01T10:00:02+05:30", "role": "tool_result", "content": "z" * 30_000,
                 "tool": {"name": "Bash", "use_id": "t"}},
            ])
            old = es.STORE_ROOT
            es.STORE_ROOT = root
            try:
                reader = EpisodeReadTool(router=SimpleNamespace(), page_chars=10_000)
                first = await safe_invoke(reader, {"id": "turn:claude:sess-r:1", "offset": 0})
                total = first.output["total_chars"] if first.error is None else 0
                got, off, pages = "", 0, 0
                while True:
                    r = await safe_invoke(reader, {"id": "turn:claude:sess-r:1", "offset": off})
                    if r.error:
                        break
                    got += r.output["content"]
                    pages += 1
                    if r.output["complete"]:
                        break
                    off = r.output["next_offset"]
                check("T5 episode_read pages a 30K-char tool output completely", pages >= 3 and len(got) >= 30_000,
                      f"pages={pages} len={len(got)} total={total}")
                miss = await safe_invoke(reader, {"id": "turn:claude:sess-r:99"})
                check("T6 a missing turn is an error", miss.error is not None)
            finally:
                es.STORE_ROOT = old

    asyncio.run(go())
    print("-" * 70)
    print(f"  {passed}/{passed + len(failed)} passed")
    if failed:
        print("  FAILED: " + ", ".join(failed))
    print("=" * 70)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_self_test()

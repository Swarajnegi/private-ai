#!/usr/bin/env python3
"""
ingest_episodes.py — fill the verbatim episode store from every host (Context Store, Phase 2).

LAYER: Tools (thin CLI — the store is memory/episode_store.py, parsers are
memory/episode_sources.py)

Run with:
    python scripts/ingest_episodes.py                       # incremental, all hosts, then merge shards
    python scripts/ingest_episodes.py --host codex          # one host
    python scripts/ingest_episodes.py --backfill            # re-read every source from byte 0 (deduped)
    python scripts/ingest_episodes.py --status              # sessions / events / bytes / shard sizes
    python scripts/ingest_episodes.py --verify 5            # source counts vs stored counts, 5 sessions/host
    python scripts/ingest_episodes.py --self-test           # offline fixtures, temp dirs only

=============================================================================
THE BIG PICTURE
=============================================================================

The owner's rule (2026-09-28): every agent's session is stored in full,
before compaction, under a unique id, and never compacted or deleted. The
hosts already write full transcripts; this script is the clock-driven step
that copies them — whole — into jarvis_data/context_store/, writes this
machine's git-tracked shards, and pulls the other machine's shards in.

Incremental by default: the manifest holds a byte offset per append-only
transcript and a content signature per Antigravity folder, so an hourly run
reads only new bytes. A run that another ingest already holds the lock for
exits 0 without work — the running one will get there.

=============================================================================
THE FLOW
=============================================================================

STEP 1: try-lock context_store/ingest (never two ingesters at once).
STEP 2: ingest_host() for each requested host.
STEP 3: merge_shards() — other machines' shards into the local store.
STEP 4: print a summary (never a silent zero).
=============================================================================
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "js-development"))

from jarvis_core.locking import try_exclusive_lock  # noqa: E402
from jarvis_core.memory import episode_store as es  # noqa: E402
from jarvis_core.memory.episode_sources import (  # noqa: E402
    HostPaths, antigravity_sources, antigravity_step_counts, claude_block_counts,
    claude_sources, codex_line_counts, codex_sources, ingest_host, iter_lines_from)
from jarvis_core.memory.episode_store import (  # noqa: E402
    HOSTS, EpisodeStore, iter_episode, iter_shard, list_episodes, merge_shards)


def run(hosts: List[str], backfill: bool = False, merge: bool = True,
        store: Optional[EpisodeStore] = None, paths: Optional[HostPaths] = None) -> Dict[str, Any]:
    store = store or EpisodeStore()
    store.root.mkdir(parents=True, exist_ok=True)
    with try_exclusive_lock(store.root / "ingest") as got:
        if not got:
            return {"ok": True, "busy": True}
        t0 = time.time()
        per_host = {h: ingest_host(store, h, paths, backfill) for h in hosts}
        merged = merge_shards(store) if merge else {}
        return {"ok": True, "busy": False, "per_host": per_host, "merge": merged,
                "stats": dict(store.stats), "seconds": round(time.time() - t0, 1)}


def reshard(store: Optional[EpisodeStore] = None) -> tuple:
    """Write every OWN local event into new shard files (foreign events are skipped)."""
    store = store or EpisodeStore()
    n = 0
    for ep in list_episodes(root=store.root):
        batch: List[Dict[str, Any]] = []
        for rec in iter_episode(ep["episode"], store.root):
            if rec.get("machine") != store.machine:
                continue
            batch.append(rec)
            if len(batch) >= es.BATCH_EVENTS:
                store.shards.write(batch)
                n, batch = n + len(batch), []
        if batch:
            store.shards.write(batch)
            n += len(batch)
    return n, len(store.shards.created), sum(p.stat().st_size for p in store.shards.created)


def _fmt_mb(n: int) -> str:
    return f"{n / es.MB:,.1f} MB"


def status(root: Optional[Path] = None) -> Dict[str, Any]:
    root = root or es.STORE_ROOT
    out: Dict[str, Any] = {"hosts": {}, "shards": {}}
    for h in HOSTS:
        eps = list_episodes(host=h, root=root)
        out["hosts"][h] = {"sessions": len(eps),
                           "events": sum(e["events"] or 0 for e in eps),
                           "bytes": sum(e["bytes"] for e in eps)}
    for f in es.shard_files(root / "shards"):
        out["shards"][f.relative_to(root / "shards").as_posix()] = f.stat().st_size
    return out


def verify(n_per_host: int = 5, seed: int = 7, root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Recount each sampled source independently and compare with the store."""
    rng = random.Random(seed)
    paths = HostPaths.default()
    store = EpisodeStore(root=root)
    results: List[Dict[str, Any]] = []

    def sample(items: List[Any]) -> List[Any]:
        items = sorted(items, key=lambda x: str(x[1]))
        return items if len(items) <= n_per_host else rng.sample(items, n_per_host)

    for sid, p, _ in sample(list(claude_sources(paths))):
        line = int(store.manifest.source(f"claude:{p}").get("line", 0))
        src = claude_block_counts(p, max_line=line)
        rows = [r for r in iter_episode(f"ep:claude:{es.safe_session(sid)}", root)
                if (r.get("source") or {}).get("path") == str(p)]
        k = Counter(r["kind"] for r in rows)
        roles = Counter(r["role"] for r in rows)
        results.append({"host": "claude", "session": sid, "source_lines": line,
                        "expected": src["expected_events"], "stored": len(rows),
                        "tool_use": (src["tool_use"], k["tool_use"]),
                        "tool_result": (src["tool_result"], k["tool_result"]),
                        "thinking": (src["thinking"], roles["thinking"]),
                        "ok": src["expected_events"] == len(rows)
                        and src["tool_use"] == k["tool_use"]
                        and src["tool_result"] == k["tool_result"]
                        and src["thinking"] == roles["thinking"]})
    for sid, p, _ in sample(list(codex_sources(paths))):
        line = int(store.manifest.source(f"codex:{p}").get("line", 0))
        src = codex_line_counts(p, max_line=line)
        rows = [r for r in iter_episode(f"ep:codex:{es.safe_session(sid)}", root)
                if (r.get("source") or {}).get("path") == str(p)]
        roles = Counter(r["role"] for r in rows)
        kinds = Counter(r["kind"] for r in rows)
        outputs = kinds["function_call_output"] + kinds["custom_tool_call_output"]
        msgs = sum(v for kk, v in kinds.items() if kk.startswith("message") or kk == "developer")
        results.append({"host": "codex", "session": sid, "source_lines": line,
                        "expected": src["expected_events"], "stored": len(rows),
                        "messages": (src["messages"], msgs),
                        "tool_calls": (src["tool_calls"], roles["tool_call"]),
                        "tool_outputs": (src["tool_outputs"], outputs),
                        "reasoning": (src["reasoning"], roles["thinking"]),
                        "compactions": (src["compactions"], roles["compaction"]),
                        "ok": src["expected_events"] == len(rows)
                        and src["messages"] == msgs and src["tool_calls"] == roles["tool_call"]
                        and src["tool_outputs"] == outputs
                        and src["reasoning"] == roles["thinking"]
                        and src["compactions"] == roles["compaction"]})
    for sid, d, _ in sample(list(antigravity_sources(paths))):
        rows = list(iter_episode(f"ep:antigravity:{sid}", root))
        steps = {(r.get("source") or {}).get("step_index") for r in rows
                 if "step_index" in (r.get("source") or {})}
        files = [f for f in d.rglob("*") if f.is_file()]
        transcripts = {"transcript_full.jsonl", "transcript.jsonl", "overview.txt"}
        n_files = sum(1 for f in files if not f.name.endswith(".metadata.json")
                      and not (f.name in transcripts and (f.parent.name == "logs" or f.parent == d)))
        file_rows = {r["key"].split(":", 1)[1].rsplit(":", 1)[0] if r["key"].startswith("file:")
                     else r["key"].split(":", 1)[1]
                     for r in rows if r["key"].startswith(("file:", "media:", "msg:"))}
        want = antigravity_step_counts(d)["distinct_steps"]
        results.append({"host": "antigravity", "session": sid,
                        "steps": (want, len(steps)), "files": (n_files, len(file_rows)),
                        "stored": len(rows),
                        "ok": want == len(steps) and n_files == len(file_rows)})
    convs = sorted(paths.conversations.glob("*.jsonl")) if paths.conversations.exists() else []
    for f in convs[:n_per_host]:
        n_lines = sum(1 for _ in iter_lines_from(f, 0, 0))
        rows = list(iter_episode(f"ep:jarvis:{es.safe_session(f.stem)}", root))
        results.append({"host": "jarvis", "session": f.stem, "expected": n_lines,
                        "stored": len(rows), "ok": n_lines == len(rows)})
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest every host's full transcripts into the episode store.")
    ap.add_argument("--host", default="all", choices=["all", *HOSTS])
    ap.add_argument("--backfill", action="store_true",
                    help="re-read every source from byte 0 (deduped by key)")
    ap.add_argument("--no-merge", action="store_true", help="skip pulling other machines' shards")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--verify", type=int, metavar="N", help="verify N sessions per host")
    ap.add_argument("--reshard", action="store_true",
                    help="write this machine's local events into NEW shard files "
                         "(repair / layout migration; merge dedupes by id)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        _run_self_test()
        return 0
    if args.status:
        s = status()
        print(f"episode store: {es.STORE_ROOT}  (machine {es.machine_name()})")
        for h, v in s["hosts"].items():
            print(f"  {h:<12} sessions {v['sessions']:>5}  events {v['events']:>9,}  {_fmt_mb(v['bytes']):>12}")
        total = sum(s["shards"].values())
        print(f"shards: {len(s['shards'])} files, {_fmt_mb(total)}")
        groups: Dict[str, List[int]] = {}
        for rel, size in s["shards"].items():
            groups.setdefault(rel.rsplit("/", 1)[0], []).append(size)
        for g, sizes in groups.items():
            print(f"  {g:<40} {len(sizes):>4} files {_fmt_mb(sum(sizes)):>10}  (max {_fmt_mb(max(sizes))})")
        return 0
    if args.verify:
        res = verify(args.verify)
        for r in res:
            print(json.dumps(r, ensure_ascii=False))
        bad = [r for r in res if not r["ok"]]
        print(f"verified {len(res)} sessions: {len(res) - len(bad)} ok, {len(bad)} mismatched")
        return 1 if bad else 0

    if args.reshard:
        n, files, size = reshard()
        print(f"resharded {n:,} events into {files} new files ({_fmt_mb(size)})")
        return 0
    hosts = list(HOSTS) if args.host == "all" else [args.host]
    result = run(hosts, backfill=args.backfill, merge=not args.no_merge)
    if result.get("busy"):
        print("another ingest holds the lock; exiting without work (it will cover this)")
        return 0
    for h, v in result["per_host"].items():
        print(f"{h:<12} sources {v['sources']:>5}  new events {v['events']:>9,}")
    print(f"merge: {result['merge']}")
    st = result["stats"]
    print(f"wrote {st['events']:,} events ({_fmt_mb(st['bytes'])} local, "
          f"{_fmt_mb(st['shard_bytes'])} shard) in {result['seconds']}s")
    return 0


# =============================================================================
# SMOKE TESTS (offline — fixture transcripts per host format, temp dirs only)
# =============================================================================

def _run_self_test() -> None:
    import shutil
    import tempfile

    print("=" * 70)
    print("  ingest_episodes.py -- Smoke Tests")
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

    def jl(rows: List[Dict[str, Any]]) -> str:
        return "".join(json.dumps(r) + "\n" for r in rows)

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        home = base / "home"
        paths = HostPaths(
            claude_projects=home / ".claude" / "projects",
            codex_home=home / ".codex",
            antigravity_brain=home / ".gemini" / "antigravity-ide" / "brain",
            conversations=base / "jd" / "conversations",
            queue=base / "jd" / "observation_queue.jsonl",
        )
        # ---- Claude fixture ----
        proj = paths.claude_projects / "E--repo"
        sid = "11111111-1111-1111-1111-111111111111"
        (proj / sid / "tool-results").mkdir(parents=True)
        (proj / sid / "subagents").mkdir(parents=True)
        persisted = proj / sid / "tool-results" / "big.txt"
        full_output = "FULL-OUTPUT " * 5000
        persisted.write_text(full_output, encoding="utf-8")
        ts = "2026-09-20T10:00:00.000Z"
        claude_rows = [
            {"type": "custom-title", "customTitle": "Fixture chat", "sessionId": sid},
            {"type": "attachment", "timestamp": ts, "attachment": {"type": "hook_success", "content": "ctx"}},
            {"type": "user", "timestamp": ts, "message": {"role": "user", "content": "hello there"}},
            {"type": "assistant", "timestamp": ts, "message": {"model": "claude-x", "content": [
                {"type": "thinking", "thinking": "let me think", "signature": "SIG"},
                {"type": "text", "text": "Reading."},
                {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/a.py"}}]}},
            {"type": "user", "timestamp": ts, "message": {"content": [
                {"type": "tool_result", "tool_use_id": "tu1",
                 "content": f"<persisted-output>\nOutput too large. Full output saved to: {persisted}\n\nPreview (first 2KB):\nFULL-OU"}]}},
            {"type": "user", "timestamp": ts, "message": {"content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR"}}]}},
            {"type": "system", "subtype": "compact_boundary", "timestamp": ts, "content": "Conversation compacted",
             "compactMetadata": {"trigger": "manual"}},
            {"type": "user", "timestamp": ts, "isCompactSummary": True,
             "message": {"content": "Summary: we built things"}},
            {"type": "file-history-snapshot", "snapshot": {}},
        ]
        transcript = proj / f"{sid}.jsonl"
        transcript.write_text(jl(claude_rows) + '{"type": "user", "timestamp": "' + ts + '", "mess',
                              encoding="utf-8")
        sub = proj / sid / "subagents" / "agent-abc.jsonl"
        sub.write_text(jl([{"type": "user", "isSidechain": True, "timestamp": ts,
                            "message": {"content": "do the subtask"}}]), encoding="utf-8")
        sub.with_suffix(".meta.json").write_text(json.dumps({"agentType": "Explore",
                                                              "description": "find X"}), encoding="utf-8")
        # ---- Codex fixture ----
        cdir = paths.codex_home / "sessions" / "2026" / "09" / "20"
        cdir.mkdir(parents=True)
        cid = "019f0000-0000-7000-8000-000000000001"
        huge = "O" * (es.STUB_BYTES + 100)
        codex_rows = [
            {"timestamp": ts, "type": "session_meta", "payload": {"id": cid, "cwd": "/repo"}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "developer",
                                                                  "content": [{"type": "input_text", "text": "sys"}]}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "user",
                                                                  "content": [{"type": "input_text", "text": "build it"}]}},
            {"timestamp": ts, "type": "event_msg", "payload": {"type": "item_completed",
                                                              "item": {"type": "UserMessage", "content": []}}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "reasoning", "summary": [
                {"type": "summary_text", "text": "**Planning**"}], "encrypted_content": "gAAAA"}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                                                                  "call_id": "c1", "arguments": "{\"cmd\":\"ls\"}"}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                                                                  "output": huge}},
            {"timestamp": ts, "type": "event_msg", "payload": {"type": "item_completed", "item": {
                "type": "CommandExecution", "id": "c1", "aggregated_output": "a.py",
                "_meta": {"screenshot": {"url": "data:image/png;base64," + "A" * 5000}}}}},
            {"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count"}},
            {"timestamp": ts, "type": "compacted", "payload": {"message": "", "replacement_history": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "build it"}]}]}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                                  "content": [{"type": "output_text", "text": "done"}]}},
        ]
        (cdir / f"rollout-2026-09-20T10-00-00-{cid}.jsonl").write_text(jl(codex_rows), encoding="utf-8")
        (paths.codex_home / "session_index.jsonl").write_text(
            json.dumps({"id": cid, "thread_name": "Codex fixture"}) + "\n", encoding="utf-8")
        # ---- Antigravity fixture ----
        ag = paths.antigravity_brain / "22222222-2222-4222-8222-222222222222"
        logs = ag / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        (ag / ".system_generated" / "messages").mkdir()
        mid = [{"step_index": i, "type": t, "created_at": ts, "content": c} for i, t, c in
               [(0, "USER_INPUT", "<USER_REQUEST>plan the app</USER_REQUEST>"),
                (1, "PLANNER_RESPONSE", "trunc"), (2, "RUN_COMMAND", "out")]]
        mid[1]["tool_calls"] = [{"name": "run_command", "args": {"CommandLine": "ls"}}]
        full = [{"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": ts,
                 "content": "the FULL planner text", "thinking": "hmm",
                 "tool_calls": [{"name": "run_command", "args": {"CommandLine": "ls"}}]},
                {"step_index": 3, "type": "PLANNER_RESPONSE", "created_at": ts, "content": "later"}]
        (logs / "transcript.jsonl").write_text(jl(mid), encoding="utf-8")
        (logs / "transcript_full.jsonl").write_text(jl(full), encoding="utf-8")
        (ag / "task.md").write_text("# Build the app\n- [x] step\n", encoding="utf-8")
        (ag / "task.md.resolved.0").write_text("# Build the app\n- [ ] step\n", encoding="utf-8")
        (ag / "task.md.metadata.json").write_text(json.dumps({"updatedAt": ts}), encoding="utf-8")
        (ag / "shot.png").write_bytes(b"\x89PNG\r\n\x00\x00")
        (ag / ".system_generated" / "messages" / "m1.json").write_text(
            json.dumps({"sender": "system", "timestamp": ts, "content": "restart notice"}), encoding="utf-8")
        # ---- JARVIS fixture ----
        paths.conversations.mkdir(parents=True)
        (paths.conversations / "conv-web-a.jsonl").write_text(jl([
            {"ts": "2026-09-28T08:50:58+05:30", "role": "user", "content": "Hi, JARVIS."},
            {"ts": "2026-09-28T08:50:58+05:30", "role": "assistant", "content": "Morning, sir."}]),
            encoding="utf-8")
        paths.queue.write_text(jl([
            {"ts": "2026-09-01T10:00:00+05:30", "session_id": "conv-web-a", "chat_label": "voice-ask",
             "machine": "alpha", "user_text": "dup of conv file", "assistant_summary": "x"},
            {"ts": "2026-09-02T10:00:00+05:30", "session_id": "terminal-1", "chat_label": "terminal-ask",
             "machine": "alpha", "user_text": "only in queue", "assistant_summary": "answer"},
            {"ts": "2026-09-03T10:00:00+05:30", "session_id": "terminal-2", "chat_label": "terminal-ask",
             "machine": "work-box", "user_text": "other machine's row", "assistant_summary": "no"},
            {"ts": "2026-09-03T10:00:00+05:30", "session_id": sid, "host": "claude",
             "machine": "alpha", "user_text": "claude row", "assistant_summary": "no"}]), encoding="utf-8")

        root = base / "cs"
        store = EpisodeStore(root=root, machine="alpha")
        r = run(list(HOSTS), store=store, paths=paths)
        cep = list(iter_episode(f"ep:claude:{sid}", root))
        kinds = Counter(x["kind"] for x in cep)
        src_counts = claude_block_counts(transcript)
        check("T1 claude: every block/attachment/system record stored, bookkeeping skipped",
              len(cep) == src_counts["expected_events"] == 9, f"{len(cep)} vs {src_counts}")
        check("T2 claude: partial trailing line NOT consumed", all(x["source"]["line"] < 9 for x in cep))
        tr = next(x for x in cep if x["kind"] == "tool_result")
        check("T3 claude: persisted-output resolved to the FULL file, preview kept",
              tr["content"] == full_output and "Preview" in tr["tool"]["model_saw"]
              and tr["tool"]["name"] == "Read")
        check("T4 claude: thinking verbatim, signature opaque; image by reference",
              any(x["role"] == "thinking" and x["content"] == "let me think" and x["opaque"]["signature"] == "SIG"
                  for x in cep) and any(x["kind"] == "image" and x["media"][0].endswith(":b0") for x in cep))
        check("T5 claude: compact boundary + summary are role=compaction",
              kinds["compact_boundary"] == 1 and kinds["compact_summary"] == 1
              and sum(1 for x in cep if x["role"] == "compaction") == 2)
        subep = list(iter_episode(f"ep:claude:{sid}.agent-abc", root))
        check("T6 claude: subagent is its own episode linked to its parent",
              len(subep) == 1 and subep[0]["parent_episode"] == f"ep:claude:{sid}"
              and subep[0].get("sidechain") is True)
        title = store.manifest.session(f"ep:claude:{sid}").get("title")
        check("T7 claude: custom title recorded in the manifest", title == "Fixture chat", str(title))

        xep = list(iter_episode(f"ep:codex:{cid}", root))
        xk = Counter(x["kind"] for x in xep)
        cc = codex_line_counts(next(cdir.glob("*.jsonl")))
        check("T8 codex: mirrored item_completed + token_count skipped, the rest stored",
              len(xep) == cc["expected_events"] == 9, f"{len(xep)} {dict(xk)} {cc}")
        comp = next(x for x in xep if x["kind"] == "compacted")
        check("T9 codex: compacted record keeps its full replacement_history",
              comp["role"] == "compaction" and "build it" in comp["content"]
              and "[replacement_history]" in comp["content"])
        big = next(x for x in xep if x["kind"] == "function_call_output")
        check("T10 codex: tool output whole locally, tool name linked to its call",
              big["content"] == huge and big["tool"]["name"] == "exec_command")
        shard = [x for f in es.shard_files(root / "shards", "alpha") for x in iter_shard(f)]
        sbig = next(x for x in shard if x["kind"] == "function_call_output")
        check("T11 codex: >1 MB output is a stub in the shard only",
              sbig["content"] == "" and sbig["stub"]["held_by"] == "alpha"
              and sbig["stub"]["bytes"] > es.STUB_BYTES)
        ce = next(x for x in xep if x["kind"] == "codex_item:CommandExecution")
        check("T12b codex: inline base64 screenshot replaced by a source reference",
              "A" * 1000 not in ce["content"] and ce["media"] and "#L" in ce["media"][0]
              and "a.py" in ce["content"])
        check("T12 codex: encrypted reasoning local-only, summary text stored",
              any(x["role"] == "thinking" and x["content"] == "**Planning**" and "opaque" in x for x in xep)
              and all("opaque" not in x for x in shard))

        aep = list(iter_episode(f"ep:antigravity:{ag.name}", root))
        steps = {x["source"].get("step_index") for x in aep if "step_index" in x["source"]}
        s1 = [x for x in aep if x["source"].get("step_index") == 1]
        check("T13 antigravity: steps unioned across files (0..3 all present)",
              steps == {0, 1, 2, 3}, str(steps))
        check("T14 antigravity: the higher-fidelity file wins per step",
              any(x["content"] == "the FULL planner text" for x in s1)
              and not any(x["content"] == "trunc" for x in s1)
              and {x["role"] for x in s1} == {"thinking", "assistant", "tool_call"})
        check("T15 antigravity: artifact versions, message, media all stored",
              sum(1 for x in aep if x["kind"] == "artifact") == 2
              and any(x["kind"] == "message" and x["content"] == "restart notice" for x in aep)
              and any(x["kind"] == "media" and x["media"][0].endswith("shot.png") for x in aep))

        jep = list(iter_episode("ep:jarvis:conv-web-a", root))
        check("T16 jarvis: conversation file stored; its queue duplicate is not",
              [x["content"] for x in jep] == ["Hi, JARVIS.", "Morning, sir."])
        check("T17 jarvis: queue-only session from THIS machine stored, other machine's is not",
              len(list(iter_episode("ep:jarvis:terminal-1", root))) == 2
              and not list(iter_episode("ep:jarvis:terminal-2", root)))

        before = sum(1 for _ in (root / "episodes").rglob("*.jsonl") for _ in open(_, "rb"))
        r2 = run(list(HOSTS), store=EpisodeStore(root=root, machine="alpha"), paths=paths)
        after = sum(1 for _ in (root / "episodes").rglob("*.jsonl") for _ in open(_, "rb"))
        check("T18 re-run is a no-op", r2["stats"]["events"] == 0 and before == after, str(r2["stats"]))
        r3 = run(list(HOSTS), backfill=True, store=EpisodeStore(root=root, machine="alpha"), paths=paths)
        check("T19 --backfill re-reads everything and still adds nothing",
              r3["stats"]["events"] == 0 and r3["stats"]["skipped"] > 0, str(r3["stats"]))

        with transcript.open("a", encoding="utf-8") as fh:
            fh.write('age": {"content": "second question"}}\n')
            fh.write(json.dumps({"type": "assistant", "timestamp": ts,
                                 "message": {"content": [{"type": "text", "text": "second answer"}]}}) + "\n")
        r4 = run(["claude"], store=EpisodeStore(root=root, machine="alpha"), paths=paths, merge=False)
        cep2 = list(iter_episode(f"ep:claude:{sid}", root))
        check("T20 incremental: the completed partial line + new line appended, nothing re-added",
              r4["stats"]["events"] == 2 and [x["content"] for x in cep2[-2:]]
              == ["second question", "second answer"] and len({x["id"] for x in cep2}) == len(cep2),
              str(r4["stats"]))
        check("T21 n stays monotonic across runs", [x["n"] for x in cep2] == list(range(len(cep2))))

        saved = es.SHARD_LIMIT_BYTES
        es.SHARD_LIMIT_BYTES = 2500
        try:
            rnd = random.Random(3)
            for i in range(5):
                noise = "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(2500))
                with transcript.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"type": "user", "timestamp": ts,
                                         "message": {"content": noise}}) + "\n")
                run(["claude"], store=EpisodeStore(root=root, machine="alpha"), paths=paths, merge=False)
        finally:
            es.SHARD_LIMIT_BYTES = saved
        parts = sorted((root / "shards" / "alpha" / "claude" / "2026-09").glob("*.jsonl.gz"))
        check("T22 immutable layout: one new small file per run, every file under the limit",
              len(parts) >= 6 and all(p.stat().st_size < 2500 for p in parts[-5:]),
              str([(p.name, p.stat().st_size) for p in parts]))
        shard_ids = [x["id"] for p in parts for x in iter_shard(p)]
        local_ids = [x["id"] for x in iter_episode(f"ep:claude:{sid}", root)]
        check("T23 every local claude event is in the shards exactly once",
              sorted(set(shard_ids) & set(local_ids)) == sorted(local_ids)
              and len(shard_ids) == len(set(shard_ids)))
        snap = {p: p.read_bytes() for p in es.shard_files(root / "shards")}
        quiet = run(list(HOSTS), store=EpisodeStore(root=root, machine="alpha"), paths=paths)
        now = {p: p.read_bytes() for p in es.shard_files(root / "shards")}
        check("T23b an idle run writes no shard file and modifies none",
              quiet["stats"]["events"] == 0 and now == snap)

        # another machine pulls these shards
        other = base / "other"
        (other / "shards").mkdir(parents=True)
        shutil.copytree(root / "shards" / "alpha", other / "shards" / "alpha")
        beta = EpisodeStore(root=other, machine="beta")
        m1 = run([], store=beta, paths=paths)
        got = list(iter_episode(f"ep:claude:{sid}", other))
        check("T24 other machine merges the shards: same ids, same order",
              [x["id"] for x in got] == local_ids and m1["merge"]["records_added"] > 0, str(m1["merge"]))
        check("T25 >1 MB output arrives as a stub naming the holder",
              next(x for x in iter_episode(f"ep:codex:{cid}", other)
                   if x["kind"] == "function_call_output")["stub"]["held_by"] == "alpha")
        m2 = run([], store=EpisodeStore(root=other, machine="beta"), paths=paths)
        check("T26 re-merge adds nothing", m2["merge"]["records_added"] == 0, str(m2["merge"]))

        with try_exclusive_lock(root / "ingest") as held:
            busy = run(["claude"], store=EpisodeStore(root=root, machine="alpha"), paths=paths)
        check("T27 a second concurrent ingest exits busy instead of racing",
              held and busy.get("busy") is True)
        st = status(root)
        check("T28 --status reports sessions/events/bytes and shard sizes",
              st["hosts"]["claude"]["sessions"] == 2 and st["hosts"]["codex"]["events"] == 9
              and any(k.startswith("alpha/codex/") for k in st["shards"]), json.dumps(st)[:300])

    total = passed + len(failed)
    print("-" * 70)
    print(f"  {passed}/{total} passed")
    if failed:
        for name in failed:
            print(f"    - {name}")
    print("=" * 70)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    raise SystemExit(main())

"""
episode_sources.py — host transcript parsers for the episode store.

LAYER: Memory (Context Store — ingestion adapters)

Import with:
    from jarvis_core.memory.episode_sources import (
        HostPaths, ingest_host, ingest_claude_transcript, claude_block_counts,
    )

=============================================================================
THE BIG PICTURE
=============================================================================

The capture adapters (agent/capture.py, scripts/ingest_codex_sessions.py,
scripts/ingest_antigravity_sessions.py) learned each host's on-disk format but
keep only user text + the final answer. This module reads the same files and
keeps the WHOLE transcript: every message block, tool call with its input,
tool output (including Claude Code's <persisted-output> files, read back in
full), reasoning, compaction summaries, artifacts and media references.

One rule per host, stated once so a verifier can count it independently:

  claude       one event per message content block; one per attachment /
               system / queue record with content; UI bookkeeping records
               (titles, modes, file-history, cost) are metadata, not events.
               Subagent transcripts are their own episodes, linked by
               parent_episode.
  codex        one event per rollout line, except token/usage/world-state
               bookkeeping and the item_completed events that merely mirror a
               response_item (AgentMessage, UserMessage, Reasoning, WebSearch,
               ContextCompaction). `compacted` records keep their full
               replacement_history.
  antigravity  transcript steps unioned across transcript_full.jsonl >
               transcript.jsonl > overview.txt (per step, the highest-fidelity
               file wins — the capture adapter picks ONE file, and on session
               5a76f739 its choice holds 55 of 2,376 steps). Each step line
               yields thinking / content / tool_calls / error parts. Plus every
               artifact version, scratch file, task log, system message, and a
               media event per image/recording (path only).
  jarvis       conversations/*.jsonl lines; capture-queue rows only for
               JARVIS sessions with no conversation file on this machine.

Images and binary media are never copied: `media` holds the host's own path
(or <transcript>#L<line>:b<block> for an inline base64 image).

=============================================================================
THE FLOW
=============================================================================

STEP 1: discover sources per host (HostPaths — overridable for tests).
        |
STEP 2: append-only JSONL sources resume from the manifest's byte offset and
        stop at a line with no terminator (the host is still writing it).
        Antigravity session folders are mutable, so a changed folder
        signature re-parses the folder and the store's keys dedupe it.
        |
STEP 3: EpisodeStore.append() -> local lines + this machine's shard member.
        |
STEP 4: record the new offset / signature in the manifest.
=============================================================================
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # standalone-run safety
from jarvis_core.config import DATA_ROOT  # noqa: E402
from jarvis_core.memory.episode_store import (  # noqa: E402
    EpisodeStore, _loads, episode_id, safe_session, to_ist)

Event = Dict[str, Any]


@dataclass(frozen=True)
class HostPaths:
    claude_projects: Path
    codex_home: Path
    antigravity_brain: Path
    conversations: Path
    queue: Path

    @classmethod
    def default(cls) -> "HostPaths":
        home = Path.home()
        return cls(
            claude_projects=home / ".claude" / "projects",
            codex_home=home / ".codex",
            antigravity_brain=home / ".gemini" / "antigravity-ide" / "brain",
            conversations=Path(DATA_ROOT) / "conversations",
            queue=Path(DATA_ROOT) / "observation_queue.jsonl",
        )


@dataclass
class _Ctx:
    title: str = ""
    last_ts: str = ""
    tool_names: Dict[str, str] = field(default_factory=dict)


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _sha(text: str, n: int = 12) -> str:
    return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()[:n]


_INLINE_MEDIA_MIN = 1000


def _externalize(obj: Any, ref: str, media: List[str]) -> Any:
    """Replace inline base64 media inside a JSON value with a reference to where it lives.

    The owner's rule: media stays in the host's files and is referenced by
    path. An inline screenshot's home is the source line it was read from.
    Measured on this machine's Codex history: 80 MB of McpToolCall records
    were one field, result._meta.codex.toolSurface.screenshot.url (data: URLs).
    """
    if isinstance(obj, dict):
        is_image = "image" in str(obj.get("type", "")) or str(obj.get("mimeType", "")).startswith("image/")
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if (isinstance(v, str) and len(v) > _INLINE_MEDIA_MIN
                    and (v.startswith("data:") or (is_image and k in ("data", "image_url", "url")))):
                media.append(ref)
                out[k] = f"[inline media, {len(v)} chars, kept in source: {ref}]"
            else:
                out[k] = _externalize(v, ref, media)
        return out
    if isinstance(obj, list):
        return [_externalize(v, ref, media) for v in obj]
    return obj


def iter_lines_from(path: Path, offset: int, line_no: int) -> Iterator[Tuple[int, int, bytes]]:
    """(line_no, end_offset, raw) for each COMPLETE line after `offset`.

    A final line without "\\n" is a line the host is still writing: stopping
    before it keeps the offset honest, so the next run reads it whole.
    """
    try:
        fh = path.open("rb")
    except OSError:
        return
    with fh:
        fh.seek(offset)
        pos = offset
        for raw in fh:
            if not raw.endswith(b"\n"):
                return
            pos += len(raw)
            yield line_no, pos, raw
            line_no += 1


def _unparseable(raw: bytes, path: Path, line: int) -> Event:
    return {"key": f"L{line}", "role": "system", "kind": "unparseable_line",
            "content": raw.decode("utf-8", "replace").rstrip("\n"),
            "source": {"path": str(path), "line": line}}


# =============================================================================
# Part 1: CLAUDE CODE
# =============================================================================

CLAUDE_METADATA_TYPES = frozenset({
    "last-prompt", "atis-latch", "custom-title", "agent-name", "ai-title", "mode",
    "file-history-snapshot", "file-history-delta", "cost-state",
})
_PERSISTED = re.compile(r"<persisted-output>.*?Full output saved to:\s*(.+?)\s*(?:\r?\n|$)", re.DOTALL)
_TEXT_EXT = frozenset({".txt", ".md", ".json", ".log", ".py", ".js", ".ts", ".csv", ".html", ".css",
                       ".yaml", ".yml", ".sql", ".sh", ".ps1", ".xml", ".toml", ".ini", ".jsonl"})


def _read_text_file(path: Path) -> Optional[str]:
    """Full text of a file, or None when it is binary (NUL bytes) or unreadable."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def _claude_result(content: Any, path: Path, line: int, block: int) -> Tuple[str, List[str]]:
    media: List[str] = []
    if isinstance(content, str):
        return content, media
    parts: List[str] = []
    for i, b in enumerate(content or []):
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(str(b.get("text", "")))
        elif isinstance(b, dict) and b.get("type") == "image":
            media.append(f"{path}#L{line}:b{block}.{i}")
        else:
            parts.append(_j(_externalize(b, f"{path}#L{line}:b{block}.{i}", media)))
    return "\n".join(parts), media


def _resolve_persisted(text: str, tool: Dict[str, Any], media: List[str]) -> str:
    """Swap Claude Code's 2 KB preview for the full output file it points at."""
    m = _PERSISTED.search(text or "")
    if not m:
        return text
    target = Path(m.group(1).strip())
    tool["persisted_path"] = str(target)
    full = _read_text_file(target) if target.exists() else None
    if full is None:
        if target.exists():
            media.append(str(target))
        tool["persisted_missing"] = not target.exists()
        return text
    tool["model_saw"] = text
    return full


def claude_record_events(rec: Dict[str, Any], line: int, path: Path, ctx: _Ctx) -> List[Event]:
    t = rec.get("type")
    ts = to_ist(rec.get("timestamp")) or ctx.last_ts
    ctx.last_ts = ts
    src = {"path": str(path), "line": line}
    base: Event = {"ts": ts, "source": src}
    if rec.get("isSidechain"):
        base["sidechain"] = True

    if t in ("custom-title", "ai-title"):
        title = rec.get("customTitle") or rec.get("aiTitle") or ""
        if title and (t == "custom-title" or not ctx.title):
            ctx.title = str(title)
        return []
    if t in CLAUDE_METADATA_TYPES:
        return []
    if t == "queue-operation":
        if not rec.get("content"):
            return []
        return [{**base, "key": f"L{line}", "role": "system",
                 "kind": f"queue:{rec.get('operation')}", "content": str(rec.get("content"))}]

    if t in ("user", "assistant"):
        msg = rec.get("message") or {}
        content = msg.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
        default_role, default_kind = ("assistant", "message") if t == "assistant" else ("user", "message")
        if rec.get("isCompactSummary"):
            default_role, default_kind = "compaction", "compact_summary"
        elif rec.get("isMeta"):
            default_role, default_kind = "system", "meta"
        if rec.get("isApiErrorMessage"):
            default_kind = "api_error"
        extra: Event = {}
        model = msg.get("model")
        if model:
            extra["model"] = model
        out: List[Event] = []
        for i, b in enumerate(blocks):
            ev: Event = {**base, **extra, "key": f"L{line}:b{i}", "source": {**src, "block": i}}
            bt = b.get("type") if isinstance(b, dict) else None
            if bt == "text":
                ev.update(role=default_role, kind=default_kind, content=str(b.get("text", "")))
            elif bt in ("thinking", "redacted_thinking"):
                ev.update(role="thinking", kind=bt, content=str(b.get("thinking", "") or ""))
                opaque = {k: b[k] for k in ("signature", "data") if b.get(k)}
                if opaque:
                    ev["opaque"] = opaque
            elif bt == "tool_use":
                ctx.tool_names[str(b.get("id"))] = str(b.get("name", ""))
                ev.update(role="tool_call", kind="tool_use", content=_j(b.get("input")),
                          tool={"name": b.get("name"), "id": b.get("id"), "input": b.get("input")})
            elif bt == "tool_result":
                text, media = _claude_result(b.get("content"), path, line, i)
                tool: Dict[str, Any] = {"use_id": b.get("tool_use_id"),
                                        "name": ctx.tool_names.get(str(b.get("tool_use_id")), "")}
                if b.get("is_error"):
                    tool["is_error"] = True
                text = _resolve_persisted(text, tool, media)
                if tool.get("persisted_missing") and rec.get("toolUseResult") is not None:
                    tool["tool_use_result"] = rec["toolUseResult"]
                ev.update(role="tool_result", kind="tool_result", content=text, tool=tool, media=media)
            elif bt == "image":
                src_meta = b.get("source") or {}
                ev.update(role=default_role, kind="image", content="",
                          media=[f"{path}#L{line}:b{i}"],
                          tool={"media_type": src_meta.get("media_type"),
                                "base64_chars": len(str(src_meta.get("data", "")))})
            else:
                blk_media: List[str] = []
                ev.update(role=default_role, kind=f"block:{bt}",
                          content=_j(_externalize(b, f"{path}#L{line}:b{i}", blk_media)),
                          media=sorted(set(blk_media)))
            out.append(ev)
        return out

    if t == "attachment":
        att = rec.get("attachment") or {}
        media: List[str] = []
        body = _j(_externalize(att, f"{path}#L{line}", media))
        return [{**base, "key": f"L{line}", "role": "system",
                 "kind": f"attachment:{att.get('type')}", "content": body,
                 "media": sorted(set(media))}]

    if t == "system":
        sub = rec.get("subtype") or ""
        if sub == "compact_boundary":
            return [{**base, "key": f"L{line}", "role": "compaction", "kind": "compact_boundary",
                     "content": _j({"content": rec.get("content"),
                                    "compactMetadata": rec.get("compactMetadata"),
                                    "logicalParentUuid": rec.get("logicalParentUuid")})}]
        body = rec.get("content")
        return [{**base, "key": f"L{line}", "role": "system", "kind": f"system:{sub}",
                 "content": body if isinstance(body, str) else _j(rec)}]

    return [{**base, "key": f"L{line}", "role": "system", "kind": f"raw:{t}", "content": _j(rec)}]


def claude_block_counts(path: Path, max_line: Optional[int] = None) -> Dict[str, int]:
    """Source-side counts for verification, derived WITHOUT the parser above."""
    c = {"records": 0, "text": 0, "tool_use": 0, "tool_result": 0, "thinking": 0,
         "image": 0, "other_blocks": 0, "attachment": 0, "system": 0, "queue": 0,
         "unknown": 0, "metadata": 0, "unparseable": 0}
    for ln, _, raw in iter_lines_from(path, 0, 0):
        if max_line is not None and ln >= max_line:
            break
        rec = _loads(raw)
        if rec is None:
            c["unparseable"] += 1
            continue
        c["records"] += 1
        t = rec.get("type")
        if t in ("user", "assistant"):
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, str):
                c["text"] += 1
                continue
            for b in content or []:
                bt = b.get("type") if isinstance(b, dict) else None
                key = {"text": "text", "tool_use": "tool_use", "tool_result": "tool_result",
                       "thinking": "thinking", "redacted_thinking": "thinking",
                       "image": "image"}.get(bt or "", "other_blocks")
                c[key] += 1
        elif t == "attachment":
            c["attachment"] += 1
        elif t == "system":
            c["system"] += 1
        elif t == "queue-operation":
            c["queue" if rec.get("content") else "metadata"] += 1
        elif t in CLAUDE_METADATA_TYPES:
            c["metadata"] += 1
        else:
            c["unknown"] += 1
    c["expected_events"] = (c["text"] + c["tool_use"] + c["tool_result"] + c["thinking"] + c["image"]
                            + c["other_blocks"] + c["attachment"] + c["system"] + c["queue"]
                            + c["unknown"] + c["unparseable"])
    return c


def claude_sources(paths: HostPaths) -> Iterator[Tuple[str, Path, Dict[str, Any]]]:
    """(session_id, transcript, extra-fields) for every main and subagent transcript."""
    root = paths.claude_projects
    if not root.exists():
        return
    for proj in sorted(p for p in root.iterdir() if p.is_dir()):
        for tp in sorted(proj.glob("*.jsonl")):
            yield tp.stem, tp, {"project": proj.name}
        # Subagents nest: <sid>/subagents/agent-*.jsonl and, for workflow
        # fan-outs, <sid>/subagents/workflows/wf_*/agent-*.jsonl.
        for sub in sorted(proj.glob("*/subagents/**/agent-*.jsonl")):
            parent = next(a for a in sub.parents if a.name == "subagents").parent.name
            extra: Dict[str, Any] = {"project": proj.name,
                                     "parent_episode": episode_id("claude", parent)}
            meta = sub.with_suffix(".meta.json")
            if meta.exists():
                try:
                    m = json.loads(meta.read_text(encoding="utf-8"))
                    extra["title"] = str(m.get("description") or m.get("agentType") or "")
                    extra["agent_type"] = m.get("agentType")
                except (OSError, ValueError):
                    pass
            yield f"{parent}.{sub.stem}", sub, extra
        # A workflow's journal holds each agent's structured result: stored as
        # its own episode of raw records (role=system, kind raw:<type>).
        for journal in sorted(proj.glob("*/subagents/**/journal.jsonl")):
            parent = next(a for a in journal.parents if a.name == "subagents").parent.name
            yield (f"{parent}.{journal.parent.name}-journal", journal,
                   {"project": proj.name, "parent_episode": episode_id("claude", parent),
                    "title": f"workflow journal {journal.parent.name}"})


# =============================================================================
# Part 2: CODEX
# =============================================================================

CODEX_SKIP_TYPES = frozenset({"world_state", "token_usage_record"})
CODEX_SKIP_EVENTS = frozenset({"token_count", "task_started", "task_complete",
                               "thread_settings_applied", "item_started", "item_updated"})
CODEX_MIRRORED_ITEMS = frozenset({"AgentMessage", "UserMessage", "Reasoning", "WebSearch",
                                  "ContextCompaction"})
_UUID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", re.I)


def _codex_blocks(content: Any, path: Path, line: int) -> Tuple[str, List[str]]:
    if isinstance(content, str):
        return content, []
    parts: List[str] = []
    media: List[str] = []
    for i, b in enumerate(content or []):
        if not isinstance(b, dict):
            parts.append(_j(b))
            continue
        bt = b.get("type")
        if bt in ("input_text", "output_text", "text", "summary_text", "reasoning_text"):
            parts.append(str(b.get("text", "")))
        elif bt in ("input_image", "image"):
            url = str(b.get("image_url") or b.get("url") or b.get("path") or "")
            media.append(f"{path}#L{line}:b{i}" if url.startswith("data:") or not url else url)
        else:
            parts.append(_j(_externalize(b, f"{path}#L{line}:b{i}", media)))
    return "\n".join(parts), media


def codex_record_events(rec: Dict[str, Any], line: int, path: Path, ctx: _Ctx) -> List[Event]:
    t = rec.get("type")
    p = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    ts = to_ist(rec.get("timestamp")) or ctx.last_ts
    ctx.last_ts = ts
    ev: Event = {"key": f"L{line}", "ts": ts, "source": {"path": str(path), "line": line}}

    if t in CODEX_SKIP_TYPES:
        return []
    if t == "session_meta":
        return [{**ev, "role": "system", "kind": "session_meta", "content": _j(p)}]
    if t == "turn_context":
        return [{**ev, "role": "system", "kind": "turn_context", "content": _j(p),
                 **({"model": p["model"]} if p.get("model") else {})}]
    if t == "compacted":
        rh = p.get("replacement_history")
        body = str(p.get("message") or "")
        if rh:
            body += ("\n\n" if body else "") + "[replacement_history]\n" + _j(rh)
        return [{**ev, "role": "compaction", "kind": "compacted", "content": body}]
    if t == "response_item":
        pt = p.get("type")
        if pt == "message":
            role = p.get("role")
            text, media = _codex_blocks(p.get("content"), path, line)
            kind = "message" + (f":{p['phase']}" if p.get("phase") else "")
            if role == "developer":
                return [{**ev, "role": "system", "kind": "developer", "content": text, "media": media}]
            return [{**ev, "role": role if role in ("user", "assistant") else "system",
                     "kind": kind, "content": text, "media": media}]
        if pt == "reasoning":
            summary, _ = _codex_blocks(p.get("summary"), path, line)
            body, _ = _codex_blocks(p.get("content"), path, line)
            out = {**ev, "role": "thinking", "kind": "reasoning",
                   "content": "\n".join(x for x in (summary, body) if x)}
            if p.get("encrypted_content"):
                out["opaque"] = {"encrypted_content": p["encrypted_content"]}
            return [out]
        if pt in ("function_call", "custom_tool_call"):
            args = p.get("arguments") if pt == "function_call" else p.get("input")
            ctx.tool_names[str(p.get("call_id"))] = str(p.get("name", ""))
            return [{**ev, "role": "tool_call", "kind": pt,
                     "content": args if isinstance(args, str) else _j(args),
                     "tool": {"name": p.get("name"), "call_id": p.get("call_id"), "input": args}}]
        if pt in ("function_call_output", "custom_tool_call_output"):
            text, media = _codex_blocks(p.get("output"), path, line)
            return [{**ev, "role": "tool_result", "kind": pt, "content": text, "media": media,
                     "tool": {"call_id": p.get("call_id"),
                              "name": ctx.tool_names.get(str(p.get("call_id")), "")}}]
        if pt == "web_search_call":
            return [{**ev, "role": "tool_call", "kind": "web_search_call",
                     "content": _j(p.get("action")), "tool": {"name": "web_search",
                                                               "status": p.get("status")}}]
        if pt == "compaction":
            out = {**ev, "role": "compaction", "kind": "compaction_item", "content": ""}
            if p.get("encrypted_content"):
                out["opaque"] = {"encrypted_content": p["encrypted_content"]}
            return [out]
        media = []
        body = _j(_externalize(p, f"{path}#L{line}", media))
        return [{**ev, "role": "system", "kind": f"response_item:{pt}", "content": body,
                 "media": sorted(set(media))}]
    if t == "event_msg":
        pt = p.get("type")
        if pt in CODEX_SKIP_EVENTS:
            return []
        if pt == "item_completed":
            it = p.get("item") or {}
            ty = it.get("type")
            if ty in CODEX_MIRRORED_ITEMS:
                return []
            if ty == "Plan":
                return [{**ev, "role": "assistant", "kind": "plan", "content": str(it.get("text", ""))}]
            if ty == "ImageView":
                return [{**ev, "role": "system", "kind": "codex_item:ImageView",
                         "content": str(it.get("path", "")), "media": [str(it.get("path", ""))]}]
            media: List[str] = []
            body = _j(_externalize(it, f"{path}#L{line}", media))
            return [{**ev, "role": "tool_result", "kind": f"codex_item:{ty}", "content": body,
                     "media": sorted(set(media)),
                     "tool": {"name": it.get("tool") or ty, "id": it.get("id"),
                              **({"server": it["server"]} if it.get("server") else {})}}]
        media = []
        body = _j(_externalize(p, f"{path}#L{line}", media))
        return [{**ev, "role": "system", "kind": f"event:{pt}", "content": body,
                 "media": sorted(set(media))}]
    if t == "realtime_item":
        if p.get("type") == "transcript_segment":
            role = p.get("role") if p.get("role") in ("user", "assistant") else "system"
            return [{**ev, "role": role, "kind": "realtime", "content": str(p.get("text", ""))}]
        return [{**ev, "role": "system", "kind": f"realtime:{p.get('type')}", "content": _j(p)}]
    return [{**ev, "role": "system", "kind": f"raw:{t}", "content": _j(rec)}]


def codex_line_counts(path: Path, max_line: Optional[int] = None) -> Dict[str, int]:
    """Source-side counts for verification, derived WITHOUT the parser above."""
    c = {"lines": 0, "messages": 0, "reasoning": 0, "tool_calls": 0, "tool_outputs": 0,
         "compactions": 0, "skipped": 0, "unparseable": 0}
    for ln, _, raw in iter_lines_from(path, 0, 0):
        if max_line is not None and ln >= max_line:
            break
        rec = _loads(raw)
        if rec is None:
            c["unparseable"] += 1
            continue
        c["lines"] += 1
        t = rec.get("type")
        p = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        pt = p.get("type")
        if t in CODEX_SKIP_TYPES or (t == "event_msg" and (
                pt in CODEX_SKIP_EVENTS or (pt == "item_completed" and
                                            (p.get("item") or {}).get("type") in CODEX_MIRRORED_ITEMS))):
            c["skipped"] += 1
        elif t == "response_item" and pt == "message":
            c["messages"] += 1
        elif t == "response_item" and pt == "reasoning":
            c["reasoning"] += 1
        elif t == "response_item" and pt in ("function_call", "custom_tool_call", "web_search_call"):
            c["tool_calls"] += 1
        elif t == "response_item" and pt in ("function_call_output", "custom_tool_call_output"):
            c["tool_outputs"] += 1
        elif t == "compacted" or (t == "response_item" and pt == "compaction"):
            c["compactions"] += 1
    c["expected_events"] = c["lines"] - c["skipped"] + c["unparseable"]
    return c


def codex_sources(paths: HostPaths) -> Iterator[Tuple[str, Path, Dict[str, Any]]]:
    home = paths.codex_home
    titles: Dict[str, str] = {}
    idx = home / "session_index.jsonl"
    if idx.exists():
        for _, _, raw in iter_lines_from(idx, 0, 0):
            rec = _loads(raw)
            if rec and rec.get("id"):
                titles[str(rec["id"])] = str(rec.get("thread_name") or "")
    files = sorted((home / "sessions").rglob("rollout-*.jsonl")) if (home / "sessions").exists() else []
    if (home / "archived_sessions").exists():
        files += sorted((home / "archived_sessions").glob("rollout-*.jsonl"))
    for f in files:
        m = _UUID.search(f.name)
        sid = m.group(1) if m else f.stem
        yield sid, f, {"title": titles.get(sid, "")}


# =============================================================================
# Part 3: ANTIGRAVITY
# =============================================================================

_AG_TRANSCRIPTS = (  # highest fidelity first
    Path(".system_generated") / "logs" / "transcript_full.jsonl",
    Path(".system_generated") / "logs" / "transcript.jsonl",
    Path(".system_generated") / "logs" / "overview.txt",
    Path("overview.txt"),
)
_AG_TOOL_TYPES_AS_SYSTEM = frozenset({
    "SYSTEM_MESSAGE", "EPHEMERAL_MESSAGE", "CONVERSATION_HISTORY", "KNOWLEDGE_ARTIFACTS",
    "CHECKPOINT", "ERROR_MESSAGE",
})
_MEDIA_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".webm", ".mp4",
                        ".mov", ".mp3", ".wav", ".pdf"})


def _ag_step_parts(rec: Dict[str, Any], src_name: str, line: int, path: Path) -> List[Event]:
    """Split one transcript step into its thinking / content / tool_calls / error parts."""
    raw_digest = _sha(_j(rec), 10)
    idx = rec.get("step_index")
    ty = str(rec.get("type") or "")
    ts = to_ist(rec.get("created_at") or rec.get("timestamp") or rec.get("ts"))
    base: Event = {"ts": ts, "source": {"path": str(path), "line": line, "step_index": idx,
                                        "file": src_name}}
    meta = {k: rec[k] for k in ("status", "source", "exit_code", "truncated_fields") if k in rec}
    out: List[Event] = []

    def part(name: str, **kw: Any) -> None:
        out.append({**base, "key": f"step{idx}:{name}:{raw_digest}", **kw})

    if rec.get("thinking"):
        part("thinking", role="thinking", kind="thinking", content=str(rec["thinking"]))
    content = rec.get("content")
    if content not in (None, ""):
        text = content if isinstance(content, str) else _j(content)
        if ty == "USER_INPUT":
            part("content", role="user", kind="USER_INPUT", content=text, tool=meta or None)
        elif ty in ("PLANNER_RESPONSE", "ASK_QUESTION"):
            part("content", role="assistant", kind=ty, content=text, tool=meta or None)
        elif ty in _AG_TOOL_TYPES_AS_SYSTEM:
            role = "compaction" if ty == "CHECKPOINT" else "system"
            part("content", role=role, kind=ty, content=text, tool=meta or None)
        else:
            part("content", role="tool_result", kind=ty, content=text,
                 tool={"name": ty, **meta})
    for k, call in enumerate(rec.get("tool_calls") or []):
        name = call.get("name") if isinstance(call, dict) else None
        args = call.get("args") if isinstance(call, dict) else call
        part(f"call{k}", role="tool_call", kind="tool_call", content=_j(args),
             tool={"name": name, "input": args})
    if rec.get("error"):
        part("error", role="system", kind="ERROR", content=_j(rec["error"]))
    if not out:
        role = "user" if ty == "USER_INPUT" else "system"
        part("marker", role=role, kind=ty or "step", content=_j(rec))
    return out


def antigravity_step_lines(sdir: Path) -> Iterator[Tuple[str, int, Dict[str, Any], Path]]:
    """(file, line, record, path) for the chosen lines, in step order."""
    chosen: Dict[Any, Tuple[int, str]] = {}
    per_file: List[Tuple[int, str, Path, List[Tuple[int, Dict[str, Any]]]]] = []
    for prio, rel in enumerate(_AG_TRANSCRIPTS):
        p = sdir / rel
        if not p.exists() or p.stat().st_size == 0:
            continue
        rows: List[Tuple[int, Dict[str, Any]]] = []
        for ln, _, raw in iter_lines_from(p, 0, 0):
            rec = _loads(raw)
            if rec is None:
                rec = {"step_index": f"unparsed-{prio}-{ln}", "type": "UNPARSEABLE",
                       "content": raw.decode("utf-8", "replace")}
            rows.append((ln, rec))
            idx = rec.get("step_index")
            if idx not in chosen:
                chosen[idx] = (prio, rel.as_posix())
        per_file.append((prio, rel.as_posix(), p, rows))
    merged: List[Tuple[Any, int, int, str, Dict[str, Any], Path]] = []
    for prio, name, p, rows in per_file:
        for ln, rec in rows:
            if chosen.get(rec.get("step_index"), (None,))[0] == prio:
                idx = rec.get("step_index")
                merged.append((idx if isinstance(idx, int) else 10 ** 9, prio, ln, name, rec, p))
    merged.sort(key=lambda x: (x[0], x[1], x[2]))
    for _, _, ln, name, rec, p in merged:
        yield name, ln, rec, p


def _ag_title(sdir: Path) -> str:
    task = sdir / "task.md"
    if task.exists():
        try:
            for line in task.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("# ") and line.strip()[2:].strip():
                    return line.strip()[2:].strip()
        except OSError:
            pass
    return ""


def antigravity_events(sdir: Path) -> Iterator[Event]:
    for name, ln, rec, p in antigravity_step_lines(sdir):
        yield from _ag_step_parts(rec, name, ln, p)
    transcripts = {(sdir / rel).resolve() for rel in _AG_TRANSCRIPTS}
    for f in sorted(x for x in sdir.rglob("*") if x.is_file()):
        rel = f.relative_to(sdir).as_posix()
        if f.resolve() in transcripts or rel.endswith(".metadata.json"):
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        ts = to_ist(st.st_mtime)
        src = {"path": str(f), "rel": rel}
        if f.suffix.lower() in _MEDIA_EXT:
            yield {"key": f"media:{rel}", "ts": ts, "role": "system", "kind": "media",
                   "content": rel, "media": [str(f)], "source": src,
                   "tool": {"bytes": st.st_size}}
            continue
        text = _read_text_file(f)
        if text is None:
            yield {"key": f"media:{rel}", "ts": ts, "role": "system", "kind": "media",
                   "content": rel, "media": [str(f)], "source": src, "tool": {"bytes": st.st_size}}
            continue
        parts = f.relative_to(sdir).parts
        tool: Dict[str, Any] = {"name": rel}
        meta_path = f.with_name(re.sub(r"\.resolved(\.\d+)?$", "", f.name) + ".metadata.json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                tool["meta"] = meta
                if meta.get("updatedAt") and not re.search(r"\.resolved\.\d+$", f.name):
                    ts = to_ist(meta["updatedAt"]) or ts
            except (OSError, ValueError):
                pass
        if parts[0] == ".system_generated" and len(parts) > 1 and parts[1] == "messages":
            try:
                msg = json.loads(text)
                yield {"key": f"msg:{rel}", "ts": to_ist(msg.get("timestamp")) or ts,
                       "role": "system", "kind": "message", "content": str(msg.get("content", "")),
                       "tool": {"name": "message", "sender": msg.get("sender"),
                                "priority": msg.get("priority")}, "source": src}
                continue
            except ValueError:
                pass
        if parts[0] == ".system_generated" and len(parts) > 1 and parts[1] == "tasks":
            role, kind = "tool_result", "task_log"
        elif parts[0] == ".system_generated" and len(parts) > 1 and parts[1] == "steps":
            role, kind = "tool_result", "step_content"
        elif parts[0] == "scratch":
            role, kind = "assistant", "scratch_file"
        elif parts[0] == ".tempmediaStorage":
            role, kind = "user", "pasted_text"
        elif parts[0] == ".user_uploaded":
            role, kind = "user", "uploaded_file"
        else:
            role, kind = "assistant", "artifact"
        yield {"key": f"file:{rel}:{_sha(text)}", "ts": ts, "role": role, "kind": kind,
               "content": text, "tool": tool, "source": src}


def antigravity_step_counts(sdir: Path) -> Dict[str, int]:
    """Distinct steps across all transcript files, independent of the parser."""
    steps: set = set()
    for rel in _AG_TRANSCRIPTS:
        p = sdir / rel
        if not p.exists():
            continue
        for _, _, raw in iter_lines_from(p, 0, 0):
            rec = _loads(raw) or {}
            steps.add(rec.get("step_index"))
    return {"distinct_steps": len(steps)}


def antigravity_sources(paths: HostPaths) -> Iterator[Tuple[str, Path, Dict[str, Any]]]:
    root = paths.antigravity_brain
    if not root.exists():
        return
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if any(True for _ in d.rglob("*") if _.is_file()):
            yield d.name, d, {"title": _ag_title(d)}


# =============================================================================
# Part 4: JARVIS
# =============================================================================

def jarvis_record_events(rec: Dict[str, Any], line: int, path: Path, ctx: _Ctx) -> List[Event]:
    role = str(rec.get("role") or "system")
    return [{"key": f"L{line}", "ts": to_ist(rec.get("ts")) or str(rec.get("ts") or ""),
             "role": role if role in ("user", "assistant", "system") else "system",
             "kind": "message", "content": str(rec.get("content", "")),
             "source": {"path": str(path), "line": line}}]


def _is_jarvis_row(row: Dict[str, Any]) -> bool:
    sid = str(row.get("session_id") or "")
    return (str(row.get("host") or "") == "jarvis" or sid.startswith(("conv-", "terminal-"))
            or row.get("chat_label") in ("terminal-ask", "voice-ask"))


def jarvis_queue_sessions(queue: Path, conversations: Path, machine: str) -> Dict[str, List[Event]]:
    """JARVIS sessions known only from capture rows written on THIS machine.

    A row from another machine belongs to that machine's store (and arrives
    here through its shard); ingesting it here too would mint colliding ids.
    """
    out: Dict[str, List[Event]] = {}
    mine = {machine, "unknown", ""}
    for ln, _, raw in iter_lines_from(queue, 0, 0):
        row = _loads(raw)
        if not row or not _is_jarvis_row(row) or str(row.get("machine") or "") not in mine:
            continue
        sid = safe_session(str(row.get("session_id") or ""))
        if (conversations / f"{sid}.jsonl").exists():
            continue
        ts = to_ist(row.get("ts")) or str(row.get("ts") or "")
        digest = _sha(f"{row.get('ts')}|{row.get('user_text')}", 16)
        src = {"path": str(queue), "line": ln, "capture_row": True}
        extra = {"model": row.get("model")} if row.get("model") else {}
        out.setdefault(sid, []).append({"key": f"q:{digest}:u", "ts": ts, "role": "user",
                                        "kind": "capture_row", "content": str(row.get("user_text", "")),
                                        "source": src, **extra})
        if row.get("assistant_summary"):
            out[sid].append({"key": f"q:{digest}:a", "ts": ts, "role": "assistant",
                             "kind": "capture_row", "content": str(row["assistant_summary"]),
                             "source": src, **extra})
    return out


# =============================================================================
# Part 5: INGESTION DRIVERS
# =============================================================================

def ingest_offset_source(store: EpisodeStore, host: str, session_id: str, path: Path,
                         parse: Callable[[Dict[str, Any], int, Path, _Ctx], List[Event]],
                         backfill: bool = False, extra: Optional[Dict[str, Any]] = None) -> int:
    """Incrementally ingest one append-only JSONL transcript."""
    try:
        st = path.stat()
    except OSError:
        return 0
    key = f"{host}:{path}"
    prev = store.manifest.source(key)
    if not backfill and prev.get("size") == st.st_size and prev.get("mtime") == st.st_mtime:
        return 0
    offset, line = (0, 0) if backfill else (int(prev.get("offset", 0)), int(prev.get("line", 0)))
    if offset > st.st_size:
        offset, line = 0, 0
    extra = dict(extra or {})
    ctx = _Ctx(title=str(extra.pop("title", "") or prev.get("title", "")))
    progress = {"offset": offset, "line": line}

    def events() -> Iterator[Event]:
        for ln, end, raw in iter_lines_from(path, offset, line):
            rec = _loads(raw)
            evs = parse(rec, ln, path, ctx) if rec is not None else [_unparseable(raw, path, ln)]
            for ev in evs:
                for k, v in extra.items():
                    ev.setdefault(k, v)
                yield ev
            progress["offset"], progress["line"] = end, ln + 1

    added = store.append(host, session_id, events(), need_keys=(offset == 0), title=ctx.title)
    if ctx.title and ctx.title != prev.get("title"):
        store.set_title(host, session_id, ctx.title)
    store.manifest.record_source(key, host=host, session=safe_session(session_id),
                                 size=st.st_size, mtime=st.st_mtime, offset=progress["offset"],
                                 line=progress["line"], title=ctx.title)
    return added


def ingest_claude_transcript(store: EpisodeStore, transcript: Path, backfill: bool = False) -> int:
    """One Claude Code transcript plus its subagents (the PreCompact hook's entry)."""
    transcript = Path(transcript)
    added = ingest_offset_source(store, "claude", transcript.stem, transcript,
                                 claude_record_events, backfill)
    sub_dir = transcript.with_suffix("") / "subagents"
    if sub_dir.is_dir():
        paths = HostPaths.default()
        paths = HostPaths(transcript.parent.parent, paths.codex_home, paths.antigravity_brain,
                          paths.conversations, paths.queue)
        for sid, p, extra in claude_sources(paths):
            if sub_dir in p.parents:
                added += ingest_offset_source(store, "claude", sid, p, claude_record_events,
                                              backfill, extra)
    return added


def _dir_signature(d: Path) -> str:
    h = hashlib.sha1()
    for f in sorted(x for x in d.rglob("*") if x.is_file()):
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{f.relative_to(d).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def ingest_host(store: EpisodeStore, host: str, paths: Optional[HostPaths] = None,
                backfill: bool = False) -> Dict[str, int]:
    """Ingest everything new for one host. Returns {sources, events}."""
    paths = paths or HostPaths.default()
    out = {"sources": 0, "events": 0}
    if host == "claude":
        for sid, p, extra in claude_sources(paths):
            out["sources"] += 1
            out["events"] += ingest_offset_source(store, "claude", sid, p, claude_record_events,
                                                  backfill, extra)
    elif host == "codex":
        for sid, p, extra in codex_sources(paths):
            out["sources"] += 1
            out["events"] += ingest_offset_source(store, "codex", sid, p, codex_record_events,
                                                  backfill, extra)
    elif host == "antigravity":
        for sid, d, extra in antigravity_sources(paths):
            out["sources"] += 1
            key = f"antigravity:{d}"
            sig = _dir_signature(d)
            if not backfill and store.manifest.source(key).get("sig") == sig:
                continue
            out["events"] += store.append("antigravity", sid, antigravity_events(d),
                                          need_keys=True, title=extra.get("title", ""))
            store.manifest.record_source(key, host="antigravity", session=sid, sig=sig)
    elif host == "jarvis":
        if paths.conversations.exists():
            for f in sorted(paths.conversations.glob("*.jsonl")):
                out["sources"] += 1
                out["events"] += ingest_offset_source(store, "jarvis", f.stem, f,
                                                      jarvis_record_events, backfill)
        if paths.queue.exists():
            st = paths.queue.stat()
            key = f"jarvis:{paths.queue}"
            prev = store.manifest.source(key)
            if backfill or prev.get("size") != st.st_size or prev.get("mtime") != st.st_mtime:
                for sid, evs in jarvis_queue_sessions(paths.queue, paths.conversations,
                                                      store.machine).items():
                    out["sources"] += 1
                    out["events"] += store.append("jarvis", sid, evs, need_keys=True)
                store.manifest.record_source(key, host="jarvis", size=st.st_size, mtime=st.st_mtime)
    else:
        raise ValueError(f"unknown host {host!r}")
    return out


if __name__ == "__main__":
    print("episode_sources: parsers only — run `python scripts/ingest_episodes.py --self-test`.")

"""Independent approval of JARVIS material before training.

LAYER: Engineer (training policy)

THE BIG PICTURE
Capture and parse routing describe history; neither proves an answer is correct.
One independent, content-bound review gate protects every training export while
leaving historical records and retrieval alone. A corrupt registry fails closed.

THE FLOW
Resolve source provenance -> preserve owner-only extracts -> apply exclusions ->
require the latest independent decision for the complete current source digest.
The explicit writer locks, validates and appends; it is not a conversational tool.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from jarvis_core.config import JARVIS_ROOT
from jarvis_core.locking import exclusive_lock
from jarvis_core.specialists.eval_exclusions import excluded_turn, has_canary, load_registry
from jarvis_core.specialists.retractions import load_retractions


class ReviewError(ValueError):
    """The registry or source cannot safely authorize training."""


def digest(content: Any) -> str:
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def identity_key(identity: Dict[str, Any]) -> str:
    if not isinstance(identity, dict):
        raise ReviewError("identity must be an object")
    if identity.get("kind") == "exchange":
        if set(identity) != {"kind", "session_id", "ts"} or not all(
                isinstance(identity.get(k), str) and identity[k].strip() for k in ("session_id", "ts")):
            raise ReviewError("exchange identity requires session_id and ts")
        try:
            datetime.fromisoformat(identity["ts"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReviewError("exchange timestamp is malformed") from exc
    elif identity.get("kind") == "kb":
        if set(identity) != {"kind", "id"} or isinstance(identity.get("id"), bool) or not (
                isinstance(identity.get("id"), (int, str)) and str(identity["id"]).strip()):
            raise ReviewError("KB identity requires an id")
        identity = {"kind": "kb", "id": str(identity["id"])}
    else:
        raise ReviewError("unknown review identity")
    return json.dumps(identity, sort_keys=True)


def _reviewer(value: Any) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"(?:codex|claude|antigravity|owner)/[^\s]+", value):
        raise ReviewError("independent reviewer must be codex/model, claude/model, antigravity/model or owner/name; JARVIS cannot self-review")


def _validate(row: Any) -> None:
    if not isinstance(row, dict):
        raise ReviewError("review must be an object")
    if set(row) != {"identity", "digest", "decision", "rationale", "evidence_refs", "reviewer", "reviewed_at"}:
        raise ReviewError("malformed review fields")
    identity_key(row.get("identity"))
    if not isinstance(row.get("digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["digest"]):
        raise ReviewError("review requires a SHA-256 digest")
    if row.get("decision") not in {"approved", "rejected"}:
        raise ReviewError("decision must be approved or rejected")
    if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
        raise ReviewError("individual rationale required")
    refs = row.get("evidence_refs")
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r.strip() for r in refs):
        raise ReviewError("nonempty evidence references required")
    _reviewer(row.get("reviewer"))
    try:
        moment = datetime.fromisoformat(row.get("reviewed_at", ""))
        if moment.tzinfo is None:
            raise ValueError("naive timestamp")
    except (TypeError, ValueError) as exc:
        raise ReviewError("aware review timestamp required") from exc


def _rows(path: Path, *, strict: bool = False) -> Iterator[Tuple[int, Dict[str, Any]]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("not an object")
            except ValueError as exc:
                if strict:
                    raise ReviewError(f"{path.name} line {number + 1}: malformed or torn record") from exc
                continue
            yield number, row


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    status: str
    reason: str
    references: Tuple[Dict[str, Any], ...] = ()


class TrainingReviewGate:
    """A per-export snapshot of source identities and independent reviews."""

    def __init__(self, root: Path = JARVIS_ROOT) -> None:
        self.root = Path(root)
        self.data = self.root / "jarvis_data"
        self.path = self.data / "training_reviews.jsonl"
        self.sources: Dict[str, Dict[str, Any]] = {}
        self.unresolvable: List[Dict[str, Any]] = []
        self.queue: Dict[int, Dict[str, Any]] = {}
        self.conversations: Dict[str, Dict[int, Dict[str, Any]]] = {}
        self.kb: Dict[str, Dict[str, Any]] = {}
        self.ambiguous_kb_ids: set[str] = set()
        self.reviews: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.retractions = load_retractions(self.data / "retractions.jsonl")
        self.exclusions = load_registry(self.data / "eval/c002/exclusions.json")
        self.routing: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for _, row in _rows(self.data / "turn_curation.jsonl"):
            self.routing[(str(row.get("session_id", "")), str(row.get("ts", "")))] = row
        self._load_sources()
        self._load_reviews()

    def _add(self, identity: dict, content: Any, refs: List[str]) -> None:
        item = {"identity": identity, "content": content, "digest": digest(content), "context_refs": refs}
        try:
            key = identity_key(identity)
        except ReviewError as exc:
            self.unresolvable.append({**item, "status": "pending", "reason": str(exc)})
            return
        if key in self.sources:
            prior = self.sources[key]
            if prior["digest"] != item["digest"]:
                prior["ambiguous"] = True
                prior.setdefault("variants", []).append(item)
            prior["context_refs"] = sorted(set(prior["context_refs"] + refs))
        else:
            self.sources[key] = item

    def _load_sources(self) -> None:
        for n, row in _rows(self.data / "observation_queue.jsonl"):
            self.queue[n] = row
            host = self._answer_host(row)
            if host in {"jarvis", "unknown"}:
                identity = {"kind": "exchange", "session_id": str(row.get("session_id", "")), "ts": str(row.get("ts", ""))}
                content = {"question": str(row.get("user_text", "")), "answer": str(row.get("assistant_summary", ""))}
                refs = [f"jarvis_data/observation_queue.jsonl#L{n}"]
                if host == "jarvis" and identity["session_id"] and identity["ts"]:
                    self._add(identity, content, refs)
                else:
                    self.unresolvable.append({"identity": identity, "content": content, "digest": digest(content),
                                              "context_refs": refs, "status": "pending", "reason": "unresolvable source host or identity"})
        for path in sorted((self.data / "conversations").glob("*.jsonl")):
            turns: Dict[int, Dict[str, Any]] = {}
            previous: Optional[Dict[str, Any]] = None
            for n, (_, row) in enumerate(_rows(path)):
                turns[n] = row
                if row.get("role") == "user":
                    previous = row
                elif row.get("role") == "assistant" and row.get("ts"):
                    self._add({"kind": "exchange", "session_id": path.stem, "ts": str(row["ts"])},
                              {"question": str(previous.get("content", "")) if previous else "", "answer": str(row.get("content", ""))},
                              [f"jarvis_data/conversations/{path.name}#L{n}", f"jarvis_data/context/{path.stem}.jsonl"])
            self.conversations[path.name] = turns
        for n, row in _rows(self.data / "knowledge_base.jsonl"):
            kb_id = row.get("id", f"line{n}")
            if str(kb_id) in self.kb and digest(self.kb[str(kb_id)]) != digest(row):
                self.ambiguous_kb_ids.add(str(kb_id))
            self.kb[str(kb_id)] = row
            if self._jarvis_kb(row):
                self._add({"kind": "kb", "id": kb_id}, row, [f"jarvis_data/knowledge_base.jsonl#id={kb_id}"])
        for source in self.sources.values():
            if source["identity"]["kind"] == "kb" and str(source["identity"]["id"]) in self.ambiguous_kb_ids:
                source["ambiguous"] = True

    def _jarvis_kb(self, row: dict) -> bool:
        tags = row.get("tags", [])
        content = str(row.get("content", ""))
        if "session-distill" in tags or content.startswith("Terminal session distill (") or row.get("origin") == "jarvis":
            return True
        source = str(row.get("source_queue", ""))
        jarvis = "source-jarvis" in tags or str(row.get("source_turn", "")).startswith("turn:jarvis:") or "|conv-" in source or "|terminal-" in source
        if not jarvis:
            return False
        # PARSE_RULE's existing extractor stores facts with a checked owner quote.
        # A bare source-jarvis label is not proof that the mixed answer was removed.
        match = re.search(r'Evidence, in the owner\'s words .*?: "(.*)"\s*$', content, re.DOTALL)
        if match and source.startswith("queue:"):
            ts, _, sid = source[6:].partition("|")
            for queue in self.queue.values():
                if str(queue.get("ts", "")) == ts and queue.get("session_id") == sid:
                    if match[1] and match[1] in str(queue.get("user_text", "")):
                        return False
        return True

    def _load_reviews(self) -> None:
        for n, row in _rows(self.path, strict=True):
            try:
                _validate(row)
            except ReviewError as exc:
                raise ReviewError(f"{self.path.name} line {n + 1}: {exc}") from exc
            self.reviews[(identity_key(row["identity"]), row["digest"])] = row

    def packet(self, identity: Dict[str, Any]) -> Dict[str, Any]:
        key = identity_key(identity)
        source = self.sources.get(key)
        if not source or source.get("ambiguous"):
            raise ReviewError("missing source or conflicting complete content for identity")
        review = self.reviews.get((key, source["digest"]))
        return {**source, "status": review["decision"] if review else "pending", "latest_review": review}

    def packets(self) -> Iterator[Dict[str, Any]]:
        yield from self.unresolvable
        for key in sorted(self.sources):
            item = self.sources[key]
            if item.get("ambiguous"):
                yield {**item, "status": "pending", "reason": "conflicting source content"}
            else:
                yield self.packet(item["identity"])

    def counts(self) -> Dict[str, int]:
        result = {"approved": 0, "rejected": 0, "pending": 0}
        for packet in self.packets():
            result[packet["status"]] += 1
        return result

    def submit(self, verdicts: List[Dict[str, Any]], reviewer: str) -> int:
        _reviewer(reviewer)
        if not isinstance(verdicts, list) or not verdicts:
            raise ReviewError("nonempty verdict list required")
        with exclusive_lock(self.path):
            current = TrainingReviewGate(self.root)
            additions = []
            for verdict in verdicts:
                if not isinstance(verdict, dict) or set(verdict) != {"identity", "digest", "decision", "rationale", "evidence_refs"}:
                    raise ReviewError("verdict fields must be identity, digest, decision, rationale and evidence_refs")
                row = {**verdict, "reviewer": reviewer, "reviewed_at": datetime.now(timezone.utc).isoformat()}
                _validate(row)
                packet = current.packet(row["identity"])
                if packet["digest"] != row["digest"]:
                    raise ReviewError("stale digest: read the complete current packet again")
                key = (identity_key(row["identity"]), row["digest"])
                prior = current.reviews.get(key)
                if prior and all(prior.get(k) == row[k] for k in ("decision", "rationale", "evidence_refs", "reviewer")):
                    continue
                current.reviews[key] = row
                additions.append(row)
            if additions:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a+b") as handle:
                    handle.seek(0, os.SEEK_END)
                    if handle.tell():
                        handle.seek(-1, os.SEEK_END)
                        if handle.read(1) != b"\n":
                            handle.write(b"\n")
                    for row in additions:
                        handle.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
        self.reviews = current.reviews
        return len(additions)

    def _decision(self, identity: dict) -> Eligibility:
        try:
            packet = self.packet(identity)
        except ReviewError as exc:
            return Eligibility(False, "pending", str(exc))
        ref = {"identity": identity, "digest": packet["digest"]}
        status = packet["status"]
        return Eligibility(status == "approved", status, "independent review " + status, (ref,))

    def _owner_extract(self, record: dict, owner: str) -> bool:
        metadata = record.get("metadata", {})
        messages = record.get("messages", [])
        if messages:
            if metadata.get("origin") != "authored_by_user":
                return False
            return self._source_fragment(record, owner)
        else:
            if record.get("source_type") != "user_voice" and metadata.get("role") != "user":
                return False
            target = record.get("text", "")
        return self._matches_text(str(target), owner)

    def _matches_text(self, target: str, source: str) -> bool:
        # Chunkers normalize whitespace; compare complete extracts, never just a label.
        target = " ".join(target.split())
        if not target:
            return False
        if target in " ".join(source.split()):
            return True
        people_path = self.data / "third_parties.json"
        if people_path.exists():
            from jarvis_core.specialists.third_parties import load, redact
            redacted, _ = redact(source, load(people_path))
            return target in " ".join(redacted.split())
        return False

    def _source_fragment(self, record: dict, source: str) -> bool:
        messages = record.get("messages", [])
        if messages:
            targets = [str(m.get("content", "")) for m in messages if m.get("role") == "assistant"]
            return bool(targets) and all(self._matches_text(t, source) for t in targets)
        return self._matches_text(str(record.get("text", "")), source)

    def _queue_result(self, row: dict, record: dict) -> Eligibility:
        sid, ts = str(row.get("session_id", "")), str(row.get("ts", ""))
        if excluded_turn(self.exclusions, sid, ts, str(row.get("user_text", "")), str(row.get("assistant_summary", ""))):
            return Eligibility(False, "excluded", "evaluation exclusion")
        turns = self.conversations.get(sid + ".jsonl", {})
        owner_only = self._owner_extract(record, str(row.get("user_text", "")))
        if any((sid + ".jsonl", n) in self.retractions.conv_turns for n, t in turns.items()
               if str(t.get("ts", "")) == ts and (not owner_only or t.get("role") == "user")):
            return Eligibility(False, "excluded", "linked conversation retraction")
        if owner_only:
            return Eligibility(True, "owner_only", "verified owner-only extract")
        host = self._answer_host(row)
        if host == "unknown":
            return Eligibility(False, "pending", "unresolvable answer host")
        if host != "jarvis":
            return Eligibility(True, "not_required", "other host contract unchanged")
        route = self.routing.get((sid, ts))
        if self._routing_denies(route, record):
            return Eligibility(False, "excluded", "existing parse routing denies training")
        text = f"USER: {row.get('user_text', '')}\nASSISTANT: {row.get('assistant_summary', '')}"
        if not self._source_fragment(record, text):
            return Eligibility(False, "pending", "artifact content does not match complete source")
        return self._decision({"kind": "exchange", "session_id": sid, "ts": ts})

    @staticmethod
    def _answer_host(row: dict) -> str:
        from jarvis_core.agent.parse_ledger import host_of
        # The JARVIS capture namespace cannot be relabelled as another host to
        # evade review; other agents' UUID namespaces keep their existing rule.
        if str(row.get("session_id", "")).startswith(("conv-", "terminal-")) or row.get("chat_label") in {"voice-ask", "terminal-ask"}:
            return "jarvis"
        return host_of(row)

    @staticmethod
    def _routing_denies(route: Optional[dict], record: dict) -> bool:
        metadata = record.get("metadata", {})
        corpus = metadata.get("training_corpus") or metadata.get("bucket") or record.get("origin_corpus")
        return bool(route) and (not route.get("corpora") or route.get("trainable") is False or
                               (corpus in {"engineer", "personalization"} and corpus not in route.get("corpora", [])))

    def eligibility(self, record: Dict[str, Any], *, _depth: int = 0) -> Eligibility:
        """Resolve original or derived records; approval never overrides exclusions."""
        if _depth > 8:
            return Eligibility(False, "pending", "derived provenance is cyclic or too deep")
        metadata = record.get("metadata", {})
        if not isinstance(metadata, dict):
            return Eligibility(False, "pending", "malformed provenance metadata")
        if has_canary(self.exclusions, json.dumps(record, ensure_ascii=False)):
            return Eligibility(False, "excluded", "evaluation canary")
        dependencies = metadata.get("training_sources", [])
        if not isinstance(dependencies, list):
            return Eligibility(False, "pending", "malformed derived provenance")
        inherited: List[Dict[str, Any]] = []
        for source in dependencies:
            if not isinstance(source, dict) or not source.get("source_path"):
                return Eligibility(False, "pending", "unresolvable derived source")
            target = metadata.get("training_corpus") or metadata.get("bucket") or record.get("origin_corpus")
            if target in {"engineer", "personalization"} and isinstance(source.get("metadata", {}), dict):
                source = {**source, "metadata": {**source.get("metadata", {}), "training_corpus": target}}
            result = self.eligibility(source, _depth=_depth + 1)
            if not result.eligible:
                return result
            inherited.extend(result.references)
        if any(k in metadata for k in ("source_queue", "source_turn", "source_kb_id", "source_exchange")) and not dependencies:
            return Eligibility(False, "pending", "derived source requires training_sources provenance")
        sp = str(record.get("source_path", ""))
        head, _, tail = sp.partition("#")
        result = Eligibility(True, "not_required", "not JARVIS answer material")
        if head == "kb" or head.endswith("knowledge_base.jsonl"):
            kb_id = tail.split("#")[0].removeprefix("id=")
            entry = self.kb.get(kb_id)
            if kb_id in self.retractions.kb_ids:
                return Eligibility(False, "excluded", "KB retraction")
            if not entry:
                return Eligibility(False, "pending", "missing KB source")
            if kb_id in self.ambiguous_kb_ids:
                return Eligibility(False, "pending", "conflicting KB identity")
            if not self._source_fragment(record, str(entry.get("content", ""))):
                return Eligibility(False, "pending", "artifact content does not match complete KB source")
            if has_canary(self.exclusions, str(entry.get("content", ""))):
                return Eligibility(False, "excluded", "evaluation KB source")
            provenance = str(entry.get("source_queue", ""))
            if provenance:
                source_ts, _, source_sid = provenance.removeprefix("queue:").partition("|")
                if excluded_turn(self.exclusions, source_sid, source_ts, str(entry.get("content", ""))):
                    return Eligibility(False, "excluded", "evaluation KB provenance")
            if self._jarvis_kb(entry):
                link = str(entry.get("source_queue", ""))
                if link:
                    ts, _, sid = link.removeprefix("queue:").partition("|")
                    matches = [r for r in self.queue.values() if str(r.get("ts", "")) == ts and r.get("session_id") == sid]
                    if len(matches) != 1:
                        return Eligibility(False, "pending", "unresolvable linked KB exchange")
                    source = matches[0]
                    linked = self._queue_result(source, {"text": f"USER: {source.get('user_text', '')}\nASSISTANT: {source.get('assistant_summary', '')}", "metadata": metadata})
                    if not linked.eligible:
                        return linked
                    inherited.extend(linked.references)
                result = self._decision({"kind": "kb", "id": entry.get("id", kb_id)})
        elif head.endswith("observation_queue.jsonl"):
            tail = tail.split("#")[0]
            candidates = [self.queue.get(int(tail[1:]))] if re.fullmatch(r"L\d+", tail) else [r for r in self.queue.values() if str(r.get("ts")) == tail and (not metadata.get("session_id") or r.get("session_id") == metadata["session_id"])]
            if len(candidates) != 1 or candidates[0] is None:
                return Eligibility(False, "pending", "missing or ambiguous queue source")
            result = self._queue_result(candidates[0], record)
        elif Path(head).name in self.conversations or "conversations/" in head.replace("\\", "/") or metadata.get("sub_source") == "conversation_store":
            filename = Path(head).name
            match = re.fullmatch(r"(?:L|turn)(\d+)", tail.split("#")[0])
            number = int(match[1]) if match else -1
            turn = self.conversations.get(filename, {}).get(number)
            if not turn:
                return Eligibility(False, "pending", "missing conversation source")
            if (filename, number) in self.retractions.conv_turns:
                return Eligibility(False, "excluded", "conversation retraction")
            sid, ts = Path(filename).stem, str(turn.get("ts", ""))
            if excluded_turn(self.exclusions, sid, ts, str(turn.get("content", ""))):
                return Eligibility(False, "excluded", "evaluation conversation")
            if turn.get("role") == "user" and self._owner_extract(record, str(turn.get("content", ""))):
                result = Eligibility(True, "owner_only", "verified owner-only extract")
            elif turn.get("role") == "assistant":
                route = self.routing.get((sid, ts))
                if self._routing_denies(route, record):
                    return Eligibility(False, "excluded", "existing parse routing denies training")
                if not self._source_fragment(record, str(turn.get("content", ""))):
                    return Eligibility(False, "pending", "artifact content does not match complete conversation source")
                result = self._decision({"kind": "exchange", "session_id": sid, "ts": ts})
            else:
                return Eligibility(False, "pending", "conversation extract is not verified owner-only content")
        elif metadata.get("origin") == "jarvis" or metadata.get("host") == "jarvis" or "session-distill" in metadata.get("tags", []) or record.get("source_type") in {"chat_history", "kb_entry", "kb_identity", "kb_judgment"}:
            return Eligibility(False, "pending", "unresolvable JARVIS provenance")
        saved = metadata.get("training_review")
        refs = tuple(inherited) + result.references
        if saved is not None and saved != list(refs):
            return Eligibility(False, "pending", "derived artifact digest differs from current source")
        return Eligibility(result.eligible, result.status, result.reason, refs)

    def filter_record(self, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result = self.eligibility(record)
        if not result.eligible:
            return None
        return {**record, "metadata": {**record.get("metadata", {}), "training_review": list(result.references)}}


def audit_training_artifacts(root: Path = JARVIS_ROOT, gate: Optional[TrainingReviewGate] = None) -> Iterator[Dict[str, Any]]:
    """Stream all five exports; never load the corpora into a health-check process."""
    review_gate = gate or TrainingReviewGate(root)
    directory = Path(root) / "jarvis_data/training_corpus"
    for name in ("engineer_corpus", "personalization_corpus", "blended_corpus", "sft_pairs", "sft_pairs_heldout"):
        path = directory / (name + ".jsonl")
        total, denied = 0, 0
        examples: List[str] = []
        try:
            for n, record in _rows(path, strict=True):
                total += 1
                result = review_gate.eligibility(record)
                if not result.eligible:
                    denied += 1
                    if len(examples) < 5:
                        examples.append(f"{name}#{n} {record.get('source_path')}: {result.status}: {result.reason}")
        except (OSError, ReviewError) as exc:
            denied += 1
            examples.append(str(exc))
        yield {"name": name, "status": "FAIL" if denied else ("OK" if total else "UNKNOWN"),
               "records": total, "ineligible": denied, "examples": examples}


if __name__ == "__main__":
    print(json.dumps(TrainingReviewGate().counts(), indent=2))

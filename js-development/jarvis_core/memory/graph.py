"""Evidence-backed, rebuildable GraphRAG projection for JARVIS facts.

The graph is deliberately a *projection*, never another source of truth:

* ``knowledge_base.jsonl`` remains the durable mind.
* ``commitments.jsonl`` remains the durable deferred-work registry.
* ``graph_index.json`` stores stable node IDs, metadata, and only relationships
  that have an explicit source citation.  It stores no duplicate full prose and
  no embeddings.

That distinction matters. ChromaDB answers "what is semantically nearby?";
this module answers "which recorded facts explicitly govern, cite, or lead to
one another?"  They are complementary retrieval paths.
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from jarvis_core.config import GRAPH_INDEX_PATH, KB_PATH, DATA_ROOT

_GRAPH_VERSION = 1
_KB_REF = re.compile(r"\bKB\s*#?\s*(\d+)\b", re.IGNORECASE)
_COMMITMENT_REF = re.compile(r"\bc\d{3,}\b", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}", re.IGNORECASE)


@dataclass(frozen=True)
class GraphNode:
    """A compact pointer to canonical data; ``id`` is never a duplicated fact."""

    id: str
    kind: str
    source_id: str
    entry_type: str
    timestamp: str
    tags: Tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphEdge:
    """One directional relationship with literal source evidence."""

    source: str
    target: str
    relation: str
    evidence: str


@dataclass(frozen=True)
class GraphStats:
    nodes: int
    edges: int
    path: Path


@dataclass(frozen=True)
class GraphHit:
    """A reachable fact plus the auditable path that made it relevant."""

    node_id: str
    kind: str
    source_id: str
    entry_type: str
    timestamp: str
    tags: Tuple[str, ...]
    score: float
    path: Tuple[GraphEdge, ...]


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return ()
    records: List[Dict[str, Any]] = []
    with handle:
        for raw in handle:
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _current_commitments(records: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Replay the append-only registry just enough to retain current state."""
    current: Dict[str, Dict[str, Any]] = {}
    for record in records:
        identifier = str(record.get("id", "")).strip()
        if not identifier:
            continue
        if record.get("status") == "open":
            current[identifier] = dict(record)
        elif identifier in current and str(record.get("status", "")) in {"resolved", "abandoned"}:
            current[identifier].update(record)
    return current


def _node_id(kind: str, source_id: object) -> str:
    return f"{kind}:{source_id}"


def _edge(source: str, target: str, relation: str, evidence: str) -> GraphEdge:
    return GraphEdge(source, target, relation, evidence[:240])


def build_graph(
    kb_path: Optional[Path] = None,
    commitments_path: Optional[Path] = None,
    graph_path: Optional[Path] = None,
) -> GraphStats:
    """Rebuild the graph atomically from canonical logs.

    Edges are intentionally narrow and deterministic:
    ``REFERENCES`` means an entry literally names ``KB N`` or ``cNNN``;
    ``GOVERNED_BY`` means a commitment's recorded ``kb_id`` links it to the
    decision that justifies it.  We never turn shared words into a graph edge.
    """
    kb = Path(kb_path or KB_PATH)
    commitments = Path(commitments_path or DATA_ROOT / "commitments.jsonl")
    target = Path(graph_path or GRAPH_INDEX_PATH)
    nodes: Dict[str, GraphNode] = {}
    edges: Dict[Tuple[str, str, str, str], GraphEdge] = {}

    for line_no, record in enumerate(_read_jsonl(kb), 1):
        source_id = str(record.get("id", f"line{line_no}")).strip()
        node_id = _node_id("kb", source_id)
        tags = tuple(sorted({str(tag).strip() for tag in record.get("tags", []) if str(tag).strip()}))
        nodes[node_id] = GraphNode(
            id=node_id, kind="kb", source_id=source_id,
            entry_type=str(record.get("type", "")), timestamp=str(record.get("timestamp", "")), tags=tags,
        )
        content = str(record.get("content", ""))
        for ref in _KB_REF.findall(content):
            target_id = _node_id("kb", ref)
            if target_id != node_id:
                edge = _edge(node_id, target_id, "REFERENCES", f"literal reference: KB {ref}")
                edges[(edge.source, edge.target, edge.relation, edge.evidence)] = edge
        for ref in _COMMITMENT_REF.findall(content):
            target_id = _node_id("commitment", ref.lower())
            edge = _edge(node_id, target_id, "REFERENCES", f"literal reference: {ref.lower()}")
            edges[(edge.source, edge.target, edge.relation, edge.evidence)] = edge

    for commitment_id, record in _current_commitments(_read_jsonl(commitments)).items():
        node_id = _node_id("commitment", commitment_id)
        nodes[node_id] = GraphNode(
            id=node_id, kind="commitment", source_id=commitment_id,
            entry_type=str(record.get("status", "open")), timestamp=str(record.get("opened", "")),
            tags=("commitment",),
        )
        kb_id = str(record.get("kb_id", "")).strip()
        if kb_id:
            edge = _edge(node_id, _node_id("kb", kb_id), "GOVERNED_BY", f"registry kb_id: {kb_id}")
            edges[(edge.source, edge.target, edge.relation, edge.evidence)] = edge
        text = " ".join(str(record.get(key, "")) for key in ("what", "resolves_when", "note"))
        for ref in _COMMITMENT_REF.findall(text):
            target_id = _node_id("commitment", ref.lower())
            if target_id != node_id:
                edge = _edge(node_id, target_id, "REFERENCES", f"literal reference: {ref.lower()}")
                edges[(edge.source, edge.target, edge.relation, edge.evidence)] = edge

    # Only retain edges whose endpoints exist. A historical/invalid literal
    # reference remains in the canonical prose but must not produce a phantom node.
    final_edges = sorted(
        (edge for edge in edges.values() if edge.source in nodes and edge.target in nodes),
        key=lambda edge: (edge.source, edge.target, edge.relation, edge.evidence),
    )
    payload = {
        "version": _GRAPH_VERSION,
        "nodes": [asdict(node) for node in sorted(nodes.values(), key=lambda node: node.id)],
        "edges": [asdict(edge) for edge in final_edges],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return GraphStats(nodes=len(nodes), edges=len(final_edges), path=target)


def _load_graph(path: Path) -> Tuple[Dict[str, GraphNode], List[GraphEdge]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, []
    if not isinstance(raw, dict) or raw.get("version") != _GRAPH_VERSION:
        return {}, []
    nodes: Dict[str, GraphNode] = {}
    for item in raw.get("nodes", []):
        try:
            node = GraphNode(
                id=str(item["id"]), kind=str(item["kind"]), source_id=str(item["source_id"]),
                entry_type=str(item.get("entry_type", "")), timestamp=str(item.get("timestamp", "")),
                tags=tuple(item.get("tags", []) or ()),
            )
            nodes[node.id] = node
        except (KeyError, TypeError):
            continue
    edges: List[GraphEdge] = []
    for item in raw.get("edges", []):
        try:
            edges.append(GraphEdge(
                source=str(item["source"]), target=str(item["target"]),
                relation=str(item["relation"]), evidence=str(item["evidence"]),
            ))
        except (KeyError, TypeError):
            continue
    return nodes, edges


def _source_texts(kb_path: Path, commitments_path: Path) -> Dict[str, str]:
    texts: Dict[str, str] = {}
    for line_no, record in enumerate(_read_jsonl(kb_path), 1):
        source_id = str(record.get("id", f"line{line_no}"))
        texts[_node_id("kb", source_id)] = " ".join((
            str(record.get("content", "")), " ".join(map(str, record.get("tags", []) or ())),
            str(record.get("type", "")),
        ))
    for commitment_id, record in _current_commitments(_read_jsonl(commitments_path)).items():
        texts[_node_id("commitment", commitment_id)] = " ".join(
            str(record.get(key, "")) for key in ("what", "resolves_when", "note", "status")
        )
    return texts


def _query_tokens(query: str) -> set[str]:
    return {token.lower() for token in _TOKEN.findall(query) if len(token) > 2}


def graph_search(
    query: str,
    *,
    k: int = 8,
    depth: int = 2,
    graph_path: Optional[Path] = None,
    kb_path: Optional[Path] = None,
    commitments_path: Optional[Path] = None,
) -> List[GraphHit]:
    """Find lexical seed facts, then expand explicit links up to ``depth`` hops.

    The seed text is read fresh from the canonical logs; the graph itself never
    duplicates it. Results are returned with an inspectable edge path so callers
    can distinguish a direct match from a two-hop relationship.
    """
    nodes, edges = _load_graph(Path(graph_path or GRAPH_INDEX_PATH))
    if not nodes:
        return []
    terms = _query_tokens(query)
    if not terms:
        return []
    source_texts = _source_texts(Path(kb_path or KB_PATH), Path(commitments_path or DATA_ROOT / "commitments.jsonl"))
    seeds = sorted(
        ((sum(term in source_texts.get(node_id, "").lower() for term in terms), node_id)
         for node_id in nodes if node_id in source_texts),
        key=lambda item: (-item[0], item[1]),
    )
    seed_ids = [node_id for score, node_id in seeds if score][: max(k, 1)]
    if not seed_ids:
        return []
    adjacency: Dict[str, List[GraphEdge]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge)
        # Following incoming links is needed to answer "what constrains this?".
        adjacency.setdefault(edge.target, []).append(
            GraphEdge(edge.target, edge.source, f"INVERSE_{edge.relation}", edge.evidence)
        )
    findings: Dict[str, GraphHit] = {}
    for seed_rank, seed_id in enumerate(seed_ids):
        queue: deque[Tuple[str, Tuple[GraphEdge, ...]]] = deque([(seed_id, ())])
        seen = {seed_id}
        while queue:
            current, path = queue.popleft()
            node = nodes.get(current)
            if node is None:
                continue
            score = (10.0 / (seed_rank + 1)) - (0.75 * len(path))
            prior = findings.get(current)
            hit = GraphHit(current, node.kind, node.source_id, node.entry_type, node.timestamp, node.tags, score, path)
            if prior is None or hit.score > prior.score:
                findings[current] = hit
            if len(path) >= max(0, depth):
                continue
            for edge in adjacency.get(current, []):
                if edge.target not in seen:
                    seen.add(edge.target)
                    queue.append((edge.target, path + (edge,)))
    return sorted(findings.values(), key=lambda hit: (-hit.score, hit.node_id))[:k]


def _self_test() -> None:
    """Offline test: only explicit citations create and traverse relationships."""
    import tempfile
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        kb = root / "knowledge_base.jsonl"
        commitments = root / "commitments.jsonl"
        graph = root / "graph_index.json"
        kb.write_text(
            '{"id": 1, "type": "Decision", "timestamp": "2026-01-01", "tags": ["memory"], "content": "Use KB 2 for the memory foundation."}\n'
            '{"id": 2, "type": "Semantic", "timestamp": "2026-01-02", "tags": ["graph"], "content": "GraphRAG is derived."}\n',
            encoding="utf-8",
        )
        commitments.write_text(
            '{"id":"c001","status":"open","opened":"2026-01-03","kb_id":1,"what":"Build graph","resolves_when":"working"}\n',
            encoding="utf-8",
        )
        stats = build_graph(kb, commitments, graph)
        assert stats.nodes == 3 and stats.edges == 2, stats
        hits = graph_search("memory foundation", graph_path=graph, kb_path=kb, commitments_path=commitments, depth=2)
        by_id = {hit.node_id: hit for hit in hits}
        assert "kb:1" in by_id and "kb:2" in by_id and "commitment:c001" in by_id, by_id
        assert any(edge.relation == "REFERENCES" for edge in by_id["kb:2"].path), by_id["kb:2"]
    print("graph.py self-test: PASS")


if __name__ == "__main__":
    _self_test()

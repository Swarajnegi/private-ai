"""
corpus.py

JARVIS Agent Layer: Training Corpus & Data Introspection tool (Category A — Callable).

Import-time registration:
    @Tool.register("corpus_stats")

LAYER: Agent (Tools)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from jarvis_core.config import DATA_ROOT, KB_PATH
from jarvis_core.agent.tool import Tool, ToolInput, ToolResult


class CorpusStatsInput(ToolInput):
    sample_size: int = Field(
        default=2, ge=0, le=5,
        description="Number of recent turn samples to include from the observation queue and KB."
    )


@Tool.register("corpus_stats")
class CorpusStatsTool(Tool):
    """Inspect metrics and volume of JARVIS's training corpus and memory stores. Read-only."""

    name = "corpus_stats"
    description = (
        "Inspect the volume, sources, and composition of JARVIS's memory and training data: "
        "observation_queue.jsonl (raw captured interaction turns across machines/agents), "
        "knowledge_base.jsonl (curated long-term memory entries by type), and "
        "domain_labels.jsonl (Stage 5 domain classifications). Use this to audit training data "
        "readiness, cross-chat capture volume, and memory health."
    )
    input_schema = CorpusStatsInput

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: CorpusStatsInput) -> ToolResult:
        data_dir = Path(DATA_ROOT)
        obs_path = data_dir / "observation_queue.jsonl"
        kb_path = Path(KB_PATH)
        domain_path = data_dir / "domain_labels.jsonl"

        # 1. Observation queue analysis
        obs_total = 0
        obs_machines = Counter()
        obs_models = Counter()
        obs_sessions = set()
        first_ts = ""
        latest_ts = ""
        obs_samples = []

        if obs_path.exists():
            try:
                with obs_path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        obs_total += 1
                        try:
                            rec = json.loads(line)
                            m_name = rec.get("machine") or "unknown"
                            obs_machines[m_name] += 1
                            m_model = rec.get("model") or "unspecified"
                            obs_models[m_model] += 1
                            if rec.get("session_id"):
                                obs_sessions.add(rec["session_id"])
                            ts = rec.get("ts", "")
                            if ts:
                                if not first_ts:
                                    first_ts = ts
                                latest_ts = ts
                            if tool_input.sample_size > 0 and len(obs_samples) < tool_input.sample_size:
                                user_text = rec.get("user_text", "")
                                obs_samples.append({
                                    "ts": ts,
                                    "machine": m_name,
                                    "user_preview": (user_text[:120] + "...") if len(user_text) > 120 else user_text,
                                })
                        except Exception:
                            continue
            except Exception as e:
                obs_samples.append({"error": f"Failed reading observation queue: {e}"})

        # 2. Knowledge base analysis
        kb_total = 0
        kb_types = Counter()
        kb_samples = []

        if kb_path.exists():
            try:
                with kb_path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        kb_total += 1
                        try:
                            rec = json.loads(line)
                            entry_type = rec.get("type", "Unknown")
                            kb_types[entry_type] += 1
                            if tool_input.sample_size > 0 and len(kb_samples) < tool_input.sample_size:
                                content = rec.get("content", "")
                                kb_samples.append({
                                    "type": entry_type,
                                    "tags": rec.get("tags", []),
                                    "content_preview": (content[:120] + "...") if len(content) > 120 else content,
                                })
                        except Exception:
                            continue
            except Exception as e:
                kb_samples.append({"error": f"Failed reading KB: {e}"})

        # 3. Domain labels analysis
        domain_total = 0
        domain_counts = Counter()
        if domain_path.exists():
            try:
                with domain_path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        domain_total += 1
                        try:
                            rec = json.loads(line)
                            dom = rec.get("domain", "unclassified")
                            domain_counts[dom] += 1
                        except Exception:
                            continue
            except Exception:
                pass

        return ToolResult(output={
            "observation_queue": {
                "total_turns": obs_total,
                "unique_sessions": len(obs_sessions),
                "earliest_timestamp": first_ts,
                "latest_timestamp": latest_ts,
                "machines": dict(obs_machines),
                "models": dict(obs_models),
                "samples": obs_samples,
            },
            "knowledge_base": {
                "total_entries": kb_total,
                "types": dict(kb_types),
                "samples": kb_samples,
            },
            "domain_labels": {
                "total_labeled": domain_total,
                "domains": dict(domain_counts),
            },
        })

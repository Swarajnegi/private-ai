#!/usr/bin/env python3
"""Offline Milestone 1 regression tests for TrainingReviewGate.

LAYER: Tools / Specialists (milestone-1 verification)

Tests independent approval gates, provenance matching, owner-only preservation,
digest integrity, and exclusion/retraction precedence using synthetic fixtures only.

THE BIG PICTURE: Independent fixtures verify policy without editing training data.
THE FLOW: Isolate sources -> submit synthetic reviews -> inspect all export routes.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = _REPO_ROOT / "js-development"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from jarvis_core.specialists.training_review import (
    ReviewError,
    TrainingReviewGate,
    audit_training_artifacts,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


class Milestone1Regressions(unittest.TestCase):
    def setUp(self) -> None:
        fixture_dir = _REPO_ROOT / ".runtime" / "milestone1" / "fixtures"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = tempfile.TemporaryDirectory(dir=fixture_dir)
        self.root = Path(self.tmp_dir.name)
        self.data_dir = self.root / "jarvis_data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Baseline empty support files
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [])
        _write_jsonl(self.data_dir / "knowledge_base.jsonl", [])
        _write_jsonl(self.data_dir / "turn_curation.jsonl", [])
        _write_jsonl(self.data_dir / "retractions.jsonl", [])
        (self.data_dir / "conversations").mkdir(parents=True, exist_ok=True)

        eval_dir = self.data_dir / "eval" / "c002"
        eval_dir.mkdir(parents=True, exist_ok=True)
        (eval_dir / "exclusions.json").write_text(
            json.dumps({"sessions": [], "canaries": ["C002_CANARY_SECRET_TRIGGER_VAL"]}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Pending Exclusion even with trainable:true
    # -------------------------------------------------------------------------
    def test_pending_exclusion_even_with_trainable_true(self) -> None:
        queue_row = {
            "session_id": "conv-test-001",
            "ts": "2026-10-14T00:00:00+00:00",
            "user_text": "How do we initialize the engine?",
            "assistant_summary": "Call engine.warm() on start.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        _write_jsonl(
            self.data_dir / "turn_curation.jsonl",
            [
                {
                    "session_id": "conv-test-001",
                    "ts": "2026-10-14T00:00:00+00:00",
                    "trainable": True,
                    "corpora": ["engineer"],
                }
            ],
        )

        gate = TrainingReviewGate(self.root)
        record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: How do we initialize the engine?\nASSISTANT: Call engine.warm() on start.",
            "metadata": {"training_corpus": "engineer"},
        }
        res = gate.eligibility(record)
        self.assertFalse(res.eligible, "Turn with trainable:true must still be ineligible without independent review")
        self.assertEqual(res.status, "pending")
        self.assertIn("independent review pending", res.reason)
        self.assertEqual(gate.counts()["pending"], 1)

    # -------------------------------------------------------------------------
    # 2. Valid Independent Approval Lifecycle
    # -------------------------------------------------------------------------
    def test_valid_independent_approval_lifecycle(self) -> None:
        queue_row = {
            "session_id": "conv-test-002",
            "ts": "2026-10-14T00:01:00+00:00",
            "user_text": "Explain memory contract.",
            "assistant_summary": "Agents parse their own turns into KB and routing.",
            "chat_label": "voice-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])

        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-test-002", "ts": "2026-10-14T00:01:00+00:00"}
        pkt = gate.packet(identity)
        self.assertEqual(pkt["status"], "pending")

        verdict = {
            "identity": identity,
            "digest": pkt["digest"],
            "decision": "approved",
            "rationale": "High-accuracy system explanation verified against docs.",
            "evidence_refs": ["jarvis_data/observation_queue.jsonl#L0"],
        }
        added = gate.submit([verdict], reviewer="codex/gpt-5.6")
        self.assertEqual(added, 1)

        # Fresh gate verifies persistence
        gate_fresh = TrainingReviewGate(self.root)
        self.assertEqual(gate_fresh.counts()["approved"], 1)

        record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: Explain memory contract.\nASSISTANT: Agents parse their own turns into KB and routing.",
        }
        res = gate_fresh.eligibility(record)
        self.assertTrue(res.eligible)
        self.assertEqual(res.status, "approved")

        filtered = gate_fresh.filter_record(record)
        self.assertIsNotNone(filtered)
        self.assertEqual(len(filtered["metadata"]["training_review"]), 1)
        self.assertEqual(filtered["metadata"]["training_review"][0]["digest"], pkt["digest"])

    # -------------------------------------------------------------------------
    # 3. Rejection and Append History
    # -------------------------------------------------------------------------
    def test_rejection_and_append_history(self) -> None:
        queue_row = {
            "session_id": "conv-test-003",
            "ts": "2026-10-14T00:02:00+00:00",
            "user_text": "What is the capital of France?",
            "assistant_summary": "Berlin.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])

        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-test-003", "ts": "2026-10-14T00:02:00+00:00"}
        pkt = gate.packet(identity)

        verdict = {
            "identity": identity,
            "digest": pkt["digest"],
            "decision": "rejected",
            "rationale": "Incorrect geographic fact hallucinated.",
            "evidence_refs": ["jarvis_data/observation_queue.jsonl#L0"],
        }
        gate.submit([verdict], reviewer="antigravity/gemini-3.8-flash")

        record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: What is the capital of France?\nASSISTANT: Berlin.",
        }
        res = gate.eligibility(record)
        self.assertFalse(res.eligible)
        self.assertEqual(res.status, "rejected")
        self.assertIn("rejected", res.reason)
        self.assertEqual(gate.counts()["rejected"], 1)

        # Submitting exact duplicate is idempotent
        re_added = gate.submit([verdict], reviewer="antigravity/gemini-3.8-flash")
        self.assertEqual(re_added, 0, "Duplicate verdict must not append redundant records")

    # -------------------------------------------------------------------------
    # 4. Stale Digest Rejection on Submission
    # -------------------------------------------------------------------------
    def test_stale_digest_rejection_on_submission(self) -> None:
        queue_row = {
            "session_id": "conv-test-004",
            "ts": "2026-10-14T00:03:00+00:00",
            "user_text": "Run check.",
            "assistant_summary": "Passed.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-test-004", "ts": "2026-10-14T00:03:00+00:00"}

        fake_digest = "a" * 64
        stale_verdict = {
            "identity": identity,
            "digest": fake_digest,
            "decision": "approved",
            "rationale": "Valid check.",
            "evidence_refs": ["jarvis_data/observation_queue.jsonl#L0"],
        }
        with self.assertRaises(ReviewError) as ctx:
            gate.submit([stale_verdict], reviewer="claude/opus-5")
        self.assertIn("stale digest", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 5. Content Change Automatically Invalidates Prior Approval
    # -------------------------------------------------------------------------
    def test_content_change_invalidates_prior_approval(self) -> None:
        queue_row = {
            "session_id": "conv-test-005",
            "ts": "2026-10-14T00:04:00+00:00",
            "user_text": "Original question.",
            "assistant_summary": "Original verified answer.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-test-005", "ts": "2026-10-14T00:04:00+00:00"}
        pkt = gate.packet(identity)

        verdict = {
            "identity": identity,
            "digest": pkt["digest"],
            "decision": "approved",
            "rationale": "Verified correct.",
            "evidence_refs": ["jarvis_data/observation_queue.jsonl#L0"],
        }
        gate.submit([verdict], reviewer="owner/shubha")

        # Now simulate source mutation in observation_queue
        mutated_row = dict(queue_row)
        mutated_row["assistant_summary"] = "Tampered answer that was never reviewed."
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [mutated_row])

        # New gate re-reads sources
        gate_reloaded = TrainingReviewGate(self.root)
        record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: Original question.\nASSISTANT: Tampered answer that was never reviewed.",
        }
        res = gate_reloaded.eligibility(record)
        self.assertFalse(res.eligible, "Changed source content must revert review status to pending")
        self.assertEqual(res.status, "pending")

    # -------------------------------------------------------------------------
    # 6. Self-Review and Reviewer Format Rejections
    # -------------------------------------------------------------------------
    def test_self_review_and_reviewer_format_rejections(self) -> None:
        queue_row = {
            "session_id": "conv-test-006",
            "ts": "2026-10-14T00:05:00+00:00",
            "user_text": "Test self review.",
            "assistant_summary": "Self response.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-test-006", "ts": "2026-10-14T00:05:00+00:00"}
        pkt = gate.packet(identity)
        verdict = {
            "identity": identity,
            "digest": pkt["digest"],
            "decision": "approved",
            "rationale": "I approved my own answer.",
            "evidence_refs": ["jarvis_data/observation_queue.jsonl#L0"],
        }

        # JARVIS self-review forbidden
        for bad_rev in ("jarvis/gemini", "jarvis/self", "jarvis/agent", "unknown/ai", "gpt-4", "admin"):
            with self.subTest(reviewer=bad_rev):
                with self.assertRaises(ReviewError):
                    gate.submit([verdict], reviewer=bad_rev)

        # Authorized reviewers accepted
        for ok_rev in ("codex/gpt-5.6", "claude/opus-5", "antigravity/gemini-3.8-flash", "owner/shubha"):
            with self.subTest(reviewer=ok_rev):
                _write_jsonl(self.data_dir / "training_reviews.jsonl", [])
                gate_clean = TrainingReviewGate(self.root)
                self.assertEqual(gate_clean.submit([verdict], reviewer=ok_rev), 1)

    # -------------------------------------------------------------------------
    # 7. Arbitrary Text Substitution Rejection
    # -------------------------------------------------------------------------
    def test_arbitrary_text_substitution_rejection(self) -> None:
        queue_row = {
            "session_id": "conv-test-007",
            "ts": "2026-10-14T00:06:00+00:00",
            "user_text": "Genuine question.",
            "assistant_summary": "Genuine answer.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-test-007", "ts": "2026-10-14T00:06:00+00:00"}
        pkt = gate.packet(identity)
        gate.submit(
            [
                {
                    "identity": identity,
                    "digest": pkt["digest"],
                    "decision": "approved",
                    "rationale": "Approved original.",
                    "evidence_refs": ["jarvis_data/observation_queue.jsonl#L0"],
                }
            ],
            reviewer="codex/gpt-5.6",
        )

        gate_approved = TrainingReviewGate(self.root)

        # An exporter attempting arbitrary substituted text
        substituted_record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: Genuine question.\nASSISTANT: Complete hallucination and fabrication.",
        }
        res = gate_approved.eligibility(substituted_record)
        self.assertFalse(res.eligible)
        self.assertEqual(res.status, "pending")
        self.assertIn("does not match complete source", res.reason)

        # Exact matching text succeeds
        valid_record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: Genuine question.\nASSISTANT: Genuine answer.",
        }
        self.assertTrue(gate_approved.eligibility(valid_record).eligible)

    # -------------------------------------------------------------------------
    # 8. Owner-Only Extraction and Origin Verification
    # -------------------------------------------------------------------------
    def test_owner_only_extraction_and_origin_verification(self) -> None:
        queue_row = {
            "session_id": "conv-test-008",
            "ts": "2026-10-14T00:07:00+00:00",
            "user_text": "I want all backups to run on 25th of every month.",
            "assistant_summary": "Understood, scheduling backups.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        gate = TrainingReviewGate(self.root)

        # User voice extraction (does not require assistant review)
        owner_record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "source_type": "user_voice",
            "text": "I want all backups to run on 25th of every month.",
            "metadata": {"role": "user"},
        }
        res_owner = gate.eligibility(owner_record)
        self.assertTrue(res_owner.eligible)
        self.assertEqual(res_owner.status, "owner_only")
        self.assertIn("verified owner-only extract", res_owner.reason)

        # SFT message format authored_by_user where assistant target matches user input
        sft_owner = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "messages": [
                {"role": "user", "content": "What is the backup schedule directive?"},
                {"role": "assistant", "content": "I want all backups to run on 25th of every month."},
            ],
            "metadata": {"origin": "authored_by_user"},
        }
        res_sft_owner = gate.eligibility(sft_owner)
        self.assertTrue(res_sft_owner.eligible)
        self.assertEqual(res_sft_owner.status, "owner_only")

        # Fake authored_by_user claim with fabricated assistant content
        sft_fake = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "messages": [
                {"role": "user", "content": "Tell me backups"},
                {"role": "assistant", "content": "Backups run daily on midnight."},
            ],
            "metadata": {"origin": "authored_by_user"},
        }
        self.assertFalse(gate.eligibility(sft_fake).eligible)

    # -------------------------------------------------------------------------
    # 9. Derived Source Gating and Cyclic Provenance
    # -------------------------------------------------------------------------
    def test_derived_source_gating_and_cyclic_provenance(self) -> None:
        queue_row = {
            "session_id": "conv-test-009",
            "ts": "2026-10-14T00:08:00+00:00",
            "user_text": "Base fact.",
            "assistant_summary": "Base answer.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-test-009", "ts": "2026-10-14T00:08:00+00:00"}
        pkt = gate.packet(identity)

        base_source = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: Base fact.\nASSISTANT: Base answer.",
            "metadata": {},
        }

        derived_record = {
            "source_path": "derived/stage5_summary.jsonl#L0",
            "text": "Summarized base fact",
            "metadata": {"training_sources": [base_source]},
        }

        # Upstream is pending -> derived is pending
        self.assertFalse(gate.eligibility(derived_record).eligible)

        # Approve upstream
        gate.submit(
            [
                {
                    "identity": identity,
                    "digest": pkt["digest"],
                    "decision": "approved",
                    "rationale": "Base verified",
                    "evidence_refs": ["jarvis_data/observation_queue.jsonl#L0"],
                }
            ],
            reviewer="codex/gpt-5.6",
        )
        gate_ok = TrainingReviewGate(self.root)
        res_derived = gate_ok.eligibility(derived_record)
        self.assertTrue(res_derived.eligible)
        self.assertEqual(len(res_derived.references), 1)

        # Deep / cyclic provenance protection (> 8 depth)
        curr = {"source_path": "leaf", "metadata": {"training_sources": []}}
        for i in range(10):
            curr = {"source_path": f"node_{i}", "metadata": {"training_sources": [curr]}}
        res_cyclic = gate_ok.eligibility(curr)
        self.assertFalse(res_cyclic.eligible)
        self.assertIn("cyclic or too deep", res_cyclic.reason)

    # -------------------------------------------------------------------------
    # 10. Retractions & Eval Exclusions Never Overridden by Approval
    # -------------------------------------------------------------------------
    def test_retractions_and_eval_exclusions_never_overridden_by_approval(self) -> None:
        queue_row = {
            "session_id": "conv-eval-010",
            "ts": "2026-10-14T00:09:00+00:00",
            "user_text": "Sensitive or evaluated turn.",
            "assistant_summary": "Answer text.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])

        # Exclude session in c002 exclusions and define canary
        (self.data_dir / "eval" / "c002" / "exclusions.json").write_text(
            json.dumps({
                "sessions": [{"prefix": "conv-eval", "since": None, "reason": "benchmark"}],
                "canaries": ["C002_CANARY_SECRET_TRIGGER_VAL"],
            }),
            encoding="utf-8",
        )

        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-eval-010", "ts": "2026-10-14T00:09:00+00:00"}
        pkt = gate.packet(identity)

        # Even if reviewer approves it in training_reviews:
        gate.submit(
            [
                {
                    "identity": identity,
                    "digest": pkt["digest"],
                    "decision": "approved",
                    "rationale": "Attempt to approve",
                    "evidence_refs": ["ref"],
                }
            ],
            reviewer="codex/gpt-5.6",
        )
        gate_approved = TrainingReviewGate(self.root)

        record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: Sensitive or evaluated turn.\nASSISTANT: Answer text.",
        }
        res_excl = gate_approved.eligibility(record)
        self.assertFalse(res_excl.eligible)
        self.assertEqual(res_excl.status, "excluded")
        self.assertIn("evaluation exclusion", res_excl.reason)

        # Canary check
        canary_record = {
            "source_path": "custom",
            "text": "Some text with C002_CANARY_SECRET_TRIGGER_VAL embedded.",
            "metadata": {},
        }
        res_canary = gate_approved.eligibility(canary_record)
        self.assertFalse(res_canary.eligible)
        self.assertEqual(res_canary.status, "excluded")
        self.assertIn("evaluation canary", res_canary.reason)

    # -------------------------------------------------------------------------
    # 11. Conversation Store Parsing and Blank Line Resilience
    # -------------------------------------------------------------------------
    def test_conversation_store_parsing_and_blank_lines(self) -> None:
        conv_path = self.data_dir / "conversations" / "conv-chat-011.jsonl"
        with conv_path.open("w", encoding="utf-8") as f:
            f.write("\n")  # leading blank
            f.write(json.dumps({"role": "user", "content": "How does hearth keep time?", "ts": "2026-10-14T00:10:00Z"}) + "\n")
            f.write("   \n")  # whitespace blank
            f.write(json.dumps({"role": "assistant", "content": "Hearth ticks on a cron loop.", "ts": "2026-10-14T00:10:05Z"}) + "\n")
            f.write("\n")

        gate = TrainingReviewGate(self.root)
        identity = {"kind": "exchange", "session_id": "conv-chat-011", "ts": "2026-10-14T00:10:05Z"}
        pkt = gate.packet(identity)
        self.assertEqual(pkt["content"]["question"], "How does hearth keep time?")
        self.assertEqual(pkt["content"]["answer"], "Hearth ticks on a cron loop.")

        # Test conversation turn route
        turn_record = {
            "source_path": "jarvis_data/conversations/conv-chat-011.jsonl#L1",
            "text": "Hearth ticks on a cron loop.",
        }
        self.assertFalse(gate.eligibility(turn_record).eligible)

        gate.submit(
            [
                {
                    "identity": identity,
                    "digest": pkt["digest"],
                    "decision": "approved",
                    "rationale": "Correct description of scheduler",
                    "evidence_refs": ["jarvis_data/conversations/conv-chat-011.jsonl#L1"],
                }
            ],
            reviewer="codex/gpt-5.6",
        )
        gate_ok = TrainingReviewGate(self.root)
        self.assertTrue(gate_ok.eligibility(turn_record).eligible)

        # Retraction on conversation turn
        _write_jsonl(
            self.data_dir / "retractions.jsonl",
            [{"kind": "conv_turn", "file": "conv-chat-011.jsonl", "line": 1, "reason": "withdrawn", "ts": "now"}],
        )
        gate_retracted = TrainingReviewGate(self.root)
        res_retracted = gate_retracted.eligibility(turn_record)
        self.assertFalse(res_retracted.eligible)
        self.assertEqual(res_retracted.status, "excluded")
        self.assertIn("conversation retraction", res_retracted.reason)

    # -------------------------------------------------------------------------
    # 12. Session Distill KB and Legacy Aliases
    # -------------------------------------------------------------------------
    def test_session_distill_kb_and_legacy_aliases(self) -> None:
        kb_rows = [
            {
                "id": 901,
                "content": "Terminal session distill (2026-09-27): ReAct loop latency breakdown.",
                "tags": ["session-distill", "latency"],
            },
            {
                "id": "line1",
                "content": "A human authored general reference note on python asyncio.",
                "tags": ["reference"],
            },
        ]
        _write_jsonl(self.data_dir / "knowledge_base.jsonl", kb_rows)

        gate = TrainingReviewGate(self.root)

        # Distill KB row 901 is JARVIS material -> requires review
        distill_record = {
            "source_path": "jarvis_data/knowledge_base.jsonl#id=901",
            "text": "Terminal session distill (2026-09-27): ReAct loop latency breakdown.",
        }
        res_distill = gate.eligibility(distill_record)
        self.assertFalse(res_distill.eligible)
        self.assertEqual(res_distill.status, "pending")

        pkt = gate.packet({"kind": "kb", "id": 901})
        gate.submit(
            [
                {
                    "identity": {"kind": "kb", "id": 901},
                    "digest": pkt["digest"],
                    "decision": "approved",
                    "rationale": "Accurate telemetry distillation",
                    "evidence_refs": ["jarvis_data/knowledge_base.jsonl#id=901"],
                }
            ],
            reviewer="codex/gpt-5.6",
        )
        gate_ok = TrainingReviewGate(self.root)
        self.assertTrue(gate_ok.eligibility(distill_record).eligible)

        # Reference row line1 is non-JARVIS -> not_required
        ref_record = {
            "source_path": "kb#id=line1",
            "text": "A human authored general reference note on python asyncio.",
        }
        res_ref = gate_ok.eligibility(ref_record)
        self.assertTrue(res_ref.eligible)
        self.assertEqual(res_ref.status, "not_required")

    # -------------------------------------------------------------------------
    # 13. Parse Routing Cross-Corpus Denials
    # -------------------------------------------------------------------------
    def test_parse_routing_cross_corpus_denials(self) -> None:
        queue_row = {
            "session_id": "conv-routing-013",
            "ts": "2026-10-14T00:12:00+00:00",
            "user_text": "Write code.",
            "assistant_summary": "Code written.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        # Routing restricts to engineer only
        _write_jsonl(
            self.data_dir / "turn_curation.jsonl",
            [
                {
                    "session_id": "conv-routing-013",
                    "ts": "2026-10-14T00:12:00+00:00",
                    "trainable": True,
                    "corpora": ["engineer"],
                }
            ],
        )

        gate = TrainingReviewGate(self.root)
        pkt = gate.packet({"kind": "exchange", "session_id": "conv-routing-013", "ts": "2026-10-14T00:12:00+00:00"})
        gate.submit(
            [
                {
                    "identity": pkt["identity"],
                    "digest": pkt["digest"],
                    "decision": "approved",
                    "rationale": "Good code",
                    "evidence_refs": ["ref"],
                }
            ],
            reviewer="codex/gpt-5.6",
        )
        gate_ok = TrainingReviewGate(self.root)

        # Exporting to engineer succeeds
        rec_eng = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: Write code.\nASSISTANT: Code written.",
            "metadata": {"training_corpus": "engineer"},
        }
        self.assertTrue(gate_ok.eligibility(rec_eng).eligible)

        # Exporting to personalization is denied by parse routing
        rec_pers = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "text": "USER: Write code.\nASSISTANT: Code written.",
            "metadata": {"training_corpus": "personalization"},
        }
        res_pers = gate_ok.eligibility(rec_pers)
        self.assertFalse(res_pers.eligible)
        self.assertEqual(res_pers.status, "excluded")
        self.assertIn("existing parse routing denies training", res_pers.reason)

    # -------------------------------------------------------------------------
    # 14. Non-JARVIS Host Contracts Unchanged
    # -------------------------------------------------------------------------
    def test_non_jarvis_host_contracts_unchanged(self) -> None:
        for host in ("claude", "codex", "antigravity"):
            with self.subTest(host=host):
                turn = {"host": host, "session_id": "263ef05f-f33c-48d6-9e9a-1410d35c7140",
                        "ts": "2026-10-14T00:13:00+00:00", "user_text": "Other-host question.",
                        "assistant_summary": "Other-host response."}
                _write_jsonl(self.data_dir / "observation_queue.jsonl", [turn])
                gate = TrainingReviewGate(self.root)
                res = gate.eligibility({"source_path": "observation_queue.jsonl#L0",
                    "text": "USER: Other-host question.\nASSISTANT: Other-host response."})
                self.assertTrue(res.eligible)
                self.assertEqual(res.status, "not_required")
                self.assertIn("other host contract unchanged", res.reason)

    # -------------------------------------------------------------------------
    # 15. Export Audits Across All Five Corpus Names
    # -------------------------------------------------------------------------
    def test_audit_training_artifacts_across_all_five_exports(self) -> None:
        corpus_dir = self.data_dir / "training_corpus"
        corpus_dir.mkdir(parents=True, exist_ok=True)

        # 1. engineer: clean external text
        _write_jsonl(
            corpus_dir / "engineer_corpus.jsonl",
            [{"source_path": "docs/arch.md", "text": "Architecture details"}],
        )
        # 2. personalization: unapproved JARVIS queue row
        queue_row = {
            "session_id": "conv-audit-015",
            "ts": "2026-10-14T00:14:00+00:00",
            "user_text": "Q",
            "assistant_summary": "A",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        _write_jsonl(
            corpus_dir / "personalization_corpus.jsonl",
            [{"source_path": "jarvis_data/observation_queue.jsonl#L0", "text": "USER: Q\nASSISTANT: A"}],
        )
        pending = {"source_path": "observation_queue.jsonl#L0", "text": "USER: Q\nASSISTANT: A"}
        names = ("engineer_corpus", "personalization_corpus", "blended_corpus", "sft_pairs", "sft_pairs_heldout")
        gate = TrainingReviewGate(self.root)
        for name in names:
            _write_jsonl(corpus_dir / (name + ".jsonl"), [pending])
        reports = list(audit_training_artifacts(self.root, gate))
        self.assertEqual({r["name"] for r in reports}, set(names))
        self.assertTrue(all(r["status"] == "FAIL" and r["ineligible"] == 1 for r in reports))
        identity = {"kind": "exchange", "session_id": queue_row["session_id"], "ts": queue_row["ts"]}
        gate.submit([{"identity": identity, "digest": gate.packet(identity)["digest"],
            "decision": "approved", "rationale": "Synthetic approved source for all five export routes.",
            "evidence_refs": ["synthetic/source"]}], reviewer="codex/fixture")
        self.assertTrue(all(r["status"] == "OK" and r["ineligible"] == 0 for r in audit_training_artifacts(self.root, gate)))

    # -------------------------------------------------------------------------
    # 17. KB Owner Fact Distillation Bypasses Review Requirement
    # -------------------------------------------------------------------------
    def test_kb_owner_fact_distillation_bypasses_review_requirement(self) -> None:
        queue_row = {
            "session_id": "conv-fact-017",
            "ts": "2026-10-14T00:17:00+00:00",
            "user_text": "I always use python 3.12 for new microservices.",
            "assistant_summary": "Recorded preference.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])

        # KB entry with source-jarvis but contains checked owner quote
        kb_distill_row = {
            "id": 999,
            "content": 'The owner standardizes on Python 3.12 for new microservices.\n\nEvidence, in the owner\'s words (2026-10-14, antigravity): "I always use python 3.12 for new microservices."',
            "tags": ["source-jarvis", "preference"],
            "source_queue": "queue:2026-10-14T00:17:00+00:00|conv-fact-017",
        }
        _write_jsonl(self.data_dir / "knowledge_base.jsonl", [kb_distill_row])

        gate = TrainingReviewGate(self.root)
        record = {
            "source_path": "jarvis_data/knowledge_base.jsonl#id=999",
            "text": kb_distill_row["content"],
        }
        res = gate.eligibility(record)
        # Because the mixed answer was stripped and the quote matches the user text, it is not_required
        self.assertTrue(res.eligible)
        self.assertEqual(res.status, "not_required")

    # -------------------------------------------------------------------------
    # 18. KB Retraction Precedence Over Approval
    # -------------------------------------------------------------------------
    def test_kb_retraction_precedence_over_approval(self) -> None:
        kb_row = {
            "id": 888,
            "content": "Terminal session distill (2026-09-28): Outdated architecture decision.",
            "tags": ["session-distill"],
        }
        _write_jsonl(self.data_dir / "knowledge_base.jsonl", [kb_row])
        _write_jsonl(self.data_dir / "retractions.jsonl", [{"kind": "kb", "id": "888", "reason": "superseded"}])

        gate = TrainingReviewGate(self.root)
        pkt = gate.packet({"kind": "kb", "id": 888})

        # Even if reviewer approved this KB entry:
        gate.submit(
            [
                {
                    "identity": {"kind": "kb", "id": 888},
                    "digest": pkt["digest"],
                    "decision": "approved",
                    "rationale": "Approve",
                    "evidence_refs": ["ref"],
                }
            ],
            reviewer="codex/gpt-5.6",
        )
        gate_reloaded = TrainingReviewGate(self.root)
        record = {
            "source_path": "jarvis_data/knowledge_base.jsonl#id=888",
            "text": kb_row["content"],
        }
        res = gate_reloaded.eligibility(record)
        self.assertFalse(res.eligible)
        self.assertEqual(res.status, "excluded")
        self.assertIn("KB retraction", res.reason)

    # -------------------------------------------------------------------------
    # 19. Both SFT Routes (Engineer and Personalization)
    # -------------------------------------------------------------------------
    def test_both_sft_routes_engineer_and_personalization(self) -> None:
        queue_row = {
            "session_id": "conv-sft-019",
            "ts": "2026-10-14T00:19:00+00:00",
            "user_text": "Write a retry decorator in python.",
            "assistant_summary": "def retry(): ...",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])
        _write_jsonl(
            self.data_dir / "turn_curation.jsonl",
            [
                {
                    "session_id": "conv-sft-019",
                    "ts": "2026-10-14T00:19:00+00:00",
                    "trainable": True,
                    "corpora": ["engineer", "personalization"],
                }
            ],
        )
        gate = TrainingReviewGate(self.root)
        pkt = gate.packet({"kind": "exchange", "session_id": "conv-sft-019", "ts": "2026-10-14T00:19:00+00:00"})
        gate.submit(
            [
                {
                    "identity": pkt["identity"],
                    "digest": pkt["digest"],
                    "decision": "approved",
                    "rationale": "Verified python decorator implementation",
                    "evidence_refs": ["jarvis_data/observation_queue.jsonl#L0"],
                }
            ],
            reviewer="codex/gpt-5.6",
        )
        gate_ok = TrainingReviewGate(self.root)

        # SFT message format for engineer corpus
        sft_eng = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "messages": [
                {"role": "user", "content": "Write a retry decorator in python."},
                {"role": "assistant", "content": "def retry(): ..."},
            ],
            "metadata": {"training_corpus": "engineer"},
        }
        self.assertTrue(gate_ok.eligibility(sft_eng).eligible)

        # SFT message format for personalization corpus
        sft_pers = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "messages": [
                {"role": "user", "content": "Write a retry decorator in python."},
                {"role": "assistant", "content": "def retry(): ..."},
            ],
            "metadata": {"training_corpus": "personalization"},
        }
        self.assertTrue(gate_ok.eligibility(sft_pers).eligible)

    # -------------------------------------------------------------------------
    # 20. Third Party Redaction Matching in Owner Extract
    # -------------------------------------------------------------------------
    def test_third_party_redaction_matching_in_owner_extract(self) -> None:
        queue_row = {
            "session_id": "conv-redact-020",
            "ts": "2026-10-14T00:20:00+00:00",
            "user_text": "Meeting scheduled with John Doe at Acme Corp.",
            "assistant_summary": "Calendar updated.",
            "chat_label": "terminal-ask",
        }
        _write_jsonl(self.data_dir / "observation_queue.jsonl", [queue_row])

        # Write third_parties.json mapping John Doe to [friend]
        (self.data_dir / "third_parties.json").write_text(
            json.dumps({
                "people": [
                    {"role": "friend", "identifiers": ["John Doe"]},
                ]
            }),
            encoding="utf-8",
        )

        gate = TrainingReviewGate(self.root)
        redacted_owner_record = {
            "source_path": "jarvis_data/observation_queue.jsonl#L0",
            "source_type": "user_voice",
            "text": "Meeting scheduled with [friend] at Acme Corp.",
            "metadata": {"role": "user"},
        }
        res = gate.eligibility(redacted_owner_record)
        self.assertTrue(res.eligible)
        self.assertEqual(res.status, "owner_only")

    # -------------------------------------------------------------------------
    # 16. Corrupt Registry Fails Closed
    # -------------------------------------------------------------------------
    def test_corrupt_registry_fails_closed(self) -> None:
        rev_path = self.data_dir / "training_reviews.jsonl"
        with rev_path.open("w", encoding="utf-8") as f:
            f.write('{"valid": false, "torn": \n')

        with self.assertRaises(ReviewError) as ctx:
            TrainingReviewGate(self.root)
        self.assertIn("malformed or torn record", str(ctx.exception))


def main() -> int:
    suite = unittest.TestLoader().loadTestsFromTestCase(Milestone1Regressions)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.argv.remove("--self-test")
    sys.exit(main())

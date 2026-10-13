"""Offline review-policy and exporter regression checks.

LAYER: Engineer
THE BIG PICTURE: a training flag or copied approval label cannot bypass review.
THE FLOW: build isolated sources -> exercise decisions and writers -> export/audit.
All fixtures use the configured D-drive temporary directory. No model calls.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "js-development"))
sys.path.insert(0, str(ROOT / "scripts"))
from jarvis_core.specialists.training_review import ReviewError, TrainingReviewGate


def write(root: Path, name: str, rows: list) -> None:
    path = root / "jarvis_data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")


def verdict(gate: TrainingReviewGate, identity: dict, decision: str = "approved", rationale: str = "Synthetic grounded answer matches the fixture.") -> dict:
    return {"identity": identity, "digest": gate.packet(identity)["digest"], "decision": decision,
            "rationale": rationale, "evidence_refs": ["synthetic-fixture/source"]}


class Reviews(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="m1-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sid = "conv-fixture-session"
        self.ts = "2026-10-13T12:00:00+05:30"
        self.identity = {"kind": "exchange", "session_id": self.sid, "ts": self.ts}
        self.kid = {"kind": "kb", "id": 1}
        self.owner = "I verify current hardware before deciding how to configure the system."
        self.answer = "This fixture has CPU execution and no measured GPU latency."
        self.queue = {"host": "jarvis", "session_id": self.sid, "ts": self.ts,
                      "user_text": self.owner, "assistant_summary": self.answer}
        self.turns = [{"role": "user", "content": self.owner, "ts": self.ts},
                      {"role": "assistant", "content": self.answer, "ts": self.ts}]
        write(self.root, "observation_queue.jsonl", [self.queue])
        write(self.root, f"conversations/{self.sid}.jsonl", self.turns)
        write(self.root, "knowledge_base.jsonl", [{"id": 1, "content": "Q: " + self.owner + " A: " + self.answer,
            "type": "Episodic", "tags": ["session-distill"]}, {"id": 2, "content": "Owner-supported fact", "tags": []}])
        self.records = [
            {"source_type": "chat_history", "source_path": "observation_queue.jsonl#L0", "text": "USER: " + self.owner + "\nASSISTANT: " + self.answer, "metadata": {"trainable": True}},
            {"source_type": "chat_history", "source_path": self.sid + ".jsonl#L1", "text": self.answer, "metadata": {"role": "assistant"}},
            {"source_type": "kb_entry", "source_path": "kb#1#chunk0", "text": self.answer, "metadata": {}},
        ]

    def gate(self) -> TrainingReviewGate:
        return TrainingReviewGate(self.root)

    def test_pending_all_routes(self) -> None:
        gate = self.gate()
        for record in self.records:
            self.assertFalse(gate.eligibility(record).eligible)
        self.assertEqual(gate.counts(), {"approved": 0, "rejected": 0, "pending": 2})

    def test_legacy_kb_and_split_owner_extracts(self) -> None:
        write(self.root, "knowledge_base.jsonl", [{"content": "Owner-supported legacy fact", "tags": []},
              {"content": "Terminal session distill (fixture): Q: q | A: a", "tags": []}])
        gate = self.gate()
        self.assertTrue(gate.eligibility({"source_path": "kb#line0#chunk0", "text": "Owner-supported legacy fact"}).eligible)
        self.assertFalse(gate.eligibility({"source_path": "kb#line1#chunk0", "text": "a"}).eligible)
        gate.submit([verdict(gate, {"kind": "kb", "id": "line1"})], "codex/fixture")
        self.assertTrue(gate.eligibility({"source_path": "kb#line1#chunk0", "text": "a"}).eligible)
        pair = {"source_path": "observation_queue.jsonl#" + self.ts + "#part2",
                "messages": [{"role": "assistant", "content": self.owner}],
                "metadata": {"origin": "authored_by_user", "session_id": self.sid}}
        self.assertTrue(gate.eligibility(pair).eligible)

    def test_host_relabelling_and_malformed_source_identity(self) -> None:
        self.queue["host"] = "codex"
        write(self.root, "observation_queue.jsonl", [self.queue])
        self.assertFalse(self.gate().eligibility(self.records[0]).eligible)
        self.queue["ts"] = "not a timestamp"
        write(self.root, "observation_queue.jsonl", [self.queue])
        gate = self.gate()
        self.assertFalse(gate.eligibility(self.records[0]).eligible)
        self.assertTrue(any(p.get("reason") == "exchange timestamp is malformed" for p in gate.packets()))

    def test_conversation_logical_indexes_and_owner_provenance(self) -> None:
        path = self.root / "jarvis_data/conversations" / (self.sid + ".jsonl")
        path.write_text(json.dumps(self.turns[0]) + "\n\n" + json.dumps(self.turns[1]) + "\n")
        gate = self.gate()
        self.assertFalse(gate.eligibility(self.records[1]).eligible)
        gate.submit([verdict(gate, self.identity)], "codex/fixture")
        self.assertTrue(gate.eligibility(self.records[1]).eligible)
        fake_owner = {"source_path": self.sid + ".jsonl#L0", "text": self.answer, "metadata": {"role": "user"}}
        self.assertFalse(gate.eligibility(fake_owner).eligible)

    def test_owner_fact_distillation_is_preserved(self) -> None:
        fact = {"id": 3, "tags": ["distilled", "source-jarvis"], "source_queue": "queue:" + self.ts + "|" + self.sid,
                "content": "Owner checks the host.\n\nEvidence, in the owner's words (2026-10-13, jarvis): \"" + self.owner + "\""}
        write(self.root, "knowledge_base.jsonl", [fact])
        gate = self.gate()
        self.assertTrue(gate.eligibility({"source_path": "kb#3#chunk0", "text": fact["content"]}).eligible)
        path = self.root / "jarvis_data/eval/c002/exclusions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sessions": [{"prefix": self.sid}]}))
        self.assertFalse(self.gate().eligibility({"source_path": "kb#3#chunk0", "text": fact["content"]}).eligible)
        path.write_text("{}")
        fact["content"] = "Unverified JARVIS output"
        write(self.root, "knowledge_base.jsonl", [fact])
        self.assertFalse(self.gate().eligibility({"source_path": "kb#3#chunk0", "text": fact["content"]}).eligible)

    def test_linked_kb_cannot_bypass_exchange_review(self) -> None:
        entry = {"id": 1, "content": "Q: " + self.owner + " A: " + self.answer, "tags": ["session-distill"],
                 "source_queue": "queue:" + self.ts + "|" + self.sid}
        write(self.root, "knowledge_base.jsonl", [entry])
        gate = self.gate()
        gate.submit([verdict(gate, self.kid)], "codex/fixture")
        self.assertFalse(gate.eligibility(self.records[2]).eligible)
        gate.submit([verdict(gate, self.identity)], "codex/fixture")
        self.assertTrue(gate.eligibility(self.records[2]).eligible)
        gate.submit([verdict(gate, self.identity, "rejected")], "codex/fixture")
        self.assertFalse(gate.eligibility(self.records[2]).eligible)

    def test_assistant_retraction_preserves_separate_owner_words(self) -> None:
        write(self.root, "retractions.jsonl", [{"kind": "conv_turn", "file": self.sid + ".jsonl", "line": 1}])
        gate = self.gate()
        self.assertFalse(gate.eligibility(self.records[0]).eligible)
        self.assertTrue(gate.eligibility({**self.records[0], "source_type": "user_voice", "text": self.owner}).eligible)
        write(self.root, "retractions.jsonl", [{"kind": "conv_turn", "file": self.sid + ".jsonl", "line": 0}])
        self.assertFalse(self.gate().eligibility({**self.records[0], "source_type": "user_voice", "text": self.owner}).eligible)

    def test_approval_queue_conversation_and_independent_kb(self) -> None:
        gate = self.gate()
        gate.submit([verdict(gate, self.identity)], "codex/fixture")
        self.assertTrue(gate.eligibility(self.records[0]).eligible)
        self.assertTrue(gate.eligibility(self.records[1]).eligible)
        self.assertFalse(gate.eligibility(self.records[2]).eligible)
        gate.submit([verdict(gate, self.kid)], "antigravity/fixture")
        self.assertTrue(gate.eligibility(self.records[2]).eligible)
        self.assertFalse(gate.eligibility({**self.records[1], "text": "Unreviewed substituted answer"}).eligible)
        self.assertFalse(gate.eligibility({**self.records[2], "text": "Unreviewed substituted distill"}).eligible)
        gate.submit([verdict(gate, self.kid, "rejected")], "codex/fixture")
        self.assertEqual(gate.eligibility(self.records[2]).status, "rejected")

    def test_rejection_and_append_history(self) -> None:
        gate = self.gate()
        good = verdict(gate, self.identity)
        self.assertEqual(gate.submit([good], "codex/fixture"), 1)
        self.assertEqual(gate.submit([good], "codex/fixture"), 0)
        gate.submit([verdict(gate, self.identity, "rejected", "Fixture now intentionally rejected.")], "claude/fixture")
        self.assertEqual(gate.eligibility(self.records[0]).status, "rejected")
        self.assertEqual(gate.eligibility(self.records[1]).status, "rejected")
        self.assertEqual(len(gate.path.read_text().splitlines()), 2)

    def test_stale_content_and_metadata(self) -> None:
        gate = self.gate()
        old = verdict(gate, self.identity)
        gate.submit([old], "codex/fixture")
        artifact = gate.filter_record(self.records[0])
        self.queue["assistant_summary"] += " changed"
        self.turns[1]["content"] += " changed"
        write(self.root, "observation_queue.jsonl", [self.queue])
        write(self.root, f"conversations/{self.sid}.jsonl", self.turns)
        current = self.gate()
        self.assertFalse(current.eligibility(artifact).eligible)
        with self.assertRaises(ReviewError):
            current.submit([old], "codex/fixture")
        current.submit([verdict(current, self.identity)], "codex/fixture")
        self.assertFalse(current.eligibility(artifact).eligible)

    def test_self_and_malformed_submissions(self) -> None:
        gate = self.gate()
        good = verdict(gate, self.identity)
        for reviewer in ("jarvis/curator", "jarvis", "unknown/model", None):
            with self.assertRaises(ReviewError):
                gate.submit([good], reviewer)
        for field, bad in (("rationale", ""), ("evidence_refs", []), ("decision", "pending"), ("digest", "abc")):
            with self.assertRaises(ReviewError):
                gate.submit([{**good, field: bad}], "codex/fixture")
        with self.assertRaises(ReviewError):
            gate.submit([good, {**good, "identity": {"kind": "kb", "id": 999}}], "codex/fixture")
        self.assertFalse(gate.path.exists())

    def test_owner_only_records_survive(self) -> None:
        gate = self.gate()
        queue_owner = {**self.records[0], "source_type": "user_voice", "text": self.owner}
        self.assertTrue(gate.eligibility(queue_owner).eligible)
        self.assertFalse(gate.eligibility({**queue_owner, "text": self.answer}).eligible)
        self.assertTrue(gate.eligibility({"source_path": "kb#2#chunk0", "text": "Owner-supported fact"}).eligible)
        pair = {"source_path": "observation_queue.jsonl#" + self.ts,
                "messages": [{"role": "user", "content": "Explain your thinking."}, {"role": "assistant", "content": self.owner}],
                "metadata": {"origin": "authored_by_user", "session_id": self.sid}}
        self.assertTrue(gate.eligibility(pair).eligible)
        self.assertFalse(gate.eligibility({**pair, "messages": [{"role": "assistant", "content": self.answer}]}).eligible)
        self.assertFalse(gate.eligibility({**pair, "messages": [*pair["messages"], {"role": "assistant", "content": self.answer}]}).eligible)

    def test_review_registry_is_a_corpus_freshness_input(self) -> None:
        from jarvis_core.serve.maintenance import fingerprint
        before = fingerprint("rebuild_corpora", self.root)
        gate = self.gate()
        gate.submit([verdict(gate, self.identity)], "codex/fixture")
        self.assertNotEqual(before, fingerprint("rebuild_corpora", self.root))

    def test_stage5_training_audit_uses_shared_gate(self) -> None:
        import eval_c002
        from jarvis_core.specialists.eval_exclusions import Registry
        path = self.root / "jarvis_data/training_corpus/engineer_corpus.jsonl"
        write(self.root, "training_corpus/engineer_corpus.jsonl", [self.records[0]])
        arguments = dict(training_files=[path], kb_path=self.root / "jarvis_data/knowledge_base.jsonl",
                         queue_path=None, conversations_dir=None, registry=Registry(), training_root=self.root)
        result = eval_c002.audit([], {}, **arguments)
        self.assertFalse(result["ok"])
        self.assertTrue(any("independent training review denied" in f for f in result["failures"]))
        gate = self.gate()
        gate.submit([verdict(gate, self.identity)], "codex/fixture")
        self.assertTrue(eval_c002.audit([], {}, **arguments)["ok"])
        gate.path.write_text('{"torn":')
        self.assertFalse(eval_c002.audit([], {}, **arguments)["ok"])

    def test_derived_and_unresolved_provenance(self) -> None:
        gate = self.gate()
        derived = {"source_path": "derived/synthetic", "text": "derived", "metadata": {"training_sources": [self.records[0]]}}
        self.assertFalse(gate.eligibility(derived).eligible)
        nested = {"source_path": "derived/nested", "text": "nested", "metadata": {"training_sources": [derived]}}
        self.assertFalse(gate.eligibility(nested).eligible)
        gate.submit([verdict(gate, self.identity)], "codex/fixture")
        self.assertTrue(gate.eligibility(derived).eligible)
        gate.submit([verdict(gate, self.identity, "rejected")], "codex/fixture")
        self.assertFalse(gate.eligibility(derived).eligible)
        for rec in ({"source_type": "chat_history", "source_path": "missing"},
                    {"metadata": {"host": "jarvis"}}, {"source_path": "kb#999"},
                    {"metadata": {"source_queue": "missing"}}):
            self.assertFalse(gate.eligibility(rec).eligible)

    def test_kb_content_and_registry_schema_changes(self) -> None:
        gate = self.gate()
        old = verdict(gate, self.kid)
        gate.submit([old], "codex/fixture")
        write(self.root, "knowledge_base.jsonl", [{"id": 1, "content": "changed", "tags": ["session-distill"]}])
        self.assertFalse(self.gate().eligibility(self.records[2]).eligible)
        with self.assertRaises(ReviewError):
            self.gate().submit([old], "codex/fixture")
        raw = json.loads(gate.path.read_text().splitlines()[0])
        raw["reviewer"] = "jarvis/curator"
        write(self.root, "training_reviews.jsonl", [raw])
        with self.assertRaises(ReviewError):
            self.gate()

    def test_kb_misattribution_and_conflicting_ids_are_held(self) -> None:
        gate = self.gate()
        self.assertFalse(gate.eligibility({"source_path": "kb#2#chunk0", "text": self.answer}).eligible)
        write(self.root, "knowledge_base.jsonl", [{"id": 1, "content": "Generated", "tags": ["session-distill"]},
              {"id": 1, "content": "Replacement owner fact", "tags": []}])
        gate = self.gate()
        self.assertFalse(gate.eligibility({"source_path": "kb#1", "text": "Replacement owner fact"}).eligible)
        with self.assertRaises(ReviewError):
            gate.packet(self.kid)

    def test_routing_retractions_evaluation_precedence(self) -> None:
        gate = self.gate()
        gate.submit([verdict(gate, self.identity), verdict(gate, self.kid)], "codex/fixture")
        write(self.root, "turn_curation.jsonl", [{"session_id": self.sid, "ts": self.ts, "corpora": ["engineer"], "trainable": False}])
        self.assertFalse(self.gate().eligibility(self.records[0]).eligible)
        self.assertFalse(self.gate().eligibility(self.records[1]).eligible)
        write(self.root, "turn_curation.jsonl", [])
        write(self.root, "turn_curation.jsonl", [{"session_id": self.sid, "ts": self.ts, "corpora": ["personalization"], "trainable": True}])
        self.assertFalse(self.gate().eligibility({**self.records[1], "metadata": {"training_corpus": "engineer"}}).eligible)
        write(self.root, "turn_curation.jsonl", [])
        write(self.root, "retractions.jsonl", [{"kind": "kb", "id": 1}, {"kind": "conv_turn", "file": self.sid + ".jsonl", "line": 1}])
        for rec in self.records:
            self.assertFalse(self.gate().eligibility(rec).eligible)
        write(self.root, "retractions.jsonl", [])
        path = self.root / "jarvis_data/eval/c002/exclusions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"sessions": [{"prefix": self.sid}]}))
        self.assertFalse(self.gate().eligibility(self.records[0]).eligible)

    def test_registry_newline_healing_and_corruption(self) -> None:
        gate = self.gate()
        gate.submit([verdict(gate, self.identity)], "codex/fixture")
        gate.path.write_bytes(gate.path.read_bytes().rstrip(b"\n"))
        gate.submit([verdict(gate, self.kid)], "codex/fixture")
        self.assertEqual(len(self.gate().reviews), 2)
        with gate.path.open("ab") as handle:
            handle.write(b'{"identity":')
        with self.assertRaises(ReviewError):
            self.gate()
        import check_pipeline
        result = check_pipeline.inv_independent_training_reviews(check_pipeline.Artifacts(self.root))
        self.assertEqual(result[0].status, "FAIL")

    def test_concurrent_process_appends(self) -> None:
        commands = [[sys.executable, __file__, "--append-worker", str(self.root), str(n)] for n in range(4)]
        workers = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in commands]
        for worker in workers:
            out, err = worker.communicate(timeout=30)
            self.assertEqual(worker.returncode, 0, (out, err))
        self.assertEqual(len(self.gate().path.read_text().splitlines()), 4)

    def test_exporters_and_all_five_audits(self) -> None:
        from jarvis_core.specialists import engineer_corpus as engineer, personalization_corpus as personal, blend_corpus as blend
        import build_sft_pairs as sft
        import check_pipeline
        owner = {"source_type": "user_voice", "source_path": "observation_queue.jsonl#L0", "text": self.owner, "metadata": {}}
        def source(_):
            for r in [*self.records, owner]:
                yield engineer.CorpusRecord(**r)
        corpus = self.root / "jarvis_data/training_corpus"
        for module, filename in ((engineer, "engineer_corpus.jsonl"), (personal, "personalization_corpus.jsonl")):
            with patch.object(module, "TrainingReviewGate", lambda: self.gate()), patch.object(module, "_SOURCE_ITERATORS", (("fixture", source),)):
                with patch.object(personal, "rebuild_index", lambda: None):
                    module.assemble_corpus(corpus / filename)
            rows = [json.loads(line) for line in (corpus / filename).read_text().splitlines()]
            self.assertEqual([r["text"] for r in rows], [self.owner])
        with patch.object(blend, "TrainingReviewGate", lambda: self.gate()), patch.object(blend, "_ENGINEER_PATH", corpus / "engineer_corpus.jsonl"), patch.object(blend, "_PERSONALIZATION_PATH", corpus / "personalization_corpus.jsonl"), patch.object(blend.third_parties, "load", lambda: ()):
            blend.blend(corpus / "blended_corpus.jsonl")
        pair = sft.SFTPair("Explain your thinking", self.owner, "personalization", "sft_personalization", "observation_queue.jsonl#L0", {"origin": "authored_by_user"})
        bad = sft.SFTPair("Q", self.answer, "engineer", "sft_engineer", "observation_queue.jsonl#L0", {})
        with patch.object(sft, "TrainingReviewGate", lambda: self.gate()), patch.object(sft, "EXTRACTORS", (("fixture", lambda: iter([pair, bad])),)), patch.object(sft, "passes_quality", lambda _: (True, "")), patch.object(sft.third_parties, "load", lambda: ()):
            pairs, _ = sft.build()
            self.assertEqual(len(pairs), 1)
            for name in ("sft_pairs.jsonl", "sft_pairs_heldout.jsonl"):
                sft.write_jsonl(pairs, corpus / name)
        findings = check_pipeline.inv_independent_training_reviews(check_pipeline.Artifacts(self.root))
        self.assertTrue(all(f.status == "OK" for f in findings), findings)
        for name in ("engineer_corpus.jsonl", "personalization_corpus.jsonl", "blended_corpus.jsonl", "sft_pairs.jsonl", "sft_pairs_heldout.jsonl"):
            write(self.root, "training_corpus/" + name, [self.records[0]])
        findings = check_pipeline.inv_independent_training_reviews(check_pipeline.Artifacts(self.root))
        self.assertEqual(sum(f.status == "FAIL" for f in findings), 5)

    def test_review_metadata_does_not_change_client_snapshot(self) -> None:
        from jarvis_core.specialists import engineer_corpus as engineer, personalization_corpus as personal, client_snapshot
        snapshot = self.root / "jarvis_data/training_corpus/client_work_snapshot.jsonl"
        records = {"engineer": {"source_type": "client_work", "source_path": "client_work/fixture/code#0", "text": "Synthetic client code", "metadata": {"attribution": "fixture"}},
                   "personalization": {"source_type": "professional_reasoning", "source_path": "client_work/fixture/notes#0", "text": "Synthetic client reasoning", "metadata": {"attribution": "fixture"}}}
        write(self.root, "training_corpus/client_work_snapshot.jsonl", [{"corpus": key, **records[key]} for key in ("engineer", "personalization")])
        before = snapshot.read_bytes()
        with patch.object(client_snapshot, "SNAPSHOT_PATH", snapshot):
            for module, key, live_name, wrapper_name in (
                (engineer, "engineer", "iter_client_work_records", "iter_client_work_with_snapshot"),
                (personal, "personalization", "iter_professional_reasoning_records", "iter_professional_reasoning_with_snapshot")):
                record = module.CorpusRecord(**records[key])
                with patch.object(module, "TrainingReviewGate", lambda: self.gate()), patch.object(module, live_name, lambda: iter([record])), \
                     patch.object(module, "_SOURCE_ITERATORS", (("fixture", lambda _: getattr(module, wrapper_name)()),)), patch.object(personal, "rebuild_index", lambda: None):
                    module.assemble_corpus(self.root / (key + ".jsonl"))
                self.assertEqual(snapshot.read_bytes(), before)
                self.assertEqual(record.metadata, {"attribution": "fixture"})
                exported = json.loads((self.root / (key + ".jsonl")).read_text().splitlines()[0])
                self.assertIn("training_review", exported["metadata"])


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.argv.remove("--self-test")
    if len(sys.argv) > 1 and sys.argv[1] == "--append-worker":
        gate = TrainingReviewGate(Path(sys.argv[2]))
        identity = {"kind": "exchange", "session_id": "conv-fixture-session", "ts": "2026-10-13T12:00:00+05:30"}
        gate.submit([verdict(gate, identity, rationale="Synthetic concurrent reviewer " + sys.argv[3])], "codex/fixture")
    else:
        unittest.main(argv=[sys.argv[0]], verbosity=2)

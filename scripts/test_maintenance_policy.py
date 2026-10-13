"""Offline scheduler policy tests. LAYER: Tools (verification)."""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))
from jarvis_core.serve import maintenance as m
from jarvis_core.serve.scheduler import Scheduler, Job, JobState, HOUR, default_jobs


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state.json"
        self.now = 1000000.0
        self.calls = []

    async def runner(self, argv, timeout):
        self.calls.append(tuple(argv))
        await asyncio.sleep(.01)
        return 0, "complete fixture output"

    def scheduler(self, name="fixture", **kwargs):
        return Scheduler(jobs=[Job(name, ("fixture",), 24 * HOUR)], state_path=self.state,
                         clock=lambda: self.now, runner=kwargs.pop("runner", self.runner),
                         resource_probe=kwargs.pop("resource_probe", lambda: m.Resources(5*m.GIB, True)),
                         **kwargs)

    async def test_two_instances_and_two_ticks_execute_once(self):
        first, second = self.scheduler(), self.scheduler()
        await asyncio.gather(first.tick(), first.tick(), second.tick())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first.status()[0]["runs"], 1)

    async def test_status_during_execution_does_not_lose_result(self):
        scheduler = self.scheduler()
        async def runner(argv, timeout):
            self.assertTrue(scheduler.status()[0]["running"])
            return 0, "whole output survives health polling"
        scheduler._runner = runner
        await scheduler.tick()
        self.assertEqual(scheduler.status()[0]["last_output"], "whole output survives health polling")
        self.assertFalse(scheduler.status()[0]["running"])

    async def test_low_memory_battery_unknown_defer_without_execution(self):
        for sample in (m.Resources(3*m.GIB, True), m.Resources(6*m.GIB, False), m.Resources(None, True), m.Resources(6*m.GIB, None)):
            scheduler = self.scheduler("reindex_memory", resource_probe=lambda: sample)
            await scheduler.tick()
            status = scheduler.status()[0]
            self.assertEqual(status["runs"], 0)
            self.assertTrue(status["deferred_reason"])
            self.assertEqual(status["next_attempt_ts"], self.now + 600)
            self.now += 601
        self.assertEqual(self.calls, [])

    async def test_unchanged_inputs_missing_outputs_and_weekly_fallback(self):
        scheduler = self.scheduler("run_all_tests")
        with patch.object(m, "fingerprint", return_value="signature"), patch.object(m, "outputs_exist", return_value=True):
            await scheduler.tick()
            success = scheduler.status()[0]["last_success_ts"]
            self.now += 24*HOUR + 1
            await scheduler.tick()
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(scheduler.status()[0]["last_success_ts"], success)
            self.assertEqual(scheduler.status()[0]["last_fresh_ts"], self.now)
            self.now += 7*24*HOUR
            await scheduler.tick()
            self.assertEqual(len(self.calls), 2)
        scheduler = self.scheduler("rebuild_corpora")
        with patch.object(m, "fingerprint", return_value="signature"), patch.object(m, "outputs_exist", return_value=False):
            await scheduler.tick()
            self.now += 24*HOUR + 1
            await scheduler.tick()
            self.assertEqual(scheduler.status()[0]["runs"], 2)

    async def test_input_changes_during_execution_never_mark_fresh(self):
        scheduler = self.scheduler("relabel_domains")
        with patch.object(m, "fingerprint", side_effect=["before", "after"]):
            await scheduler.tick()
        raw = json.loads(self.state.read_text())
        self.assertEqual(raw["relabel_domains"]["input_fingerprint"], "")
        self.assertEqual(raw["relabel_domains"]["last_fresh_ts"], 0)

    async def test_deferral_preserves_prior_failure_and_diagnostics(self):
        state = JobState(last_run=self.now-100000, last_rc=1, last_output="full failure evidence",
                         last_status="FAILED rc=1", consecutive_failures=2, failures=2, runs=2)
        self.state.write_text(json.dumps({"reindex_memory": state.to_dict()}))
        scheduler = self.scheduler("reindex_memory", resource_probe=lambda: m.Resources(3*m.GIB, True))
        await scheduler.tick()
        result = scheduler.status()[0]
        self.assertEqual(result["last_output"], "full failure evidence")
        self.assertEqual(result["consecutive_failures"], 2)
        self.assertEqual(result["runs"], 2)

    async def test_cooldown_allows_light_work(self):
        scheduler = self.scheduler("reindex_memory")
        m.atomic_json(scheduler._runtime.policy_path, {"cooldown_until": self.now+120})
        await scheduler.tick()
        self.assertEqual(self.calls, [])
        await self.scheduler("capture-fixture").tick()
        self.assertEqual(len(self.calls), 1)

    def test_schedule_and_admission(self):
        jobs = {j.name:j for j in default_jobs()}
        expected = {"reindex_memory":12,"index_episodes":6,"relabel_domains":24,"rebuild_corpora":48,"run_all_tests":24}
        for name,hours in expected.items():
            self.assertEqual(jobs[name].interval_seconds, hours*HOUR)
            self.assertLessEqual(jobs[name].timeout_seconds, 1800)
            self.assertEqual(jobs[name].retry_after_failure_seconds, 6*HOUR)
        self.assertEqual(m.admission(m.Resources(4*m.GIB, True)), "")

    def test_state_commit_failure_is_not_silently_accepted(self):
        scheduler=self.scheduler()
        with patch.object(Path,"replace",side_effect=OSError("fixture disk error")):
            with self.assertRaisesRegex(RuntimeError,"state commit failed"):
                scheduler._save()
        self.assertTrue(scheduler._runtime.metrics["state_commit_failed"])

    def test_fingerprints_detect_edits_deletions_and_ignore_outputs(self):
        root=Path(self.temp.name)
        source=root/"jarvis_data"/"observation_queue.jsonl"
        source.parent.mkdir(exist_ok=True)
        source.write_text("first",encoding="utf-8")
        first=m.fingerprint("relabel_domains",root)
        source.write_text("other",encoding="utf-8")
        second=m.fingerprint("relabel_domains",root)
        self.assertNotEqual(first,second)
        (source.parent/"domain_labels.jsonl").write_text("generated",encoding="utf-8")
        self.assertEqual(second,m.fingerprint("relabel_domains",root))
        source.unlink()
        self.assertNotEqual(second,m.fingerprint("relabel_domains",root))

    async def test_restart_records_interrupted_attempt_and_defers_retry(self):
        state=JobState(running=True,last_output="previous details",runs=2,first_seen_ts=self.now-100)
        self.state.write_text(json.dumps({"reindex_memory":state.to_dict()}))
        scheduler=self.scheduler("reindex_memory")
        await scheduler.tick()
        result=scheduler.status()[0]
        self.assertFalse(result["running"])
        self.assertEqual(result["last_rc"],130)
        self.assertEqual(result["runs"],3)
        self.assertEqual(result["next_attempt_ts"],self.now+6*HOUR)
        self.assertEqual(self.calls,[])

    def test_different_next_owner_preserves_interrupted_output_once(self):
        root = Path(self.temp.name)
        state_path = root / "jarvis_data" / ".hearth_jobs.json"
        runtime = m.Runtime(root, clock=lambda: self.now)
        state = JobState(running=True, runs=2, last_output="older execution")
        m.atomic_json(state_path, {"index_episodes": state.to_dict()})
        runtime.directory.mkdir(exist_ok=True)
        log = runtime.directory / "interrupted.log"
        evidence = "complete interrupted output\n" * 300
        log.write_text(evidence, encoding="utf-8")
        m.atomic_json(runtime.lease_path, {"job": "index_episodes", "output_file": str(log)})
        with runtime.lease("capture-fixture") as acquired:
            self.assertTrue(acquired)
            recovered = json.loads(state_path.read_text())["index_episodes"]
            self.assertFalse(recovered["running"])
            self.assertEqual(recovered["runs"], 3)
            self.assertTrue(recovered["last_output"].startswith(evidence))
            self.assertEqual(recovered["next_attempt_ts"], self.now + 6*HOUR)
        with runtime.lease("another-command"):
            self.assertEqual(json.loads(state_path.read_text())["index_episodes"]["runs"], 3)

    def test_pipeline_freshness_does_not_clear_failed_execution(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location("maintenance_pipeline_fixture",Path(__file__).with_name("pipeline_health.py"))
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        job=Job("run_all_tests",("fixture",),24*HOUR)
        state=JobState(last_run=self.now-3*24*HOUR,last_success_ts=self.now-3*24*HOUR,
                       last_checked_ts=self.now,last_fresh_ts=self.now,last_rc=0)
        self.state.write_text(json.dumps({job.name:state.to_dict()}))
        breaches,_=module.check_jobs(self.now,[job],self.state)
        self.assertEqual(breaches,[])
        state.consecutive_failures=1;state.last_rc=1;state.last_output="whole failed output"
        self.state.write_text(json.dumps({job.name:state.to_dict()}))
        breaches,_=module.check_jobs(self.now,[job],self.state)
        self.assertEqual(breaches[0]["output"],"whole failed output")
        state.consecutive_failures=0;state.last_success_ts=self.now-9*24*HOUR
        self.state.write_text(json.dumps({job.name:state.to_dict()}))
        breaches,_=module.check_jobs(self.now,[job],self.state)
        self.assertIn("weekly test fallback",breaches[0]["detail"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PolicyTests))
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    raise SystemExit(main())

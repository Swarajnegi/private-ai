"""LAYER: Agent/Brain — offline end-to-end permission and lifecycle verification.

THE BIG PICTURE: component tests cannot prove an action waits for its owner.
THE FLOW: scripted model -> real dispatch/broker/transport -> isolated D fixtures.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "js-development"))
from jarvis_core.agent.tool import ToolInput, ToolResult
from jarvis_core.agent.react import ReActLoop
from jarvis_core.agent.execution import ProcessRunner
from jarvis_core.agent.permissions import PermissionDecision
from jarvis_core.agent.tools.file_write import FileCreateTool
from jarvis_core.agent.tools.fs import FileReadTool
from jarvis_core.agent.tools.runtime import RuntimeInspectTool
from jarvis_core.agent.powershell_classifier import PowerShellClassifier
from jarvis_core.brain.permgate import build_permission_context
from jarvis_core.serve.hearth import Hearth, HearthConfig, build_app
from jarvis_core.serve.approvals import ApprovalBroker
from jarvis_core.serve import live_voice as lv


def scope(path, method="POST", session="", stream=False):
    return {"type": "http", "path": path, "method": method, "query_string": ("session=" + session).encode(),
            "client": ("127.0.0.1", 1), "headers": [(b"authorization", b"Bearer fixture-token"),
            (b"accept", b"text/event-stream" if stream else b"application/json")]}


class HarnessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        base = ROOT / ".runtime/milestone2/fixtures"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def spin(self, predicate):
        for _ in range(500):
            if predicate():
                return
            await asyncio.sleep(.01)
        self.fail("Fixture did not reach the expected state")

    async def test_native_calls_are_literal_parsed_and_not_final_answers(self):
        from jarvis_core.agent.parser import parse_tool_calls, ToolCall, ParseError
        native = "<|tool_call_start|>[file_read(path='literal.txt', offset=0)]<|tool_call_end|>"
        parsed = parse_tool_calls(native)
        self.assertIsInstance(parsed[0], ToolCall)
        self.assertEqual(parsed[0].arguments, {"path": "literal.txt", "offset": 0})
        for unsafe in ["file_read(path=__import__('os').getenv('KEY'))", "os.system(command='unsafe')", "file_read(**{'path':'x'})"]:
            self.assertIsInstance(parse_tool_calls("<|tool_call_start|>"+unsafe+"<|tool_call_end|>")[0], ParseError)
        target = self.root / "native.txt"
        target.write_text("Current actual bytes")
        replies = iter(["<|tool_call_start|>[file_read(path="+repr(str(target))+")]<|tool_call_end|>", "I read the actual bytes."])
        result = await ReActLoop(lambda messages: next(replies), {"file_read": FileReadTool()}, max_iterations=2).run("fixture")
        self.assertEqual(len(result.tool_calls), 1)
        self.assertNotIn("tool_call", result.final_text)

    async def test_forced_synthesis_never_displays_unexecuted_tool_call(self):
        target = self.root / "synthesis.txt"
        target.write_text("verified bytes")
        native = "<|tool_call_start|>[file_read(path="+repr(str(target))+")]<|tool_call_end|>"
        replies = iter([native, native])
        result = await ReActLoop(lambda messages: next(replies), {"file_read": FileReadTool()}, max_iterations=1).run("fixture")
        self.assertEqual(result.final_text, "")
        self.assertIn("did not complete", result.error)
        self.assertEqual(len(result.tool_calls), 1)

    async def test_native_search_fallback_uses_actual_feed_or_reports_unavailable(self):
        import io
        from jarvis_core.agent.tools.web import _native_rss_client, WebSearchTool
        raw = b"<rss><channel><item><title>Actual source</title><link>https://example.com/source</link><description>Recorded snippet</description></item></channel></rss>"
        with patch("jarvis_core.agent.tools.web.urlopen", return_value=io.BytesIO(raw)):
            results = _native_rss_client("query", 5)
        self.assertEqual(results, [{"url": "https://example.com/source", "title": "Actual source", "snippet": "Recorded snippet"}])
        with patch("jarvis_core.agent.tools.web.urlopen", return_value=io.BytesIO(b"<html>Unavailable</html>")):
            result = await WebSearchTool(client=_native_rss_client).invoke(__import__("jarvis_core.agent.tools.web", fromlist=["WebSearchInput"]).WebSearchInput(query="fixture"))
        self.assertTrue(result.is_error)
        self.assertEqual(result.metadata["error_code"], "unavailable")

    async def test_denied_action_is_not_reprompted_or_executed(self):
        target = self.root / "denied-repeat.txt"
        command = json.dumps({"name": "file_create", "arguments": {"path": str(target), "content": "not approved"}})
        replies = iter([command, command, "The action was denied and was not performed."])
        decisions = []
        def deny(name, args):
            decisions.append(args)
            return PermissionDecision.DENY
        tools = {"file_create": FileCreateTool(self.root)}
        result = await ReActLoop(lambda messages: next(replies), tools, permission_context=build_permission_context(tools), ask_handler=deny, max_iterations=3).run("fixture")
        self.assertEqual(len(decisions), 1)
        self.assertFalse(target.exists())
        self.assertTrue(all(res.metadata["error_code"] == "permission_denied" for tc,res in result.tool_calls))

    async def test_terminal_stream_submits_only_the_bound_decision(self):
        import io
        sys.path.insert(0, str(ROOT / "scripts"))
        import jarvis_client
        approval = {"id": "fixture-a", "request_id": "fixture-r", "session": "fixture-s", "digest": "fixture-digest", "tool": "file_create", "proposal": {"path": "scratch.txt", "content": "exact"}}
        stream = ("event: approval\ndata: " + json.dumps(approval) + "\n\nevent: answer\ndata: {\"ok\":true,\"answer\":\"done\"}\n\n").encode()
        recorded = []
        def open_request(request, **kwargs):
            recorded.append((request.full_url,json.loads(request.data)))
            return io.BytesIO(stream if request.full_url.endswith("/v1/ask") else b'{"ok":true}')
        with patch("jarvis_client.urllib.request.urlopen", side_effect=open_request):
            result = jarvis_client.ask_streaming("fixture", "http://fixture", "fixture-token", approval_handler=lambda name,args: PermissionDecision.ALLOW)
        self.assertTrue(result["ok"])
        self.assertTrue(recorded[0][1]["interactive_approvals"])
        self.assertEqual(recorded[1][1], {"request_id":"fixture-r","session":"fixture-s","digest":"fixture-digest","decision":"approve"})
        with patch("jarvis_client.urllib.request.urlopen", return_value=io.BytesIO(b'{"ok":true}')) as opened:
            jarvis_client.ask_buffered("fixture", "http://fixture", "fixture-token")
        self.assertFalse(json.loads(opened.call_args.args[0].data)["interactive_approvals"])

    async def test_ephemeral_spine_writes_no_history_state_queue_or_kb(self):
        from jarvis_core.brain.orchestrator import ask
        from jarvis_core.brain.confidence import ConfidenceGate
        kb = self.root / "kb.jsonl"
        kb.write_text("")
        state = self.root / "session-state.json"
        queue = self.root / "queue.jsonl"
        appended = []
        class Store:
            def load_context(self, *args): return []
            def append_turn(self, *args): appended.append(args)
        replies = iter([json.dumps([{"tool_name":"calculator","description":"compute"}]), json.dumps({"name":"calculator","arguments":{"expression":"1+1"}}), "Two."])
        result = await ask("ephemeral fixture", llm_call=lambda messages: next(replies), capture=False,
            kb_path=kb, queue_path=queue, session="ephemeral-fixture", session_state_path=state,
            conv_store=Store(), store_factory=lambda: None, inhale=False, use_profile=False,
            gate=ConfidenceGate(embed_fn=lambda texts:[[1.,0.] for _ in texts]), printer=lambda line:None)
        self.assertFalse(result.persisted)

        self.assertFalse(result.captured)
        self.assertEqual(result.distill_status,"skipped")
        self.assertEqual(appended,[])
        self.assertFalse(state.exists())
        self.assertFalse(queue.exists())
        self.assertEqual(kb.read_text(),"")

    async def test_environment_fallbacks_preserve_paid_and_explicit_router_policy(self):
        from jarvis_core.brain.orchestrator import environment_free_fallbacks
        for model, expected in [('fixture/missing:free', ['fixture/missing:free', 'openrouter/free']), ('openrouter/free', None), ('fixture/paid', None), ('', None)]:
            with patch.dict(os.environ, {'OPENROUTER_MODEL': model}):
                self.assertEqual(environment_free_fallbacks(), expected)
        inspector = RuntimeInspectTool(snapshot_provider=lambda:{'hardware': None, 'brain':{'model':'old configured primary'}})
        inspector.brain_state = lambda:{'configured_model':'fixture/missing:free','requested_primary':'fixture/missing:free','model':'openrouter/free','location':'cloud API'}
        snapshot = (await inspector.invoke(ToolInput())).output
        self.assertEqual(snapshot['brain']['model'], 'openrouter/free')
        self.assertEqual(snapshot['brain']['configured_model'], 'fixture/missing:free')

    async def test_default_free_model_404_fails_over_with_reasoning_and_budget(self):
        from jarvis_core.brain.orchestrator import ask
        from jarvis_core.brain.llm_client import OpenRouterClient
        from jarvis_core.brain.model_stats import ModelStatsStore
        from jarvis_core.brain.confidence import ConfidenceGate
        replies = iter([json.dumps([{'tool_name':'calculator','description':'compute'}]), json.dumps({'name':'calculator','arguments':{'expression':'1+1'}}), 'Two.'])
        sent, constructed, captured = [], [], []
        async def transport(url, headers, payload, timeout):
            if url.endswith('/models'):
                return 200, {'data':[{'id': m, 'pricing': {'prompt':'0', 'completion':'0'}} for m in ['fixture/missing:free', 'openrouter/free']]}
            sent.append(payload)
            if payload['model'] == 'fixture/missing:free':
                return 404, {'error': {'code':404,'message':'No endpoints found'}}
            return 200, {'model':'fixture/actual:free','choices':[{'message':{'content':next(replies)},'finish_reason':'stop'}], 'usage':{'prompt_tokens':5,'completion_tokens':5}}
        def build(**kwargs):
            constructed.append(kwargs)
            return OpenRouterClient(api_key='fixture-only', transport=transport, **{k:v for k,v in kwargs.items() if v is not None})
        class Store:
            def load_context(self, *args): return []
            def append_turn(self, *args): captured.append(args)
        kb = self.root / 'fallback-kb.jsonl'
        kb.write_text('')
        lines = []
        with patch.dict(os.environ, {'OPENROUTER_MODEL':'fixture/missing:free'}), patch('jarvis_core.brain.llm_client.build_llm_call', side_effect=build):
            result = await ask('fixture addition', capture=False, session='fallback-fixture', kb_path=kb,
                store_factory=lambda:None, conv_store=Store(), inhale=False, use_profile=False, reasoning_effort='high',
                model_stats_store=ModelStatsStore(path=self.root/'fallback-stats.jsonl'), budget_usd=.01,
                gate=ConfidenceGate(embed_fn=lambda texts:[[1.,0.] for _ in texts]), printer=lines.append)
        self.assertEqual(result.answer, 'Two.')
        self.assertFalse(result.persisted)
        self.assertEqual(sum(p['model']=='fixture/missing:free' for p in sent), 1)
        self.assertTrue(any(p['model']=='openrouter/free' for p in sent))
        self.assertTrue(all(p['reasoning']=={'effort':'high'} for p in sent))
        self.assertTrue(any('404' in line and 'failover' in line for line in lines))
        self.assertTrue(all(c['budget_usd']==.01 for c in constructed))
        self.assertIs(constructed[0]['cost_tracker'], constructed[1]['cost_tracker'])
        self.assertEqual(captured, [])

    async def test_validation_precedes_policy_and_aliases_are_bound(self):
        calls = iter([json.dumps({"name": "file_create", "arguments": {"path": str(self.root / "bad.txt")}}), "Done"])
        checked = []
        async def policy(name, args):
            checked.append(args)
            return PermissionDecision.ALLOW
        loop = ReActLoop(lambda messages: next(calls), {"file_create": FileCreateTool(self.root)},
                         permission_context=SimpleNamespace(check=policy), max_iterations=2, enable_cot_monitor=False)
        result = await loop.run("fixture")
        self.assertEqual(checked, [])
        self.assertEqual(result.tool_calls[0][1].metadata["error_code"], "invalid_arguments")
        self.assertFalse((self.root / "bad.txt").exists())
        calls = iter([json.dumps({"name": "file_create", "arguments": {"file_path": "alias.txt", "content": "bound"}}), "Done"])
        loop = ReActLoop(lambda messages: next(calls), {"file_create": FileCreateTool(self.root)}, permission_context=SimpleNamespace(check=policy), max_iterations=2, enable_cot_monitor=False)
        result = await loop.run("fixture")
        self.assertEqual(checked[0]["path"], str((self.root / "alias.txt").resolve()))
        self.assertNotIn("file_path", checked[0])
        self.assertEqual((self.root / "alias.txt").read_text(), "bound")

    async def test_react_reuses_only_successful_unchanged_read(self):
        target = self.root / "read.txt"
        target.write_text("all bytes", encoding="utf-8")
        class Reader(FileReadTool):
            count = 0
            async def invoke(inner, data):
                inner.count += 1
                return await super(Reader, inner).invoke(data)
        reader = Reader()
        call = {"name": "file_read", "arguments": {"path": str(target)}}
        calls = iter([json.dumps([call, call]), "Evidence read."])
        result = await ReActLoop(lambda messages: next(calls), {"file_read": reader}, max_iterations=2, enable_cot_monitor=False).run("fixture")
        self.assertEqual(reader.count, 1)
        self.assertTrue(result.tool_calls[1][1].metadata["reused"])

    async def test_hardware_preflight_is_current_evidence_before_model(self):
        snapshots = []
        def measure():
            snapshots.append(True)
            return {"gpu": {"name": "Measured fixture GPU", "vram_mib": 6144}}
        def model(messages):
            self.assertIn("Measured fixture GPU", json.dumps(messages))
            return "Current measurement: 6144 MiB. Latency has not been benchmarked."
        result = await ReActLoop(model, {"runtime_inspect": RuntimeInspectTool(snapshot_provider=measure)}, max_iterations=1).run("What are this laptop's specs?")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(result.tool_calls[0][0].name, "runtime_inspect")

    async def test_powershell_uncertain_syntax_never_autoallows(self):
        if os.name != "nt":
            self.skipTest("Native Windows parser")
        parser = PowerShellClassifier(self.root)
        for command in ["Write-Output $(Set-Content x y)", "& 'Get-Location'", "Get-Content x > y", "Get-ChildItem | ForEach-Object {Remove-Item $_}", "python -c 'print(1)'", "Get-CimInstance -ClassName Win32_Process", "Get-Content -Path C:/Windows/win.ini", "while(1){Get-Location}", "Get-Content *", "Get-Item Env:OPENROUTER_API_KEY", "Get-Content .ENV", "Write-Output '.hearth_token' | Get-Content", "Get-ChildItem | Get-Content"]:
            self.assertNotEqual(await parser.classify_async({"command": command, "cwd": str(self.root)}), PermissionDecision.ALLOW, command)
        self.assertEqual(await parser.classify_async({"command": "Get-ChildItem", "cwd": str(self.root.parent.parent.parent)}), PermissionDecision.ASK)
        original_resolve = Path.resolve
        def resolved(path, *args, **kwargs):
            return self.root.parent if path == self.root / "123" else original_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolved):
            self.assertEqual(await parser.classify_async({"command": "Get-Content -Path 123", "cwd": str(self.root)}), PermissionDecision.ASK)

    async def test_unmeasurable_gpu_preserves_other_runtime_evidence(self):
        if os.name != "nt":
            self.skipTest("Windows inspection")
        async def measurement(runner, argv, **kwargs):
            text = 'Fixture GPU, [N/A]' if any('--query-gpu' in a for a in argv) else '{"cpu":"Fixture CPU","ram_bytes":1073741824}'
            return ToolResult(output={"stdout": text, "stderr": "", "exit_code": 0})
        with patch.object(ProcessRunner, "run", measurement), patch("jarvis_core.agent.tools.runtime.shutil.which", return_value="fixture-gpu"):
            result = await RuntimeInspectTool().invoke(ToolInput())
        self.assertTrue(result.is_success)
        self.assertEqual(result.output["hardware"]["ram_gib"], 1)
        self.assertIsNone(result.output["gpu"])
        self.assertIn("unavailable", result.output["unknown"]["gpu"])
        self.assertIn("observed_at", result.output)

    async def test_file_edit_preserves_utf32_byte_order(self):
        from jarvis_core.agent.tools.file_write import FileEditTool
        from jarvis_core.agent.tool import safe_invoke
        target = self.root / "utf32.txt"
        original = b"\x00\x00\xfe\xff" + "first\r\nold\r\n".encode("utf-32-be")
        target.write_bytes(original)
        result = await safe_invoke(FileEditTool(self.root), {"path": str(target), "expected_sha256": hashlib.sha256(original).hexdigest(), "old_text": "old", "new_text": "new", "encoding": "utf-32"})
        self.assertTrue(result.is_success, result)
        self.assertEqual(target.read_bytes(), b"\x00\x00\xfe\xff" + "first\r\nnew\r\n".encode("utf-32-be"))

    async def test_expiry_and_restart_never_approve(self):
        broker = ApprovalBroker(ttl=.03)
        async def cancel():
            pass
        async def emit(*args):
            pass
        broker.register("r", "s", cancel)
        task = asyncio.create_task(broker.wait("r", "synthetic", {}, emit))
        await self.spin(lambda: bool(broker.pending_for("s")))
        approval = broker.pending_for("s")[0]
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertRaises(ValueError):
            broker.decide(approval["id"], request_id="r", session="s", digest=approval["digest"], decision="approve")
        with self.assertRaises(ValueError):
            ApprovalBroker().decide(approval["id"], request_id="r", session="s", digest=approval["digest"], decision="approve")

    async def make_hearth(self, hold=False):
        target = self.root / "approved.txt"
        invocations = []
        async def ask(question, **kwargs):
            invocations.append(question)
            self.assertIs(kwargs.get("capture"), False)
            commands = iter([json.dumps({"name": "file_create", "arguments": {"path": str(target), "content": "approved bytes"}}), "Completed with evidence."])
            tools = {"file_create": FileCreateTool()}
            result = await ReActLoop(lambda messages: next(commands), tools, permission_context=build_permission_context(tools),
                                     ask_handler=kwargs["ask_handler"], max_iterations=2, enable_cot_monitor=False).run(question)
            if hold:
                await asyncio.sleep(60)
            return SimpleNamespace(question=question, answer=result.final_text, verdict="fixture", confidence_score=1)
        hearth = Hearth(HearthConfig(token="fixture-token"), ask_fn=ask)
        return hearth, target, invocations

    async def test_termination_reports_completed_changes_without_rollback(self):
        hearth, target, _ = await self.make_hearth(hold=True)
        events = []
        async def emit(event, data):
            events.append((event, data))
        request_id = "completed-fixture"
        task = asyncio.create_task(hearth.run_ask("fixture", emit, session="completed-session", capture=False, request_id=request_id))
        await self.spin(lambda: bool(hearth.approvals.pending_for("completed-session")))
        approval = hearth.approvals.pending_for("completed-session")[0]
        hearth.approvals.decide(approval["id"], request_id=request_id, session="completed-session", digest=approval["digest"], decision="approve")
        request = hearth.approvals.requests[request_id]
        await self.spin(lambda: bool(request["completed_actions"]))
        await hearth.approvals.cancel(request_id, "completed-session")
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(target.read_text(), "approved bytes")
        self.assertEqual(request["completed_actions"][0]["status"], "created")
        self.assertEqual(request["completed_actions"][0]["path"], str(target.resolve()))
        from jarvis_core.agent.tool import ACTION_REPORTER
        self.assertIsNone(ACTION_REPORTER.get())

    async def test_http_disconnect_resume_approval_runs_once(self):
        hearth, target, invocations = await self.make_hearth()
        app = build_app(hearth)
        inbound = asyncio.Queue()
        await inbound.put({"type": "http.request", "body": json.dumps({"question": "fixture change", "session": "fixture-http", "capture": False}).encode(), "more_body": False})
        sent = []
        async def send(message):
            sent.append(message)
        original = asyncio.create_task(app(scope("/v1/ask", stream=True), inbound.get, send))
        await self.spin(lambda: bool(hearth.approvals.pending_for("fixture-http")))
        self.assertFalse(target.exists())
        approval = hearth.approvals.pending_for("fixture-http")[0]
        await inbound.put({"type": "http.disconnect"})
        await original
        self.assertTrue(hearth._slot.locked())
        self.assertFalse(hearth.approvals.requests[approval["request_id"]]["attached"])
        with self.assertRaises(ValueError):
            hearth.approvals.decide(approval["id"], request_id=approval["request_id"], session="fixture-http", digest=approval["digest"], decision="approve")
        resumed_in = asyncio.Queue()
        await resumed_in.put({"type": "http.request", "body": json.dumps({"resume_request": approval["request_id"], "session": "fixture-http"}).encode(), "more_body": False})
        resumed = asyncio.create_task(app(scope("/v1/ask", stream=True), resumed_in.get, send))
        await self.spin(lambda: hearth.approvals.requests[approval["request_id"]]["attached"])
        hearth.approvals.decide(approval["id"], request_id=approval["request_id"], session="fixture-http", digest=approval["digest"], decision="approve")
        await resumed
        self.assertEqual(invocations, ["fixture change"])
        self.assertEqual(target.read_text(), "approved bytes")
        self.assertFalse(hearth._slot.locked())

    async def test_terminate_waiting_action_keeps_disk_unchanged(self):
        hearth, target, invocations = await self.make_hearth()
        async def send(message):
            pass
        class Brain:
            async def respond(self, *args, **kwargs):
                yield {"type": "deep", "model": "fixture"}
        live = lv.LiveSession(hearth, send, brain=Brain(), engine=SimpleNamespace())
        live.session, live.ephemeral, live.speak = "fixture-cancel", True, False
        live._log = lambda timing: asyncio.sleep(0)
        await live.on_text(json.dumps({"type": "text", "question": "fixture change"}))
        await self.spin(lambda: bool(hearth.approvals.pending_for(live.session)))
        request_id = live.request_id
        await live.on_text(json.dumps({"type": "interrupt", "request_id": request_id}))
        self.assertFalse(target.exists())
        self.assertFalse(hearth._slot.locked())
        self.assertFalse(hearth.approvals.pending_for(live.session))

    async def test_cancellation_kills_real_child_process(self):
        if os.name != "nt":
            self.skipTest("Windows Job Object assertion")
        pid_file = self.root / "child.pid"
        script = "import subprocess,sys,time; from pathlib import Path; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
        runner = ProcessRunner()
        running = asyncio.create_task(runner.run([sys.executable, "-c", script, str(pid_file)], cwd=str(self.root), timeout=10))
        await self.spin(pid_file.exists)
        pid = int(pid_file.read_text())
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        from jarvis_core.serve.maintenance import _birth
        self.assertEqual(_birth(pid), 0)
        self.assertFalse(runner.cleanup_failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(HarnessTests))
    raise SystemExit(not result.wasSuccessful())

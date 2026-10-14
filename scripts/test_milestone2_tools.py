#!/usr/bin/env python3
"""Offline Milestone 2 tool regression tests for JARVIS Agent & Serve layers.

LAYER: Tools / Agent / Brain (Milestone 2 verification)

Tests bounded offline tool behaviors:
1. prepare_input & argument aliasing before permission gating.
2. FileCreateTool creation, existence refusal, workspace escapes, and protected path rejection.
3. FileEditTool digest checking, unique replacement, CRLF preservation, and atomic update.
4. ReadCoverage request-local verified read reuse and invalidation on disk change.
5. Error classification distinguishing path_not_found from unknown_tool.
6. RuntimeInspectTool snapshot inspection, observed_at, scope, and unknown dictionary.
7. ProcessRunner supervision: nonzero exit code, hard timeout, and cancellation cleanup.
8. ApprovalBroker single-use approval lifecycle, decision validation, attach gating, and cancellation.
9. PowerShellClassifier allowlist, syntax parsing, and credential denial.

All tests run strictly offline with synthetic fixtures under .runtime/milestone2/fixtures.
No real models called, no turn capture, no secrets inspected, and no production data modified.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from typing import Any, Dict, List

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PKG_DIR = _REPO_ROOT / "js-development"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from jarvis_core.agent.errors import ClassifiedError, ToolErrorKind, classify_error
from jarvis_core.agent.execution import ProcessRunner
from jarvis_core.agent.permissions import PermissionDecision
from jarvis_core.agent.powershell_classifier import PowerShellClassifier
from jarvis_core.agent.read_cache import ReadCoverage
from jarvis_core.agent.tool import ToolInput, ToolResult, prepare_input, safe_invoke
from jarvis_core.agent.tools.file_write import FileCreateTool, FileEditTool
from jarvis_core.agent.tools.fs import FileReadTool
from jarvis_core.agent.tools.runtime import RuntimeInspectTool
from jarvis_core.agent.tools.shell import ShellRunTool
from jarvis_core.serve.approvals import ApprovalBroker


class Milestone2ToolRegressions(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_base = _REPO_ROOT / ".runtime" / "milestone2" / "fixtures"
        self.fixture_base.mkdir(parents=True, exist_ok=True)
        self.tmp_dir = tempfile.TemporaryDirectory(dir=self.fixture_base)
        self.workspace = Path(self.tmp_dir.name).resolve()

        # Seed standard workspace structure
        (self.workspace / "docs").mkdir(parents=True, exist_ok=True)
        (self.workspace / "src").mkdir(parents=True, exist_ok=True)
        (self.workspace / "jarvis_data").mkdir(parents=True, exist_ok=True)
        (self.workspace / "client_work").mkdir(parents=True, exist_ok=True)
        (self.workspace / ".git").mkdir(parents=True, exist_ok=True)
        (self.workspace / ".venv").mkdir(parents=True, exist_ok=True)
        (self.workspace / ".cache").mkdir(parents=True, exist_ok=True)
        (self.workspace / "corpus").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        try:
            self.tmp_dir.cleanup()
        except OSError as error:
            self.fail(f"Fixture cleanup failed: {error}")

    # =========================================================================
    # 1. PREPARE_INPUT & ARGUMENT ALIASING BEFORE PERMISSION
    # =========================================================================

    def test_01_prepare_input_resolves_aliases_and_records_notes(self) -> None:
        """Alias resolution maps near-miss fields before schema validation."""
        tool = FileCreateTool(root=self.workspace)
        raw = {"file_path": "docs/readme.txt", "content": "Hello World"}
        validated, notes = prepare_input(tool, raw)

        self.assertEqual(validated.content, "Hello World")
        expected_path = str((self.workspace / "docs" / "readme.txt").resolve())
        self.assertEqual(validated.path, expected_path)
        self.assertTrue(any("file_path" in n and "path" in n for n in notes))

    def test_02_prepare_input_rejects_invalid_arguments_early(self) -> None:
        """Invalid or missing arguments fail validation with invalid_arguments code."""
        tool = FileCreateTool(root=self.workspace)
        # Missing required 'content'
        res = asyncio.run(safe_invoke(tool, {"path": "docs/invalid.txt"}))
        self.assertTrue(res.is_error)
        self.assertEqual(res.metadata.get("error_code"), "invalid_arguments")
        self.assertIn("Input validation failed", res.error)

    def test_03_prepare_input_normalizes_shell_run_defaults(self) -> None:
        """Shell tool normalizes 'auto' shell to powershell on Windows and resolves cwd."""
        tool = ShellRunTool()
        raw = {"command": "Write-Output test", "cwd": str(self.workspace)}
        validated, _ = prepare_input(tool, raw)
        if os.name == "nt":
            self.assertEqual(validated.shell, "powershell")
        self.assertEqual(validated.cwd, str(self.workspace.resolve()))

    # =========================================================================
    # 2. FILE_CREATE_TOOL: CREATION & REFUSAL CONSTRAINTS
    # =========================================================================

    def test_04_file_create_successfully_writes_new_file(self) -> None:
        """Creating an absent text file inside workspace succeeds atomically."""
        tool = FileCreateTool(root=self.workspace)
        target = "docs/new_doc.txt"
        res = asyncio.run(safe_invoke(tool, {"path": target, "content": "Sample content"}))

        self.assertTrue(res.is_success)
        self.assertEqual(res.output.get("status"), "created")
        file_path = self.workspace / target
        self.assertTrue(file_path.is_file())
        self.assertEqual(file_path.read_text(encoding="utf-8"), "Sample content")
        self.assertEqual(res.output.get("sha256"), hashlib.sha256(b"Sample content").hexdigest())

    def test_05_file_create_refuses_existing_file(self) -> None:
        """Creating an already existing file is refused with conflict error code."""
        tool = FileCreateTool(root=self.workspace)
        target = self.workspace / "docs" / "existing.txt"
        target.write_text("Already exists", encoding="utf-8")

        res = asyncio.run(safe_invoke(tool, {"path": "docs/existing.txt", "content": "Overwriting attempt"}))
        self.assertTrue(res.is_error)
        self.assertEqual(res.metadata.get("error_code"), "conflict")
        self.assertIn("File already exists", res.error)
        self.assertEqual(target.read_text(encoding="utf-8"), "Already exists")

    def test_06_file_create_refuses_workspace_escapes(self) -> None:
        """Paths traversing outside workspace boundary are rejected."""
        tool = FileCreateTool(root=self.workspace)
        res = asyncio.run(safe_invoke(tool, {"path": "../../outside_escape.txt", "content": "malicious"}))
        self.assertTrue(res.is_error)
        self.assertEqual(res.metadata.get("error_code"), "invalid_arguments")
        self.assertIn("File changes must remain inside the workspace", res.error)

    def test_07_file_create_refuses_authoritative_protected_records(self) -> None:
        """Protected stores (jarvis_data, client_work, .git, .venv, .cache, corpus) are refused."""
        tool = FileCreateTool(root=self.workspace)
        protected_prefixes = ["jarvis_data", "client_work", ".git", ".venv", ".cache", "corpus"]

        for prefix in protected_prefixes:
            target_rel = f"{prefix}/sneaky.txt"
            res = asyncio.run(safe_invoke(tool, {"path": target_rel, "content": "data"}))
            self.assertTrue(res.is_error, f"Expected refusal for protected record: {prefix}")
            self.assertIn("Protected records/artifacts require their dedicated writer", res.error)

    def test_08_file_create_refuses_missing_parent_directory(self) -> None:
        """Parent directory must already exist before creating file."""
        tool = FileCreateTool(root=self.workspace)
        res = asyncio.run(safe_invoke(tool, {"path": "nonexistent_dir/file.txt", "content": "abc"}))
        self.assertTrue(res.is_error)
        self.assertIn("Parent directory must already exist", res.error)

    # =========================================================================
    # 3. FILE_EDIT_TOOL: DIGEST & REPLACEMENT CONSTRAINTS
    # =========================================================================

    def test_09_file_edit_succeeds_with_matching_digest_and_unique_target(self) -> None:
        """Unique replacement with matching sha256 updates file atomically."""
        tool = FileEditTool(root=self.workspace)
        doc = self.workspace / "src" / "sample.py"
        initial_bytes = b"def hello():\n    return 'world'\n"
        doc.write_bytes(initial_bytes)
        current_sha = hashlib.sha256(doc.read_bytes()).hexdigest()

        res = asyncio.run(safe_invoke(tool, {
            "path": "src/sample.py",
            "expected_sha256": current_sha,
            "old_text": "'world'",
            "new_text": "'jarvis'",
        }))
        self.assertTrue(res.is_success)
        self.assertEqual(res.output.get("status"), "edited")
        updated = doc.read_text(encoding="utf-8")
        self.assertEqual(updated, "def hello():\n    return 'jarvis'\n")
        self.assertEqual(res.output.get("sha256"), hashlib.sha256(doc.read_bytes()).hexdigest())

    def test_10_file_edit_refuses_stale_or_mismatched_digest(self) -> None:
        """Mismatched expected_sha256 refuses edit with conflict error code."""
        tool = FileEditTool(root=self.workspace)
        doc = self.workspace / "src" / "stale.py"
        doc.write_bytes(b"v1 content\n")
        wrong_sha = "0" * 64

        res = asyncio.run(safe_invoke(tool, {
            "path": "src/stale.py",
            "expected_sha256": wrong_sha,
            "old_text": "v1",
            "new_text": "v2",
        }))
        self.assertTrue(res.is_error)
        self.assertEqual(res.metadata.get("error_code"), "conflict")
        self.assertIn("File changed; read and approve the current content", res.error)
        self.assertEqual(doc.read_bytes(), b"v1 content\n")

    def test_11_file_edit_refuses_non_unique_or_absent_match(self) -> None:
        """Target string must occur exactly once (count == 1)."""
        tool = FileEditTool(root=self.workspace)
        doc = self.workspace / "src" / "counts.txt"
        doc.write_bytes(b"repeat repeat repeat\n")
        current_sha = hashlib.sha256(doc.read_bytes()).hexdigest()

        # Multiple matches (count = 3)
        res_multi = asyncio.run(safe_invoke(tool, {
            "path": "src/counts.txt",
            "expected_sha256": current_sha,
            "old_text": "repeat",
            "new_text": "single",
        }))
        self.assertTrue(res_multi.is_error)
        self.assertEqual(res_multi.metadata.get("error_code"), "conflict")
        self.assertIn("Replacement must match exactly once", res_multi.error)

        # Zero matches (count = 0)
        res_zero = asyncio.run(safe_invoke(tool, {
            "path": "src/counts.txt",
            "expected_sha256": current_sha,
            "old_text": "nonexistent",
            "new_text": "single",
        }))
        self.assertTrue(res_zero.is_error)
        self.assertEqual(res_zero.metadata.get("error_code"), "conflict")
        self.assertIn("Replacement must match exactly once", res_zero.error)

    def test_12_file_edit_preserves_crlf_line_endings(self) -> None:
        """CRLF files preserve CRLF endings when new text uses LF."""
        tool = FileEditTool(root=self.workspace)
        doc = self.workspace / "src" / "crlf_file.txt"
        raw_bytes = b"Line 1\r\nLine 2\r\nLine 3\r\n"
        doc.write_bytes(raw_bytes)
        current_sha = hashlib.sha256(raw_bytes).hexdigest()

        res = asyncio.run(safe_invoke(tool, {
            "path": "src/crlf_file.txt",
            "expected_sha256": current_sha,
            "old_text": "Line 2",
            "new_text": "Modified Line 2",
        }))
        self.assertTrue(res.is_success)
        after_bytes = doc.read_bytes()
        self.assertIn(b"\r\n", after_bytes)
        self.assertNotIn(b"Line 2\n", after_bytes.replace(b"\r\n", b""))
        self.assertEqual(after_bytes, b"Line 1\r\nModified Line 2\r\nLine 3\r\n")

    # =========================================================================
    # 4. READ_COVERAGE: VERIFIED READ REUSE & INVALIDATION
    # =========================================================================

    def test_13_read_coverage_reuses_unchanged_read(self) -> None:
        """Unchanged file with matching arguments reuses cached result."""
        coverage = ReadCoverage()
        file_path = self.workspace / "docs" / "cached.txt"
        file_content = "Constant file content"
        file_path.write_text(file_content, encoding="utf-8")
        file_sha = hashlib.sha256(file_content.encode("utf-8")).hexdigest()

        args = {"path": str(file_path), "encoding": "utf-8", "offset": 0, "max_bytes": None}
        initial_result = ToolResult(
            output={"content": file_content, "sha256": file_sha, "size_bytes": len(file_content)},
            metadata={"execution": "fresh read"},
        )
        coverage.remember(args, initial_result)

        cached = coverage.get(args)
        self.assertIsNotNone(cached)
        self.assertTrue(cached.metadata.get("reused"))
        self.assertEqual(cached.metadata.get("execution"), "prior verified read")
        self.assertEqual(cached.output.get("content"), file_content)

    def test_14_read_coverage_invalidates_on_file_modification(self) -> None:
        """Modifying file content on disk invalidates cached read."""
        coverage = ReadCoverage()
        file_path = self.workspace / "docs" / "mutable.txt"
        file_path.write_text("Version 1", encoding="utf-8")
        sha1 = hashlib.sha256(b"Version 1").hexdigest()

        args = {"path": str(file_path), "encoding": "utf-8", "offset": 0, "max_bytes": None}
        initial_result = ToolResult(output={"content": "Version 1", "sha256": sha1})
        coverage.remember(args, initial_result)

        # Mutate file content
        file_path.write_text("Version 2 - changed bytes", encoding="utf-8")

        # Cache lookup must detect digest mismatch and return None
        lookup = coverage.get(args)
        self.assertIsNone(lookup)

    def test_15_read_coverage_misses_on_different_range(self) -> None:
        """Different offset or max_bytes produces cache miss."""
        coverage = ReadCoverage()
        file_path = self.workspace / "docs" / "ranged.txt"
        file_path.write_text("0123456789", encoding="utf-8")
        sha = hashlib.sha256(b"0123456789").hexdigest()

        args_full = {"path": str(file_path), "encoding": "utf-8", "offset": 0, "max_bytes": None}
        coverage.remember(args_full, ToolResult(output={"content": "0123456789", "sha256": sha}))

        # Query with offset
        args_offset = {"path": str(file_path), "encoding": "utf-8", "offset": 5, "max_bytes": None}
        self.assertIsNone(coverage.get(args_offset))

    # =========================================================================
    # 5. ERROR CLASSIFICATION: PATH_NOT_FOUND VS UNKNOWN_TOOL
    # =========================================================================

    def test_16_error_classification_distinguishes_path_not_found(self) -> None:
        """Missing file path classifies as EXECUTION_FAILED with repair hint, not UNKNOWN_TOOL."""
        res = ToolResult(
            error="File not found: /missing/path.txt",
            metadata={"error_code": "path_not_found"},
        )
        classified = classify_error(res, attempted_tool_name="file_read")
        self.assertEqual(classified.kind, ToolErrorKind.EXECUTION_FAILED)
        self.assertNotEqual(classified.kind, ToolErrorKind.UNKNOWN_TOOL)
        self.assertIn("The requested path is missing", classified.repair_hint)
        self.assertIn("file_search", classified.repair_hint)

    def test_17_error_classification_identifies_unknown_tool(self) -> None:
        """Unknown or unregistered tool classifies as UNKNOWN_TOOL."""
        res = ToolResult(
            error="tool 'magic_wand' not registered",
            metadata={"error_code": "unknown_tool"},
        )
        classified = classify_error(res, attempted_tool_name="magic_wand")
        self.assertEqual(classified.kind, ToolErrorKind.UNKNOWN_TOOL)
        self.assertEqual(classified.tool_name, "magic_wand")

    def test_18_error_classification_identifies_invalid_arguments(self) -> None:
        """Argument schema mismatch classifies as VALIDATION_FAILED."""
        res = ToolResult(
            error="Input validation failed for 'file_edit': missing expected_sha256",
            metadata={"error_code": "invalid_arguments"},
        )
        classified = classify_error(res, attempted_tool_name="file_edit")
        self.assertEqual(classified.kind, ToolErrorKind.VALIDATION_FAILED)

    # =========================================================================
    # 6. RUNTIME_INSPECT_TOOL: SYSTEM MEASUREMENT & UNKNOWN DISCLOSURE
    # =========================================================================

    def test_19_runtime_inspect_returns_measured_snapshot_and_scope(self) -> None:
        """RuntimeInspectTool returns observed_at timestamp and explicit measurement scope."""
        synthetic_snapshot = {
            "hostname": "test-host",
            "os": "Windows-11-Test",
            "hardware": {"cpu": "Synthetic CPU", "ram_bytes": 16000000000},
            "gpu": None,
        }
        mock_tools = {"file_read": FileReadTool(), "file_edit": FileEditTool()}
        tool = RuntimeInspectTool(snapshot_provider=lambda: synthetic_snapshot, tools=mock_tools)

        res = asyncio.run(safe_invoke(tool, {}))
        self.assertTrue(res.is_success)
        out = res.output
        self.assertIn("observed_at", out)
        self.assertEqual(out.get("measurement_scope"), "current host; no latency benchmark performed")
        self.assertEqual(out.get("hostname"), "test-host")

        # Verify tool declarations
        tools_list = out.get("tools", [])
        tool_names = [t["name"] for t in tools_list]
        self.assertIn("file_read", tool_names)
        self.assertIn("file_edit", tool_names)

    def test_20_runtime_inspect_discloses_unknown_fields_honestly(self) -> None:
        """Unknown runtime fields are labeled in unknown dictionary without fabrication."""
        def partial_provider():
            return {"hostname": "laptop", "unknown": {"gpu": "nvidia-smi is unavailable; VRAM was not measured"}}

        tool = RuntimeInspectTool(snapshot_provider=partial_provider)
        res = asyncio.run(safe_invoke(tool, {}))
        self.assertTrue(res.is_success)
        unknowns = res.output.get("unknown", {})
        self.assertIn("gpu", unknowns)
        self.assertIn("nvidia-smi is unavailable", unknowns["gpu"])

    # =========================================================================
    # 7. PROCESS_RUNNER: PROCESS SUPERVISION & TREE TEARDOWN
    # =========================================================================

    def test_21_process_runner_handles_clean_and_nonzero_exit_codes(self) -> None:
        """ProcessRunner correctly captures stdout, stderr, and nonzero exit codes."""
        runner = ProcessRunner()

        # Success command
        r_ok = asyncio.run(runner.run(
            [sys.executable, "-c", "import sys; sys.stdout.write('supervised output'); sys.exit(0)"],
            cwd=str(self.workspace),
            timeout=10,
        ))
        self.assertTrue(r_ok.is_success)
        self.assertEqual(r_ok.output.get("exit_code"), 0)
        self.assertEqual(r_ok.output.get("stdout"), "supervised output")
        self.assertEqual(r_ok.output.get("status"), "completed")

        # Nonzero exit command
        r_fail = asyncio.run(runner.run(
            [sys.executable, "-c", "import sys; sys.stderr.write('failed badly'); sys.exit(42)"],
            cwd=str(self.workspace),
            timeout=10,
        ))
        self.assertTrue(r_fail.is_error)
        self.assertEqual(r_fail.metadata.get("error_code"), "process_exit")
        self.assertEqual(r_fail.output.get("exit_code"), 42)
        self.assertIn("failed badly", r_fail.output.get("stderr"))
        self.assertEqual(r_fail.output.get("status"), "failed")

    def test_22_process_runner_hard_timeout_terminates_process_tree(self) -> None:
        """Process exceeding timeout is killed cleanly with timeout error code."""
        runner = ProcessRunner()
        # Launch python process sleeping 15 seconds with 0.5s timeout
        r_timeout = asyncio.run(runner.run(
            [sys.executable, "-c", "import time; time.sleep(15)"],
            cwd=str(self.workspace),
            timeout=0.5,
        ))
        self.assertTrue(r_timeout.is_error)
        self.assertEqual(r_timeout.metadata.get("error_code"), "timeout")
        self.assertEqual(r_timeout.output.get("status"), "timed_out")
        self.assertFalse(runner.cleanup_failed)

    def test_23_process_runner_cancellation_cleans_up_process_tree(self) -> None:
        """Cancelling the asyncio task kills process tree and re-raises CancelledError."""
        runner = ProcessRunner()

        async def run_and_cancel() -> None:
            task = asyncio.create_task(runner.run(
                [sys.executable, "-c", "import time; time.sleep(15)"],
                cwd=str(self.workspace),
                timeout=10,
            ))
            await asyncio.sleep(0.2)
            task.cancel()
            await task

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(run_and_cancel())
        self.assertFalse(runner.cleanup_failed)

    # =========================================================================
    # 8. APPROVAL_BROKER: SINGLE-USE REQUEST-BOUND APPROVALS
    # =========================================================================

    def test_24_approval_broker_allows_approved_request(self) -> None:
        """Approving a pending request returns PermissionDecision.ALLOW."""
        current_time = 1000.0
        broker = ApprovalBroker(clock=lambda: current_time, ttl=60.0)
        emitted_events: List[tuple[str, dict]] = []

        async def mock_emit(event: str, data: dict) -> None:
            emitted_events.append((event, data))

        async def mock_cancel() -> None:
            pass

        broker.register("req_001", "session_alpha", mock_cancel, attached=True)

        async def scenario() -> PermissionDecision:
            wait_task = asyncio.create_task(
                broker.wait("req_001", "fake_action", {"param": "val"}, mock_emit)
            )
            await asyncio.sleep(0.01)

            pending = broker.pending_for("session_alpha")
            self.assertEqual(len(pending), 1)
            approval_id = pending[0]["id"]
            digest = pending[0]["digest"]

            # Decide approve
            decided = broker.decide(
                approval_id,
                request_id="req_001",
                session="session_alpha",
                digest=digest,
                decision="approve",
            )
            self.assertEqual(decided["status"], "approved")
            return await wait_task

        decision = asyncio.run(scenario())
        self.assertEqual(decision, PermissionDecision.ALLOW)

    def test_25_approval_broker_denies_rejected_request(self) -> None:
        """Denying a pending request returns PermissionDecision.DENY."""
        current_time = 1000.0
        broker = ApprovalBroker(clock=lambda: current_time, ttl=60.0)

        async def mock_emit(event: str, data: dict) -> None:
            pass

        async def mock_cancel() -> None:
            pass

        broker.register("req_002", "session_beta", mock_cancel, attached=True)

        async def scenario() -> PermissionDecision:
            wait_task = asyncio.create_task(
                broker.wait("req_002", "fake_action", {"flag": True}, mock_emit)
            )
            await asyncio.sleep(0.01)

            pending = broker.pending_for("session_beta")
            approval_id = pending[0]["id"]
            digest = pending[0]["digest"]

            broker.decide(
                approval_id,
                request_id="req_002",
                session="session_beta",
                digest=digest,
                decision="deny",
            )
            return await wait_task

        decision = asyncio.run(scenario())
        self.assertEqual(decision, PermissionDecision.DENY)

    def test_26_approval_broker_rejects_mutated_digest_or_wrong_session(self) -> None:
        """Mismatched digest, wrong request_id, or wrong session raises ValueError."""
        broker = ApprovalBroker(clock=lambda: 1000.0, ttl=60.0)

        async def mock_emit(event: str, data: dict) -> None:
            pass

        async def mock_cancel() -> None:
            pass

        broker.register("req_003", "session_gamma", mock_cancel, attached=True)

        async def run_checks() -> None:
            task = asyncio.create_task(
                broker.wait("req_003", "fake_action", {"target": "x"}, mock_emit)
            )
            await asyncio.sleep(0.01)
            pending = broker.pending_for("session_gamma")
            approval_id = pending[0]["id"]
            digest = pending[0]["digest"]

            # 1. Wrong session
            with self.assertRaises(ValueError):
                broker.decide(
                    approval_id,
                    request_id="req_003",
                    session="wrong_session",
                    digest=digest,
                    decision="approve",
                )

            # 2. Mutated digest
            with self.assertRaises(ValueError):
                broker.decide(
                    approval_id,
                    request_id="req_003",
                    session="session_gamma",
                    digest="corrupted_digest_hex",
                    decision="approve",
                )

            # 3. Wrong request_id
            with self.assertRaises(ValueError):
                broker.decide(
                    approval_id,
                    request_id="wrong_req",
                    session="session_gamma",
                    digest=digest,
                    decision="approve",
                )

            broker.invalidate("req_003")
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_checks())

    def test_27_approval_broker_rejects_unattached_client_or_replay(self) -> None:
        """Detached client (attached=False) or replay on resolved approval is rejected."""
        broker = ApprovalBroker(clock=lambda: 1000.0, ttl=60.0)

        async def mock_emit(event: str, data: dict) -> None:
            pass

        async def mock_cancel() -> None:
            pass

        broker.register("req_004", "session_delta", mock_cancel, attached=True)

        async def run_checks() -> None:
            task = asyncio.create_task(
                broker.wait("req_004", "fake_action", {"foo": "bar"}, mock_emit)
            )
            await asyncio.sleep(0.01)
            pending = broker.pending_for("session_delta")
            approval_id = pending[0]["id"]
            digest = pending[0]["digest"]

            # Detach request
            broker.attach("req_004", "session_delta", attached=False)
            with self.assertRaises(ValueError):
                broker.decide(
                    approval_id,
                    request_id="req_004",
                    session="session_delta",
                    digest=digest,
                    decision="approve",
                )

            # Re-attach and decide
            broker.attach("req_004", "session_delta", attached=True)
            broker.decide(
                approval_id,
                request_id="req_004",
                session="session_delta",
                digest=digest,
                decision="approve",
            )
            await task

            # Replay attempt on now-approved record
            with self.assertRaises(ValueError):
                broker.decide(
                    approval_id,
                    request_id="req_004",
                    session="session_delta",
                    digest=digest,
                    decision="approve",
                )

        asyncio.run(run_checks())

    def test_28_approval_broker_handles_invalidation_and_cancellation(self) -> None:
        """cancel() calls registered cancel callback and marks approval resolved."""
        cancelled = False

        async def mock_cancel() -> None:
            nonlocal cancelled
            cancelled = True

        async def mock_emit(event: str, data: dict) -> None:
            pass

        broker = ApprovalBroker(clock=lambda: 1000.0, ttl=60.0)
        broker.register("req_005", "session_eps", mock_cancel, attached=True)

        async def scenario() -> None:
            task = asyncio.create_task(
                broker.wait("req_005", "fake_action", {"k": "v"}, mock_emit)
            )
            await asyncio.sleep(0.01)
            self.assertTrue(broker.has_pending("req_005"))

            await broker.cancel("req_005", "session_eps")
            self.assertTrue(cancelled)

            try:
                await task
            except asyncio.CancelledError:
                pass

            self.assertFalse(broker.has_pending("req_005"))

        asyncio.run(scenario())

    # =========================================================================
    # 9. POWERSHELL_CLASSIFIER: SAFE CMDLETS VS DANGEROUS/CREDENTIAL ACCESS
    # =========================================================================

    def test_29_powershell_classifier_allows_safe_read_commands(self) -> None:
        """PowerShellClassifier allows safe query commands within workspace."""
        if os.name != "nt":
            self.skipTest("PowerShellClassifier requires Windows native environment")

        classifier = PowerShellClassifier(root=self.workspace)
        safe_cmds = [
            "Get-Location",
            "Write-Output 'testing safe'",
            "Get-ChildItem -Path docs",
            "Test-Path -Path docs",
        ]
        for cmd in safe_cmds:
            decision = asyncio.run(classifier.classify_async({"command": cmd, "cwd": str(self.workspace)}))
            self.assertEqual(decision, PermissionDecision.ALLOW, f"Command should be allowed: {cmd}")

    def test_30_powershell_classifier_denies_credential_access(self) -> None:
        """PowerShellClassifier explicitly DENIES reading credentials or .env files."""
        if os.name != "nt":
            self.skipTest("PowerShellClassifier requires Windows native environment")

        classifier = PowerShellClassifier(root=self.workspace)
        sensitive_cmds = [
            "Get-Content -Path .env",
            "Get-Content -Path credentials",
            "Get-Content -Path .hearth_token",
        ]
        for cmd in sensitive_cmds:
            decision = asyncio.run(classifier.classify_async({"command": cmd, "cwd": str(self.workspace)}))
            self.assertEqual(decision, PermissionDecision.DENY, f"Command should be denied: {cmd}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.parse_args()
    unittest.main(argv=[sys.argv[0]], verbosity=2)

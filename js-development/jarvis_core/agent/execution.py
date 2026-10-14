"""LAYER: Agent — supervised command execution.

THE BIG PICTURE: approvals permit a bounded action, never an orphaned process.
THE FLOW: spawn suspended -> assign tree -> resume -> drain -> confirm cleanup.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import signal
import subprocess
from typing import Sequence
import uuid

from jarvis_core.config import JARVIS_ROOT
from jarvis_core.agent.tool import ToolResult


def execution_environment() -> dict[str, str]:
    env = dict(os.environ)
    root = Path(JARVIS_ROOT)
    tmp = root / ".runtime" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for name in ("TEMP", "TMP", "TMPDIR"):
        env[name] = str(tmp)
    paths = {"PIP_CACHE_DIR": "pip", "HF_HOME": "huggingface", "HF_HUB_CACHE": "huggingface/hub",
             "HUGGINGFACE_HUB_CACHE": "huggingface/hub", "SENTENCE_TRANSFORMERS_HOME": "sentence-transformers",
             "TORCH_HOME": "torch", "XDG_CACHE_HOME": "", "UV_CACHE_DIR": "uv", "npm_config_cache": "npm"}
    for name, suffix in paths.items():
        env[name] = str(root / ".cache" / suffix)
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        env[name] = "2"
    env["PYTHONUTF8"] = "1"
    return env


def powershell_path() -> str:
    candidate = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not candidate.is_file():
        raise FileNotFoundError("Native Windows PowerShell is unavailable")
    return str(candidate)


CLEANUP_UNCONFIRMED = False


class ProcessRunner:
    def __init__(self) -> None:
        self.cleanup_failed = False

    async def run(self, argv: Sequence[str], *, cwd: str, timeout: float = 30) -> ToolResult:
        global CLEANUP_UNCONFIRMED
        if CLEANUP_UNCONFIRMED:
            return ToolResult(error="Previous tool cleanup is unconfirmed; restart Hearth before another execution", metadata={"error_code": "cleanup_unconfirmed"})
        tree = None
        proc = None
        drain = None
        try:
            kwargs = {"cwd": cwd, "env": execution_environment(), "stdin": subprocess.DEVNULL,
                      "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
            if os.name == "nt":
                from jarvis_core.serve.maintenance import WindowsTree
                tree = WindowsTree("JarvisTool-" + uuid.uuid4().hex)
                kwargs["creationflags"] = 0x4 | subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
            else:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(list(argv), **kwargs)
            if tree is not None:
                tree.assign_resume(proc)
            drain = asyncio.create_task(asyncio.to_thread(proc.communicate))
            try:
                stdout, stderr = await asyncio.wait_for(asyncio.shield(drain), timeout)
            except asyncio.TimeoutError:
                self._kill(proc, tree)
                stdout, stderr = await asyncio.wait_for(asyncio.shield(drain), 10)
                return ToolResult(output={"stdout": stdout.decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace"),
                                          "exit_code": proc.returncode, "status": "timed_out"},
                                  error=f"Command timeout after {timeout}s; execution tree stopped", metadata={"error_code": "timeout"})
            output = {"stdout": stdout.decode("utf-8", "replace"), "stderr": stderr.decode("utf-8", "replace"),
                      "exit_code": proc.returncode, "status": "completed" if proc.returncode == 0 else "failed"}
            return ToolResult(output=output, error=None if proc.returncode == 0 else f"Command exited with code {proc.returncode}",
                              metadata={} if proc.returncode == 0 else {"error_code": "process_exit"})
        except asyncio.CancelledError:
            if proc is not None:
                self._kill(proc, tree)
            if drain is not None:
                await asyncio.wait_for(asyncio.shield(drain), 10)
            raise
        except (OSError, RuntimeError) as exc:
            return ToolResult(error=str(exc), metadata={"error_code": "unavailable"})
        finally:
            try:
                if proc is not None:
                    self._kill(proc, tree)
                    if proc.poll() is None:
                        await asyncio.to_thread(proc.wait, 10)
                if tree is not None:
                    for _ in range(100):
                        if tree.active() == 0:
                            break
                        await asyncio.sleep(.05)
                    else:
                        raise RuntimeError("Tool process-tree cleanup could not be confirmed")
            except BaseException:
                self.cleanup_failed = True
                CLEANUP_UNCONFIRMED = True
                raise
            finally:
                if tree is not None:
                    tree.close()

    @staticmethod
    def _kill(proc: subprocess.Popen, tree: object) -> None:
        if tree is not None:
            tree.kill()
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


if __name__ == "__main__":
    import sys
    print(asyncio.run(ProcessRunner().run([sys.executable, "-c", "print('supervised')"], cwd=str(JARVIS_ROOT))))

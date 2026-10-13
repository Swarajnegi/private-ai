"""Real process-tree fixtures; no models or production data. LAYER: Tools."""
from __future__ import annotations
import argparse
import asyncio
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "js-development"))
from jarvis_core.serve import maintenance as m


def alive(pid):
    if os.name == "nt":
        from ctypes import wintypes as w
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [w.DWORD,w.BOOL,w.DWORD]; k.OpenProcess.restype = w.HANDLE
        k.GetExitCodeProcess.argtypes = [w.HANDLE,ctypes.POINTER(w.DWORD)]
        k.CloseHandle.argtypes = [w.HANDLE]
        handle = k.OpenProcess(0x1000, False, pid)
        if not handle: return False
        code = w.DWORD()
        try: return bool(k.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value == 259
        finally: k.CloseHandle(handle)
    try: os.kill(pid,0); return True
    except ProcessLookupError: return False


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "js-development")})
        environment.start()
        self.addCleanup(environment.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = m.Runtime(self.root,probe=lambda:m.Resources(5*m.GIB,True))

    def command(self, body):
        path = self.root / "fixture.py"
        path.write_text(body,encoding="utf-8")
        return [sys.executable,str(path)]

    async def test_mutual_exclusion_and_inherited_lease(self):
        cmd = self.command("from pathlib import Path\nfrom jarvis_core.serve.maintenance import valid_lease\nprint(valid_lease(Path("+repr(str(self.root))+")))\n")
        with self.runtime.lease("fixture") as first:
            self.assertTrue(first)
            with m.Runtime(self.root).lease("second") as second:
                self.assertFalse(second)
            rc,out = await self.runtime.run(cmd,10)
            self.assertEqual((rc,out),(0,"True"))
        old = os.environ.get(m.LEASE_ENV)
        os.environ[m.LEASE_ENV] = "forged"
        try: self.assertFalse(m.valid_lease(self.root))
        finally:
            if old is None: os.environ.pop(m.LEASE_ENV,None)
            else: os.environ[m.LEASE_ENV]=old

    async def test_timeout_cleans_grandchild_and_keeps_all_output(self):
        pidfile = self.root / "child.pid"
        cmd = self.command("import subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\nPath("+repr(str(pidfile))+").write_text(str(p.pid))\nprint('START'+'x'*5000+'END',flush=True)\ntime.sleep(60)\n")
        with self.runtime.lease("fixture"):
            rc,out = await self.runtime.run(cmd,1)
            self.assertEqual(rc,124)
            self.assertIn("START"+"x"*5000+"END",out)
            self.assertFalse(alive(int(pidfile.read_text())))
            self.assertFalse(self.runtime.metrics.get("cleanup_unconfirmed"))

    async def test_cancellation_cleans_tree_and_retains_output(self):
        cmd = self.command("import time\nprint('cancellation evidence',flush=True)\ntime.sleep(60)\n")
        with self.runtime.lease("fixture"):
            task = asyncio.create_task(self.runtime.run(cmd,60))
            await asyncio.sleep(.4)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertIn("cancellation evidence",self.runtime.metrics["interrupted_output"])

    async def test_independent_manual_command_cannot_reuse_copied_token(self):
        holder=self.root/"holder.py"
        holder.write_text("import time\nfrom pathlib import Path\nfrom jarvis_core.serve.maintenance import Runtime\nr=Runtime(Path("+repr(str(self.root))+"))\nwith r.lease('scheduled-fixture'):\n print('READY',flush=True)\n time.sleep(60)\n",encoding="utf-8")
        proc=subprocess.Popen([sys.executable,str(holder)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if self.runtime.lease_path.exists(): break
                await asyncio.sleep(.02)
            lease=json.loads(self.runtime.lease_path.read_text(encoding="utf-8"))
            manual=self.root/"manual.py"
            manual.write_text("from jarvis_core.serve.maintenance import cli_entry\ncli_entry('index_episodes',__file__)\nprint('WORK EXECUTED')\n",encoding="utf-8")
            env={**os.environ,"JARVIS_ROOT":str(self.root),m.LEASE_ENV:lease['token']}
            result=await asyncio.to_thread(subprocess.run,[sys.executable,str(manual)],env=env,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,m.BUSY)
            self.assertIn(b"Maintenance busy",result.stdout)
            self.assertNotIn(b"WORK EXECUTED",result.stdout)
        finally:
            proc.kill();proc.communicate(timeout=5)

    async def test_supervisor_crash_and_restart(self):
        pidfile = self.root / "worker.pid"
        worker = self.root / "worker.py"
        worker.write_text("import os,time\nfrom pathlib import Path\nPath("+repr(str(pidfile))+").write_text(str(os.getpid()))\ntime.sleep(60)\n",encoding="utf-8")
        supervisor = self.command("import asyncio,sys\nfrom pathlib import Path\nfrom jarvis_core.serve.maintenance import Runtime\nr=Runtime(Path("+repr(str(self.root))+"))\nwith r.lease('crash-fixture'):\n asyncio.run(r.run([sys.executable,"+repr(str(worker))+"],60))\n")
        proc = subprocess.Popen(supervisor,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if pidfile.exists(): break
                await asyncio.sleep(.02)
            self.assertTrue(pidfile.exists())
            proc.kill(); proc.communicate(timeout=5)
            with m.Runtime(self.root).lease("after-crash") as acquired:
                self.assertTrue(acquired)
                self.assertFalse(alive(int(pidfile.read_text())))
        finally:
            if proc.poll() is None: proc.kill()
            proc.communicate(timeout=5)

    async def test_ram_monitor_aborts_without_real_memory_pressure(self):
        self.runtime.probe=lambda:m.Resources(m.GIB,True)
        cmd=self.command("import time\nprint('RAM interruption evidence',flush=True)\ntime.sleep(60)\n")
        with self.runtime.lease("ram-fixture"):
            rc,out=await self.runtime.run(cmd,30,heavy=True)
        self.assertEqual(rc,m.RESOURCE_ABORT)
        self.assertIn("RAM interruption evidence",out)
        self.assertLess(self.runtime.metrics["duration_s"],20)


def main():
    p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true");p.parse_args()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProcessTests))
    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__": raise SystemExit(main())

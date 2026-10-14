"""LAYER: Agent — measured current-host awareness without model loading.

THE BIG PICTURE: stored laptop facts are historical, not a runtime measurement.
THE FLOW: inspect native host -> read existing capabilities -> label unknowns.
"""
from __future__ import annotations
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import platform
import re
from pathlib import Path
import shutil
from typing import Callable, Optional

from jarvis_core.agent.execution import ProcessRunner, powershell_path
from jarvis_core.agent.tool import Tool, ToolInput, ToolResult
from jarvis_core.config import JARVIS_ROOT


def needs_inspection(question: str) -> bool:
    return bool(re.search(r"(?i)\b(hardware|specs|specifications|gpu|vram|cpu|ram|processor|graphics card|video card|this (?:pc|laptop|machine)|current (?:models?|runtime|host)|(?:which|what) (?:models?|voice|brain).{0,25}(?:using|use|running)|(?:ears|voice|brain) models?)\b", question))


@Tool.register("runtime_inspect")
class RuntimeInspectTool(Tool):
    name = "runtime_inspect"
    description = "Measure THIS machine and read current service/model/tool capabilities. Call before current hardware/runtime claims. Unknown fields are not historical facts or predicted benchmarks. Does not load models."
    input_schema = ToolInput

    def __init__(self, snapshot_provider: Optional[Callable] = None, tools: Optional[dict] = None) -> None:
        self.snapshot_provider = snapshot_provider
        self.tools = tools if tools is not None else {}
        self.brain_model = ""
        self.brain_state: Optional[Callable] = None
        self.unavailable_tools = {}

    @property
    def is_concurrency_safe(self) -> bool:
        return True

    async def invoke(self, tool_input: ToolInput) -> ToolResult:
        unknown = {}
        if self.snapshot_provider is not None:
            snapshot = deepcopy(self.snapshot_provider())
        else:
            snapshot = {"hostname": platform.node(), "os": platform.platform(), "hardware": None, "gpu": None,
                        "brain": {"location": "cloud API", "model": self.brain_model or os.environ.get("OPENROUTER_MODEL") or None}}
            if os.name == "nt":
                script = "$c=Get-CimInstance Win32_ComputerSystem; $p=Get-CimInstance Win32_Processor; @{manufacturer=$c.Manufacturer; model=$c.Model; ram_bytes=$c.TotalPhysicalMemory; cpu=$p.Name} | ConvertTo-Json -Compress"
                try:
                    r = await ProcessRunner().run([powershell_path(), "-NoProfile", "-NonInteractive", "-Command", script], cwd=str(JARVIS_ROOT), timeout=10)
                    if r.is_success:
                        snapshot["hardware"] = json.loads(r.output["stdout"])
                    else:
                        unknown["hardware"] = r.error
                except (OSError, ValueError) as exc:
                    unknown["hardware"] = str(exc)
            else:
                unknown["hardware"] = "Native Windows measurement is unavailable on this platform"
            gpu = shutil.which("nvidia-smi")
            if not gpu and os.name == "nt":
                candidates = [Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/nvidia-smi.exe",
                              Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "NVIDIA Corporation/NVSMI/nvidia-smi.exe"]
                gpu = next((str(path) for path in candidates if path.is_file()), None)
            if gpu:
                try:
                    r = await ProcessRunner().run([gpu, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], cwd=str(JARVIS_ROOT), timeout=5)
                    if r.is_success:
                        snapshot["gpu"] = [{"name": row.rsplit(",", 1)[0].strip(), "vram_mib": int(row.rsplit(",", 1)[1].strip())}
                                           for row in r.output["stdout"].splitlines() if "," in row]
                        if not snapshot["gpu"]:
                            unknown["gpu"] = "No GPU measurement was returned"
                    else:
                        unknown["gpu"] = r.error
                except (OSError, ValueError) as exc:
                    snapshot["gpu"] = None
                    unknown["gpu"] = "GPU measurement unavailable: " + str(exc)
            else:
                unknown["gpu"] = "nvidia-smi is unavailable; VRAM was not measured"
            try:
                from jarvis_core.serve.speech import ENGINE
                snapshot["voice"] = ENGINE.status()
            except (ImportError, AttributeError) as exc:
                snapshot["voice"] = None
                unknown["voice"] = str(exc)
        hardware = snapshot.get("hardware")
        if self.brain_state is not None:
            snapshot["brain"] = self.brain_state()
        if isinstance(hardware, dict) and isinstance(hardware.get("ram_bytes"), (int, float)):
            hardware["ram_gib"] = round(hardware["ram_bytes"] / 1024**3, 3)
        if isinstance(snapshot.get("gpu"), list):
            for item in snapshot["gpu"]:
                if isinstance(item.get("vram_mib"), (int, float)):
                    item["vram_gib"] = item["vram_mib"] / 1024
        store = getattr(self.tools.get("memory_semantic_search"), "_store", None)
        encoder = getattr(store, "_encoder", None)
        snapshot["local_embeddings"] = {"device": str(getattr(encoder, "device", "unknown")), "loaded": encoder is not None}
        snapshot["unavailable_tools"] = dict(self.unavailable_tools)
        snapshot["observed_at"] = datetime.now(timezone.utc).isoformat()
        snapshot["measurement_scope"] = "current host; no latency benchmark performed"
        snapshot.setdefault("unknown", unknown)
        snapshot["tools"] = [{"name": name, "requires_permission": bool(tool.requires_permission), "available": True, "backend": getattr(tool, "backend", None)}
                             for name, tool in sorted(self.tools.items())]
        return ToolResult(output=snapshot)


if __name__ == "__main__":
    print(asyncio.run(RuntimeInspectTool().invoke(ToolInput())))

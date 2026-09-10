"""
serve — the hearth: the one process that owns the clock.

LAYER: Brain (transport shell)

Everything in here is an ADAPTER. The mind lives in `agent/` and `brain/`; this
package only carries requests to it and events back. No reasoning, no state, no
second copy of any organ — per the Consciousness Portability Contract (KB L321),
a limb never grows its own brain.
"""

from jarvis_core.serve.hearth import Hearth, HearthConfig, build_app
from jarvis_core.serve.scheduler import Job, Scheduler

__all__ = ["Hearth", "HearthConfig", "build_app", "Job", "Scheduler"]

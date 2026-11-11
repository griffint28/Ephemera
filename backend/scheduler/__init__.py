"""Pure-Python schedulers and metrics.

No FastAPI, SQLAlchemy or `ephemera` imports belong here; a test enforces it. The package sits
beside `ephemera/` so that the boundary is structural.
"""

from scheduler.fcfs import FcfsScheduler
from scheduler.types import Scheduler

SCHEDULERS: dict[str, type[Scheduler]] = {FcfsScheduler.name: FcfsScheduler}


def get_scheduler(name: str) -> Scheduler:
    try:
        return SCHEDULERS[name.lower()]()
    except KeyError:
        raise KeyError(f"unknown scheduler {name!r}; choose from {', '.join(sorted(SCHEDULERS))}") from None

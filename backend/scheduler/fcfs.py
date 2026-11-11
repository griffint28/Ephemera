"""First come, first served: the baseline.

Passes are considered in rise order. A pass is used if, at its rise, its antenna is free and
its satellite is not already talking to another antenna. So when two passes overlap on one
antenna, the one that rises first wins, whatever either satellite is carrying.
"""

from collections.abc import Sequence
from datetime import datetime

from scheduler.types import Assignment, DataChunk, PassWindow, Scheduler, assignment_for


class FcfsScheduler(Scheduler):
    name = "fcfs"

    def schedule(self, passes: Sequence[PassWindow], demands: Sequence[DataChunk]) -> list[Assignment]:
        antenna_free_at: dict[str, datetime] = {}
        satellite_free_at: dict[str, datetime] = {}
        assignments = []
        for p in sorted(passes, key=lambda p: (p.rise, p.set, p.id)):
            if p.rise < antenna_free_at.get(p.station, p.rise):
                continue
            if p.rise < satellite_free_at.get(p.satellite, p.rise):
                continue
            assignments.append(assignment_for(p))
            antenna_free_at[p.station] = p.set
            satellite_free_at[p.satellite] = p.set
        return assignments

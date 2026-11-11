"""Translate database rows to the scheduler's dataclasses and back.

This is the only place that knows both vocabularies. The scheduler never sees an ORM object.
"""

from collections.abc import Iterable, Sequence

from scheduler.types import Assignment as SchedAssignment
from scheduler.types import DataChunk as SchedChunk
from scheduler.types import PassWindow

from ephemera import models


def pass_windows(passes: Iterable[models.Pass]) -> list[PassWindow]:
    """Capacity = duration x the satellite's (illustrative) downlink rate."""
    return [
        PassWindow(
            id=p.id,
            satellite=p.satellite.code,
            station=p.station.code,
            rise=p.rise_time,
            set=p.set_time,
            capacity_gb=p.duration_s / 60 * p.satellite.downlink_rate_gb_per_min,
        )
        for p in passes
    ]


def data_chunks(chunks: Iterable[models.DataChunk]) -> list[SchedChunk]:
    return [
        SchedChunk(id=c.id, satellite=c.satellite.code, created_at=c.created_at, size_gb=c.size_gb, urgent=c.urgent)
        for c in chunks
    ]


def assignments_from_rows(rows: Iterable[models.Assignment], windows: Sequence[PassWindow]) -> list[SchedAssignment]:
    by_id = {w.id: w for w in windows}
    out = []
    for row in rows:
        w = by_id[row.pass_id]
        out.append(SchedAssignment(pass_id=w.id, satellite=w.satellite, station=w.station, start=w.rise, end=w.set))
    return out


def assignment_rows(run: models.ScheduleRun, assignments: Iterable[SchedAssignment]) -> list[models.Assignment]:
    return [models.Assignment(schedule_run=run, pass_id=a.pass_id) for a in assignments]


def storage_capacities(satellites: Iterable[models.Satellite]) -> dict[str, float]:
    return {s.code: s.storage_capacity_gb for s in satellites}

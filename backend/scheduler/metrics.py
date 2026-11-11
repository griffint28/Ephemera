"""The four headline metrics, computed from an Execution. A report, not a fact: never stored."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from scheduler.execution import Execution
from scheduler.types import PassWindow


@dataclass(frozen=True)
class Metrics:
    scheduler: str
    window_hours: float

    total_downlinked_gb: float
    total_generated_gb: float

    # From an urgent chunk's creation to the arrival of its last byte, averaged over the urgent
    # chunks that were fully downlinked. Chunks never downlinked are counted, not averaged.
    urgent_delay_avg_s: float | None
    urgent_chunks: int
    urgent_downlinked: int

    # Time an antenna spent tracking, as a fraction of the window.
    antenna_utilization: float
    antenna_utilization_by_station: dict[str, float]

    stranded_gb: float  # onboard when the window closed
    stranded_gb_by_satellite: dict[str, float]
    dropped_gb: float  # lost because storage was full
    dropped_gb_by_satellite: dict[str, float]

    passes_available: int
    passes_used: int
    passes_used_by_station: dict[str, int] = field(default_factory=dict)


def compute_metrics(
    scheduler: str,
    passes: Sequence[PassWindow],
    execution: Execution,
    *,
    stations: Sequence[str],
    satellites: Sequence[str],
) -> Metrics:
    window_s = (execution.window_end - execution.window_start).total_seconds()

    tracking_s = {s: 0.0 for s in stations}
    used_by_station = {s: 0 for s in stations}
    for outcome in execution.passes.values():
        a = outcome.assignment
        tracking_s[a.station] = tracking_s.get(a.station, 0.0) + (a.end - a.start).total_seconds()
        used_by_station[a.station] = used_by_station.get(a.station, 0) + 1

    urgent = [c for c in execution.chunks.values() if c.chunk.urgent]
    delays = [c.delay.total_seconds() for c in urgent if c.delay is not None]

    stranded = {s: execution.stranded_gb(s) for s in satellites}
    dropped = {s: execution.dropped_gb(s) for s in satellites}

    return Metrics(
        scheduler=scheduler,
        window_hours=window_s / 3600,
        total_downlinked_gb=sum(p.downlinked_gb for p in execution.passes.values()),
        total_generated_gb=sum(c.chunk.size_gb for c in execution.chunks.values()),
        urgent_delay_avg_s=(sum(delays) / len(delays)) if delays else None,
        urgent_chunks=len(urgent),
        urgent_downlinked=len(delays),
        antenna_utilization=(sum(tracking_s.values()) / (window_s * len(stations))) if stations and window_s else 0.0,
        antenna_utilization_by_station={s: (t / window_s if window_s else 0.0) for s, t in tracking_s.items()},
        stranded_gb=sum(stranded.values()),
        stranded_gb_by_satellite=stranded,
        dropped_gb=sum(dropped.values()),
        dropped_gb_by_satellite=dropped,
        passes_available=len(passes),
        passes_used=len(execution.passes),
        passes_used_by_station=used_by_station,
    )

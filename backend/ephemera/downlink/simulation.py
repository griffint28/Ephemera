"""Seeded simulation of the data each satellite creates during the window.

ILLUSTRATIVE. Generation rates, storage capacities, downlink rates and urgent-event statistics
are made-up defaults, not spacecraft specifications. Every figure derived from them is labelled
"simulated workload" wherever it appears.

Pure: standard library only. The same seed and inputs always give the same chunks.

Model:
- Storage is empty at the window start.
- Routine data arrives as one chunk every `routine_chunk_minutes`, sized by the satellite's
  generation rate, created at the end of each interval. No chunk is created at or after the
  window end.
- Urgent data arrives as a Poisson process at `urgent_events_per_day`, each event one chunk of
  `urgent_chunk_gb`. Each satellite draws from its own generator seeded from (seed, code), so
  adding a satellite to the fleet does not change another's events.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_ROUTINE_CHUNK_MINUTES = 10
DEFAULT_URGENT_EVENTS_PER_DAY = 2.0
DEFAULT_URGENT_CHUNK_GB = 5.0


@dataclass(frozen=True)
class SatelliteWorkload:
    code: str
    generation_rate_gb_per_hour: float


@dataclass(frozen=True)
class SimulationParams:
    seed: int
    start: datetime
    end: datetime
    routine_chunk_minutes: float = DEFAULT_ROUTINE_CHUNK_MINUTES
    urgent_events_per_day: float = DEFAULT_URGENT_EVENTS_PER_DAY
    urgent_chunk_gb: float = DEFAULT_URGENT_CHUNK_GB

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.routine_chunk_minutes <= 0:
            raise ValueError("routine_chunk_minutes must be positive")
        if self.urgent_events_per_day < 0 or self.urgent_chunk_gb < 0:
            raise ValueError("urgent parameters must not be negative")


@dataclass(frozen=True)
class GeneratedChunk:
    satellite: str
    created_at: datetime
    size_gb: float
    urgent: bool


def simulate(workloads: Sequence[SatelliteWorkload], params: SimulationParams) -> list[GeneratedChunk]:
    """Every chunk created in [start, end), ordered by (created_at, satellite, urgent)."""
    chunks: list[GeneratedChunk] = []
    for w in workloads:
        chunks += _routine(w, params)
        chunks += _urgent(w, params)
    chunks.sort(key=lambda c: (c.created_at, c.satellite, c.urgent))
    return chunks


def _routine(w: SatelliteWorkload, p: SimulationParams) -> list[GeneratedChunk]:
    if w.generation_rate_gb_per_hour <= 0:
        return []
    interval = timedelta(minutes=p.routine_chunk_minutes)
    size = w.generation_rate_gb_per_hour * p.routine_chunk_minutes / 60
    out = []
    k = 1
    while (t := p.start + interval * k) < p.end:
        out.append(GeneratedChunk(w.code, t, size, urgent=False))
        k += 1
    return out


def _urgent(w: SatelliteWorkload, p: SimulationParams) -> list[GeneratedChunk]:
    if p.urgent_events_per_day <= 0 or p.urgent_chunk_gb <= 0:
        return []
    rng = random.Random(f"{p.seed}:{w.code}")
    rate_per_s = p.urgent_events_per_day / 86400
    out = []
    t = p.start
    while True:
        t += timedelta(seconds=rng.expovariate(rate_per_s))
        if t >= p.end:
            return out
        out.append(GeneratedChunk(w.code, t.replace(microsecond=0), p.urgent_chunk_gb, urgent=True))

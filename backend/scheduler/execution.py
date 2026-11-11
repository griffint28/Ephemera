"""Replay a schedule against the simulated data to find out what actually came down.

Rules, applied in time order:
- A chunk becomes available onboard at its creation time. If it does not fit in the storage
  capacity, the part that does not fit is dropped (lost) at creation.
- At an assigned pass, the satellite downlinks what it holds, urgent chunks first (oldest
  first), then routine chunks oldest first, until the pass capacity is used up. Chunks may be
  split across passes. A chunk's delay is measured from creation to the moment its last byte
  arrives, at the pass's constant rate.
- Only data created before the pass rises is eligible in that pass.
- Whatever is still onboard at the window end is stranded.

The same inputs always give the same result, so nothing here needs to be stored.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from scheduler.types import Assignment, DataChunk, PassWindow


@dataclass
class ChunkOutcome:
    chunk: DataChunk
    dropped_gb: float = 0.0  # lost at creation because storage was full
    downlinked_gb: float = 0.0
    completed_at: datetime | None = None  # when the last byte of it reached the ground

    @property
    def remaining_gb(self) -> float:
        return self.chunk.size_gb - self.dropped_gb - self.downlinked_gb

    @property
    def delay(self) -> timedelta | None:
        return None if self.completed_at is None else self.completed_at - self.chunk.created_at


@dataclass
class PassOutcome:
    assignment: Assignment
    capacity_gb: float
    downlinked_gb: float = 0.0
    chunk_ids: list[int] = field(default_factory=list)


@dataclass
class Execution:
    window_start: datetime
    window_end: datetime
    chunks: dict[int, ChunkOutcome]
    passes: dict[int, PassOutcome]  # by pass id, assigned passes only

    def stranded_gb(self, satellite: str) -> float:
        return sum(c.remaining_gb for c in self.chunks.values() if c.chunk.satellite == satellite)

    def dropped_gb(self, satellite: str) -> float:
        return sum(c.dropped_gb for c in self.chunks.values() if c.chunk.satellite == satellite)


def execute(
    passes: Sequence[PassWindow],
    chunks: Sequence[DataChunk],
    assignments: Sequence[Assignment],
    *,
    window_start: datetime,
    window_end: datetime,
    storage_capacity_gb: Mapping[str, float] | None = None,
) -> Execution:
    by_id = {p.id: p for p in passes}
    outcomes = {c.id: ChunkOutcome(c) for c in chunks}
    pass_outcomes: dict[int, PassOutcome] = {}
    onboard: dict[str, list[ChunkOutcome]] = {}
    capacity = storage_capacity_gb or {}

    # Chunk creations and pass starts, in time order; a creation at the same instant as a rise
    # comes first, so that chunk is eligible for the pass.
    events: list[tuple[datetime, int, object]] = [(c.created_at, 0, outcomes[c.id]) for c in chunks]
    for a in assignments:
        if a.pass_id not in by_id:
            raise ValueError(f"assignment refers to unknown pass {a.pass_id}")
        events.append((a.start, 1, a))
    events.sort(key=lambda e: (e[0], e[1]))

    for _, kind, item in events:
        if kind == 0:
            outcome = item  # type: ignore[assignment]
            assert isinstance(outcome, ChunkOutcome)
            held = onboard.setdefault(outcome.chunk.satellite, [])
            cap = capacity.get(outcome.chunk.satellite)
            if cap is not None:
                used = sum(c.remaining_gb for c in held)
                excess = used + outcome.chunk.size_gb - cap
                if excess > 0:
                    outcome.dropped_gb = min(excess, outcome.chunk.size_gb)
            if outcome.remaining_gb > 0:
                held.append(outcome)
        else:
            assignment = item
            assert isinstance(assignment, Assignment)
            window = by_id[assignment.pass_id]
            _downlink(window, assignment, onboard.get(assignment.satellite, []), pass_outcomes)

    return Execution(window_start=window_start, window_end=window_end, chunks=outcomes, passes=pass_outcomes)


def _downlink(
    window: PassWindow, assignment: Assignment, held: list[ChunkOutcome], pass_outcomes: dict[int, PassOutcome]
) -> None:
    result = PassOutcome(assignment=assignment, capacity_gb=window.capacity_gb)
    pass_outcomes[window.id] = result
    budget = window.capacity_gb
    if window.duration_s <= 0 or budget <= 0:
        return
    rate_gb_per_s = window.capacity_gb / window.duration_s
    clock = assignment.start
    # Urgent first (oldest first), then routine oldest first. Sort is stable; keep list order.
    held.sort(key=lambda c: (not c.chunk.urgent, c.chunk.created_at, c.chunk.id))
    for outcome in list(held):
        if budget <= 0:
            break
        take = min(outcome.remaining_gb, budget)
        outcome.downlinked_gb += take
        budget -= take
        clock += timedelta(seconds=take / rate_gb_per_s)
        result.downlinked_gb += take
        result.chunk_ids.append(outcome.chunk.id)
        if outcome.remaining_gb <= 1e-9:
            outcome.completed_at = clock
            held.remove(outcome)

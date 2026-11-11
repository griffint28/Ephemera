"""The scheduler's vocabulary. Plain dataclasses; no framework or `ephemera` imports.

Units: data in GB, time as timezone-aware datetimes. Satellites and stations are identified by
their short codes ("L8", "FAIR") so that a schedule reads like the page that will display it.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PassWindow:
    """One opportunity: a satellite visible from one antenna between rise and set."""

    id: int
    satellite: str
    station: str
    rise: datetime
    set: datetime
    capacity_gb: float  # duration x the satellite's downlink rate

    @property
    def duration_s(self) -> float:
        return (self.set - self.rise).total_seconds()

    def overlaps(self, other: "PassWindow") -> bool:
        """True if the two passes share any instant. Touching end to start is not overlap."""
        return self.rise < other.set and other.rise < self.set


@dataclass(frozen=True)
class DataChunk:
    """A piece of data created onboard a satellite at a given moment."""

    id: int
    satellite: str
    created_at: datetime
    size_gb: float
    urgent: bool


@dataclass(frozen=True)
class Assignment:
    """A pass the scheduler chose to use. The antenna tracks the satellite for the whole pass."""

    pass_id: int
    satellite: str
    station: str
    start: datetime
    end: datetime


class Scheduler(ABC):
    """The seam. FCFS and greedy implement it; an OR-Tools solver can drop in later.

    `passes` are every predicted opportunity in the window; `demands` are the data chunks the
    simulation created, with their creation times. The result is which passes to use. What each
    pass downlinks follows deterministically from `execution.execute`.
    """

    name: str

    @abstractmethod
    def schedule(self, passes: Sequence[PassWindow], demands: Sequence[DataChunk]) -> list[Assignment]: ...


def assignment_for(p: PassWindow) -> Assignment:
    return Assignment(pass_id=p.id, satellite=p.satellite, station=p.station, start=p.rise, end=p.set)

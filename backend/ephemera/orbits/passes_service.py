"""Compute passes from the cached element sets and store them; read them back.

Never talks to CelesTrak: it uses whatever element sets are already in the database.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from ephemera.models import OrbitalElements, Pass, Satellite, Station
from ephemera.orbits.pass_prediction import GroundSite, predict_passes

# SGP4 error grows with element age. Beyond this, warn that predictions may drift.
STALE_ELEMENTS_AGE = timedelta(days=3)


class DependentRunsError(RuntimeError):
    def __init__(self, run_ids: list[int]) -> None:
        self.run_ids = run_ids
        ids = ", ".join(str(i) for i in run_ids)
        super().__init__(
            f"schedule run(s) {ids} use passes in this window. Recomputing replaces those passes, so "
            "the runs would no longer describe anything. Re-run with --delete-dependent-runs to "
            "delete them (re-run the schedulers afterwards), or choose a different window."
        )


@dataclass
class ComputeResult:
    start: datetime
    end: datetime
    counts: dict[tuple[str, str], int] = field(default_factory=dict)  # (sat code, station code)
    replaced: int = 0
    deleted_schedule_runs: list[int] = field(default_factory=list)
    no_elements: list[str] = field(default_factory=list)
    stale_elements: list[tuple[str, datetime]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def latest_elements(session: Session, satellite: Satellite) -> OrbitalElements | None:
    return session.scalar(
        select(OrbitalElements)
        .where(OrbitalElements.satellite_id == satellite.id)
        .order_by(OrbitalElements.epoch.desc())
        .limit(1)
    )


def compute_passes(
    session: Session,
    satellites: Sequence[Satellite],
    stations: Sequence[Station],
    *,
    start: datetime,
    hours: float,
    now: datetime,
    delete_dependent_runs: bool = False,
) -> ComputeResult:
    """Predict and store passes rising in [start, start + hours).

    For each satellite and station, stored passes whose rise time falls in the window are
    replaced; passes outside it are left alone. Schedule runs that used those passes are
    deleted if `delete_dependent_runs` is set, otherwise the call refuses and changes nothing.
    """
    from ephemera.downlink.runs import schedule_runs_using_passes

    end = start + timedelta(hours=hours)
    result = ComputeResult(start=start, end=end)
    dependents = schedule_runs_using_passes(
        session, [s.id for s in satellites], [s.id for s in stations], start, end
    )
    if dependents and not delete_dependent_runs:
        raise DependentRunsError([r.id for r in dependents])
    for run in dependents:
        session.delete(run)
        result.deleted_schedule_runs.append(run.id)
    session.flush()
    for sat in satellites:
        elements = latest_elements(session, sat)
        if elements is None:
            result.no_elements.append(sat.code)
            continue
        if abs(start - elements.epoch) > STALE_ELEMENTS_AGE:
            result.stale_elements.append((sat.code, elements.epoch))
        record = json.loads(elements.omm_json)
        for station in stations:
            site = GroundSite(
                latitude_deg=station.latitude_deg,
                longitude_deg=station.longitude_deg,
                altitude_m=station.altitude_m,
                min_elevation_deg=station.min_elevation_deg,
            )
            predicted = predict_passes(record, site, start, end)
            result.replaced += session.execute(
                delete(Pass).where(
                    Pass.satellite_id == sat.id,
                    Pass.station_id == station.id,
                    Pass.rise_time >= start,
                    Pass.rise_time < end,
                )
            ).rowcount
            session.add_all(
                Pass(
                    satellite_id=sat.id,
                    station_id=station.id,
                    orbital_elements_id=elements.id,
                    rise_time=p.rise_time,
                    peak_time=p.peak_time,
                    set_time=p.set_time,
                    duration_s=p.duration_s,
                    peak_elevation_deg=p.peak_elevation_deg,
                    rise_azimuth_deg=p.rise_azimuth_deg,
                    peak_azimuth_deg=p.peak_azimuth_deg,
                    set_azimuth_deg=p.set_azimuth_deg,
                    min_elevation_deg=station.min_elevation_deg,
                    computed_at=now,
                )
                for p in predicted
            )
            result.counts[(sat.code, station.code)] = len(predicted)
    session.flush()
    return result


def list_passes(
    session: Session,
    *,
    satellite: Satellite | None = None,
    station: Station | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Sequence[Pass]:
    """Stored passes rising in [start, end), ordered by rise time."""
    query = select(Pass).options(joinedload(Pass.satellite), joinedload(Pass.station))
    if satellite is not None:
        query = query.where(Pass.satellite_id == satellite.id)
    if station is not None:
        query = query.where(Pass.station_id == station.id)
    if start is not None:
        query = query.where(Pass.rise_time >= start)
    if end is not None:
        query = query.where(Pass.rise_time < end)
    return session.scalars(query.order_by(Pass.rise_time, Pass.station_id)).all()

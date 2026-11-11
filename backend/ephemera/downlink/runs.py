"""Create simulation runs, run a scheduler over one, and load a stored run for reporting."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from scheduler import get_scheduler
from scheduler.execution import Execution, execute
from scheduler.metrics import Metrics, compute_metrics
from scheduler.types import Assignment as SchedAssignment
from scheduler.types import DataChunk as SchedChunk
from scheduler.types import PassWindow
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ephemera import models
from ephemera.downlink import adapters
from ephemera.downlink.simulation import SatelliteWorkload, SimulationParams, simulate
from ephemera.fleet import lookup
from ephemera.orbits.passes_service import list_passes


class RunError(RuntimeError):
    pass


def create_simulation(
    session: Session, satellites: Sequence[models.Satellite], params: SimulationParams, *, now: datetime
) -> models.SimulationRun:
    """Simulate the fleet's data over the window and store the run with its chunks."""
    workloads = [SatelliteWorkload(s.code, s.generation_rate_gb_per_hour) for s in satellites]
    by_code = {s.code: s for s in satellites}
    run = models.SimulationRun(
        seed=params.seed,
        window_start=params.start,
        window_end=params.end,
        routine_chunk_minutes=params.routine_chunk_minutes,
        urgent_events_per_day=params.urgent_events_per_day,
        urgent_chunk_gb=params.urgent_chunk_gb,
        created_at=now,
    )
    run.chunks = [
        models.DataChunk(satellite=by_code[c.satellite], created_at=c.created_at, size_gb=c.size_gb, urgent=c.urgent)
        for c in simulate(workloads, params)
    ]
    session.add(run)
    session.flush()
    return run


def get_simulation(session: Session, run_id: int) -> models.SimulationRun:
    run = session.get(models.SimulationRun, run_id)
    if run is None:
        raise RunError(f"no simulation run with id {run_id}")
    return run


def get_schedule_run(session: Session, run_id: int) -> models.ScheduleRun:
    run = session.get(models.ScheduleRun, run_id)
    if run is None:
        raise RunError(f"no schedule run with id {run_id}")
    return run


def run_scheduler(
    session: Session, simulation: models.SimulationRun, scheduler_name: str, *, now: datetime
) -> models.ScheduleRun:
    """Schedule the simulation's chunks over the passes stored for its window; store the result."""
    try:
        scheduler = get_scheduler(scheduler_name)
    except KeyError as exc:
        raise RunError(str(exc)) from None
    inputs = _inputs(session, simulation)
    if not inputs.passes:
        raise RunError(
            f"no stored passes rise between {simulation.window_start:%Y-%m-%d %H:%M} and "
            f"{simulation.window_end:%Y-%m-%d %H:%M} UTC; run compute-passes for that window first"
        )
    assignments = scheduler.schedule(inputs.passes, inputs.chunks)
    run = models.ScheduleRun(simulation_run=simulation, scheduler=scheduler.name, created_at=now)
    run.assignments = adapters.assignment_rows(run, assignments)
    session.add(run)
    session.flush()
    return run


@dataclass(frozen=True)
class RunInputs:
    passes: list[PassWindow]
    chunks: list[SchedChunk]
    stations: list[str]
    satellites: list[str]
    storage_capacity_gb: dict[str, float]


def _inputs(session: Session, simulation: models.SimulationRun) -> RunInputs:
    satellites = lookup.all_satellites(session)
    stations = lookup.all_stations(session)
    rows = list_passes(session, start=simulation.window_start, end=simulation.window_end)
    chunks = session.scalars(
        select(models.DataChunk)
        .where(models.DataChunk.simulation_run_id == simulation.id)
        .options(joinedload(models.DataChunk.satellite))
        .order_by(models.DataChunk.created_at, models.DataChunk.id)
    ).all()
    return RunInputs(
        passes=adapters.pass_windows(rows),
        chunks=adapters.data_chunks(chunks),
        stations=[s.code for s in stations],
        satellites=[s.code for s in satellites],
        storage_capacity_gb=adapters.storage_capacities(satellites),
    )


@dataclass(frozen=True)
class LoadedRun:
    run: models.ScheduleRun
    inputs: RunInputs
    assignments: list[SchedAssignment]
    execution: Execution
    metrics: Metrics


def load_run(session: Session, run: models.ScheduleRun) -> LoadedRun:
    """Replay a stored run and compute its metrics on demand."""
    simulation = run.simulation_run
    inputs = _inputs(session, simulation)
    assignments = adapters.assignments_from_rows(run.assignments, inputs.passes)
    execution = execute(
        inputs.passes,
        inputs.chunks,
        assignments,
        window_start=simulation.window_start,
        window_end=simulation.window_end,
        storage_capacity_gb=inputs.storage_capacity_gb,
    )
    metrics = compute_metrics(
        run.scheduler, inputs.passes, execution, stations=inputs.stations, satellites=inputs.satellites
    )
    return LoadedRun(run=run, inputs=inputs, assignments=assignments, execution=execution, metrics=metrics)


def schedule_runs_using_passes(
    session: Session, satellite_ids: Sequence[int], station_ids: Sequence[int], start: datetime, end: datetime
) -> list[models.ScheduleRun]:
    """Schedule runs with an assignment on a pass that a recompute of this window would replace."""
    query = (
        select(models.ScheduleRun)
        .join(models.Assignment)
        .join(models.Pass)
        .where(
            models.Pass.satellite_id.in_(satellite_ids),
            models.Pass.station_id.in_(station_ids),
            models.Pass.rise_time >= start,
            models.Pass.rise_time < end,
        )
        .distinct()
        .order_by(models.ScheduleRun.id)
    )
    return list(session.scalars(query).all())

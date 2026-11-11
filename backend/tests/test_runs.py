"""Simulation and schedule runs end to end on SQLite, with the synthetic element set."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from ephemera import models
from ephemera.downlink.runs import RunError, create_simulation, load_run, run_scheduler
from ephemera.downlink.simulation import SimulationParams
from ephemera.fleet import lookup
from ephemera.fleet.config_loader import load_fleet
from ephemera.fleet.seed import seed_fleet
from ephemera.orbits.celestrak_client import parse_epoch
from ephemera.orbits.passes_service import DependentRunsError, compute_passes
from tests.conftest import REPO_CONFIG, load_omm

OMM = load_omm("synthetic_sso_omm.json")
START = parse_epoch(OMM["EPOCH"]).replace(minute=0, second=0, microsecond=0)
HOURS = 48


@pytest.fixture
def world(session):
    """Seeded fleet, the synthetic element set on L8 and L9, passes for both over 48 h."""
    seed_fleet(session, load_fleet(REPO_CONFIG))
    sats = lookup.all_satellites(session)
    stations = lookup.all_stations(session)
    for code, ra in (("L8", 30.0), ("L9", 120.0)):  # a second plane, so the two fleets' passes differ
        sat = lookup.get_satellite(session, code)
        record = {**OMM, "NORAD_CAT_ID": sat.norad_id, "RA_OF_ASC_NODE": ra}
        session.add(
            models.OrbitalElements(
                satellite=sat, epoch=parse_epoch(OMM["EPOCH"]), fetched_at=START, source="test", omm_json=json.dumps(record)
            )
        )
    session.commit()
    compute_passes(session, sats, stations, start=START, hours=HOURS, now=START)
    session.commit()
    return sats, stations


def _params(seed=1):
    return SimulationParams(seed=seed, start=START, end=START + timedelta(hours=HOURS))


def test_simulation_is_stored_and_reproducible(session, world):
    sats, _ = world
    a = create_simulation(session, sats, _params(seed=5), now=START)
    b = create_simulation(session, sats, _params(seed=5), now=START)
    key = lambda c: (c.satellite.code, c.created_at, c.size_gb, c.urgent)  # noqa: E731
    assert sorted(map(key, a.chunks)) == sorted(map(key, b.chunks))
    assert len(a.chunks) == session.scalar(
        select(func.count()).select_from(models.DataChunk).where(models.DataChunk.simulation_run_id == a.id)
    )
    assert any(c.urgent for c in a.chunks)


def test_fcfs_run_is_stored_and_identical_on_rerun(session, world):
    sats, stations = world
    sim = create_simulation(session, sats, _params(), now=START)
    first = run_scheduler(session, sim, "fcfs", now=START)
    second = run_scheduler(session, sim, "fcfs", now=START)
    assert sorted(a.pass_id for a in first.assignments) == sorted(a.pass_id for a in second.assignments)
    assert first.assignments

    loaded = load_run(session, first)
    m = loaded.metrics
    assert m.scheduler == "fcfs" and m.window_hours == HOURS
    assert m.passes_used <= m.passes_available
    assert 0 < m.total_downlinked_gb <= m.total_generated_gb
    assert m.total_downlinked_gb + m.stranded_gb + m.dropped_gb == pytest.approx(m.total_generated_gb)
    assert set(m.stranded_gb_by_satellite) == {s.code for s in sats}
    # A satellite without passes fills its recorder: it strands exactly the cap and drops the rest.
    npp_generated = sum(c.size_gb for c in loaded.inputs.chunks if c.satellite == "NPP")
    assert m.stranded_gb_by_satellite["NPP"] == 150.0
    assert m.dropped_gb_by_satellite["NPP"] == pytest.approx(npp_generated - 150.0)
    assert m.dropped_gb_by_satellite["NPP"] > 0
    assert 0 < m.antenna_utilization < 1


def test_no_antenna_double_booked_in_the_stored_run(session, world):
    sats, _ = world
    sim = create_simulation(session, sats, _params(), now=START)
    run = run_scheduler(session, sim, "fcfs", now=START)
    loaded = load_run(session, run)
    used = sorted(loaded.assignments, key=lambda a: a.start)
    for station in {a.station for a in used}:
        rows = [a for a in used if a.station == station]
        assert all(prev.end <= nxt.start for prev, nxt in zip(rows, rows[1:], strict=False))
    for sat in {a.satellite for a in used}:
        rows = [a for a in used if a.satellite == sat]
        assert all(prev.end <= nxt.start for prev, nxt in zip(rows, rows[1:], strict=False))


def test_run_without_passes_is_an_error(session, world):
    sats, _ = world
    far = SimulationParams(seed=1, start=START + timedelta(days=30), end=START + timedelta(days=31))
    sim = create_simulation(session, sats, far, now=START)
    with pytest.raises(RunError, match="no stored passes"):
        run_scheduler(session, sim, "fcfs", now=START)
    with pytest.raises(RunError, match="unknown scheduler"):
        run_scheduler(session, create_simulation(session, sats, _params(), now=START), "nope", now=START)


def test_recompute_refuses_then_deletes_dependent_runs(session, world):
    sats, stations = world
    sim = create_simulation(session, sats, _params(), now=START)
    run = run_scheduler(session, sim, "fcfs", now=START)
    session.commit()
    run_id = run.id

    with pytest.raises(DependentRunsError) as info:
        compute_passes(session, sats, stations, start=START, hours=HOURS, now=START)
    assert info.value.run_ids == [run_id]
    session.rollback()
    assert session.get(models.ScheduleRun, run_id) is not None

    # A disjoint window touches no run.
    result = compute_passes(session, sats, stations, start=START + timedelta(hours=HOURS), hours=1, now=START)
    assert result.deleted_schedule_runs == []

    result = compute_passes(session, sats, stations, start=START, hours=HOURS, now=START, delete_dependent_runs=True)
    assert result.deleted_schedule_runs == [run_id]
    session.commit()
    assert session.get(models.ScheduleRun, run_id) is None
    assert session.scalar(select(func.count()).select_from(models.Assignment)) == 0
    assert session.get(models.SimulationRun, sim.id) is not None  # the simulation itself is kept

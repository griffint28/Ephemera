import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from ephemera.fleet.config_loader import load_fleet
from ephemera.fleet.seed import seed_fleet
from ephemera.models import OrbitalElements, Pass, Satellite, Station
from ephemera.orbits.celestrak_client import parse_epoch
from ephemera.orbits.passes_service import compute_passes, list_passes
from tests.conftest import REPO_CONFIG, load_omm

OMM = load_omm("synthetic_sso_omm.json")
START = parse_epoch(OMM["EPOCH"]).replace(minute=0, second=0, microsecond=0)


@pytest.fixture
def fleet(session):
    seed_fleet(session, load_fleet(REPO_CONFIG))
    l8 = session.scalar(select(Satellite).where(Satellite.code == "L8"))
    session.add(
        OrbitalElements(
            satellite=l8, epoch=parse_epoch(OMM["EPOCH"]), fetched_at=START, source="test", omm_json=json.dumps(OMM)
        )
    )
    session.commit()
    return l8, session.scalars(select(Station)).all()


def test_compute_stores_passes_and_reports_missing_elements(session, fleet):
    l8, stations = fleet
    others = session.scalars(select(Satellite).where(Satellite.code != "L8")).all()
    result = compute_passes(session, [l8, *others], stations, start=START, hours=48, now=START)
    assert sorted(result.no_elements) == sorted(s.code for s in others)
    stored = session.scalars(select(Pass)).all()
    assert len(stored) == result.total > 0
    # Svalbard, at 78 N, sees a sun-synchronous satellite far more often than Wallops.
    assert result.counts[("L8", "SVAL")] > result.counts[("L8", "WALL")]
    assert all(START <= p.rise_time < START + timedelta(hours=48) for p in stored)
    assert all(p.min_elevation_deg == 10 for p in stored)


def test_recompute_replaces_only_the_window(session, fleet):
    l8, stations = fleet
    compute_passes(session, [l8], stations, start=START, hours=48, now=START)
    before = {(p.station_id, p.rise_time) for p in session.scalars(select(Pass))}

    # Recompute the second day only.
    result = compute_passes(session, [l8], stations, start=START + timedelta(hours=24), hours=24, now=START)
    after = {(p.station_id, p.rise_time) for p in session.scalars(select(Pass))}
    assert result.replaced == result.total
    assert after == before  # same elements, same passes, no duplicates


def test_list_passes_filters(session, fleet):
    l8, stations = fleet
    compute_passes(session, [l8], stations, start=START, hours=24, now=START)
    fair = next(s for s in stations if s.code == "FAIR")
    rows = list_passes(session, satellite=l8, station=fair, start=START, end=START + timedelta(hours=12))
    assert rows and all(p.station.code == "FAIR" for p in rows)
    assert [p.rise_time for p in rows] == sorted(p.rise_time for p in rows)
    assert all(p.rise_time < START + timedelta(hours=12) for p in rows)

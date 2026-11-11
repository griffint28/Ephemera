from dataclasses import replace

from sqlalchemy import func, select

from ephemera.fleet.config_loader import load_fleet
from ephemera.fleet.seed import seed_fleet
from ephemera.models import Satellite, Station
from tests.conftest import REPO_CONFIG


def test_seed_is_idempotent(session):
    fleet = load_fleet(REPO_CONFIG)
    first = seed_fleet(session, fleet)
    assert len(first.created) == 10
    second = seed_fleet(session, fleet)
    assert second.created == [] and second.updated == [] and len(second.unchanged) == 10
    assert session.scalar(select(func.count()).select_from(Satellite)) == 7
    assert session.scalar(select(func.count()).select_from(Station)) == 3


def test_seed_updates_changed_rows_and_keeps_removed_ones(session):
    fleet = load_fleet(REPO_CONFIG)
    seed_fleet(session, fleet)
    stations = (replace(fleet.stations[0], min_elevation_deg=5.0), *fleet.stations[1:])
    changed = replace(fleet, satellites=fleet.satellites[1:], stations=stations)
    result = seed_fleet(session, changed)
    assert result.updated == ["station SVAL"]
    assert result.not_in_config == ["satellite L8 (39084)"]
    assert session.scalar(select(Station.min_elevation_deg).where(Station.code == "SVAL")) == 5.0
    assert session.scalar(select(func.count()).select_from(Satellite)) == 7

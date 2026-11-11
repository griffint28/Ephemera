from datetime import timedelta

import pytest

from ephemera.downlink.simulation import SatelliteWorkload, SimulationParams, simulate
from tests.conftest import utc

START = utc(2026, 11, 12, 0)
FLEET = [SatelliteWorkload("L8", 3.0), SatelliteWorkload("NPP", 6.0)]


def params(seed=1, hours=48, **kw):
    return SimulationParams(seed=seed, start=START, end=START + timedelta(hours=hours), **kw)


def test_same_seed_same_output():
    assert simulate(FLEET, params(seed=42)) == simulate(FLEET, params(seed=42))


def test_different_seed_moves_the_urgent_events_only():
    a, b = simulate(FLEET, params(seed=1)), simulate(FLEET, params(seed=2))
    assert [c for c in a if not c.urgent] == [c for c in b if not c.urgent]
    assert [c for c in a if c.urgent] != [c for c in b if c.urgent]


def test_adding_a_satellite_does_not_change_the_others():
    before = simulate(FLEET, params())
    after = simulate([*FLEET, SatelliteWorkload("L9", 3.0)], params())
    assert [c for c in after if c.satellite != "L9"] == before


def test_routine_chunks_cover_the_window_at_the_generation_rate():
    chunks = [c for c in simulate(FLEET, params(hours=48)) if not c.urgent]
    l8 = [c for c in chunks if c.satellite == "L8"]
    assert len(l8) == 48 * 6 - 1  # one per 10 min, none at or after the window end
    assert all(c.size_gb == pytest.approx(0.5) for c in l8)
    assert l8[0].created_at == START + timedelta(minutes=10)
    assert l8[-1].created_at == START + timedelta(hours=48) - timedelta(minutes=10)
    assert sum(c.size_gb for c in chunks if c.satellite == "NPP") == pytest.approx(6.0 * 48 - 1.0)


def test_urgent_events_have_a_plausible_count_and_sit_inside_the_window():
    p = params(hours=48, urgent_events_per_day=2.0, urgent_chunk_gb=5.0)
    urgent = [c for c in simulate(FLEET, p) if c.urgent]
    assert all(p.start < c.created_at < p.end for c in urgent)
    assert all(c.size_gb == 5.0 for c in urgent)
    # Expected 2/day x 2 days x 2 satellites = 8. Poisson; allow a wide band.
    assert 1 <= len(urgent) <= 20


def test_zero_urgent_rate_gives_no_urgent_chunks():
    assert not [c for c in simulate(FLEET, params(urgent_events_per_day=0)) if c.urgent]


def test_output_is_sorted_by_creation_time():
    chunks = simulate(FLEET, params())
    assert [c.created_at for c in chunks] == sorted(c.created_at for c in chunks)


def test_bad_params_rejected():
    with pytest.raises(ValueError):
        SimulationParams(seed=1, start=START, end=START)
    with pytest.raises(ValueError):
        params(routine_chunk_minutes=0)

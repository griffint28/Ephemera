"""Elevation mask and window boundaries.

Uses a synthetic 705 km sun-synchronous element set (tests/fixtures/synthetic_sso_omm.json;
see the fixtures README) and the Fairbanks station, with windows anchored to the element epoch.
"""

from datetime import datetime, timedelta

import pytest
from skyfield.api import load, wgs84

from ephemera.orbits.celestrak_client import parse_epoch
from ephemera.orbits.pass_prediction import (
    ElementsError,
    GroundSite,
    PredictedPass,
    build_satellite,
    predict_passes,
)
from tests.conftest import load_omm

OMM = load_omm("synthetic_sso_omm.json")
EPOCH = parse_epoch(OMM["EPOCH"]).replace(minute=0, second=0, microsecond=0)
FAIR = GroundSite(latitude_deg=64.9780, longitude_deg=-147.4990, altitude_m=319, min_elevation_deg=10)
DAY = (EPOCH, EPOCH + timedelta(hours=24))

ts = load.timescale()
SAT = build_satellite(OMM)
TOPOS = wgs84.latlon(FAIR.latitude_deg, FAIR.longitude_deg, elevation_m=FAIR.altitude_m)


def elevation(t: datetime) -> float:
    alt, _, _ = (SAT - TOPOS).at(ts.from_datetime(t)).altaz()
    return float(alt.degrees)


@pytest.fixture(scope="module")
def day_passes() -> list[PredictedPass]:
    passes = predict_passes(OMM, FAIR, *DAY)
    assert len(passes) >= 4, "Landsat 8 should pass Fairbanks several times a day"
    return passes


# --- elevation mask ------------------------------------------------------------------------


def test_rise_and_set_are_at_the_mask(day_passes):
    for p in day_passes:
        assert elevation(p.rise_time) == pytest.approx(10, abs=0.05)
        assert elevation(p.set_time) == pytest.approx(10, abs=0.05)


def test_satellite_is_above_mask_throughout_and_below_just_outside(day_passes):
    for p in day_passes:
        steps = 20
        for i in range(1, steps):
            assert elevation(p.rise_time + (p.set_time - p.rise_time) * i / steps) > 10
        assert elevation(p.rise_time - timedelta(seconds=30)) < 10
        assert elevation(p.set_time + timedelta(seconds=30)) < 10


def test_peak_is_the_highest_point(day_passes):
    for p in day_passes:
        assert p.rise_time < p.peak_time < p.set_time
        assert p.peak_elevation_deg >= 10
        assert elevation(p.peak_time) == pytest.approx(p.peak_elevation_deg, abs=0.01)  # time rounded to 1 s
        for offset in (-60, 60):
            assert elevation(p.peak_time + timedelta(seconds=offset)) < p.peak_elevation_deg


def test_azimuths_are_compass_degrees(day_passes):
    for p in day_passes:
        for az in (p.rise_azimuth_deg, p.peak_azimuth_deg, p.set_azimuth_deg):
            assert 0 <= az < 360


def test_durations_are_plausible_for_leo(day_passes):
    for p in day_passes:
        assert p.duration_s == (p.set_time - p.rise_time).total_seconds()
        assert 0 < p.duration_s < 16 * 60


def test_higher_mask_gives_shorter_passes_nested_in_lower_mask_passes(day_passes):
    high = predict_passes(OMM, GroundSite(**{**FAIR.__dict__, "min_elevation_deg": 30}), *DAY)
    assert len(high) < len(day_passes)
    for h in high:
        [outer] = [p for p in day_passes if p.rise_time < h.rise_time and h.set_time < p.set_time]
        assert h.peak_elevation_deg == pytest.approx(outer.peak_elevation_deg, abs=0.01)
        assert h.duration_s < outer.duration_s


def test_zero_mask_gives_more_passes_than_ten(day_passes):
    zero = predict_passes(OMM, GroundSite(**{**FAIR.__dict__, "min_elevation_deg": 0}), *DAY)
    assert len(zero) >= len(day_passes)


# --- window boundaries ([start, end) by rise time) ---------------------------------------


def test_every_pass_rises_inside_the_window(day_passes):
    assert all(DAY[0] <= p.rise_time < DAY[1] for p in day_passes)
    assert [p.rise_time for p in day_passes] == sorted(p.rise_time for p in day_passes)


def test_pass_in_progress_at_window_start_is_excluded(day_passes):
    target = day_passes[1]
    start = target.rise_time + timedelta(minutes=1)
    passes = predict_passes(OMM, FAIR, start, start + timedelta(hours=6))
    assert target.rise_time not in {p.rise_time for p in passes}
    assert all(p.rise_time >= start for p in passes)


def test_pass_rising_exactly_at_window_start_is_included(day_passes):
    target = day_passes[1]
    passes = predict_passes(OMM, FAIR, target.rise_time, target.rise_time + timedelta(hours=1))
    assert passes and passes[0].rise_time == pytest.approx(target.rise_time, abs=timedelta(seconds=1))


def test_last_pass_may_set_after_window_end(day_passes):
    target = day_passes[1]
    end = target.rise_time + timedelta(seconds=10)
    passes = predict_passes(OMM, FAIR, end - timedelta(hours=3), end)
    last = passes[-1]
    assert last.rise_time == pytest.approx(target.rise_time, abs=timedelta(seconds=1))
    assert last.set_time > end
    assert last.set_time == pytest.approx(target.set_time, abs=timedelta(seconds=1))


def test_pass_rising_at_window_end_is_excluded(day_passes):
    target = day_passes[1]
    passes = predict_passes(OMM, FAIR, target.rise_time - timedelta(hours=3), target.rise_time - timedelta(seconds=1))
    assert all(p.rise_time < target.rise_time - timedelta(seconds=1) for p in passes)
    assert target.rise_time not in {p.rise_time for p in passes}


def test_adjacent_windows_partition_the_passes(day_passes):
    middle = EPOCH + timedelta(hours=11, minutes=17)
    first = predict_passes(OMM, FAIR, DAY[0], middle)
    second = predict_passes(OMM, FAIR, middle, DAY[1])
    joined = [p.rise_time for p in first + second]
    assert len(joined) == len(day_passes)
    for a, b in zip(joined, (p.rise_time for p in day_passes), strict=True):
        assert a == pytest.approx(b, abs=timedelta(seconds=1))


# --- inputs ----------------------------------------------------------------------------------


def test_naive_or_reversed_window_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        predict_passes(OMM, FAIR, datetime(2026, 1, 1), DAY[1])
    with pytest.raises(ValueError, match="after start"):
        predict_passes(OMM, FAIR, DAY[1], DAY[0])


def test_bad_elements_rejected():
    with pytest.raises(ElementsError):
        predict_passes({**OMM, "ECCENTRICITY": "nope"}, FAIR, *DAY)

from pathlib import Path

import pytest

from ephemera.fleet.config_loader import ConfigError, load_fleet, load_satellites, load_stations
from tests.conftest import REPO_CONFIG


def test_repo_config_loads():
    fleet = load_fleet(REPO_CONFIG)
    assert [s.code for s in fleet.satellites] == ["L8", "L9", "2A", "2B", "N20", "N21", "NPP"]
    assert {s.norad_id for s in fleet.satellites} == {39084, 49260, 40697, 42063, 43013, 54234, 37849}
    assert [s.code for s in fleet.stations] == ["SVAL", "FAIR", "WALL"]
    assert all(s.min_elevation_deg == 10 for s in fleet.stations)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


SAT = "  - {code: L8, name: Landsat 8, norad_id: 39084, operator: USGS}\n"
STATION = (
    "  - {code: FAIR, name: Fairbanks, operator: NOAA, latitude_deg: 64.978,"
    " longitude_deg: -147.499, altitude_m: 319, min_elevation_deg: 10, timezone: America/Anchorage}\n"
)


def test_duplicate_norad_id_rejected(tmp_path):
    path = _write(tmp_path, "s.yaml", "satellites:\n" + SAT + SAT.replace("L8", "X1"))
    with pytest.raises(ConfigError, match="duplicate norad_id"):
        load_satellites(path)


def test_duplicate_code_rejected(tmp_path):
    path = _write(tmp_path, "s.yaml", "satellites:\n" + SAT + SAT.replace("39084", "1"))
    with pytest.raises(ConfigError, match="duplicate code"):
        load_satellites(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("latitude_deg: 64.978", "latitude_deg: 95", "latitude_deg"),
        ("longitude_deg: -147.499", "longitude_deg: -181", "longitude_deg"),
        ("min_elevation_deg: 10", "min_elevation_deg: 90", "min_elevation_deg"),
        ("timezone: America/Anchorage", "timezone: Mars/Olympus", "unknown timezone"),
        ("altitude_m: 319", "altitude_m: high", "must be a number"),
        ("operator: NOAA, ", "", "missing 'operator'"),
    ],
)
def test_bad_station_values_rejected(tmp_path, old, new, message):
    assert old in STATION
    path = _write(tmp_path, "g.yaml", "stations:\n" + STATION.replace(old, new))
    with pytest.raises(ConfigError, match=message):
        load_stations(path)


def test_empty_or_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_satellites(tmp_path / "nope.yaml")
    with pytest.raises(ConfigError, match="non-empty"):
        load_satellites(_write(tmp_path, "e.yaml", "satellites: []\n"))

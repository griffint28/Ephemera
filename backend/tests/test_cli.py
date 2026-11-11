import json

import pytest
from typer.testing import CliRunner

from ephemera import cli
from ephemera.orbits.celestrak_client import parse_epoch
from tests.conftest import load_omm

OMM = load_omm("synthetic_sso_omm.json")
runner = CliRunner()


@pytest.fixture(autouse=True)
def _env(db_env, engine):  # type: ignore[no-untyped-def]
    yield


def run(*args: str):
    result = runner.invoke(cli.app, list(args))
    return result


def test_end_to_end_with_a_stubbed_fetch(monkeypatch):
    from ephemera.orbits import celestrak_client

    assert run("seed-fleet").exit_code == 0

    epoch = parse_epoch(OMM["EPOCH"])
    monkeypatch.setattr(cli, "_now", lambda: epoch)

    def fake_fetch(norad_id):
        if norad_id == 39084:
            return OMM
        raise celestrak_client.CelestrakError("HTTP 503")

    monkeypatch.setattr(celestrak_client, "fetch_gp", fake_fetch)
    fetched = run("fetch-orbital-data")
    assert fetched.exit_code == 1  # six satellites "failed"
    assert "L8" in fetched.output and "new" in fetched.output

    again = run("fetch-orbital-data", "--satellite", "L8", "--force")
    assert again.exit_code == 0 and "too-soon" in again.output

    start = epoch.replace(minute=0, second=0, microsecond=0).isoformat()
    computed = run("compute-passes", "--start", start, "--hours", "24", "--satellite", "39084")
    assert computed.exit_code == 0, computed.output
    assert "passes stored" in computed.output

    shown = run("show-passes", "--satellite", "L8", "--station", "fair", "--start", start, "--hours", "24")
    assert shown.exit_code == 0, shown.output
    assert "FAIR" in shown.output and "39084" in shown.output


def test_unknown_station_is_an_error():
    run("seed-fleet")
    result = run("show-passes", "--station", "NOPE")
    assert result.exit_code == 1
    assert "no station" in result.output


def test_compute_without_seed_is_an_error():
    result = run("compute-passes")
    assert result.exit_code == 1

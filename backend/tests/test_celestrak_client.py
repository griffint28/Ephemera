import json
from datetime import timedelta
from io import BytesIO
from urllib.error import HTTPError

import pytest
from sqlalchemy import select

from ephemera.models import OrbitalElements, Satellite
from ephemera.orbits.celestrak_client import (
    CelestrakError,
    fetch_gp,
    parse_gp_response,
    refresh_orbital_elements,
)
from tests.conftest import WORKLOAD, load_omm, utc

NOW = utc(2026, 11, 11, 12)


@pytest.fixture
def omm():
    return load_omm("synthetic_sso_omm.json")


@pytest.fixture
def sat(session):
    s = Satellite(norad_id=39084, code="L8", name="Landsat 8", operator="USGS / NASA", **WORKLOAD)
    session.add(s)
    session.commit()
    return s


class FakeFetch:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def __call__(self, norad_id):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _refresh(session, sat, fetch, now=NOW, force=False, hours=12):
    [outcome] = refresh_orbital_elements(session, [sat], now=now, refresh_hours=hours, force=force, fetch=fetch)
    return outcome


def _snapshots(session):
    return session.scalars(select(OrbitalElements)).all()


def test_first_fetch_stores_element_set(session, sat, omm):
    outcome = _refresh(session, sat, FakeFetch(omm))
    assert outcome.status == "new"
    [snap] = _snapshots(session)
    assert json.loads(snap.omm_json) == omm
    assert snap.fetched_at == NOW
    assert sat.last_fetch_success_at == NOW == sat.last_fetch_attempt_at


def test_within_refresh_interval_uses_cache(session, sat, omm):
    _refresh(session, sat, FakeFetch(omm))
    fetch = FakeFetch()
    outcome = _refresh(session, sat, fetch, now=NOW + timedelta(hours=11, minutes=59))
    assert outcome.status == "cached" and fetch.calls == 0


def test_after_refresh_interval_fetches_again(session, sat, omm):
    _refresh(session, sat, FakeFetch(omm))
    newer = {**omm, "EPOCH": "2099-01-01T00:00:00.000000"}
    outcome = _refresh(session, sat, FakeFetch(newer), now=NOW + timedelta(hours=12))
    assert outcome.status == "new"
    assert len(_snapshots(session)) == 2


def test_same_epoch_is_not_duplicated(session, sat, omm):
    _refresh(session, sat, FakeFetch(omm))
    outcome = _refresh(session, sat, FakeFetch(omm), now=NOW + timedelta(hours=13))
    assert outcome.status == "unchanged"
    assert len(_snapshots(session)) == 1
    assert sat.last_fetch_success_at == NOW + timedelta(hours=13)


def test_force_bypasses_refresh_interval_but_not_two_hour_floor(session, sat, omm):
    _refresh(session, sat, FakeFetch(omm))
    fetch = FakeFetch(omm)
    assert _refresh(session, sat, fetch, now=NOW + timedelta(minutes=119), force=True).status == "too-soon"
    assert fetch.calls == 0
    assert _refresh(session, sat, fetch, now=NOW + timedelta(hours=2), force=True).status == "unchanged"
    assert fetch.calls == 1


def test_failed_fetch_keeps_cache_and_counts_toward_floor(session, sat, omm):
    _refresh(session, sat, FakeFetch(omm))
    later = NOW + timedelta(hours=12)
    outcome = _refresh(session, sat, FakeFetch(CelestrakError("HTTP 503")), now=later)
    assert outcome.status == "failed"
    [snap] = _snapshots(session)
    assert json.loads(snap.omm_json) == omm
    assert sat.last_fetch_success_at == NOW and sat.last_fetch_attempt_at == later
    # The failed attempt still starts the 2 h floor, even with --force.
    fetch = FakeFetch(omm)
    assert _refresh(session, sat, fetch, now=later + timedelta(hours=1), force=True).status == "too-soon"
    assert fetch.calls == 0


def test_refresh_interval_below_floor_rejected(session, sat):
    with pytest.raises(ValueError):
        refresh_orbital_elements(session, [sat], now=NOW, refresh_hours=1, fetch=FakeFetch())


# --- response parsing ---------------------------------------------------------------------


def test_parse_accepts_real_record(omm):
    assert parse_gp_response(39084, json.dumps([omm]).encode()) == omm


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"No GP data found", "no element set"),
        (b"[]", "no element set"),
        (b'{"a": 1}', "no element set"),
    ],
)
def test_parse_rejects_empty_or_text_answers(body, message):
    with pytest.raises(CelestrakError, match=message):
        parse_gp_response(39084, body)


def test_parse_rejects_wrong_satellite(omm):
    with pytest.raises(CelestrakError, match="expected one"):
        parse_gp_response(12345, json.dumps([omm]).encode())


def test_parse_rejects_unusable_elements(omm):
    broken = {**omm, "MEAN_MOTION": "not-a-number"}
    with pytest.raises(CelestrakError, match="unusable"):
        parse_gp_response(39084, json.dumps([broken]).encode())


def test_fetch_builds_catalog_number_url(omm):
    seen = {}

    class Response(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout):
        seen["url"] = request.full_url
        return Response(json.dumps([omm]).encode())

    assert fetch_gp(39084, opener=opener) == omm
    assert seen["url"] == "https://celestrak.org/NORAD/elements/gp.php?CATNR=39084&FORMAT=json"


def test_fetch_wraps_http_errors():
    def opener(request, timeout):
        raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

    with pytest.raises(CelestrakError, match="HTTP 403"):
        fetch_gp(39084, opener=opener)

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError

from ephemera.models import NaiveDatetimeError, Satellite
from tests.conftest import utc


def test_naive_datetime_rejected(session):
    session.add(Satellite(norad_id=1, code="X", name="X", operator="X", last_fetch_attempt_at=datetime(2026, 1, 1)))
    with pytest.raises(StatementError) as info:
        session.flush()
    assert isinstance(info.value.orig, NaiveDatetimeError)


def test_aware_datetime_stored_as_utc_and_returned_aware(session):
    plus_two = timezone(timedelta(hours=2))
    session.add(
        Satellite(norad_id=1, code="X", name="X", operator="X", last_fetch_attempt_at=datetime(2026, 1, 1, 12, tzinfo=plus_two))
    )
    session.commit()
    session.expunge_all()
    sat = session.scalar(select(Satellite))
    assert sat.last_fetch_attempt_at == utc(2026, 1, 1, 10)
    assert sat.last_fetch_attempt_at.utcoffset() == timedelta(0)

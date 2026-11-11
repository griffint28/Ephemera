"""Find satellites and stations by the identifiers people type."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ephemera.models import Satellite, Station


class NotFoundError(LookupError):
    pass


def get_satellite(session: Session, ident: str) -> Satellite:
    """Find a satellite by NORAD catalog number ("39084") or code ("L8", case-insensitive)."""
    ident = ident.strip()
    sat = None
    if ident.isdigit():
        sat = session.scalar(select(Satellite).where(Satellite.norad_id == int(ident)))
    if sat is None:
        sat = session.scalar(select(Satellite).where(Satellite.code == ident.upper()))
    if sat is None:
        raise NotFoundError(f"no satellite with NORAD id or code {ident!r} (run seed-fleet?)")
    return sat


def get_station(session: Session, code: str) -> Station:
    station = session.scalar(select(Station).where(Station.code == code.strip().upper()))
    if station is None:
        raise NotFoundError(f"no station with code {code!r} (run seed-fleet?)")
    return station


def all_satellites(session: Session) -> Sequence[Satellite]:
    return session.scalars(select(Satellite).order_by(Satellite.id)).all()


def all_stations(session: Session) -> Sequence[Station]:
    return session.scalars(select(Station).order_by(Station.id)).all()

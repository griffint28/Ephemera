"""Predict passes of one satellite over one ground site with Skyfield (SGP4).

Pure: Skyfield and the standard library only. No framework, database or `ephemera` imports.

Window rule: a pass belongs to the window [start, end) if it *rises* inside it. A pass already
in progress at `start` is not included; the last pass may set after `end`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sgp4 import omm
from sgp4.api import Satrec
from skyfield.api import EarthSatellite, load, wgs84

# Longer than any pass a LEO satellite makes above a 0-degree mask. The event search is padded
# by this on both sides, then passes are kept by rise time: a pass rising just before the window
# end is followed to its set, and a pass rising exactly at the window start is still seen as a
# rise (a search that starts on the mask crossing does not report it).
_SEARCH_MARGIN = timedelta(hours=1)

_ts = load.timescale()  # built-in leap-second/UT1 tables; no download


class ElementsError(ValueError):
    pass


@dataclass(frozen=True)
class GroundSite:
    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    min_elevation_deg: float


@dataclass(frozen=True)
class PredictedPass:
    rise_time: datetime
    peak_time: datetime
    set_time: datetime
    peak_elevation_deg: float
    rise_azimuth_deg: float
    peak_azimuth_deg: float
    set_azimuth_deg: float

    @property
    def duration_s(self) -> float:
        return (self.set_time - self.rise_time).total_seconds()


def build_satellite(omm_record: Mapping[str, Any]) -> EarthSatellite:
    """Build a Skyfield satellite from a CelesTrak GP (OMM JSON) record."""
    fields = {k: str(v) for k, v in omm_record.items() if v is not None}
    try:
        sat = EarthSatellite.from_omm(_ts, fields)
    except (KeyError, ValueError, TypeError) as exc:
        raise ElementsError(f"unusable element set: {exc!r}") from exc
    if sat.model.error:
        raise ElementsError(f"SGP4 rejected the element set (error {sat.model.error})")
    return sat


def validate_elements(omm_record: Mapping[str, Any]) -> None:
    """Raise ElementsError if the record cannot be propagated."""
    fields = {k: str(v) for k, v in omm_record.items() if v is not None}
    satrec = Satrec()
    try:
        omm.initialize(satrec, fields)
    except (KeyError, ValueError, TypeError) as exc:
        raise ElementsError(f"unusable element set: {exc!r}") from exc
    if satrec.error:
        raise ElementsError(f"SGP4 rejected the element set (error {satrec.error})")


def predict_passes(
    omm_record: Mapping[str, Any], site: GroundSite, start: datetime, end: datetime
) -> list[PredictedPass]:
    """Every pass above `site.min_elevation_deg` that rises in [start, end)."""
    _require_utc(start, "start")
    _require_utc(end, "end")
    if end <= start:
        raise ValueError("end must be after start")

    sat = build_satellite(omm_record)
    topos = wgs84.latlon(site.latitude_deg, site.longitude_deg, elevation_m=site.altitude_m)
    relative = sat - topos

    def altaz(t: Any) -> tuple[float, float]:
        alt, az, _ = relative.at(t).altaz()
        return float(alt.degrees), float(az.degrees)

    times, events = sat.find_events(
        topos,
        _ts.from_datetime(start - _SEARCH_MARGIN),
        _ts.from_datetime(end + _SEARCH_MARGIN),
        altitude_degrees=site.min_elevation_deg,
    )

    passes: list[PredictedPass] = []
    rise = None
    peaks: list[Any] = []
    for t, event in zip(times, events, strict=True):
        if event == 0:  # rise
            rise, peaks = t, []
        elif event == 1:  # culmination
            if rise is not None:
                peaks.append(t)
        elif event == 2:  # set
            if rise is not None:  # skip a pass already in progress at the search start
                passes.append(_make_pass(rise, peaks, t, altaz))
            rise, peaks = None, []

    return [p for p in passes if start <= p.rise_time < end]


def _make_pass(rise: Any, peaks: list[Any], set_: Any, altaz: Any) -> PredictedPass:
    if not peaks:  # grazing pass with no reported culmination: use the midpoint
        peaks = [_ts.tt_jd((rise.tt + set_.tt) / 2)]
    peak_t = max(peaks, key=lambda t: altaz(t)[0])
    peak_alt, peak_az = altaz(peak_t)
    _, rise_az = altaz(rise)
    _, set_az = altaz(set_)
    return PredictedPass(
        rise_time=_to_datetime(rise),
        peak_time=_to_datetime(peak_t),
        set_time=_to_datetime(set_),
        peak_elevation_deg=peak_alt,
        rise_azimuth_deg=rise_az,
        peak_azimuth_deg=peak_az,
        set_azimuth_deg=set_az,
    )


def _to_datetime(t: Any) -> datetime:
    """UTC, rounded to the whole second.

    SGP4 is good to seconds at best, and rounding makes recomputation stable: the root finder
    otherwise returns slightly different microseconds depending on where the search started.
    """
    dt = t.utc_datetime().astimezone(UTC)
    return (dt + timedelta(microseconds=500_000)).replace(microsecond=0)


def _require_utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware (UTC)")

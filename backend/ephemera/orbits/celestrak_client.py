"""CelesTrak GP data: the HTTP fetch and the cache policy around it.

This is the only module that talks to CelesTrak, and only the `fetch-orbital-data` CLI command
imports it. API routes and schedulers must never import it (a test enforces this).

Cache policy, per satellite:
- Skip if the last *successful* fetch is younger than the refresh interval (default 12 h).
  `force` bypasses this.
- Always skip if the last *attempt*, successful or not, is younger than 2 h. Nothing bypasses
  this: it is the floor CelesTrak asks clients to respect.
- A failed fetch records the attempt and leaves the cached element sets untouched.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from ephemera.models import OrbitalElements, Satellite
from ephemera.orbits.pass_prediction import ElementsError, validate_elements
from ephemera.settings import CELESTRAK_MIN_REFRESH_HOURS

GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
USER_AGENT = "ephemera-ground-station-scheduler/0.1"
SOURCE = "celestrak-gp"
_REQUIRED = ("NORAD_CAT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION")


class CelestrakError(RuntimeError):
    pass


Fetcher = Callable[[int], dict[str, Any]]


def fetch_gp(norad_id: int, *, timeout: float = 30.0, opener: Callable[..., Any] = urlopen) -> dict[str, Any]:
    """Fetch the current GP element set (OMM JSON) for one catalog number."""
    url = f"{GP_URL}?CATNR={norad_id}&FORMAT=json"
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as exc:
        raise CelestrakError(f"HTTP {exc.code} from CelesTrak for {norad_id}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise CelestrakError(f"could not reach CelesTrak for {norad_id}: {exc}") from exc
    return parse_gp_response(norad_id, body)


def parse_gp_response(norad_id: int, body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # CelesTrak answers unknown or decayed objects with plain text, e.g. "No GP data found".
        raise CelestrakError(f"CelesTrak returned no element set for {norad_id}: {text[:120]!r}") from None
    if not isinstance(data, list) or not data:
        raise CelestrakError(f"CelesTrak returned no element set for {norad_id}")
    matches = [r for r in data if isinstance(r, dict) and _as_int(r.get("NORAD_CAT_ID")) == norad_id]
    if len(matches) != 1:
        raise CelestrakError(f"expected one element set for {norad_id}, got {len(matches)}")
    record = matches[0]
    missing = [k for k in _REQUIRED if record.get(k) in (None, "")]
    if missing:
        raise CelestrakError(f"element set for {norad_id} lacks {', '.join(missing)}")
    try:
        parse_epoch(record["EPOCH"])
        validate_elements(record)
    except (ValueError, ElementsError) as exc:
        raise CelestrakError(f"element set for {norad_id} is unusable: {exc}") from exc
    return record


def parse_epoch(value: str) -> datetime:
    """CelesTrak epochs are ISO 8601 UTC without an offset."""
    epoch = datetime.fromisoformat(str(value))
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=UTC)
    return epoch.astimezone(UTC)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class FetchOutcome:
    code: str
    norad_id: int
    status: str  # "new" | "unchanged" | "cached" | "too-soon" | "failed"
    detail: str
    epoch: datetime | None = None


def refresh_orbital_elements(
    session: Session,
    satellites: Iterable[Satellite],
    *,
    now: datetime,
    refresh_hours: float,
    force: bool = False,
    fetch: Fetcher = fetch_gp,
) -> list[FetchOutcome]:
    """Apply the cache policy and fetch what is due. Commits after each satellite."""
    if refresh_hours < CELESTRAK_MIN_REFRESH_HOURS:
        raise ValueError(f"refresh_hours cannot be below {CELESTRAK_MIN_REFRESH_HOURS}")
    floor = timedelta(hours=CELESTRAK_MIN_REFRESH_HOURS)
    refresh = timedelta(hours=refresh_hours)

    outcomes = []
    for sat in satellites:
        if sat.last_fetch_attempt_at and now - sat.last_fetch_attempt_at < floor:
            wait = sat.last_fetch_attempt_at + floor - now
            outcomes.append(_outcome(sat, "too-soon", f"last attempt under 2 h ago; retry in {_fmt(wait)}"))
            continue
        if not force and sat.last_fetch_success_at and now - sat.last_fetch_success_at < refresh:
            age = now - sat.last_fetch_success_at
            outcomes.append(_outcome(sat, "cached", f"fetched {_fmt(age)} ago"))
            continue

        sat.last_fetch_attempt_at = now
        session.commit()  # the attempt counts toward the 2 h floor even if the fetch fails
        try:
            record = fetch(sat.norad_id)
        except CelestrakError as exc:
            outcomes.append(_outcome(sat, "failed", f"{exc}; cached elements kept"))
            continue

        epoch = parse_epoch(record["EPOCH"])
        existing = session.scalar(
            select(OrbitalElements).where(
                OrbitalElements.satellite_id == sat.id, OrbitalElements.epoch == epoch
            )
        )
        if existing is None:
            session.add(
                OrbitalElements(
                    satellite_id=sat.id,
                    epoch=epoch,
                    fetched_at=now,
                    source=SOURCE,
                    omm_json=json.dumps(record, sort_keys=True),
                )
            )
            status, detail = "new", "new element set"
        else:
            status, detail = "unchanged", "same epoch as the cached element set"
        sat.last_fetch_success_at = now
        session.commit()
        outcomes.append(_outcome(sat, status, detail, epoch))
    return outcomes


def _outcome(sat: Satellite, status: str, detail: str, epoch: datetime | None = None) -> FetchOutcome:
    return FetchOutcome(code=sat.code, norad_id=sat.norad_id, status=status, detail=detail, epoch=epoch)


def _fmt(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    return f"{minutes // 60} h {minutes % 60:02d} min"

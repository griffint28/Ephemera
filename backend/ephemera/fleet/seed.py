"""Copy the fleet config into the database (insert or update; never delete)."""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ephemera.fleet.config_loader import FleetConfig
from ephemera.models import Satellite, Station


@dataclass
class SeedResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    # In the database but no longer in config. Kept, because passes may reference them.
    not_in_config: list[str] = field(default_factory=list)


def seed_fleet(session: Session, fleet: FleetConfig) -> SeedResult:
    result = SeedResult()

    sats = {s.norad_id: s for s in session.scalars(select(Satellite))}
    for cfg in fleet.satellites:
        label = f"satellite {cfg.code} ({cfg.norad_id})"
        values = {"code": cfg.code, "name": cfg.name, "operator": cfg.operator}
        row = sats.pop(cfg.norad_id, None)
        if row is None:
            session.add(Satellite(norad_id=cfg.norad_id, **values))
            result.created.append(label)
        else:
            _apply(row, values, label, result)
    result.not_in_config += [f"satellite {s.code} ({s.norad_id})" for s in sats.values()]

    stations = {s.code: s for s in session.scalars(select(Station))}
    for cfg in fleet.stations:
        label = f"station {cfg.code}"
        values = {
            "name": cfg.name,
            "operator": cfg.operator,
            "latitude_deg": cfg.latitude_deg,
            "longitude_deg": cfg.longitude_deg,
            "altitude_m": cfg.altitude_m,
            "min_elevation_deg": cfg.min_elevation_deg,
            "timezone": cfg.timezone,
        }
        row = stations.pop(cfg.code, None)
        if row is None:
            session.add(Station(code=cfg.code, **values))
            result.created.append(label)
        else:
            _apply(row, values, label, result)
    result.not_in_config += [f"station {s.code}" for s in stations.values()]

    session.flush()
    return result


def _apply(row: object, values: dict[str, object], label: str, result: SeedResult) -> None:
    changed = False
    for key, value in values.items():
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed = True
    (result.updated if changed else result.unchanged).append(label)

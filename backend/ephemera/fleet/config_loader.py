"""Load and validate config/satellites.yaml and config/stations.yaml.

Pure: no framework or database imports.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SatelliteConfig:
    code: str
    name: str
    norad_id: int
    operator: str
    # Simulated workload. Illustrative values, not spacecraft specifications.
    storage_capacity_gb: float
    generation_rate_gb_per_hour: float
    downlink_rate_gb_per_min: float


@dataclass(frozen=True)
class StationConfig:
    code: str
    name: str
    operator: str
    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    min_elevation_deg: float
    timezone: str


@dataclass(frozen=True)
class FleetConfig:
    satellites: tuple[SatelliteConfig, ...]
    stations: tuple[StationConfig, ...]


def load_fleet(config_dir: Path) -> FleetConfig:
    return FleetConfig(
        satellites=load_satellites(config_dir / "satellites.yaml"),
        stations=load_stations(config_dir / "stations.yaml"),
    )


def load_satellites(path: Path) -> tuple[SatelliteConfig, ...]:
    entries = _read_list(path, "satellites")
    sats = tuple(_satellite(e, path, i) for i, e in enumerate(entries))
    _require_unique(path, "code", [s.code for s in sats])
    _require_unique(path, "norad_id", [s.norad_id for s in sats])
    return sats


def load_stations(path: Path) -> tuple[StationConfig, ...]:
    entries = _read_list(path, "stations")
    stations = tuple(_station(e, path, i) for i, e in enumerate(entries))
    _require_unique(path, "code", [s.code for s in stations])
    return stations


def _read_list(path: Path, key: str) -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path}: file not found") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get(key), list) or not data[key]:
        raise ConfigError(f"{path}: expected a non-empty '{key}:' list")
    for i, entry in enumerate(data[key]):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: {key}[{i}] is not a mapping")
    return data[key]


def _field(entry: dict[str, Any], name: str, kind: type, where: str) -> Any:
    if name not in entry or entry[name] is None:
        raise ConfigError(f"{where}: missing '{name}'")
    value = entry[name]
    if kind is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"{where}: '{name}' must be a number")
        return float(value)
    if kind is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{where}: '{name}' must be an integer")
        return value
    # Strings: accept YAML scalars (e.g. a code like 2A is a string, but be forgiving).
    text = str(value).strip()
    if not text:
        raise ConfigError(f"{where}: '{name}' must not be empty")
    return text


def _satellite(entry: dict[str, Any], path: Path, i: int) -> SatelliteConfig:
    where = f"{path}: satellites[{i}]"
    workload = entry.get("workload")
    if not isinstance(workload, dict):
        raise ConfigError(f"{where}: missing 'workload' mapping")
    wwhere = f"{where}.workload"
    sat = SatelliteConfig(
        code=_field(entry, "code", str, where),
        name=_field(entry, "name", str, where),
        norad_id=_field(entry, "norad_id", int, where),
        operator=_field(entry, "operator", str, where),
        storage_capacity_gb=_field(workload, "storage_capacity_gb", float, wwhere),
        generation_rate_gb_per_hour=_field(workload, "generation_rate_gb_per_hour", float, wwhere),
        downlink_rate_gb_per_min=_field(workload, "downlink_rate_gb_per_min", float, wwhere),
    )
    if len(sat.code) > 8:
        raise ConfigError(f"{where}: code '{sat.code}' is longer than 8 characters")
    if not 0 < sat.norad_id < 1_000_000_000:
        raise ConfigError(f"{where}: norad_id {sat.norad_id} is out of range")
    for name in ("storage_capacity_gb", "generation_rate_gb_per_hour", "downlink_rate_gb_per_min"):
        if getattr(sat, name) <= 0:
            raise ConfigError(f"{wwhere}: {name} must be positive")
    return sat


def _station(entry: dict[str, Any], path: Path, i: int) -> StationConfig:
    where = f"{path}: stations[{i}]"
    st = StationConfig(
        code=_field(entry, "code", str, where),
        name=_field(entry, "name", str, where),
        operator=_field(entry, "operator", str, where),
        latitude_deg=_field(entry, "latitude_deg", float, where),
        longitude_deg=_field(entry, "longitude_deg", float, where),
        altitude_m=_field(entry, "altitude_m", float, where),
        min_elevation_deg=_field(entry, "min_elevation_deg", float, where),
        timezone=_field(entry, "timezone", str, where),
    )
    if len(st.code) > 8:
        raise ConfigError(f"{where}: code '{st.code}' is longer than 8 characters")
    if not -90 <= st.latitude_deg <= 90:
        raise ConfigError(f"{where}: latitude_deg must be within [-90, 90]")
    if not -180 <= st.longitude_deg <= 180:
        raise ConfigError(f"{where}: longitude_deg must be within [-180, 180]")
    if not 0 <= st.min_elevation_deg < 90:
        raise ConfigError(f"{where}: min_elevation_deg must be within [0, 90)")
    try:
        ZoneInfo(st.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"{where}: unknown timezone '{st.timezone}'") from None
    return st


def _require_unique(path: Path, name: str, values: list[Any]) -> None:
    seen: set[Any] = set()
    for v in values:
        if v in seen:
            raise ConfigError(f"{path}: duplicate {name} {v!r}")
        seen.add(v)

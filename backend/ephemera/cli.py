"""Command line: python -m ephemera <command>."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from ephemera.db import session_scope
from ephemera.fleet import lookup
from ephemera.fleet.config_loader import ConfigError, load_fleet
from ephemera.fleet.seed import seed_fleet as seed_fleet_into
from ephemera.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Ephemera ground station scheduler.")

SatelliteOpt = Annotated[
    list[str] | None, typer.Option("--satellite", "-s", help="NORAD id or code. Repeatable. Default: all.")
]
StationOpt = Annotated[list[str] | None, typer.Option("--station", "-g", help="Station code. Repeatable. Default: all.")]
StartOpt = Annotated[
    str | None, typer.Option(help="Window start, ISO 8601. No offset means UTC. Default: now (UTC).")
]
HoursOpt = Annotated[float | None, typer.Option(help="Window length in hours. Default: PASS_WINDOW_HOURS (48).")]


def _now() -> datetime:
    return datetime.now(UTC)


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(f"not an ISO 8601 time: {value!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@app.command("seed-fleet")
def seed_fleet(
    config_dir: Annotated[Path | None, typer.Option(help="Default: CONFIG_DIR or the repo's config/.")] = None,
) -> None:
    """Load config/satellites.yaml and config/stations.yaml into the database."""
    directory = config_dir or get_settings().config_dir
    try:
        fleet = load_fleet(directory)
    except ConfigError as exc:
        _fail(str(exc))
    with session_scope() as session:
        result = seed_fleet_into(session, fleet)
    for label, items in (("created", result.created), ("updated", result.updated)):
        for item in items:
            typer.echo(f"{label:<9} {item}")
    typer.echo(
        f"{len(fleet.satellites)} satellites and {len(fleet.stations)} stations in config: "
        f"{len(result.created)} created, {len(result.updated)} updated, {len(result.unchanged)} unchanged."
    )
    for item in result.not_in_config:
        typer.secho(f"warning   {item} is in the database but not in config (kept)", fg=typer.colors.YELLOW)


@app.command("fetch-orbital-data")
def fetch_orbital_data(
    satellite: SatelliteOpt = None,
    force: Annotated[
        bool, typer.Option("--force", help="Bypass the refresh interval. Never bypasses the 2 h floor.")
    ] = False,
) -> None:
    """Fetch GP element sets from CelesTrak into the database cache. Safe to re-run."""
    # Imported here so that nothing but this command loads the CelesTrak client.
    from ephemera.orbits import celestrak_client

    settings = get_settings()
    with session_scope() as session:
        sats = _satellites(session, satellite)
        outcomes = celestrak_client.refresh_orbital_elements(
            session,
            sats,
            now=_now(),
            refresh_hours=settings.orbital_refresh_hours,
            force=force,
            fetch=celestrak_client.fetch_gp,
        )
    for o in outcomes:
        epoch = f" epoch {o.epoch:%Y-%m-%d %H:%M:%S} UTC" if o.epoch else ""
        color = typer.colors.RED if o.status == "failed" else None
        typer.secho(f"{o.code:<4} {o.norad_id:>6}  {o.status:<9} {o.detail}{epoch}", fg=color)
    if any(o.status == "failed" for o in outcomes):
        raise typer.Exit(1)


@app.command("compute-passes")
def compute_passes(
    start: StartOpt = None,
    hours: HoursOpt = None,
    satellite: SatelliteOpt = None,
    station: StationOpt = None,
) -> None:
    """Predict passes from cached element sets and store them (replaces passes in the window)."""
    from ephemera.orbits.passes_service import compute_passes as compute

    now = _now()
    window_start = parse_time(start) if start else now.replace(second=0, microsecond=0)
    window_hours = hours if hours is not None else get_settings().pass_window_hours
    if window_hours <= 0:
        raise typer.BadParameter("hours must be positive", param_hint="--hours")
    with session_scope() as session:
        sats = _satellites(session, satellite)
        stations = _stations(session, station)
        result = compute(session, sats, stations, start=window_start, hours=window_hours, now=now)
    typer.echo(f"Window {result.start:%Y-%m-%d %H:%M} to {result.end:%Y-%m-%d %H:%M} UTC")
    for (sat_code, station_code), count in result.counts.items():
        typer.echo(f"  {sat_code:<4} over {station_code:<5} {count:>3} passes")
    typer.echo(f"{result.total} passes stored ({result.replaced} previous passes in the window replaced).")
    if result.replaced:
        typer.echo("Schedule runs derived from the old passes must be re-run.")
    for code in result.no_elements:
        typer.secho(f"warning   {code}: no cached element set; run fetch-orbital-data", fg=typer.colors.YELLOW)
    for code, epoch in result.stale_elements:
        typer.secho(
            f"warning   {code}: element set epoch {epoch:%Y-%m-%d %H:%M} UTC is more than 3 days "
            "from the window start; predictions may drift",
            fg=typer.colors.YELLOW,
        )
    if result.no_elements and not result.counts:
        raise typer.Exit(1)


@app.command("show-passes")
def show_passes(
    satellite: Annotated[str | None, typer.Option("--satellite", "-s", help="NORAD id or code.")] = None,
    station: Annotated[str | None, typer.Option("--station", "-g", help="Station code.")] = None,
    start: StartOpt = None,
    hours: HoursOpt = None,
    local_time: Annotated[bool, typer.Option("--local-time", help="Show times in each station's zone.")] = False,
) -> None:
    """List stored passes rising in the window (default: from now, PASS_WINDOW_HOURS long)."""
    from ephemera.orbits.passes_service import list_passes
    from ephemera.orbits.report import format_passes

    window_start = parse_time(start) if start else _now()
    window_hours = hours if hours is not None else get_settings().pass_window_hours
    with session_scope() as session:
        try:
            sat = lookup.get_satellite(session, satellite) if satellite else None
            stn = lookup.get_station(session, station) if station else None
        except lookup.NotFoundError as exc:
            _fail(str(exc))
        passes = list_passes(
            session,
            satellite=sat,
            station=stn,
            start=window_start,
            end=window_start + timedelta(hours=window_hours),
        )
        typer.echo(format_passes(passes, local_time=local_time))


def _satellites(session, idents):  # type: ignore[no-untyped-def]
    try:
        if idents:
            return [lookup.get_satellite(session, i) for i in idents]
        sats = lookup.all_satellites(session)
    except lookup.NotFoundError as exc:
        _fail(str(exc))
    if not sats:
        _fail("no satellites in the database; run seed-fleet first")
    return sats


def _stations(session, codes):  # type: ignore[no-untyped-def]
    try:
        if codes:
            return [lookup.get_station(session, c) for c in codes]
        stations = lookup.all_stations(session)
    except lookup.NotFoundError as exc:
        _fail(str(exc))
    if not stations:
        _fail("no stations in the database; run seed-fleet first")
    return stations

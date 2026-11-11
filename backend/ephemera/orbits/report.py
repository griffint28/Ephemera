"""Plain-text tables for the CLI."""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from ephemera.models import Pass


def format_passes(passes: Sequence[Pass], *, local_time: bool = False) -> str:
    if not passes:
        return "No stored passes match. Run compute-passes first, or widen the window."
    zone_label = "station local" if local_time else "UTC"
    header = (
        f"{'SAT':<4} {'NORAD':>6} {'STN':<5} {'DATE':<10} {'RISE':>8} {'PEAK':>8} {'SET':>8}"
        f" {'DUR':>6} {'MAX EL':>6}  {'AZ RISE>PEAK>SET':<16}"
    )
    lines = [f"Times in {zone_label}. Elevation mask per station; azimuth degrees from north.", header]
    for p in passes:
        zone = ZoneInfo(p.station.timezone) if local_time else None
        rise, peak, set_ = (_in(t, zone) for t in (p.rise_time, p.peak_time, p.set_time))
        minutes, seconds = divmod(round(p.duration_s), 60)
        lines.append(
            f"{p.satellite.code:<4} {p.satellite.norad_id:>6} {p.station.code:<5}"
            f" {rise:%Y-%m-%d} {rise:%H:%M:%S} {peak:%H:%M:%S} {set_:%H:%M:%S}"
            f" {minutes:>3}:{seconds:02d} {p.peak_elevation_deg:>5.1f}°"
            f"  {p.rise_azimuth_deg:>3.0f}>{p.peak_azimuth_deg:>3.0f}>{p.set_azimuth_deg:>3.0f}"
        )
    lines.append(f"{len(passes)} pass{'es' if len(passes) != 1 else ''}.")
    return "\n".join(lines)


def _in(t: datetime, zone: ZoneInfo | None) -> datetime:
    return t.astimezone(zone) if zone else t

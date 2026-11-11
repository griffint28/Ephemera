"""Plain-text tables for the CLI."""

from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from scheduler.metrics import Metrics

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


def format_metrics(m: Metrics, *, simulation_id: int, run_id: int, seed: int) -> str:
    """Headline metrics for one run. Labelled as simulated workload, as every figure derived
    from the data simulation must be."""
    delay = "n/a (no urgent chunk fully downlinked)" if m.urgent_delay_avg_s is None else _hm(m.urgent_delay_avg_s)
    lines = [
        f"Schedule run {run_id}: {m.scheduler} over simulation {simulation_id} (seed {seed}), "
        f"{m.window_hours:.0f} h window. SIMULATED WORKLOAD; passes are real.",
        "",
        f"  Passes used              {m.passes_used} of {m.passes_available}"
        + "".join(f"  {s} {n}" for s, n in m.passes_used_by_station.items()),
        f"  Total downlinked         {m.total_downlinked_gb:8.1f} GB  of {m.total_generated_gb:.1f} GB generated",
        f"  Avg urgent delay         {delay}  ({m.urgent_downlinked} of {m.urgent_chunks} urgent chunks downlinked)",
        f"  Antenna utilization      {m.antenna_utilization:7.1%}"
        + "".join(f"  {s} {u:.1%}" for s, u in m.antenna_utilization_by_station.items()),
        f"  Stranded at window end   {m.stranded_gb:8.1f} GB"
        + (f"  (dropped, storage full: {m.dropped_gb:.1f} GB)" if m.dropped_gb else ""),
    ]
    lines.append("  Stranded per satellite")
    for sat, gb in m.stranded_gb_by_satellite.items():
        extra = f"  dropped {m.dropped_gb_by_satellite[sat]:.1f} GB" if m.dropped_gb_by_satellite.get(sat) else ""
        lines.append(f"    {sat:<4} {gb:8.1f} GB{extra}")
    return "\n".join(lines)


def _hm(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min"

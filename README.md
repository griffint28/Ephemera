# Ephemera

A ground station scheduler for a small civil Earth-observing fleet. It predicts every satellite
pass over a 48-hour window and compares two scheduling strategies on identical input.

> **Status: early development.** The design is finished; the build has not started. There are no
> measured results in this README yet. When there are, they will come from a named run with its
> seed recorded — not from the design mockups.

## The problem

Earth-observing satellites record data all orbit long, but they can only send it down while a
ground antenna can see them. That window — a *pass* — lasts roughly 7 to 10 minutes, and an
antenna can track only one satellite at a time.

So when two passes overlap on the same antenna, one satellite has to wait for its next contact,
which may be hours away. If the satellite that waits is the one carrying urgent data, the urgent
data is what arrives late.

Polar orbits sharpen the problem. They converge near the poles, so passes pile up at
high-latitude stations like Svalbard and Fairbanks — exactly where the fleet is most visible.

## What Ephemera does

It predicts every pass above 10° elevation over a configurable window (48 hours by default),
simulates the data each satellite is holding — some of it marked urgent — and runs two
schedulers over identical input:

| Scheduler | Rule |
|---|---|
| **FCFS** | First come, first served: whichever satellite rises first gets the antenna. The baseline. |
| **Greedy** | Priority-aware: prefers the satellite holding urgent data, then the one holding the most. |

Both are then scored on the same four metrics:

- **Total data downlinked**
- **Average urgent-data delay** — from when urgent data is created to when it reaches the ground
- **Antenna utilization**
- **Stranded data** — still onboard when the window closes

The comparison is the point, not either scheduler on its own. A single schedule tells you
nothing; two schedules over the same passes and the same onboard data tell you what
prioritization actually costs and buys.

## What's real and what's simulated

**The orbits are real.** Satellite catalog numbers and station coordinates are public values.
Orbital elements come from [CelesTrak](https://celestrak.org/) GP data, cached locally and
refreshed at most twice a day. Pass geometry is computed with
[Skyfield](https://rhodesmill.org/skyfield/) and checked by hand against Heavens-Above.

**The workload is simulated.** Downlink rate, onboard storage capacity, data-generation rate and
which data counts as urgent are illustrative values, not published spacecraft specifications.
They are seeded, so any run reproduces exactly.

In short: the passes are when these satellites really do fly overhead. What they are carrying is
invented, and labelled that way everywhere it appears.

## The fleet

Seven satellites sharing three antennas:

| Code | Satellite | NORAD | Operator |
|---|---|---|---|
| L8 | Landsat 8 | 39084 | USGS / NASA |
| L9 | Landsat 9 | 49260 | USGS / NASA |
| 2A | Sentinel-2A | 40697 | ESA / Copernicus |
| 2B | Sentinel-2B | 42063 | ESA / Copernicus |
| N20 | NOAA-20 (JPSS-1) | 43013 | NOAA / NASA |
| N21 | NOAA-21 (JPSS-2) | 54234 | NOAA / NASA |
| NPP | Suomi NPP | 37849 | NASA / NOAA |

| Code | Station | Location | Operator |
|---|---|---|---|
| SVAL | Svalbard Satellite Station | 78.2298° N, 15.4078° E | KSAT |
| FAIR | Fairbanks, Gilmore Creek | 64.9780° N, 147.4990° W | NOAA |
| WALL | Wallops Island, Virginia | 37.9467° N, 75.4587° W | NOAA |

All three use a 10° minimum elevation mask. The fleet is editable in `config/satellites.yaml`
and `config/stations.yaml`.

## Stack

Python 3.12, FastAPI, SQLAlchemy and Alembic over MariaDB, Skyfield for orbit propagation,
pytest. React, TypeScript and Plotly on the front end. Docker throughout.

Two boundaries are enforced by tests rather than convention:

- The schedulers are plain Python with no web framework, ORM or application imports, behind one
  interface — `schedule(passes, demands) -> list[Assignment]` — so a constraint solver can drop
  in beside the heuristics later.
- Only an explicit CLI command talks to CelesTrak. API routes and the scheduler never do, and
  nothing fetches on page load or per request.

## Roadmap

1. **Orbits and passes** — config, schema, CelesTrak fetch and cache, Skyfield pass prediction, CLI
2. **Simulation and the FCFS baseline** — seeded onboard data, the scheduler interface, metrics
3. **Greedy scheduler and comparison** — head-to-head results and where the two schedules disagree
4. **Read-only API** — fleet, passes, runs, timeline, comparison
5. **Front end** — the timeline, both schedules side by side, metrics above
6. **Ship** — deployment, measured results, CI

Afterwards: an OR-Tools CP-SAT solver as a third scheduler, to measure how close the heuristic
gets to optimal and what the gap costs in solve time.

This is phase 1 of a larger mini ground segment — later phases add a simulated spacecraft
downlinking CCSDS telemetry during its scheduled contacts, and a mission control console to
watch it.

---

*eph·em·er·a* (n.) things that exist only briefly. Like a pass.

# Pass prediction: hand check against Heavens-Above

Milestone 1 is done when five predicted passes agree with Heavens-Above on rise and set time to
within about a minute.

**Status: not yet performed.** On 2026-11-11 at 13:43 UTC, CelesTrak's GP endpoint answered
HTTP 500 with an empty body for all seven catalog numbers. A single follow-up `curl` got the same
500, while celestrak.org's home page answered 200, so the fault was on CelesTrak's side. No element
sets are cached yet, and the 2 h floor allows the next attempt from 15:44 UTC.

## Method

1. `python -m ephemera fetch-orbital-data`, then `python -m ephemera compute-passes`.
2. Pick five passes covering different satellites, all three stations, and both high and low peak
   elevations: `python -m ephemera show-passes --satellite <id> --station <code>`.
3. For each, open Heavens-Above with the station's coordinates and the satellite's NORAD id,
   showing all passes (not only visible ones), e.g.
   `https://www.heavens-above.com/PassSummary.aspx?satid=39084&lat=64.978&lng=-147.499&alt=319&tz=UCT&showall=t`.
   Heavens-Above lists the 10-degree crossings ("Start" and "End" at 10°) alongside its own
   element set, which may be a different epoch from ours.
4. Record both sets of times below. Agreement within about 60 s on rise and set passes.

## Results

| # | Satellite | Station | Ephemera rise / set (UTC) | Heavens-Above rise / set (UTC) | Δ rise | Δ set | Peak el. (E / HA) |
|---|---|---|---|---|---|---|---|

Element set epochs used: (to be filled in)

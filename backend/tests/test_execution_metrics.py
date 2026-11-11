"""Replay and metrics on a scenario small enough to work out by hand.

Window: 06:00 to 08:00 (2 h). One station FAIR, two satellites.

Chunks (created, size):
  L8  routine 06:10  3 GB
  L8  URGENT  06:20  5 GB
  L8  routine 06:30  3 GB
  NPP URGENT  06:05  5 GB
  NPP routine 06:50  3 GB (created during the NPP pass: not eligible in it)

Passes (rise, duration, capacity = 1 GB/min):
  P1  L8  FAIR 06:40  10 min  10 GB   assigned
  P2  NPP FAIR 06:45   8 min   8 GB   NOT assigned (overlaps P1)
  P3  NPP FAIR 07:30   4 min   4 GB   assigned

Replay:
  P1: L8 holds 3 + 5 + 3 = 11 GB. Urgent first: 5 GB done at 06:45:00 (delay 25 min). Then the
      06:10 chunk: 3 GB done at 06:48:00. Then 2 of the 3 GB of the 06:30 chunk; 1 GB remains.
      Pass downlinks 10 GB.
  P3: NPP holds 5 (urgent) + 3. Urgent: 4 GB of 5 -> 1 GB remains, not completed. 4 GB down.

Metrics:
  downlinked        14 GB   generated 19 GB
  urgent delay      25 min  (1 of 2 urgent chunks fully down)
  utilization       (10 + 4) / 120 = 11.67 %
  stranded          L8 1 GB, NPP 1 + 3 = 4 GB  -> 5 GB
  passes used       2 of 3
"""

from datetime import timedelta

import pytest
from scheduler.execution import execute
from scheduler.metrics import compute_metrics
from scheduler.types import DataChunk, PassWindow, assignment_for

from tests.conftest import utc

START, END = utc(2026, 11, 12, 6), utc(2026, 11, 12, 8)


def at(h, m):
    return utc(2026, 11, 12, h, m)


def pw(id_, sat, h, m, minutes):
    return PassWindow(id_, sat, "FAIR", at(h, m), at(h, m) + timedelta(minutes=minutes), capacity_gb=float(minutes))


CHUNKS = [
    DataChunk(1, "L8", at(6, 10), 3, False),
    DataChunk(2, "L8", at(6, 20), 5, True),
    DataChunk(3, "L8", at(6, 30), 3, False),
    DataChunk(4, "NPP", at(6, 5), 5, True),
    DataChunk(5, "NPP", at(6, 50), 3, False),
]
PASSES = [pw(1, "L8", 6, 40, 10), pw(2, "NPP", 6, 45, 8), pw(3, "NPP", 7, 30, 4)]
ASSIGNED = [assignment_for(PASSES[0]), assignment_for(PASSES[2])]


@pytest.fixture(scope="module")
def result():
    execution = execute(PASSES, CHUNKS, ASSIGNED, window_start=START, window_end=END)
    metrics = compute_metrics("fcfs", PASSES, execution, stations=["FAIR"], satellites=["L8", "NPP"])
    return execution, metrics


def test_replay_per_chunk(result):
    execution, _ = result
    c = execution.chunks
    assert c[2].completed_at == at(6, 45) and c[2].delay == timedelta(minutes=25)
    assert c[1].completed_at == at(6, 48)
    assert c[3].downlinked_gb == 2 and c[3].completed_at is None and c[3].remaining_gb == 1
    assert c[4].downlinked_gb == 4 and c[4].completed_at is None
    assert c[5].downlinked_gb == 0  # created during P2's window, after P3? no: before P3, but P3 was full
    assert execution.passes[1].downlinked_gb == 10 and execution.passes[1].chunk_ids == [2, 1, 3]
    assert execution.passes[3].downlinked_gb == 4
    assert 2 not in execution.passes


def test_metrics_by_hand(result):
    _, m = result
    assert m.total_downlinked_gb == 14
    assert m.total_generated_gb == 19
    assert m.urgent_delay_avg_s == 25 * 60
    assert (m.urgent_chunks, m.urgent_downlinked) == (2, 1)
    assert m.antenna_utilization == pytest.approx(14 / 120)
    assert m.antenna_utilization_by_station == {"FAIR": pytest.approx(14 / 120)}
    assert m.stranded_gb_by_satellite == {"L8": 1, "NPP": 4}
    assert m.stranded_gb == 5
    assert m.dropped_gb == 0
    assert (m.passes_available, m.passes_used) == (3, 2)
    assert m.window_hours == 2


def test_chunk_created_during_pass_is_not_eligible():
    # NPP's 06:50 chunk is created inside P2's window; give NPP P2 instead and check it is skipped.
    execution = execute(PASSES, CHUNKS, [assignment_for(PASSES[1])], window_start=START, window_end=END)
    assert execution.passes[2].chunk_ids == [4]
    assert execution.chunks[5].downlinked_gb == 0


def test_nothing_downlinked_beyond_what_was_onboard():
    huge = [PassWindow(9, "L8", "FAIR", at(6, 35), at(7, 35), capacity_gb=1000)]
    execution = execute(huge, CHUNKS, [assignment_for(huge[0])], window_start=START, window_end=END)
    assert execution.passes[9].downlinked_gb == 11  # all three L8 chunks, nothing more
    assert all(c.downlinked_gb <= c.chunk.size_gb for c in execution.chunks.values())


def test_storage_cap_drops_the_excess_at_creation():
    execution = execute(PASSES, CHUNKS, [], window_start=START, window_end=END, storage_capacity_gb={"L8": 7})
    # L8: 3 fits, 5 -> 8 > 7, drop 1; then 3 -> 7 + 3 > 7, drop 3 entirely.
    assert execution.chunks[2].dropped_gb == 1
    assert execution.chunks[3].dropped_gb == 3
    assert execution.dropped_gb("L8") == 4
    assert execution.stranded_gb("L8") == 7


def test_no_urgent_delay_when_nothing_urgent_came_down():
    execution = execute(PASSES, CHUNKS, [], window_start=START, window_end=END)
    m = compute_metrics("fcfs", PASSES, execution, stations=["FAIR"], satellites=["L8", "NPP"])
    assert m.urgent_delay_avg_s is None and m.total_downlinked_gb == 0 and m.stranded_gb == 19


def test_unknown_pass_in_assignment_rejected():
    bogus = assignment_for(pw(42, "L8", 7, 0, 5))
    with pytest.raises(ValueError, match="unknown pass"):
        execute(PASSES, CHUNKS, [bogus], window_start=START, window_end=END)

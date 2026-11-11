"""FCFS and the schedule invariants every scheduler must keep."""

from datetime import timedelta

import pytest
from scheduler import SCHEDULERS, get_scheduler
from scheduler.fcfs import FcfsScheduler
from scheduler.types import PassWindow

from tests.conftest import utc

T0 = utc(2026, 11, 12, 6)


def pw(id_, sat, station, rise_min, dur_min=8, rate=1.0):
    rise = T0 + timedelta(minutes=rise_min)
    return PassWindow(id_, sat, station, rise, rise + timedelta(minutes=dur_min), capacity_gb=dur_min * rate)


def check_invariants(passes, assignments):
    by_id = {p.id: p for p in passes}
    used = [by_id[a.pass_id] for a in assignments]
    assert len({a.pass_id for a in assignments}) == len(assignments), "a pass used twice"
    for i, a in enumerate(used):
        for b in used[i + 1 :]:
            if a.station == b.station:
                assert not a.overlaps(b), f"antenna {a.station} double-booked: {a.id} and {b.id}"
            if a.satellite == b.satellite:
                assert not a.overlaps(b), f"{a.satellite} on two antennas: {a.id} and {b.id}"


def test_earlier_rise_wins_an_overlap():
    passes = [pw(1, "L8", "FAIR", 0), pw(2, "NPP", "FAIR", 5)]  # NPP overlaps the tail of L8
    assignments = FcfsScheduler().schedule(passes, [])
    assert [a.pass_id for a in assignments] == [1]
    check_invariants(passes, assignments)


def test_non_overlapping_passes_are_all_used():
    passes = [pw(1, "L8", "FAIR", 0), pw(2, "NPP", "FAIR", 8), pw(3, "L9", "SVAL", 3)]  # 2 touches 1
    assignments = FcfsScheduler().schedule(passes, [])
    assert sorted(a.pass_id for a in assignments) == [1, 2, 3]
    check_invariants(passes, assignments)


def test_satellite_cannot_be_on_two_antennas_at_once():
    passes = [pw(1, "L8", "FAIR", 0), pw(2, "L8", "SVAL", 4)]
    assignments = FcfsScheduler().schedule(passes, [])
    assert [a.pass_id for a in assignments] == [1]
    check_invariants(passes, assignments)


def test_losing_a_conflict_frees_the_loser_elsewhere():
    # NPP loses FAIR to L8 but is then free to take SVAL, which overlaps the FAIR pass it lost.
    passes = [pw(1, "L8", "FAIR", 0), pw(2, "NPP", "FAIR", 2), pw(3, "NPP", "SVAL", 6)]
    assignments = FcfsScheduler().schedule(passes, [])
    assert sorted(a.pass_id for a in assignments) == [1, 3]


def test_input_order_does_not_matter():
    passes = [pw(i, sat, st, m) for i, (sat, st, m) in enumerate([("L8", "FAIR", 0), ("NPP", "FAIR", 5), ("L9", "SVAL", 1), ("2A", "SVAL", 7)])]
    forward = FcfsScheduler().schedule(passes, [])
    backward = FcfsScheduler().schedule(list(reversed(passes)), [])
    assert forward == backward


@pytest.mark.parametrize("name", sorted(SCHEDULERS))
def test_invariants_on_a_dense_random_day(name):
    import random

    rng = random.Random(7)
    passes = []
    for i in range(300):
        rise = rng.uniform(0, 48 * 60)
        passes.append(pw(i, rng.choice(["L8", "L9", "2A", "2B", "N20", "N21", "NPP"]), rng.choice(["SVAL", "FAIR", "WALL"]), rise, rng.uniform(4, 11)))
    assignments = get_scheduler(name).schedule(passes, [])
    assert assignments
    check_invariants(passes, assignments)
    assert get_scheduler(name).schedule(passes, []) == assignments  # deterministic


def test_unknown_scheduler_name():
    with pytest.raises(KeyError, match="unknown scheduler"):
        get_scheduler("optimal")

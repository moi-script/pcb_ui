from __future__ import annotations

import sys
import threading
import time

import pytest

from grbl.protocol import parse_reply, parse_status
from grbl.streamer import (
    DisconnectedEvent,
    ReplyEvent,
    SentEvent,
    StatusEvent,
)
from grbl.state import MachineState
from grbl.profile import Profile


@pytest.fixture()
def state():
    return MachineState(
        Profile(travel_x=300.0, travel_y=200.0, travel_z=5.0,
                pen_up_z=5.0, pen_down_z=0.0)
    )


def status_event(line: str) -> StatusEvent:
    parsed = parse_status(line)
    assert parsed is not None
    return StatusEvent(parsed)


def reply_event(line: str) -> ReplyEvent:
    parsed = parse_reply(line)
    assert parsed is not None
    return ReplyEvent(parsed)


def test_starts_disconnected(state):
    snap = state.snapshot()
    assert snap["conn"]["connected"] is False
    assert snap["state"] == "Disconnected"


def test_snapshot_has_every_documented_key(state):
    snap = state.snapshot()
    for key in (
        "conn", "state", "mpos", "wpos", "wco", "feed",
        "spindle", "ov", "pen", "alarm", "error", "job", "seq",
    ):
        assert key in snap


def test_status_updates_position_and_state(state):
    state.apply(status_event("<Run|MPos:124.500,62.858,5.000|FS:800,0|WCO:100.000,50.000,0.000>"))
    snap = state.snapshot()
    assert snap["state"] == "Run"
    assert snap["mpos"] == [124.5, 62.858, 5.0]
    assert snap["wpos"] == pytest.approx([24.5, 12.858, 5.0])
    assert snap["feed"] == 800


def test_wco_is_carried_between_reports(state):
    state.apply(status_event("<Idle|MPos:100.000,50.000,0.000|FS:0,0|WCO:100.000,50.000,0.000>"))
    state.apply(status_event("<Idle|MPos:110.000,50.000,0.000|FS:0,0>"))
    snap = state.snapshot()
    assert snap["wco"] == [100.0, 50.0, 0.0]
    assert snap["wpos"] == pytest.approx([10.0, 0.0, 0.0])


def test_pen_is_derived_from_z(state):
    """profile has pen_up_z=5, pen_down_z=0."""
    state.apply(status_event("<Idle|MPos:0.000,0.000,5.000|FS:0,0>"))
    assert state.snapshot()["pen"] == "up"
    state.apply(status_event("<Idle|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["pen"] == "down"
    state.apply(status_event("<Idle|MPos:0.000,0.000,2.500|FS:0,0>"))
    assert state.snapshot()["pen"] == "moving"


def test_alarm_reply_sets_the_alarm_field(state):
    state.apply(reply_event("ALARM:2"))
    snap = state.snapshot()
    assert snap["alarm"] is not None
    assert "Soft limit" in snap["alarm"]


def test_error_reply_sets_the_error_field(state):
    state.apply(reply_event("error:20"))
    assert state.snapshot()["error"] is not None


def test_a_good_status_clears_a_stale_error(state):
    state.apply(reply_event("error:20"))
    assert state.snapshot()["error"] is not None
    state.apply(status_event("<Idle|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["error"] is None


def test_alarm_survives_until_the_state_leaves_alarm(state):
    state.apply(reply_event("ALARM:2"))
    state.apply(status_event("<Alarm|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["alarm"] is not None
    state.apply(status_event("<Idle|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["alarm"] is None


def test_console_records_both_directions(state):
    state.apply(SentEvent("$J=G91 G21 X10 F1000"))
    state.apply(reply_event("ok"))
    tail = state.console_tail()
    assert tail[0]["direction"] == "tx"
    assert tail[1]["direction"] == "rx"


def test_console_is_capped(state):
    for i in range(2500):
        state.apply(SentEvent(f"G0 X{i}"))
    tail = state.console_tail()
    assert len(tail) <= 2000
    assert tail[-1]["text"].endswith("2499")


def test_status_reports_do_not_flood_the_console(state):
    """Polling at 5 Hz would drown the log in status lines."""
    for _ in range(20):
        state.apply(status_event("<Idle|MPos:0.000,0.000,0.000|FS:0,0>"))
    assert state.console_tail() == []


def test_disconnect_resets_the_connection(state):
    state.set_connection("COM5", 115200, "Grbl 1.1h")
    assert state.snapshot()["conn"]["connected"] is True
    state.apply(DisconnectedEvent("cable pulled"))
    snap = state.snapshot()
    assert snap["conn"]["connected"] is False
    assert snap["state"] == "Disconnected"
    assert "cable pulled" in snap["error"]


def test_seq_increases_on_every_change(state):
    first = state.snapshot()["seq"]
    state.apply(status_event("<Idle|MPos:1.000,0.000,0.000|FS:0,0>"))
    assert state.snapshot()["seq"] > first


def test_dirty_flag_tracks_unbroadcast_changes(state):
    state.apply(status_event("<Idle|MPos:1.000,0.000,0.000|FS:0,0>"))
    assert state.dirty is True
    state.snapshot()
    assert state.dirty is False


def test_console_head_seq_tracks_the_latest_console_line(state):
    assert state.console_head_seq() == -1
    state.apply(SentEvent("G0 X1"))
    first = state.console_head_seq()
    assert first != -1
    tail = state.console_tail()
    assert first == tail[-1]["seq"]
    state.apply(reply_event("ok"))
    second = state.console_head_seq()
    assert second > first
    tail = state.console_tail()
    assert second == tail[-1]["seq"]


def test_snapshot_is_never_torn_under_concurrent_apply(state):
    """apply() writes several fields non-atomically. A snapshot() taken from
    another thread mid-write must never observe a mixture of an old field
    and a new field — it must always be one internally-consistent report.
    """
    event_run = status_event("<Run|MPos:1.000,1.000,1.000|FS:0,0>")
    event_idle = status_event("<Idle|MPos:2.000,2.000,2.000|FS:0,0>")

    stop = threading.Event()
    started = threading.Event()
    failures: list[dict] = []

    def hammer():
        toggle = False
        while not stop.is_set():
            state.apply(event_run if toggle else event_idle)
            toggle = not toggle
            started.set()

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        t = threading.Thread(target=hammer, daemon=True)
        t.start()
        started.wait(timeout=2)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            snap = state.snapshot()
            is_run = snap["state"] == "Run" and snap["mpos"] == [1.0, 1.0, 1.0]
            is_idle = snap["state"] == "Idle" and snap["mpos"] == [2.0, 2.0, 2.0]
            if not (is_run or is_idle):
                failures.append(snap)
        stop.set()
        t.join(timeout=2)
    finally:
        sys.setswitchinterval(old_interval)

    assert failures == []

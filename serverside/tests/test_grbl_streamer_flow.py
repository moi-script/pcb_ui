from __future__ import annotations

import sys
import time

from grbl.streamer import DisconnectedEvent, Streamer
from grbl.sim import GrblSim


def run_until_idle(streamer: Streamer, sim: GrblSim, max_steps: int = 20000) -> int:
    """Drive sim and streamer in lockstep. Returns the number of steps taken."""
    for step in range(max_steps):
        streamer.pump()
        sim.tick(0.002)
        if not streamer._outbox and streamer.pending_bytes == 0 and sim.state == "Idle":
            return step
    raise AssertionError("never went idle")


def test_never_exceeds_the_rx_buffer():
    """The simulator asserts on overflow, so simply completing proves this."""
    sim = GrblSim(rx_buffer=128, planner_blocks=15)
    s = Streamer(sim, rx_buffer=128)
    for i in range(200):
        s.send_line(f"G1 X{i % 50}.000 Y{i % 30}.000 F1000")
    # Long zig-zags at the firmware's 500 mm/min cap: give it simulated time.
    run_until_idle(s, sim, max_steps=200_000)
    assert sim.peak_rx_used <= 128


def test_keeps_more_than_one_line_in_flight():
    """Character counting exists to keep the planner fed. If only one line is
    ever outstanding we have accidentally written send-response."""
    sim = GrblSim(rx_buffer=128, planner_blocks=15)
    s = Streamer(sim, rx_buffer=128)
    for i in range(50):
        s.send_line(f"G1 X{i}.000 F1000")
    s.pump()
    assert len(s._pending) > 1


def test_every_line_is_delivered_in_order():
    sim = GrblSim(rx_buffer=128, planner_blocks=15)
    sent: list[str] = []
    original = sim._line
    sim._line = lambda ln: (sent.append(ln), original(ln))[1]  # type: ignore[method-assign]

    s = Streamer(sim, rx_buffer=128)
    expected = [f"G1 X{i}.000 F1000" for i in range(100)]
    for line in expected:
        s.send_line(line)
    run_until_idle(s, sim)
    assert sent == expected


def test_a_smaller_buffer_still_completes():
    sim = GrblSim(rx_buffer=48, planner_blocks=4)
    s = Streamer(sim, rx_buffer=48)
    for i in range(60):
        s.send_line(f"G1 X{i % 20}.000 F1000")
    run_until_idle(s, sim)
    assert sim.peak_rx_used <= 48


def test_polling_thread_produces_status_events():
    sim = GrblSim()
    events: list = []
    s = Streamer(sim, on_event=events.append)
    s.start(poll_hz=20.0)
    try:
        deadline = time.time() + 1.0
        while time.time() < deadline:
            sim.tick(0.01)
            time.sleep(0.01)
    finally:
        s.stop()
    from grbl.streamer import StatusEvent
    assert len([e for e in events if isinstance(e, StatusEvent)]) >= 5


def test_unanswered_polls_raise_a_disconnect():
    sim = GrblSim()
    sim.stop_answering_status = True
    events: list = []
    s = Streamer(sim, on_event=events.append)
    s.max_missed_polls = 3  # the default waits five seconds; the rule is the same
    s.start(poll_hz=20.0)
    try:
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if any(isinstance(e, DisconnectedEvent) for e in events):
                break
            time.sleep(0.02)
    finally:
        s.stop()
    assert any(isinstance(e, DisconnectedEvent) for e in events)
    # A controller that stopped answering may still be moving: it is reset,
    # and the port is released so the next Connect can open it.
    assert sim._closed


def test_the_watchdog_tolerates_a_few_seconds_of_silence():
    s = Streamer(GrblSim())
    assert s.max_missed_polls * s.poll_timeout >= 5.0


def test_send_line_is_safe_while_the_poll_loop_runs():
    """The lock exists so an outside thread calling the PUBLIC pump()
    directly (what Task 7+ does to force a read from a request thread)
    cannot interleave with the background loop's own locked pump()/
    send_realtime() calls. This calls s.pump() itself from the main thread
    -- send_line() alone would not exercise that path, since send_line()
    and the loop's pump() call were already mutually exclusive before this
    fix; the vulnerable path is a second, independent caller of pump().

    The lock's critical sections here (a check against pending_bytes
    followed by a write) are only a few bytecodes wide, so under CPython's
    default GIL switch interval (5ms) an unlocked pump() only rarely gets
    interrupted mid-section -- confirmed by hand: 10+ runs of this body
    against a deliberately-unlocked pump() at the default interval did not
    fail. Lowering the switch interval for the duration of this test (and
    restoring it in finally) makes thread handoffs far more frequent without
    changing what either thread does, and reliably reproduces the race
    against an unlocked pump() while remaining a no-op against a correctly
    locked one. A small rx_buffer and non-uniform line lengths leave little
    slack, so a lost update trips GrblSim's own
    `assert self._rx_used <= self.rx_buffer` immediately."""
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(0.00001)
    try:
        sim = GrblSim(rx_buffer=48, planner_blocks=4)
        events: list = []
        s = Streamer(sim, rx_buffer=48, on_event=events.append)
        s.start(poll_hz=50.0)
        try:
            deadline = time.time() + 1.0
            i = 0
            while time.time() < deadline:
                length = (i % 20) + 1
                s.send_line(f"G1 X{i % 999}.{'0' * length} F1000")
                s.pump()
                sim.tick(0.001)
                i += 1
        finally:
            s.stop()
    finally:
        sys.setswitchinterval(old_interval)
    assert not any(isinstance(e, DisconnectedEvent) for e in events)
    assert sim.peak_rx_used <= 48


def test_stop_is_idempotent():
    sim = GrblSim()
    s = Streamer(sim)
    s.start()
    s.stop()
    s.stop()  # must not raise

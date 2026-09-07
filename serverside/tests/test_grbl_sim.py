from __future__ import annotations

from grbl.protocol import State, parse_status
from grbl.sim import GrblSim


def drain(sim: GrblSim) -> list[str]:
    return [ln for ln in sim.read_available().decode().splitlines() if ln]


def test_emits_banner_on_wake():
    sim = GrblSim()
    sim.write(b"\r\n")
    lines = drain(sim)
    assert any(ln.startswith("Grbl 1.1") for ln in lines)


def test_answers_status_query_with_a_report():
    sim = GrblSim()
    sim.write(b"?")
    lines = drain(sim)
    status = parse_status(lines[-1])
    assert status is not None
    assert status.state is State.IDLE


def test_answers_a_motion_line_with_ok():
    sim = GrblSim()
    sim.write(b"G0 X10 Y10 F1000\n")
    assert "ok" in drain(sim)


def test_rejects_unknown_command_with_a_real_error():
    sim = GrblSim()
    sim.write(b"$nonsense\n")
    assert any(ln.startswith("error:") for ln in drain(sim))


def test_dollar_dollar_dumps_settings():
    sim = GrblSim()
    sim.write(b"$$\n")
    lines = drain(sim)
    assert any(ln.startswith("$100=") for ln in lines)
    assert lines[-1] == "ok"


def test_position_integrates_over_time():
    sim = GrblSim()
    sim.write(b"G0 X10 Y0 F600\n")   # 600 mm/min = 10 mm/s
    drain(sim)
    sim.tick(0.5)
    assert 4.0 < sim.pos[0] < 6.0     # about halfway
    assert sim.state == "Run"
    sim.tick(1.0)
    assert abs(sim.pos[0] - 10.0) < 1e-6
    assert sim.state == "Idle"


def test_soft_reset_returns_to_alarm_with_a_banner():
    sim = GrblSim()
    sim.write(b"\x18")
    lines = drain(sim)
    assert any(ln.startswith("Grbl 1.1") for ln in lines)
    assert sim.state == "Alarm"


def test_feed_hold_and_resume():
    sim = GrblSim()
    sim.write(b"G0 X100 F600\n")
    drain(sim)
    sim.tick(0.2)
    sim.write(b"!")
    assert sim.state == "Hold"
    frozen = sim.pos[0]
    sim.tick(1.0)
    assert sim.pos[0] == frozen       # no motion while held
    sim.write(b"~")
    assert sim.state == "Run"


def test_unlock_clears_alarm():
    sim = GrblSim()
    sim.write(b"\x18")
    drain(sim)
    assert sim.state == "Alarm"
    sim.write(b"$X\n")
    assert "ok" in drain(sim)
    assert sim.state == "Idle"


def test_motion_is_refused_while_in_alarm():
    sim = GrblSim()
    sim.write(b"\x18")
    drain(sim)
    sim.write(b"G0 X10\n")
    assert any(ln == "error:9" for ln in drain(sim))


def test_soft_limit_violation_raises_alarm_2():
    sim = GrblSim(travel=(300.0, 200.0, 5.0))
    sim.write(b"G0 X400\n")
    lines = drain(sim)
    assert any(ln.startswith("ALARM:2") for ln in lines)
    assert sim.state == "Alarm"


def test_planner_backpressure_withholds_ok_when_full():
    """With the planner full, `ok` is withheld — which is what makes the
    host's character-counting accounting observable."""
    sim = GrblSim(planner_blocks=2)
    for _ in range(5):
        sim.write(b"G1 X1 F100\n")
    oks = [ln for ln in drain(sim) if ln == "ok"]
    assert len(oks) < 5


def test_rx_buffer_overflow_is_an_assertion_failure():
    """The sim polices the host: exceeding the RX buffer is a host bug."""
    sim = GrblSim(rx_buffer=32, planner_blocks=1)
    try:
        for _ in range(50):
            sim.write(b"G1 X1 Y1 Z1 F1000\n")
    except AssertionError as exc:
        assert "RX buffer" in str(exc)
    else:
        raise AssertionError("sim should have caught the overflow")


def test_status_can_be_made_to_stop_answering():
    sim = GrblSim()
    sim.stop_answering_status = True
    sim.write(b"?")
    assert drain(sim) == []


def test_error_can_be_injected_on_a_chosen_line():
    sim = GrblSim()
    sim.error_on_line = 2
    sim.write(b"G0 X1\n")
    assert "ok" in drain(sim)
    sim.write(b"G0 X2\n")
    assert any(ln.startswith("error:") for ln in drain(sim))


def test_every_line_gets_exactly_one_ok_after_backpressure():
    """Regression test for _finish_block's ok-release bookkeeping.

    Sends more lines than the planner can hold at once (so some are acked
    immediately at enqueue and some are withheld), then drains motion with
    tick() until the queue empties. Every line must get exactly one `ok` —
    not zero (a lost ack, which hangs the host) and not two (a double ack,
    which hands the host free buffer credit it never spent). Line lengths
    are deliberately non-uniform so a leftover/duplicated rx_cost in the
    scalar `_rx_used` pool would actually show up.
    """
    sim = GrblSim(planner_blocks=2)
    lines = [
        b"G1 X1 F100\n",
        b"G1 X12 F100\n",
        b"G1 X103 F100\n",
        b"G1 X4 F100\n",
        b"G1 X105 F100\n",
    ]
    for line in lines:
        sim.write(line)

    oks = [ln for ln in drain(sim) if ln == "ok"]

    ticks = 0
    while sim._queue and ticks < 1000:
        sim.tick(1.0)
        oks += [ln for ln in drain(sim) if ln == "ok"]
        ticks += 1

    assert not sim._queue
    assert len(oks) == len(lines)
    assert sim._rx_used == 0


def test_queued_relative_moves_accumulate():
    """Real GRBL resolves a G91 offset against the planner's END position,
    not the live position, so back-to-back queued relative jogs stack on
    top of each other rather than overwriting one another.

    Three X+100 relative jogs are issued back to back with a slow feed, so
    all three are still queued (none have executed) by the time the last
    one is parsed. With the live-position bug, each is resolved against
    wherever self.pos happens to be (0 at parse time, since nothing has
    moved yet), so they collide and the final position is only +100. Fixed,
    they must accumulate to +300.
    """
    sim = GrblSim(planner_blocks=15)
    sim.write(b"$J=G91 G21 X100 F60\n")
    sim.write(b"$J=G91 G21 X100 F60\n")
    sim.write(b"$J=G91 G21 X100 F60\n")
    drain(sim)

    ticks = 0
    while sim._queue and ticks < 100000:
        sim.tick(0.05)
        ticks += 1

    assert abs(sim.pos[0] - 300.0) < 1e-6

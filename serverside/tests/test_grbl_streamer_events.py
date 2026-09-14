from __future__ import annotations

import time

from grbl.protocol import Realtime, State
from grbl.streamer import (
    DisconnectedEvent,
    ReplyEvent,
    SentEvent,
    StatusEvent,
    Streamer,
)
from grbl.sim import GrblSim


def collect() -> tuple[list, callable]:
    events: list = []
    return events, events.append


def test_banner_arrives_as_a_reply_event():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    sim.write(b"\r\n")
    s.pump()
    banners = [e for e in events if isinstance(e, ReplyEvent) and e.reply.kind == "banner"]
    assert banners


def test_status_query_produces_a_status_event():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    s.send_realtime(Realtime.STATUS)
    s.pump()
    statuses = [e for e in events if isinstance(e, StatusEvent)]
    assert statuses
    assert statuses[-1].status.state is State.IDLE


def test_sent_lines_are_reported_before_their_reply():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    s.send_line("G0 X1 Y1 F1000")
    s.pump()
    kinds = [type(e).__name__ for e in events]
    assert kinds.index("SentEvent") < kinds.index("ReplyEvent")


def test_realtime_bytes_are_not_counted_against_the_buffer():
    sim = GrblSim()
    s = Streamer(sim)
    before = s.pending_bytes
    s.send_realtime(Realtime.STATUS)
    s.send_realtime(Realtime.FEED_HOLD)
    assert s.pending_bytes == before


def test_partial_lines_are_buffered_until_complete():
    """Serial reads split lines anywhere; the assembler must not lose them."""
    class Chunked:
        def __init__(self) -> None:
            self.chunks = [b"<Idle|MPos:1.000,", b"2.000,3.000|FS:0,0>\r\n"]
        def write(self, data: bytes) -> None: ...
        def read_available(self) -> bytes:
            return self.chunks.pop(0) if self.chunks else b""
        def close(self) -> None: ...

    events, sink = collect()
    s = Streamer(Chunked(), on_event=sink)
    s.pump()
    assert not [e for e in events if isinstance(e, StatusEvent)]
    s.pump()
    statuses = [e for e in events if isinstance(e, StatusEvent)]
    assert statuses[-1].status.mpos == (1.0, 2.0, 3.0)


class Flaky:
    """The simulator behind a port that fails a few reads and writes.

    What a CH340 does when a servo or stepper kicks noise onto the USB
    line: Windows fails one call, and the next one works."""

    def __init__(self, write_failures: int = 0, read_failures: int = 0) -> None:
        self.sim = GrblSim()
        self.write_failures = write_failures
        self.read_failures = read_failures

    def write(self, data: bytes) -> None:
        if self.write_failures:
            self.write_failures -= 1
            raise OSError("WriteFile failed (PermissionError(13, 'The device does not recognize the command.'))")
        self.sim.write(data)

    def read_available(self) -> bytes:
        if self.read_failures:
            self.read_failures -= 1
            raise OSError("ClearCommError failed (PermissionError(13, 'The device does not recognize the command.'))")
        return self.sim.read_available()

    def close(self) -> None:
        self.sim.close()


def test_a_failed_write_is_retried_not_treated_as_a_disconnect():
    port = Flaky(write_failures=2)
    events, sink = collect()
    s = Streamer(port, on_event=sink)
    s.send_line("G0 X1")
    for _ in range(20):
        s.pump()
        port.sim.tick(0.01)
    assert s.connected
    assert not [e for e in events if isinstance(e, DisconnectedEvent)]
    # The line was not lost: it went out once the port recovered, and its
    # `ok` came back.
    assert [e.line for e in events if isinstance(e, SentEvent)] == ["G0 X1"]
    assert [e for e in events if isinstance(e, ReplyEvent) and e.reply.kind == "ok"]
    assert s.quiet


def test_a_failed_read_is_not_treated_as_a_disconnect():
    port = Flaky(read_failures=3)
    events, sink = collect()
    s = Streamer(port, on_event=sink)
    s.send_realtime(Realtime.STATUS)
    for _ in range(10):
        s.pump()
    assert s.connected
    assert [e for e in events if isinstance(e, StatusEvent)]


def test_a_port_that_keeps_failing_is_disconnected():
    class Dead:
        def write(self, data: bytes) -> None:
            raise OSError("device disappeared")
        def read_available(self) -> bytes:
            raise OSError("device disappeared")
        def close(self) -> None: ...

    events, sink = collect()
    s = Streamer(Dead(), on_event=sink)
    s.error_grace = 0.05
    s.send_line("G0 X1")
    s.pump()
    assert s.connected  # one failure is not a verdict
    time.sleep(0.1)
    s.pump()
    dropped = [e for e in events if isinstance(e, DisconnectedEvent)]
    assert dropped
    assert "device disappeared" in dropped[0].reason


def test_the_error_grace_rides_out_a_usb_hiccup():
    assert Streamer(GrblSim()).error_grace >= 2.0


def test_error_reply_is_surfaced_with_its_human_text():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    s.send_line("$nonsense")
    s.pump()
    errors = [e for e in events if isinstance(e, ReplyEvent) and e.reply.kind == "error"]
    assert errors
    assert errors[0].reply.text


def test_a_control_byte_is_retried_when_its_write_fails():
    """Pause, Stop and E-stop cannot be allowed to vanish into a USB hiccup
    the way a lost `?` harmlessly can."""
    class Recording:
        def __init__(self) -> None:
            self.failures = 2
            self.written: list[bytes] = []
        def write(self, data: bytes) -> None:
            if self.failures:
                self.failures -= 1
                raise OSError("Write timeout")
            self.written.append(data)
        def read_available(self) -> bytes:
            return b""
        def close(self) -> None: ...

    port = Recording()
    s = Streamer(port)
    s.send_realtime(Realtime.SOFT_RESET)
    assert port.written == [Realtime.SOFT_RESET]
    assert s.connected

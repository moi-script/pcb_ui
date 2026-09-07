from __future__ import annotations

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


def test_write_failure_produces_a_disconnected_event():
    class Dead:
        def write(self, data: bytes) -> None:
            raise OSError("device disappeared")
        def read_available(self) -> bytes:
            return b""
        def close(self) -> None: ...

    events, sink = collect()
    s = Streamer(Dead(), on_event=sink)
    s.send_line("G0 X1")
    s.pump()
    dropped = [e for e in events if isinstance(e, DisconnectedEvent)]
    assert dropped
    assert "device disappeared" in dropped[0].reason


def test_error_reply_is_surfaced_with_its_human_text():
    sim = GrblSim()
    events, sink = collect()
    s = Streamer(sim, on_event=sink)
    s.send_line("$nonsense")
    s.pump()
    errors = [e for e in events if isinstance(e, ReplyEvent) and e.reply.kind == "error"]
    assert errors
    assert errors[0].reply.text

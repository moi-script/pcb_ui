"""The single authoritative picture of the machine.

Everything the browser shows — readout, state badge, pen indicator, console,
connection light — is a field of one snapshot built here. There is deliberately
no second source for any of it, so the panels cannot drift apart.

Mutated only by events from the streamer thread; read by the WebSocket
broadcaster. That makes it testable by feeding it a list of events.

Threading: `apply()` is called from the streamer's background polling thread
and from request threads (a SentEvent fires from whichever thread called
send_line), always while the streamer's own lock is already held. `snapshot()`
and `console_tail()` are called from FastAPI request handlers on other threads
entirely, holding no lock. `apply()` writes several fields non-atomically, so
without a lock a concurrent snapshot() could observe a torn read — position
from a new report, machine state from the old one. An RLock around each
public method's body prevents that. Because `apply()` runs while the
streamer's lock is already held, this lock is always acquired second: nothing
here may call back into the streamer (no stop(), no send_line) or a lock
cycle could deadlock. `apply()` itself must stay fast — it is on the hot path
of both the status poll and the G-code stream. It does not swallow
exceptions: every field access it makes is already guarded by the parsers
upstream (`_vec3` pads vectors to length 3, `parse_status` never yields an
unknown state, `ov` is always padded), so nothing here is expected to raise.
If it ever does, the streamer's own dispatch loop converts that into a
visible disconnect rather than a silent, permanently stale snapshot.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable

from grbl.protocol import resolve_positions
from grbl.streamer import (
    DisconnectedEvent,
    ReplyEvent,
    SentEvent,
    StatusEvent,
)
from grbl.profile import Profile

CONSOLE_LIMIT = 2000
PEN_EPS = 0.01


@dataclass
class ConsoleLine:
    direction: str  # "tx" | "rx" | "sys"
    text: str
    kind: str       # "ok" | "error" | "alarm" | "message" | "banner" | "settings" | "line"
    seq: int


class MachineState:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self._lock = threading.RLock()

        # Filled in by machine.Session with the live job's snapshot function.
        # A callable rather than the Job itself: MachineState sits below the
        # job in the stack and must not import it.
        self.job_source: Callable[[], dict | None] | None = None

        self.connected = False
        self.port: str | None = None
        self.baud = profile.baud
        self.firmware = ""

        self.state = "Disconnected"
        self.mpos = [0.0, 0.0, 0.0]
        self.wpos = [0.0, 0.0, 0.0]
        self.wco: list[float] = [0.0, 0.0, 0.0]
        self._cached_wco: tuple[float, float, float] | None = None
        self.feed = 0.0
        self.spindle = 0.0
        self.ov = [100, 100, 100]

        self.alarm: str | None = None
        self.error: str | None = None

        self._console: deque[ConsoleLine] = deque(maxlen=CONSOLE_LIMIT)
        self._seq = 0
        self.dirty = False

        # Monotonic count of status reports actually APPLIED via
        # _apply_status -- incremented there and nowhere else. Deliberately
        # not `_seq`, which also advances on console lines (SentEvent,
        # ReplyEvent, DisconnectedEvent), so it can tick forward with no new
        # status report having arrived at all.
        #
        # What this counter DOES prove: a report was APPLIED after the
        # moment a given snapshot of it was taken. What it does NOT prove --
        # and round 3 wrongly claimed it did -- is that the report was
        # GENERATED after that moment. A report already in flight when the
        # snapshot is taken advances this counter the instant it lands,
        # while still describing pre-snapshot reality. server/main.py's
        # Session.settle() therefore treats it as one NECESSARY condition
        # among several, never a sufficient one; the condition that actually
        # proves the queue drained is `status_quiet` below (see the round-4
        # section of postfix-jog-envelope-report.md).
        self._status_seq = 0

        # Whether the most recently applied status report was dispatched
        # while the streamer held zero unacknowledged lines -- see
        # StatusEvent.quiet in grbl/streamer.py. Carried on
        # the event (rather than read from the streamer separately) so it
        # stays welded to the report it describes and travels through the
        # same atomic snapshot() as `state` and `mpos`.
        self.status_quiet = False

    # --- mutation ----------------------------------------------------------

    def _touch(self) -> None:
        self._seq += 1
        self.dirty = True

    def set_connection(self, port: str | None, baud: int, firmware: str) -> None:
        with self._lock:
            self.connected = port is not None
            self.port = port
            self.baud = baud
            self.firmware = firmware
            if self.connected:
                self._log("sys", f"connected to {port} at {baud} — {firmware}", "message")
            else:
                self.state = "Disconnected"
                self._log("sys", "disconnected", "message")
            self._touch()

    def apply(self, event: object) -> None:
        with self._lock:
            if isinstance(event, StatusEvent):
                self._apply_status(event)
            elif isinstance(event, ReplyEvent):
                self._apply_reply(event)
            elif isinstance(event, SentEvent):
                self._log("tx", event.line, "line")
                self._touch()
            elif isinstance(event, DisconnectedEvent):
                self.connected = False
                self.port = None
                self.state = "Disconnected"
                self.error = f"connection lost: {event.reason}"
                self._log("sys", self.error, "error")
                self._touch()

    def _apply_status(self, event: StatusEvent) -> None:
        status = event.status
        mpos, wpos, wco = resolve_positions(status, self._cached_wco)
        if status.wco is not None:
            self._cached_wco = status.wco

        self.mpos = list(mpos)
        self.wpos = list(wpos)
        self.wco = list(wco)
        self.state = (
            f"{status.state.value}:{status.substate}"
            if status.substate is not None and status.state.value == "Hold"
            else status.state.value
        )
        self.feed = status.feed
        self.spindle = status.spindle
        if status.ov is not None:
            self.ov = list(status.ov)

        # A report arriving at all means the last error is history.
        self.error = None
        if not self.state.startswith("Alarm"):
            self.alarm = None

        self.connected = True
        self._touch()
        self._status_seq += 1
        self.status_quiet = event.quiet
        # Status reports are NOT logged: at 5 Hz they would bury everything else.

    def _apply_reply(self, event: ReplyEvent) -> None:
        reply = event.reply
        if reply.kind == "error":
            self.error = reply.text
        elif reply.kind == "alarm":
            self.alarm = reply.text
        elif reply.kind == "banner":
            self.firmware = reply.text

        self._log("rx", reply.text, reply.kind)
        self._touch()

    def _log(self, direction: str, text: str, kind: str) -> None:
        self._console.append(ConsoleLine(direction, text, kind, self._seq))

    # --- reads -------------------------------------------------------------

    def _pen(self) -> str:
        z = self.wpos[2]
        if abs(z - self.profile.pen_down_z) < PEN_EPS:
            return "down"
        if abs(z - self.profile.pen_up_z) < PEN_EPS:
            return "up"
        return "moving"

    def snapshot(self) -> dict:
        with self._lock:
            self.dirty = False
            return {
                "conn": {
                    "connected": self.connected,
                    "port": self.port,
                    "baud": self.baud,
                    "firmware": self.firmware,
                    "profile": self.profile.name,
                    "penMode": self.profile.pen_mode,
                    "travel": [
                        self.profile.travel_x,
                        self.profile.travel_y,
                        self.profile.travel_z,
                    ],
                },
                "state": self.state,
                "mpos": list(self.mpos),
                "wpos": list(self.wpos),
                "wco": list(self.wco),
                "feed": self.feed,
                "spindle": self.spindle,
                "ov": {"feed": self.ov[0], "rapid": self.ov[1], "spindle": self.ov[2]},
                "pen": self._pen(),
                "alarm": self.alarm,
                "error": self.error,
                "job": self.job_source() if self.job_source else None,
                "seq": self._seq,
                # Both are safety bookkeeping for server/main.py's jog
                # gating, included here (rather than exposed as separate
                # accessors) so the jog route can derive EVERY input to its
                # decision from one atomic read: three separate reads of
                # `state`, `mpos` and the counter can straddle an incoming
                # report and mix a newer counter with older coordinates.
                "statusSeq": self._status_seq,
                "statusQuiet": self.status_quiet,
            }

    def console_tail(self, n: int = CONSOLE_LIMIT) -> list[dict]:
        with self._lock:
            lines = list(self._console)[-n:]
        return [
            {"direction": l.direction, "text": l.text, "kind": l.kind, "seq": l.seq}
            for l in lines
        ]

    def console_head_seq(self) -> int:
        """Highest seq present in the console, or -1 when it is empty."""
        with self._lock:
            return self._console[-1].seq if self._console else -1

    def status_seq(self) -> int:
        """Monotonic count of status reports applied so far.

        Only `_apply_status` increments this. It proves a report was
        APPLIED after a given earlier moment -- nothing more. A report
        already in flight at that moment advances it too, so this is never
        on its own evidence that the report describes reality after that
        moment (see the comment on `_status_seq` in __init__).
        """
        with self._lock:
            return self._status_seq

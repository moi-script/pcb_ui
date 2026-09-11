"""Owns the serial port: reads replies, sends lines under flow control.

Split from grbl.py deliberately — everything here touches a transport, and
everything in grbl.py does not. The transport is a Protocol rather than a
pyserial object so the simulator can stand in for hardware with no mocking.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol

from grbl.protocol import Realtime, Reply, Status, parse_reply, parse_status


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read_available(self) -> bytes: ...
    def close(self) -> None: ...


@dataclass
class StatusEvent:
    status: Status
    # Was the streamer holding zero unacknowledged lines at the moment this
    # report was DISPATCHED (both `_pending` and `_outbox` empty)? Computed
    # in `Streamer._dispatch`, which parses the byte stream strictly in
    # order, so `_pending` at that point reflects exactly the lines whose
    # `ok`/`error` had NOT yet appeared ahead of this report in the stream.
    #
    # GRBL emits `ok` for a line only once it has parsed and queued it, and
    # its serial output is FIFO. So "quiet at dispatch" means every line we
    # had sent was already parsed and queued by the controller BEFORE it
    # generated this report -- which, combined with the report saying
    # `Idle`, is a statement about the DATA that genuinely means "the queue
    # drained", not a statement about arrival timing. `server/main.py`'s
    # Session.settle() uses it to lift a taint (see the round-4 section of
    # .superpowers/sdd/2026-08-25-machine-control-slice-1/postfix-jog-envelope-report.md).
    #
    # Defaulted so existing constructions (`StatusEvent(parsed)` in tests)
    # keep working; the default is the conservative value.
    quiet: bool = False


@dataclass
class ReplyEvent:
    reply: Reply


@dataclass
class SentEvent:
    line: str


@dataclass
class DisconnectedEvent:
    reason: str


class Streamer:
    def __init__(
        self,
        transport: Transport,
        rx_buffer: int = 128,
        on_event: Callable[[object], None] | None = None,
        lock: "threading.RLock | None" = None,
    ) -> None:
        # `lock` is the shared link lock (see machine.Session.connect). The
        # streamer, the job and the machine state all guard themselves with
        # ONE re-entrant lock, because they call each other's callbacks in
        # both directions: the streamer dispatches a reply into the job
        # while holding this, and the job feeds the next lines back into the
        # streamer while holding it too. With a lock each, those two paths
        # take them in opposite orders and the server deadlocks mid-plot.
        # One lock has no order to get wrong. It is coarse, and deliberately
        # so: there is one serial port and one machine, so this work is
        # already serial. Defaults to a private lock so a Streamer built on
        # its own (tests, the CLI) still guards itself.
        self.transport = transport
        self.rx_buffer = rx_buffer
        self._on_event = on_event or (lambda _e: None)

        self._partial = ""
        self._pending: deque[int] = deque()   # byte cost of each unacknowledged line
        self._outbox: deque[str] = deque()    # lines waiting for buffer space
        self.connected = True

        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = lock if lock is not None else threading.RLock()
        self._last_poll = 0.0
        self._awaiting_status_since: float | None = None
        self.missed_polls = 0
        self.poll_timeout = 0.5
        self.max_missed_polls = 3

    # --- outbound ----------------------------------------------------------

    @property
    def pending_bytes(self) -> int:
        return sum(self._pending)

    @property
    def quiet(self) -> bool:
        """True when no line we sent is still unaccounted for.

        `_pending` holds the lines written but not yet acknowledged by an
        `ok`/`error`; `_outbox` holds lines accepted by `send_line` but not
        yet written because the RX budget was full. Both empty means the
        controller has parsed and queued everything we handed it and there
        is nothing of ours left to go out.

        Exposed as a property that takes this object's own lock so callers
        never reach into `_pending`/`_outbox` themselves. Takes only
        `Streamer._lock` and calls nothing else, so it is safe to read from
        a request thread that holds no other lock (and callers must read it
        BEFORE taking any leaf lock of their own, to keep the
        `Streamer._lock` -> `MachineState._lock` -> leaf ordering).
        """
        with self._lock:
            return not self._pending and not self._outbox

    def clear_outbox(self) -> int:
        """Drop every line accepted but not yet written. Returns how many.

        Lines already written are the controller's business and cannot be
        recalled — that is what a feed hold or a soft reset is for. This
        covers the rest of the file, which is otherwise still on its way out
        after the operator pressed Stop.
        """
        with self._lock:
            dropped = len(self._outbox)
            self._outbox.clear()
            return dropped

    def send_realtime(self, byte: bytes) -> None:
        """Send a single realtime byte.

        Deliberately a different method from send_line with a different
        argument type: realtime bytes bypass the planner queue, get no `ok`,
        and must never touch the pending-byte accounting.
        """
        with self._lock:
            if not self.connected:
                return
            try:
                self.transport.write(byte)
            except OSError as exc:
                self._drop(str(exc))

    def send_line(self, line: str) -> None:
        """Queue a line for transmission under flow control."""
        with self._lock:
            self._outbox.append(line.strip())
            self._flush_outbox()

    def _flush_outbox(self) -> None:
        while self._outbox and self.connected:
            line = self._outbox[0]
            cost = len(line) + 1
            if self.pending_bytes + cost >= self.rx_buffer:
                return  # no room; wait for an `ok` to free some
            self._outbox.popleft()
            try:
                self.transport.write((line + "\n").encode())
            except OSError as exc:
                self._drop(str(exc))
                return
            self._pending.append(cost)
            self._on_event(SentEvent(line))

    # --- inbound -----------------------------------------------------------

    def pump(self) -> None:
        """Read whatever is available and dispatch it. One non-blocking step."""
        with self._lock:
            if not self.connected:
                return
            try:
                chunk = self.transport.read_available()
            except OSError as exc:
                self._drop(str(exc))
                return

            if chunk:
                self._partial += chunk.decode(errors="replace")
                while "\n" in self._partial:
                    raw, _, self._partial = self._partial.partition("\n")
                    self._dispatch(raw.strip())

            self._flush_outbox()

    def _dispatch(self, line: str) -> None:
        if not line:
            return

        status = parse_status(line)
        if status is not None:
            self._awaiting_status_since = None
            self.missed_polls = 0
            # Snapshot "nothing of ours is unaccounted for" AT DISPATCH, in
            # stream order, and hand it to the consumer as part of the
            # report itself. Reading it later, separately, would not be the
            # same statement: it would describe some other moment. See
            # StatusEvent.quiet. Both reads are plain container truth-tests
            # on state this method already owns under `_lock` -- no
            # blocking, no raising, no call back out.
            self._on_event(
                StatusEvent(status, quiet=not self._pending and not self._outbox)
            )
            return

        reply = parse_reply(line)
        if reply is None:
            return

        # `ok` and `error` both close out exactly one queued line.
        if reply.kind in ("ok", "error") and self._pending:
            self._pending.popleft()

        if reply.kind in ("alarm", "banner"):
            # An alarm wipes the controller's planner and RX buffer: GRBL
            # discards whatever it was holding and answers nothing further
            # for those lines. The simulator behaves the same way (see
            # GrblSim._motion's over-travel path, which emits ALARM:2 and
            # NO `ok`). Without this, every line outstanding at the moment
            # of the alarm stays in `_pending` forever, and `quiet` -- the
            # data property Session.settle() lifts a taint on -- could
            # never become true again for the rest of the session: a
            # permanent jog lockout, fail-safe but unusable. Clearing here
            # matches what the controller itself just did.
            #
            # A banner means the same thing and must be treated the same
            # way: the controller has RESTARTED, so everything we sent is
            # gone by definition. It matters because a SOFT RESET (^X, the
            # E-STOP button) announces itself with a banner, and not
            # necessarily with an alarm -- real GRBL only adds `ALARM:3`
            # ("Reset while in motion") when it was actually moving, so a
            # reset while Idle with lines still unparsed in the
            # controller's RX buffer would otherwise leave those lines
            # charged against `_pending` for the rest of the session,
            # locking jogging out permanently (round 5, F1). Safe at
            # connect time too, where the banner is how we detect the
            # controller at all: `_pending` is empty there, so this is a
            # no-op.
            self._pending.clear()
            self._outbox.clear()

        self._on_event(ReplyEvent(reply))

    # --- background loop ---------------------------------------------------

    def start(self, poll_hz: float = 5.0) -> None:
        """Run the pump on its own thread, polling `?` at poll_hz."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        interval = 1.0 / poll_hz

        def loop() -> None:
            try:
                while self._running and self.connected:
                    with self._lock:
                        self.pump()
                        now = time.monotonic()
                        if now - self._last_poll >= interval:
                            self._last_poll = now
                            if self._awaiting_status_since is None:
                                self._awaiting_status_since = now
                            self.send_realtime(Realtime.STATUS)
                        self._check_poll_timeout(now)
                    time.sleep(0.005)
            except Exception as exc:  # noqa: BLE001 - must never die silently
                self._drop(f"internal error in streamer loop: {exc}")

        self._thread = threading.Thread(target=loop, name="grbl-streamer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _check_poll_timeout(self, now: float) -> None:
        """Three unanswered `?` polls at poll_timeout each means the link is gone."""
        started = self._awaiting_status_since
        if started is None:
            return
        if now - started < self.poll_timeout:
            return
        self._awaiting_status_since = now
        self.missed_polls += 1
        if self.missed_polls >= self.max_missed_polls:
            self._drop(
                f"no response to {self.max_missed_polls} status polls "
                f"({self.max_missed_polls * self.poll_timeout:.1f}s)"
            )

    def _drop(self, reason: str) -> None:
        with self._lock:
            if not self.connected:
                return
            self.connected = False
            self._pending.clear()
            self._outbox.clear()
            self._on_event(DisconnectedEvent(reason))

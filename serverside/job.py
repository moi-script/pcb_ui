"""Streams one G-code file to the controller.

The streamer already handles flow control — how many bytes may be in flight.
This handles the file: which line is next, how far along we are, and what
"stop" means when a hundred moves are already queued in the controller.

Progress is counted in acknowledged lines, not sent lines. GRBL returns `ok`
when it has PARSED AND QUEUED a line, not when it has executed it, so `sent`
runs well ahead of the pen and `acked` runs a little ahead. Neither is the
pen's position; the status report's WPos is. Both numbers are exposed and
named for what they are rather than blended into one dishonest percentage.
"""
from __future__ import annotations

import threading

from grbl.protocol import Realtime
from grbl.streamer import DisconnectedEvent, ReplyEvent, Streamer


def load_lines(text: str) -> list[str]:
    """Cleaned G-code lines: `;` comments and blank lines removed.

    Same rule as pcb_send.load_lines, which is what the CLI has always sent.
    Comments cost RX budget and buy nothing.
    """
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line:
            out.append(line)
    return out


class Job:
    """One file, streaming. Not thread-safe to construct twice concurrently —
    the session enforces one at a time."""

    def __init__(
        self,
        lines: list[str],
        streamer: Streamer,
        check: bool = False,
        name: str = "",
    ) -> None:
        self.lines = lines
        self.streamer = streamer
        self.check = check
        self.name = name

        self._lock = threading.RLock()
        self.state = "idle"          # idle|running|paused|done|error|stopped
        self.sent = 0
        self.acked = 0
        self.error: str | None = None
        self.error_line: int | None = None
        self._check_on = False
        # `$C` and its closing partner are lines like any other, so GRBL
        # acknowledges them: without discounting those acks, a check-mode job
        # would count two acknowledgements it never sent file lines for and
        # declare itself done two lines early.
        self._bookkeeping_acks = 0

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self.state == "running":
                return
            self.state = "running"
            if self.check:
                # $C is a toggle, not a mode flag: it must be sent once here
                # and once at the end, and the end must happen on every exit
                # path or the next job silently validates instead of plotting.
                self._send_bookkeeping("$C")
                self._check_on = True
            self._feed()

    def pause(self) -> None:
        """Stop feeding and feed-hold what is already queued.

        Both halves are needed. Feeding stops immediately, but the controller
        may hold a hundred queued moves; without the hold the machine keeps
        drawing for seconds after the button was pressed.
        """
        with self._lock:
            if self.state != "running":
                return
            self.state = "paused"
        self.streamer.send_realtime(Realtime.FEED_HOLD)

    def resume(self) -> None:
        with self._lock:
            if self.state != "paused":
                return
            self.state = "running"
        self.streamer.send_realtime(Realtime.RESUME)
        with self._lock:
            self._feed()

    def stop(self) -> None:
        """Hold, then abandon the rest of the file.

        A soft reset would be faster but costs the operator their work zero,
        which they set by hand and would have to set again. Holding and
        dropping the remaining lines leaves the machine parked and zeroed;
        the queued moves already in the controller still play out, which is
        why this is 'stop', not 'e-stop'. E-stop is its own endpoint.
        """
        with self._lock:
            if self.state in ("done", "error", "stopped"):
                return
            self.state = "stopped"
        # Drop what has not gone out yet, or the rest of the file keeps
        # streaming to a machine the operator just told to stop.
        self.streamer.clear_outbox()
        self.streamer.send_realtime(Realtime.FEED_HOLD)
        with self._lock:
            self._end_check_mode()

    # --- feeding -----------------------------------------------------------

    # How many lines may be outstanding — handed to the streamer but not yet
    # acknowledged. The streamer's own outbox already keeps the RX buffer
    # from overflowing, so this is not about flow control; it is about Stop
    # meaning something. Handing the streamer the whole file at once makes
    # every line irrevocably queued, so pressing Stop halfway through a
    # 40,000-line board would only feed-hold a machine that still has the
    # entire rest of the file coming. A window big enough to keep the RX
    # buffer saturated (128 bytes is roughly eight lines) and small enough
    # that Stop is nearly immediate.
    WINDOW = 32

    def _feed(self) -> None:
        """Top the streamer up to WINDOW unacknowledged lines.

        Called with `self._lock` held, from `start`, `resume`, and every
        acknowledgement.
        """
        if self.state != "running":
            return
        while (
            self.sent < len(self.lines)
            and self.sent - self.acked < self.WINDOW
        ):
            self.streamer.send_line(self.lines[self.sent])
            self.sent += 1

    def _send_bookkeeping(self, line: str) -> None:
        """Send a line of ours that is not part of the file being plotted."""
        self._bookkeeping_acks += 1
        self.streamer.send_line(line)

    def _end_check_mode(self) -> None:
        if self._check_on:
            self._send_bookkeeping("$C")
            self._check_on = False

    # --- inbound -----------------------------------------------------------

    def on_streamer_event(self, event: object) -> None:
        """Count acknowledgements; fail loudly on error or a dropped link."""
        if isinstance(event, DisconnectedEvent):
            with self._lock:
                if self.state in ("running", "paused"):
                    self.state = "error"
                    self.error = f"link lost: {event.reason}"
            return

        if not isinstance(event, ReplyEvent):
            return

        reply = event.reply
        with self._lock:
            if self.state not in ("running", "paused"):
                return
            if reply.kind == "ok":
                if self._bookkeeping_acks:
                    self._bookkeeping_acks -= 1
                    return
                self.acked += 1
                if self.acked >= len(self.lines):
                    self.state = "done"
                    self._end_check_mode()
                else:
                    self._feed()
            elif reply.kind in ("error", "alarm"):
                self.error_line = self.acked + 1
                offending = (
                    self.lines[self.error_line - 1]
                    if self.error_line <= len(self.lines)
                    else "?"
                )
                self.error = f"line {self.error_line}: {offending} -> {reply.text}"
                self.state = "error"
                self._end_check_mode()

    # --- reporting ---------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "name": self.name,
                "state": self.state,
                "sent": self.sent,
                "acked": self.acked,
                "total": len(self.lines),
                "check": self.check,
                "error": self.error,
                "errorLine": self.error_line,
            }

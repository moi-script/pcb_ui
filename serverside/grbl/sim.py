"""A model of a GRBL 1.1 controller, used as a transport in tests and demos.

This is deliberately not a stub. It models the RX buffer and the planner
queue, because the only way to prove the host's character-counting flow
control is correct — rather than accidentally working — is to run it against
something that withholds `ok` under backpressure and complains when the host
oversends.
"""
from __future__ import annotations

import math

BANNER = "Grbl 1.1h ['$' for help]"

DEFAULT_SETTINGS: dict[int, str] = {
    10: "1",        # status report mask: machine position
    20: "0",        # soft limits off
    22: "0",        # homing off
    100: "80.000",  # X steps/mm
    101: "80.000",  # Y steps/mm
    102: "100.000", # Z steps/mm
    110: "5000.000",# X max rate
    111: "5000.000",# Y max rate
    112: "1000.000",# Z max rate
    120: "300.000", # X accel
    121: "300.000", # Y accel
    122: "100.000", # Z accel
    130: "300.000", # X max travel
    131: "200.000", # Y max travel
    132: "5.000",   # Z max travel
}

AXES = ("X", "Y", "Z")

# Word letters GRBL 1.1 understands on a block. Anything else draws
# `error:20` ("Unsupported or invalid g-code command"). Modelled because
# check mode ($C) exists precisely to find these before the pen is down, and
# a simulator that accepts every letter cannot demonstrate that it works.
SUPPORTED_WORDS = set("GMNXYZIJKRFSTPL")


class _Ack:
    """One reply owed to the host, in the order the line was parsed.

    GRBL answers strictly in parse order and its serial output is FIFO, so a
    reply that is ready before an earlier one still has to wait its turn.
    `ready` is False only for a line the planner could not take yet.
    """

    __slots__ = ("text", "cost", "ready")

    def __init__(self, text: str, cost: int, ready: bool) -> None:
        self.text = text
        self.cost = cost
        self.ready = ready


class _Block:
    """One queued motion block."""

    def __init__(self, target: list[float], feed: float, rx_cost: int) -> None:
        self.target = target
        self.feed = feed
        self.rx_cost = rx_cost
        self.ack: _Ack | None = None


class GrblSim:
    def __init__(
        self,
        rx_buffer: int = 128,
        planner_blocks: int = 15,
        travel: tuple[float, float, float] = (300.0, 200.0, 5.0),
    ) -> None:
        self.rx_buffer = rx_buffer
        self.planner_blocks = planner_blocks
        self.travel = list(travel)

        self.pos: list[float] = [0.0, 0.0, 0.0]
        self.wco: list[float] = [0.0, 0.0, 0.0]
        self.state = "Idle"
        self.feed = 0.0
        # $C is a toggle, not a flag, and leaking it on makes the next file
        # silently validate instead of plotting. Modelled as state so a test
        # can assert it was turned back off.
        self.check_mode = False

        self._out: list[str] = []
        self._partial = ""
        self._queue: list[_Block] = []
        # Replies owed to the host, in parse order. Nothing is emitted (and
        # nothing is credited back against the RX buffer) until every earlier
        # line has been answered: the host counts bytes off its own FIFO, so
        # an out-of-order `ok` credits the wrong line's cost and the drift
        # compounds until it oversends a buffer it believes has room.
        self._acks: list[_Ack] = []
        self._rx_used = 0
        self.peak_rx_used = 0
        self._lines_seen = 0
        self._closed = False

        # fault injection
        self.fail_after_lines: int | None = None
        self.stop_answering_status: bool = False
        self.error_on_line: int | None = None

    # --- transport surface -------------------------------------------------

    def write(self, data: bytes) -> None:
        if self._closed:
            raise OSError("port closed")
        for byte in data:
            ch = bytes([byte])
            if ch in (b"?", b"!", b"~", b"\x18", b"\x85", b"\x84"):
                self._realtime(ch)
                continue
            text = ch.decode("latin-1")
            if text in "\r\n":
                if self._partial.strip():
                    self._line(self._partial.strip())
                self._partial = ""
                if not data.strip():
                    self._emit(BANNER)
            else:
                self._partial += text

    def read_available(self) -> bytes:
        out = "".join(line + "\r\n" for line in self._out)
        self._out.clear()
        return out.encode()

    def close(self) -> None:
        self._closed = True

    # --- internals ---------------------------------------------------------

    def _emit(self, line: str) -> None:
        self._out.append(line)

    def _realtime(self, ch: bytes) -> None:
        if ch == b"?":
            if not self.stop_answering_status:
                self._emit(self._status_report())
        elif ch == b"!":
            if self.state == "Run":
                self.state = "Hold"
        elif ch == b"~":
            if self.state == "Hold":
                self.state = "Run" if self._queue else "Idle"
        elif ch == b"\x85":
            if self.state == "Jog":
                self._queue.clear()
                self._reset_acks()
                self.state = "Idle"
        elif ch == b"\x18":
            self._queue.clear()
            self._reset_acks()
            self.state = "Alarm"
            self._emit("")
            self._emit(BANNER)
            # Real GRBL 1.1 reports ALARM:3, "Reset while in motion", after
            # the restart banner: the soft reset aborted motion, so the
            # position is no longer trusted. Modelling it matters beyond
            # realism -- a soft reset discards every line still sitting in
            # the RX buffer un-acknowledged, and the host has to learn that
            # from what the controller says. Emitting only the banner (as
            # this did before) hid a whole class of host-side bookkeeping
            # bug (round 5, F1). Emitted unconditionally, matching this
            # model's existing choice to enter Alarm on every soft reset.
            self._emit("ALARM:3")

    def _status_report(self) -> str:
        mpos = ",".join(f"{v:.3f}" for v in self.pos)
        return (
            f"<{self.state}|MPos:{mpos}|FS:{self.feed:.0f},0"
            f"|WCO:{self.wco[0]:.3f},{self.wco[1]:.3f},{self.wco[2]:.3f}>"
        )

    def _line(self, line: str) -> None:
        self._lines_seen += 1
        cost = len(line) + 1

        self._rx_used += cost
        self.peak_rx_used = max(self.peak_rx_used, self._rx_used)
        assert self._rx_used <= self.rx_buffer, (
            f"host overflowed the RX buffer: {self._rx_used} > {self.rx_buffer} bytes "
            f"in flight after {line!r}"
        )

        if self.fail_after_lines is not None and self._lines_seen > self.fail_after_lines:
            self._closed = True
            raise OSError("simulated disconnect")

        if self.error_on_line is not None and self._lines_seen == self.error_on_line:
            self._reply("error:20", cost)
            return

        upper = line.upper()

        if upper == "$C":
            self.check_mode = not self.check_mode
            self._emit("[Enabled]" if self.check_mode else "[Disabled]")
            self._reply("ok", cost)
            return

        if upper == "$X":
            self.state = "Idle"
            self._reply("ok", cost)
            return

        if upper == "$$":
            for key in sorted(DEFAULT_SETTINGS):
                self._emit(f"${key}={DEFAULT_SETTINGS[key]}")
            self._reply("ok", cost)
            return

        if upper == "$I":
            self._emit("[VER:1.1h.20190825:]")
            self._emit("[OPT:V,15,128]")
            self._reply("ok", cost)
            return

        if upper == "$H":
            self.pos = [0.0, 0.0, 0.0]
            self.state = "Idle"
            self._reply("ok", cost)
            return

        if self.state == "Alarm":
            self._reply("error:9", cost)
            return

        bad = self._unsupported_word(upper)
        if bad is not None:
            self._reply("error:20", cost)
            return

        if self.check_mode and not upper.startswith("$"):
            # Check mode parses and validates every line and replies `ok`,
            # but queues no motion: the point is to find a bad file without
            # moving anything.
            self._reply("ok", cost)
            return

        if upper.startswith("$J="):
            self._motion(upper[3:], cost, jog=True)
            return

        if upper.startswith("G10 L20"):
            for i, axis in enumerate(AXES):
                token = self._word(upper, axis)
                if token is not None:
                    self.wco[i] = self.pos[i] - token
            self._reply("ok", cost)
            return

        if upper.startswith("G0") or upper.startswith("G1") or upper.startswith("G9"):
            self._motion(upper, cost, jog=False)
            return

        if upper.startswith("$"):
            self._reply("error:3", cost)
            return

        self._reply("ok", cost)

    @staticmethod
    def _unsupported_word(line: str) -> str | None:
        """The first word letter GRBL would refuse, or None.

        Only applied to plain blocks: `$` commands have their own grammar,
        and comments are stripped by the host before anything gets here.
        """
        if line.startswith("$") or line.startswith("("):
            return None
        for ch in line:
            if ch.isalpha() and ch.upper() not in SUPPORTED_WORDS:
                return ch.upper()
        return None

    @staticmethod
    def _word(line: str, letter: str) -> float | None:
        idx = line.find(letter)
        if idx < 0:
            return None
        num = ""
        for ch in line[idx + 1:]:
            if ch.isdigit() or ch in "+-.":
                num += ch
            else:
                break
        try:
            return float(num)
        except ValueError:
            return None

    def _motion(self, body: str, cost: int, jog: bool) -> None:
        relative = "G91" in body
        # Real GRBL resolves a relative (G91) offset against the planner's
        # END position -- the target of the last queued block -- not the
        # live position, because queued blocks have not executed yet and
        # must still stack on top of each other. Using self.pos here would
        # let each newly queued relative move overwrite the one before it
        # instead of accumulating, which is not how the real controller (or
        # the safety checks that assume its behavior) works.
        base = self._queue[-1].target if self._queue else self.pos
        target = list(base)
        moved = False
        for i, axis in enumerate(AXES):
            value = self._word(body, axis)
            if value is None:
                continue
            moved = True
            target[i] = base[i] + value if relative else value

        feed = self._word(body, "F")
        if feed is not None:
            self.feed = feed

        if not moved:
            self._reply("ok", cost)
            return

        for i, axis_travel in enumerate(self.travel):
            if target[i] < -1e-6 or target[i] > axis_travel + 1e-6:
                self._queue.clear()
                self._reset_acks()
                self.state = "Alarm"
                self._emit("ALARM:2")
                return

        block = _Block(target, self.feed or 1000.0, cost)
        if len(self._queue) >= self.planner_blocks:
            # Planner full: the line stays in the RX buffer, un-acknowledged,
            # and so does every line parsed after it. This is the backpressure
            # the host's flow control must respect.
            block.ack = self._withhold(cost)
            self._queue.append(block)
        else:
            self._queue.append(block)
            self._reply("ok", cost)
        # A feed hold is not lifted by handing the controller more work.
        if self.state != "Hold":
            self.state = "Jog" if jog else "Run"

    def _reply(self, text: str, cost: int) -> None:
        """Answer a line — once every line parsed before it has been answered."""
        self._acks.append(_Ack(text, cost, True))
        self._flush_acks()

    def _withhold(self, cost: int) -> _Ack:
        """Take a line the planner cannot accept yet. Answered when it runs."""
        ack = _Ack("ok", cost, False)
        self._acks.append(ack)
        return ack

    def _flush_acks(self) -> None:
        while self._acks and self._acks[0].ready:
            ack = self._acks.pop(0)
            self._rx_used = max(0, self._rx_used - ack.cost)
            self._emit(ack.text)

    def _reset_acks(self) -> None:
        """A reset or an alarm discards everything the controller was holding."""
        self._acks.clear()
        self._rx_used = 0

    def tick(self, dt: float) -> None:
        """Advance simulated motion by dt seconds."""
        if self.state in ("Hold", "Alarm"):
            return

        remaining = dt
        while remaining > 1e-9 and self._queue:
            block = self._queue[0]
            delta = [block.target[i] - self.pos[i] for i in range(3)]
            distance = math.sqrt(sum(d * d for d in delta))
            if distance < 1e-9:
                self._finish_block()
                continue

            speed = block.feed / 60.0  # mm/min -> mm/s
            step = speed * remaining
            if step >= distance:
                self.pos = list(block.target)
                remaining -= distance / speed
                self._finish_block()
            else:
                frac = step / distance
                self.pos = [self.pos[i] + delta[i] * frac for i in range(3)]
                remaining = 0.0

        if not self._queue and self.state in ("Run", "Jog"):
            self.state = "Idle"
            self.feed = 0.0

    def _finish_block(self) -> None:
        done = self._queue.pop(0)
        # A block that was held back by a full planner gets its `ok` now —
        # through the ordered queue, so it still cannot overtake an earlier
        # line's reply.
        if done.ack is not None and not done.ack.ready:
            done.ack.ready = True
            self._flush_acks()

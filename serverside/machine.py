"""Owns the one serial connection to the one machine.

A module-level singleton, not a per-account object: there is one physical
plotter on the PC running this server. Keying the connection by user would
model a fleet that does not exist and would let two browser tabs each
believe they own the port.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from grbl.limits import AXIS_INDEX, LimitError, check_jog
from grbl.profile import DEFAULT_PROFILE, Profile, with_setup
from grbl.protocol import Realtime
from grbl.state import MachineState
from grbl.streamer import ReplyEvent, Streamer, Transport
from job import Job, modal_preamble

BANNER_TIMEOUT = 3.0

log = logging.getLogger("traceworks.machine")


def default_setup_path() -> Path:
    """Where the operator's machine setup (bed, corner, reversed axes) lives."""
    base = os.environ.get("TRACEWORKS_DATA_DIR")
    return Path(base) / "machine_setup.json" if base else (
        Path(__file__).resolve().parent / "machine_setup.json"
    )


SIM_PORT = "SIM"

# The simulated board's EEPROM. It outlives each SimTransport the way the
# real one outlives a reset, so reconnecting to SIM behaves like re-plugging
# the Arduino: position back to zero, stored work offset still there.
_SIM_EEPROM: dict = {}


def _sim_transport() -> Transport:
    """The simulator, wired to a real clock and safe to share across threads.

    `GrblSim` models motion but has no clock of its own — slice-1 ticked it
    from a loop in its `serve_sim` launcher. Here the transport ticks itself,
    because nothing else in the request path is in a position to: the
    streamer thread pumps on a 5 Hz status poll, and a machine that only
    advanced when someone asked for its position would report motion in
    200 ms lurches.

    The lock is the other half of that: `tick` mutates the same queue and
    output buffer that `write`/`read_available` touch from the streamer
    thread, and `GrblSim` itself is single-threaded by design.
    """
    from grbl.sim import GrblSim

    class SimTransport(GrblSim):
        TICK = 0.01

        def __init__(self) -> None:
            # travel=None: soft limits off, as grbl_servo_z ships ($20=0).
            # The app's own envelope checks are what keep a plot on the bed.
            super().__init__(eeprom=_SIM_EEPROM, travel=None)
            self._lock = threading.RLock()
            self._stop = threading.Event()
            self._clock = threading.Thread(
                target=self._run_clock, name="grbl-sim-clock", daemon=True
            )
            self._clock.start()

        def _run_clock(self) -> None:
            last = time.monotonic()
            while not self._stop.is_set():
                now = time.monotonic()
                with self._lock:
                    if self._closed:
                        return
                    self.tick(now - last)
                last = now
                time.sleep(self.TICK)

        def write(self, data: bytes) -> None:
            with self._lock:
                super().write(data)

        def read_available(self) -> bytes:
            with self._lock:
                return super().read_available()

        def close(self) -> None:
            self._stop.set()
            with self._lock:
                super().close()

    return SimTransport()


def make_transport(port: str, baud: int) -> Transport:
    """The transport for a port name. `SIM` is the simulator, not a device.

    Routing the simulator through the same factory the real port uses means
    every layer above this line — session, endpoints, job runner, the UI —
    is exercised identically with and without hardware. A separate "sim
    mode" flag threaded through those layers would leave them untested in
    the configuration that ships.
    """
    if port == SIM_PORT:
        return _sim_transport()
    return SerialTransport(port, baud)


# How close the live mpos must be to a tracked planned jog target before an
# "Idle" status report is trusted as proof that target was actually reached
# (see Session.settle). Wide enough to absorb normal float/reporting noise,
# tight enough that a stale pre-move report (whose mpos is still at the OLD
# position) cannot be mistaken for a settled one.
#
# This must also stay smaller than the smallest jog step the UI offers
# (userpage/app/dashboard/device/page.tsx, STEPS = [0.1, 1, 10, 100]) or the
# match check below could pass for a real, not-yet-executed jog of that
# size, silently disabling the whole mechanism for that step. Mirrored here
# (rather than imported — it lives in a TS file) and asserted at import
# time so a future finer step can't regress this silently.
PLANNED_MATCH_EPS = 0.05
SMALLEST_JOG_STEP_MM = 0.1
assert PLANNED_MATCH_EPS < SMALLEST_JOG_STEP_MM, (
    "PLANNED_MATCH_EPS must stay below the smallest jog step the UI offers, "
    "or Session.settle() can mistake a real, unexecuted jog for a settled one"
)


class _Tainted:
    """Sentinel for `Session._planned`: the tracked base is untrustworthy.

    Distinct from `None` (meaning "nothing tracked; trust live mpos") and
    from a `list[float]` (a trusted planned target). A two-valued model
    cannot express "I no longer know where the queue ends" -- which is
    exactly the state after a jog gets bounced by the controller (Alarm),
    or after a command we can't parse (raw console line, coordinate zero)
    may have started motion we have no target for. In that state, neither
    the old target NOR live mpos can be trusted, so jogs must be refused
    outright rather than validated against a guess.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "TAINTED"


TAINTED = _Tainted()


class PositionUncertain(Exception):
    """`_planned` is TAINTED: refuse the jog rather than guess a base."""


class SerialTransport:
    """pyserial wrapped in the Transport protocol."""

    def __init__(self, port: str, baud: int) -> None:
        import serial

        # write_timeout keeps write() from blocking forever if the OS TX
        # buffer fills or the USB adapter is yanked mid-write. Without it, a
        # stuck write() would hold the streamer's lock indefinitely, and the
        # streamer thread — which needs that same lock to notice the link is
        # dead — would never get to run. A timed-out write is retried; only
        # one that keeps failing ends the connection (Streamer.error_grace).
        self._ser = serial.Serial(port, baud, timeout=0, write_timeout=1.0)
        # Toggling DTR resets an Arduino, which is how we provoke the banner.
        self._ser.dtr = False
        time.sleep(0.1)
        self._ser.dtr = True
        time.sleep(0.2)

    def write(self, data: bytes) -> None:
        self._ser.write(data)

    def read_available(self) -> bytes:
        waiting = self._ser.in_waiting
        return self._ser.read(waiting) if waiting else b""

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class Session:
    """Holds the one connection and the one machine state.

    The profile is `grbl.profile.DEFAULT_PROFILE` with the operator's machine
    setup laid over it — bed size, start corner, reversed axes — kept in a
    small JSON file (see update_setup). Everything else about the machine is
    fixed by its firmware and does not change between requests.
    """

    profile: Profile

    def __init__(self, setup_path: Path | None = None) -> None:
        # `setup_path` None keeps the setup in memory only (tests); the
        # module-level session persists it, so a reversed axis stays
        # reversed across restarts of the app.
        self._setup_path = setup_path
        self.profile = self._load_setup(DEFAULT_PROFILE)
        self.state = MachineState(self.profile)
        # Set by every restart banner the controller sends; see halt().
        self._banner = threading.Event()
        self.streamer: Streamer | None = None
        self.job: Job | None = None
        # Where the pen stopped when the link died, in the lost plot's work
        # frame, waiting to be restored on resume. Set when a reconnect
        # rebooted the board under an interrupted plot (machine position
        # restarts at 0 wherever the pen is); cleared when the operator sets
        # a zero of their own, which then is the frame to trust.
        self.resume_anchor: tuple[float, float] | None = None

        # `_planned` tracks the end of the last jog we validated and sent —
        # the planner's queued target, not the live reported position. Jogs
        # fired in rapid succession are validated against this instead of
        # `state.mpos`, because `mpos` lags: the controller has not caught up
        # to a just-sent jog yet, so a second jog checked against the stale
        # live position could pass a check whose sum with the first exceeds
        # the travel envelope.
        #
        # Three states, not two: `None` (nothing tracked; trust live mpos),
        # a `list[float]` (a trusted target), or `TAINTED` (the base is
        # unknown; refuse jogs until confirmed Idle). Falling back to live
        # mpos is only safe when nothing is queued -- collapsing "unknown"
        # into "trust mpos" is exactly what let a rejected-by-the-controller
        # jog, or a raw command / zero mid-flight, poison the base downward
        # (see PositionUncertain and the call sites below).
        #
        # A plain Lock (not MachineState's RLock) guards it: it protects a
        # single small piece of state private to Session, is never held
        # while calling into the streamer or MachineState (no I/O, no
        # send_line under this lock). `reserve_jog` holds it across the whole
        # read-base -> check -> commit sequence so two concurrent jog
        # requests (rapid clicking fires them with no client-side
        # serialization) can't both read the same base and both pass.
        self._planned_lock = threading.Lock()
        self._planned: list[float] | _Tainted | None = None

        # Snapshot of MachineState.status_seq() taken at the moment `_planned`
        # was last set to TAINTED. Only meaningful while `_planned is
        # TAINTED`; settle() requires the CURRENT status_seq to have
        # advanced past this snapshot (not just is_idle) before lifting the
        # taint -- see settle() and taint_and_resync() below for why a bare
        # `state == "Idle"` read is not enough on its own (N1).
        self._planned_taint_seq: int | None = None

    # --- machine setup -----------------------------------------------------

    def _load_setup(self, base: Profile) -> Profile:
        if self._setup_path is None or not self._setup_path.is_file():
            return base
        try:
            data = json.loads(self._setup_path.read_text(encoding="utf-8"))
            return with_setup(
                base,
                travel_x=data.get("travel_x"),
                travel_y=data.get("travel_y"),
                origin=data.get("origin"),
                invert_x=data.get("invert_x"),
                invert_y=data.get("invert_y"),
            )
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            log.warning("ignoring unreadable machine setup %s: %s",
                        self._setup_path, exc)
            return base

    def update_setup(self, **changes) -> Profile:
        """Change the bed size, start corner or axis directions.

        Refused mid-plot: a file already streaming was measured and placed
        against the old setup, and flipping an axis under it would send the
        rest of the board the other way. Raises ValueError on a bad value.
        """
        if self.job is not None and self.job.state in ("running", "paused"):
            raise HTTPException(
                409, "A plot is running. Stop it before changing the machine setup."
            )
        profile = with_setup(self.profile, **changes)
        if self._setup_path is not None:
            self._setup_path.parent.mkdir(parents=True, exist_ok=True)
            self._setup_path.write_text(json.dumps({
                "travel_x": profile.travel_x,
                "travel_y": profile.travel_y,
                "origin": profile.origin,
                "invert_x": profile.invert_x,
                "invert_y": profile.invert_y,
            }, indent=2), encoding="utf-8")

        self.profile = profile
        self.state.set_profile(profile)
        streamer = self.streamer
        if streamer is not None:
            with streamer._lock:
                streamer.axis_map = profile.axis_map
            # Positions already on the books are in the old frame; nothing
            # may be jogged against them until a fresh report arrives.
            self.taint_planned()
        return profile

    def require(self) -> Streamer:
        if self.streamer is None or not self.streamer.connected:
            raise HTTPException(409, "Machine is not connected.")
        return self.streamer

    def start_job(self, lines: list[str], check: bool, name: str) -> Job:
        """Begin streaming a file. One at a time, deliberately.

        Two concurrent jobs on one machine is not a feature with a sensible
        meaning — it is two files interleaved into one nonsense toolpath.
        """
        streamer = self.require()
        if self.job is not None and self.job.state in ("running", "paused"):
            raise HTTPException(409, "A job is already running.")
        job = Job(lines, streamer, check=check, name=name)
        self.resume_anchor = None
        self.job = job
        self.state.job_source = job.snapshot
        job.start()
        return job

    def resume_interrupted(self) -> Job:
        """Carry on a plot whose USB link died, from where the pen stopped.

        The controller drew out the lines it already held and stopped at the
        end of the last one; reconnecting rebooted it there, with machine
        position back at 0. So: restore the old work frame around that spot,
        put back the modes the skipped lines had set, lift the pen, and
        stream the file from the start of the stroke that was cut off.
        """
        streamer = self.require()
        old = self.job
        if old is None or not old.resumable or old.state in ("running", "paused"):
            raise HTTPException(409, "There is no interrupted plot to resume.")

        start, (px, py) = old.resume_plan()
        if self.resume_anchor is not None:
            # G10 L2 sets the offset itself: work = machine - offset, and
            # machine was 0 with the pen at (px, py). Jogs made since the
            # reconnect moved machine and work together, so they still agree.
            streamer.send_line(f"G10 L2 P1 X{-px:g} Y{-py:g} Z0")
            self.resume_anchor = None
        self.taint_planned()

        preamble = modal_preamble(old.lines, start, self.profile.pen_up_z,
                                  self.profile.z_feed)
        job = Job(old.lines, streamer, check=False, name=old.name,
                  start_at=start, preamble=preamble)
        log.info("resuming %r from line %d of %d (pen stopped at X%g Y%g)",
                 old.name, start + 1, len(old.lines), px, py)
        self.job = job
        self.state.job_source = job.snapshot
        job.start()
        return job

    # How long a restart waits for each step of halting the controller: the
    # feed hold to finish decelerating (a fraction of a second at this
    # machine's 500 mm/min), then the reset banner. Bounded so a wedged
    # controller answers instead of hanging the request.
    HOLD_TIMEOUT = 5.0
    RESET_TIMEOUT = 3.0

    def restart_job(self) -> Job:
        """Stop what is plotting and run the same file again from line 1.

        This used to stop the job and then wait for the controller to draw
        out every move already queued in it -- sixteen planner blocks plus a
        full RX buffer, which on long traverses is most of a minute -- before
        answering. The button looked frozen the whole time.

        Now it halts the controller instead of waiting on it (see halt()),
        lifts the pen, and streams the file from the top. Work zero is never
        touched: a botched plot should not cost the corner set by hand.
        """
        streamer = self.require()
        job = self.require_job()
        lines, check, name = list(job.lines), job.check, job.name

        if check:
            # Check mode moves nothing, and a reset would swallow the `$C`
            # that turns it back off. The ordinary stop is already instant.
            job.stop()
            return self.start_job(lines, check, name)

        self.halt(streamer, job)

        # A halt lands the head somewhere nobody planned; nothing may be
        # jogged against that base until a report proves where it is.
        self.taint_planned()

        # Pen up before the file's own first move. Z >= 0 is the servo's
        # "up" (see Profile); the reset already raised the servo, but machine
        # Z still reads down until a move says otherwise.
        streamer.send_line(
            f"G1 Z{self.profile.pen_up_z:g} F{self.profile.z_feed:g}"
        )
        # Let its `ok` (and the unlock's, if there was one) come back first:
        # the job counts acknowledgements, and one it did not send would
        # declare the file finished a line early.
        deadline = time.monotonic() + 2.0
        while not streamer.quiet and time.monotonic() < deadline:
            time.sleep(0.02)

        return self.start_job(lines, check, name)

    def halt(self, streamer: Streamer, job: Job | None = None) -> None:
        """Bring the controller to rest with an empty queue, in about a second.

        1. stop feeding the file;
        2. feed-hold, and wait for the hold to COMPLETE (`Hold:0`): the
           motors decelerate to rest under control, so no step is lost;
        3. soft-reset. From a completed hold Grbl discards its whole queue
           and comes back Idle without ALARM:3 -- machine position is kept,
           the G54 work zero lives in EEPROM, and grbl_servo_z's mc_reset()
           lifts the pen.

        Raises 409 if the controller never comes to rest or never answers.
        """
        if job is not None:
            job.abort()

        snap = self.state.snapshot()
        # Held whenever it could be moving. A cached `Idle` is not evidence
        # otherwise: it can be a report from between two blocks, a fifth of
        # a second old, with the next move already parsed. A hold on a truly
        # idle Grbl does nothing.
        if not snap["state"].startswith(("Alarm", "Disconnected")):
            baseline = snap["statusSeq"]
            streamer.send_realtime(Realtime.FEED_HOLD)
            if not self._wait_for_state(("Hold:0", "Idle"), baseline,
                                        self.HOLD_TIMEOUT):
                raise HTTPException(
                    409,
                    "The machine did not come to a stop after a feed hold. "
                    "Use the e-stop.",
                )

        self._banner.clear()
        baseline = self.state.snapshot()["statusSeq"]
        streamer.send_realtime(Realtime.SOFT_RESET)
        deadline = time.monotonic() + self.RESET_TIMEOUT
        while not self._banner.is_set():
            if time.monotonic() >= deadline or not streamer.connected:
                raise HTTPException(
                    409, "The controller did not answer the reset. Reconnect it."
                )
            time.sleep(0.02)

        # A reset that caught the motors moving anyway (a hold that had not
        # really finished) comes back in ALARM:3 and refuses every line.
        # Steps may have been lost then, but the operator asked to start
        # again, and at this machine's feeds the loss is a fraction of a
        # millimetre: unlock rather than leave the restart dead.
        if self._wait_for_state(("Idle", "Alarm"), baseline, 1.0) and \
                self.state.snapshot()["state"].startswith("Alarm"):
            log.warning("restart: the reset left the controller in alarm; unlocking")
            streamer.send_line("$X")

    def _wait_for_state(self, states: tuple[str, ...], baseline: int,
                        timeout: float) -> bool:
        """Wait for a status report newer than `baseline` in one of `states`."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snap = self.state.snapshot()
            if snap["statusSeq"] > baseline and any(
                snap["state"].startswith(st) for st in states
            ):
                return True
            time.sleep(0.02)
        return False

    def require_job(self) -> Job:
        if self.job is None:
            raise HTTPException(409, "No job is running.")
        return self.job

    def _on_streamer_event(self, event: object) -> None:
        """MachineState.apply(), plus an immediate taint on alarm/error.

        All the taint call sites above cover alarms *we* provoke (a jog
        while already in Alarm, an out-of-envelope raw command). A hardware
        fault -- a limit switch, an e-stop wired into the controller itself
        -- can also alarm the controller with no REST call of ours in
        between, and the only way we would otherwise learn about it is the
        next background status poll, up to one poll interval later. During
        that narrow window `session.state.state` can still read as
        non-Alarm, and the jog route's Alarm gate is a `state.state` read,
        so it would not fire. Reacting here, directly on the alarm REPLY
        the controller sends (which arrives as soon as GRBL reports it, not
        on our polling schedule), closes that window immediately rather
        than waiting for the next poll to catch up -- and does so for any
        cause of Alarm, not just the ones a REST route can see coming.

        Also taints on any `"error"` reply, not just `"alarm"` (M2). GRBL
        replies `error:N` (not `alarm:N`) to a single line it rejects while
        otherwise staying in whatever state it was in -- e.g. `error:15`,
        "travel exceeded", when soft limits are on ($20=1) and a jog would
        overshoot. A jog line that draws an `error` reply means a target
        was booked in `_planned` for a move that never actually happened:
        exactly the stale-low shape this whole mechanism exists to close,
        just via a different reply kind than `"alarm"`. Correlating a
        specific error reply to a specific sent line is not attempted here
        -- the streamer's flow-control accounting (`_pending`) tracks byte
        cost per line, not a routable per-line callback, and this handler
        must stay fast, never raise, and never call back into the streamer
        (it runs on the streamer thread with `Streamer._lock` already
        held). Tainting unconditionally on any error is the simple,
        provably-safe rule: it costs one extra Idle-confirmation wait on
        the rare line that legitimately errors, in exchange for never
        leaving a target on the books for a move the controller refused.
        """
        # The job first: it counts acknowledgements, and an `ok` it does not
        # see is a line of progress the operator never gets back.
        job = self.job
        if job is not None:
            job.on_streamer_event(event)
        self.state.apply(event)
        if isinstance(event, ReplyEvent) and event.reply.kind == "banner":
            self._banner.set()
        if isinstance(event, ReplyEvent) and event.reply.kind in ("alarm", "error"):
            self.taint_planned()

    def connect(self, transport: Transport, port: str, baud: int) -> str:
        self.disconnect()

        # One lock for the whole link: the state, the streamer and the job
        # this connection goes on to run all share it. They call each
        # other's callbacks in both directions, so a lock apiece can be —
        # and was — taken in opposite orders by the request thread and the
        # streamer thread, deadlocking the server mid-plot. A new one per
        # connection, alongside the new MachineState.
        link_lock = threading.RLock()

        # A plot the last link dropped stays on the books, so it can be
        # picked up from where it stopped instead of started over.
        interrupted = self.job if self.job is not None and self.job.resumable else None

        self.state = MachineState(self.profile, lock=link_lock)
        self.job = interrupted
        self.state.job_source = interrupted.snapshot if interrupted else None
        self.resume_anchor = None

        streamer = Streamer(
            transport,
            rx_buffer=self.profile.rx_buffer,
            on_event=self._on_streamer_event,
            lock=link_lock,
            axis_map=self.profile.axis_map,
        )
        self.streamer = streamer

        # Wait for the controller to identify itself. The DTR toggle in
        # SerialTransport is what actually resets an Arduino; this newline is
        # only a nudge for a board that was already powered up. One byte, so
        # the realtime contract still holds.
        streamer.send_realtime(b"\n")
        deadline = time.time() + BANNER_TIMEOUT
        while time.time() < deadline and not self.state.firmware:
            streamer.pump()
            time.sleep(0.02)

        if not self.state.firmware:
            # Some boards miss the reset window; a status poll also proves life.
            streamer.send_realtime(Realtime.STATUS)
            deadline = time.time() + 1.0
            while time.time() < deadline and self.state.state == "Disconnected":
                streamer.pump()
                time.sleep(0.02)

        if not self.state.firmware and self.state.state == "Disconnected":
            self.disconnect()
            raise HTTPException(
                502,
                f"Opened {port} but the controller never identified itself. "
                "Wrong baud rate, or not a GRBL controller.",
            )

        if self.state.firmware:
            # It announced itself, so it has just booted: machine position
            # restarts at 0 wherever the pen is, but the G54 work offset
            # comes back from EEPROM. With no homing that stored offset
            # points at an arbitrary spot, and the first move of a plot
            # heads off to it, far from the board. Start from the pen.
            streamer.send_line("G10 L2 P1 X0 Y0 Z0")
            streamer.send_line("G92.1")
            if interrupted is not None:
                # ...and "the pen" is where the lost plot stopped: its frame
                # goes back on when the operator resumes.
                self.resume_anchor = interrupted.resume_plan()[1]
        streamer.send_line("$I")
        streamer.send_line("$$")
        streamer.start(poll_hz=5.0)
        self.state.set_connection(port, baud, self.state.firmware or "unknown")
        self.clear_planned()
        return self.state.firmware

    def disconnect(self) -> None:
        # A pulled cable must not leave a job reading "running" forever: the
        # progress bar would sit still and say nothing about why.
        if self.job is not None and self.job.state in ("running", "paused"):
            self.job.state = "error"
            self.job.error = "disconnected"
        if self.streamer is not None:
            self.streamer.stop()
            if self.streamer.connected:
                # Closing the port does not stop Grbl: it goes on executing
                # every move already in its planner and RX buffer, so the
                # plotter kept drawing after Disconnect. A soft reset halts
                # it at once, drops the queue, and grbl_servo_z's mc_reset()
                # lifts the pen. Position is lost, but the next connect
                # reboots the board and starts from the pen anyway.
                try:
                    self.streamer.send_realtime(Realtime.SOFT_RESET)
                    time.sleep(0.1)  # let the byte leave before the port closes
                except Exception:  # noqa: BLE001 - a dead link is already stopped
                    pass
            try:
                self.streamer.transport.close()
            except Exception:
                pass
            self.streamer = None
        self.state.set_connection(None, self.profile.baud, "")
        self.clear_planned()

    def clear_planned(self) -> None:
        """Unconditionally reset `_planned` to None (trust live mpos).

        Callers: `connect()` and `disconnect()` — and nothing else. Both
        are safe because position is known immediately and exactly there: a
        fresh connection has commanded nothing yet, and after a disconnect
        no jog can reach `reserve_jog` again until `require()` passes,
        which only happens after the next `connect()` resets everything
        anyway.

        `/machine/unlock` used to be listed here; it went through
        `taint_and_resync` in round 3. `/machine/estop` used to call this and
        now calls `taint_planned()` (round 4): a soft reset aborts motion
        mid-move, so the machine stops at a point nobody knows, and live
        mpos has certainly not caught up to it.
        """
        with self._planned_lock:
            self._planned = None
            self._planned_taint_seq = None

    def taint_planned(self) -> None:
        """Mark the base unknown. Refuses jogs until confirmed Idle.

        Called whenever motion may be in flight and we can no longer prove
        where it will end: a jog attempted while the controller reports
        Alarm (the controller will bounce it with error:9, not move, but we
        can't be sure whether prior queued motion already got cut off
        somewhere unknown); a jog whose send may not have reached the
        controller (dropped write / lost connection); a raw `/machine/command`
        line (may itself be a motion command this route can't parse); and
        `/machine/zero` (may run while a jog is still in flight; simplest
        correct rule is to always taint rather than try to detect it).

        Unlike `clear_planned`, this does NOT fall back to live mpos --
        that fallback is exactly what let a controller-rejected jog (or an
        unparsed raw command) poison the base downward in round 1. There is
        nothing safe to fall back to here except refusing until `settle()`
        confirms Idle.

        Also snapshots `MachineState.status_seq()` into
        `_planned_taint_seq`. `settle()` requires that counter to have
        advanced past this snapshot before it will lift the taint. That is
        a NECESSARY condition only: it rules out lifting on a report the
        session had already applied before the taint, but it does NOT prove
        the lifting report was GENERATED after the taint (a report in
        flight at taint time advances the counter the moment it lands).
        Round 3 claimed that stronger property and was wrong; what actually
        proves the queue drained is the `statusQuiet` condition in
        `settle()`. The seq read happens before `_planned_lock` is acquired
        (not nested inside it) -- MachineState._lock is taken and released
        first, so this never holds two locks at once and adds no new
        ordering.
        """
        seq = self.state.status_seq()
        with self._planned_lock:
            self._planned = TAINTED
            self._planned_taint_seq = seq

    # Bound on how long taint_and_resync will wait, synchronously, for a
    # fresh status report before giving up and leaving the taint in place.
    # The calling routes (jog/cancel, home, zero, command, unlock) are sync
    # `def`s running on FastAPI's threadpool, so a brief wait here is safe;
    # unbounded would not be. On timeout the taint simply stays set -- the
    # next jog attempt (or the background poller feeding a later settle())
    # will lift it once a genuinely fresh Idle report arrives.
    RESYNC_TIMEOUT = 0.25
    RESYNC_POLL_INTERVAL = 0.02

    def taint_and_resync(self, streamer: Streamer) -> None:
        """Taint, then wait for a status report OBSERVED AFTER the taint.

        `settle()`'s old "trust a bare Idle report" rule for lifting a
        taint has a race: `MachineState.state` is only as fresh as the last
        status report the background poll thread happened to drain, and a
        report can be *generated* (query sent) before this taint-causing
        line, yet not get *dispatched* (applied to MachineState) until
        after it, purely because dispatch runs lazily on a ~5 Hz background
        timer. If that stale report says Idle, a jog checked immediately
        after would see current_state == "Idle" and wrongly lift the taint
        before the real motion this call may have started has even been
        reported (N1).

        Round 4 note: the loop below is a best-effort *nudge*, not the
        safety gate. It exists so the operator's next jog is not refused
        purely because nobody had pumped the transport yet. The decision
        about whether the taint may actually be lifted is `settle()`'s
        alone, and this method calls it with a fresh atomic snapshot on
        every iteration, so a taint whose queue genuinely drained is lifted
        here immediately, and one whose queue did not simply stays set.

        A single synchronous `pump()` right after sending `?` is NOT enough
        to close this on real hardware: `SerialTransport.read_available()`
        only returns bytes ALREADY sitting in the OS buffer
        (`self._ser.in_waiting`) -- the reply this call's own `?` just
        provoked is still on the wire, not yet arrived, so that first pump
        typically drains nothing. (The bundled simulator masked this: its
        `write()` appends the reply into its output list synchronously, so
        the very next `pump()` genuinely does see it -- true for the sim,
        never true for real serial.)

        So instead of trusting a single pump, this polls `pump()` in a
        short bounded loop (see RESYNC_TIMEOUT/RESYNC_POLL_INTERVAL) until
        `MachineState.status_seq()` has advanced past the value snapshotted
        by `taint_planned()` above. The status query is written exactly
        once, before the loop starts; the transport is a strict FIFO
        guarded by one lock (`Streamer._lock` via the sim, or the OS serial
        buffer via real hardware), so whatever was written before that
        query (the taint-causing line itself) is necessarily queued ahead
        of it -- meaning the first status report dispatched with a fresher
        seq than the snapshot is guaranteed to reflect state at least as
        current as this call's own effect, not a stale report that merely
        happened to dispatch late. Looping is what lets the common case
        (reply arrives within a poll interval or two) resolve without
        costing the operator an extra click, while staying bounded for the
        uncommon case where it does not arrive in time.

        Jogs themselves stay fire-and-forget -- this is not called from the
        jog route itself, only from routes that are already occasional and
        can afford a bounded synchronous wait (raw command, zero, cancel,
        home, unlock).
        """
        self.taint_planned()
        with self._planned_lock:
            target_seq = self._planned_taint_seq

        streamer.send_realtime(Realtime.STATUS)
        deadline = time.monotonic() + self.RESYNC_TIMEOUT
        while True:
            streamer.pump()
            # Read the streamer's own property first, then the state
            # snapshot, then (inside settle) `_planned_lock`: the
            # established order, no lock held across another.
            quiet = streamer.quiet
            snap = self.state.snapshot()
            self.settle(snap, quiet)
            if target_seq is not None and snap["statusSeq"] > target_seq:
                return
            if time.monotonic() >= deadline:
                return
            time.sleep(self.RESYNC_POLL_INTERVAL)

    def settle(self, snap: dict, streamer_quiet: bool) -> None:
        """Clear a matched target, or a confirmed-drained taint, on Idle.

        A plain `MachineState.state == "Idle"` read is not enough on its
        own to trust as "the queue drained": status polling runs on a
        background thread at a fixed rate, so a report processed right
        after we send a jog can still be one that was IN FLIGHT before we
        sent it -- generated (and so still reflecting the pre-jog position)
        before our line went out, but not applied to MachineState until
        after, purely because of unrelated thread scheduling. Trusting a
        bare Idle read there would clear `_planned` while the real move is
        still in progress, and the next jog would then be checked against a
        live `mpos` that hasn't caught up either -- exactly the hole this
        whole mechanism exists to close.

        For a tracked TARGET, that's solved by requiring the reported
        `mpos` to actually MATCH the target (within `PLANNED_MATCH_EPS`)
        before trusting Idle: a stale, pre-move report necessarily still
        shows the old position and so cannot pass the match by accident,
        while a report that legitimately arrives once the controller has
        caught up will. That's a property of the data itself, not of when
        it happened to be processed.

        A TAINT has no numeric target to match against -- that's the whole
        point of tainting instead of leaving the old (possibly wrong) value
        in place. Rounds 2 and 3 tried to make Idle trustworthy by reasoning
        about WHEN the report showed up: round 2 trusted a bare cached Idle,
        round 3 required `status_seq()` to have advanced past a snapshot
        taken at taint time. Both are statements about arrival order, and
        arrival order cannot answer "has the queue drained?":

        - a report generated BEFORE the taint but still in flight when the
          taint is set advances the counter the instant it lands, so it
          satisfies the round-3 check while describing pre-taint reality;
        - worse, real GRBL pulls `?` out of the RX stream in its ISR, so it
          can answer `Idle` at the pre-jog position while our jog lines are
          still sitting unparsed in its RX buffer -- a report provably
          generated after our query can still read Idle-at-the-old-position.

        So round 4 gates on a property of the DATA instead, the same shape
        as the target-match rule above. GRBL emits `ok` for a line only
        after it has parsed and queued it, and its serial output is FIFO.
        `snap["statusQuiet"]` records whether the streamer held zero
        unacknowledged lines at the moment THIS report was dispatched (see
        StatusEvent.quiet), i.e. whether every line we had sent was already
        parsed and queued by the controller before it generated the report.
        Idle + that = the planner really was empty with nothing of ours
        left outside it: the queue drained. `streamer_quiet` adds the same
        statement for right now, covering anything handed to the streamer
        after that report was dispatched.

        The four conditions for lifting a taint, all required:
          1. the report says Idle;
          2. it was dispatched with nothing of ours unacknowledged;
          3. nothing of ours is unacknowledged now either;
          4. `statusSeq` has advanced past the taint-time snapshot -- kept
             as a necessary condition (it rules out lifting on a report the
             session had already applied before the taint) but, unlike what
             round 3 claimed, NOT sufficient on its own.

        Everything about the machine comes from ONE snapshot: `state`,
        `mpos`, `statusQuiet` and `statusSeq` read separately could straddle
        an incoming report and mix a newer counter with older coordinates.
        `streamer_quiet` is passed in, read by the caller before any leaf
        lock is taken, so `_planned_lock` never nests inside
        `Streamer._lock`.
        """
        if snap["state"] != "Idle":
            return
        live_mpos = snap["mpos"]
        current_seq = snap["statusSeq"]
        report_quiet = bool(snap["statusQuiet"])
        with self._planned_lock:
            if self._planned is TAINTED:
                if (
                    report_quiet
                    and streamer_quiet
                    and self._planned_taint_seq is not None
                    and current_seq > self._planned_taint_seq
                ):
                    self._planned = None
                    self._planned_taint_seq = None
                return
            if self._planned is None:
                return
            if all(
                abs(a - b) < PLANNED_MATCH_EPS
                for a, b in zip(self._planned, live_mpos)
            ):
                self._planned = None

    def reserve_jog(
        self, live_mpos: list[float], axis: str, distance: float
    ) -> list[float]:
        """Atomically validate and reserve one jog's target.

        Holds `_planned_lock` across the whole read-base -> check_jog ->
        commit sequence (not just the individual reads), so two jog
        requests racing on FastAPI's threadpool -- rapid clicking fires
        them with no client-side serialization or disabling, the exact
        gesture that found the original defect -- cannot both read the
        same base, both pass `check_jog`, and both commit: whichever
        acquires the lock second sees the first one's committed target.
        Raises `PositionUncertain` if tainted, `LimitError` (from
        `check_jog`, uncaught here) if the resulting move would leave the
        envelope. Never calls out to the streamer or MachineState while
        holding the lock -- `send_line` happens after this returns.
        """
        with self._planned_lock:
            if self._planned is TAINTED:
                raise PositionUncertain(
                    "Position is uncertain after an alarm or manual "
                    "command. Wait for the machine to reach Idle, then "
                    "try again."
                )
            base = list(self._planned) if self._planned is not None else list(live_mpos)
            check_jog(self.profile, (base[0], base[1], base[2]), axis, distance)
            target = list(base)
            target[AXIS_INDEX[axis.upper()]] += distance
            self._planned = target
            return target


session = Session(default_setup_path())

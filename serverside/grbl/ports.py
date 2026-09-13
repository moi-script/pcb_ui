"""Enumerate serial ports and guess which one is the controller."""
from __future__ import annotations

from dataclasses import dataclass

# USB vendor IDs seen on GRBL-capable boards. Mapping VID to a chip name lets
# the UI say "COM5 - CH340" instead of leaving the user to guess.
KNOWN_VENDORS: dict[int, str] = {
    0x1A86: "CH340",     # WCH, on most clone Unos and Nanos
    0x10C4: "CP2102",    # Silicon Labs, on some Nano and Pro Mini clones
    0x0403: "FTDI",      # FTDI, on older Arduinos
    0x2341: "Arduino",   # Arduino SA
    0x2A03: "Arduino",   # Arduino SRL
    0x1B4F: "SparkFun",
}

BAUD_RATES: list[int] = [115200, 250000, 57600, 38400, 19200, 9600]


@dataclass(frozen=True)
class PortInfo:
    device: str
    description: str
    vid: int | None
    pid: int | None
    likely_controller: bool
    chip: str | None


def identify(vid: int | None, pid: int | None) -> tuple[bool, str | None]:
    """Return (looks like a controller, chip name)."""
    if vid is None:
        return False, None
    chip = KNOWN_VENDORS.get(vid)
    return (chip is not None), chip


def list_ports() -> list[PortInfo]:
    """Enumerate the machine's serial ports."""
    from serial.tools import list_ports as pyserial_ports

    out: list[PortInfo] = []
    for p in pyserial_ports.comports():
        likely, chip = identify(p.vid, p.pid)
        out.append(
            PortInfo(
                device=p.device,
                description=p.description or p.device,
                vid=p.vid,
                pid=p.pid,
                likely_controller=likely,
                chip=chip,
            )
        )
    return sorted(out, key=lambda p: (not p.likely_controller, p.device))


def autoselect(ports: list[PortInfo]) -> str | None:
    """Pre-select a port only when exactly one candidate is present.

    Guessing between two plausible boards is worse than asking, so ambiguity
    deliberately returns None rather than picking the first.
    """
    likely = [p for p in ports if p.likely_controller]
    return likely[0].device if len(likely) == 1 else None

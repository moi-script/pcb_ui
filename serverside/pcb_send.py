"""Stream a G-code file to a GRBL / FluidNC controller over USB serial.

Uses the standard GRBL send-response handshake: send one line, wait for the
controller's "ok" before sending the next. Any "error:N" reply is reported.

    python pcb_send.py --port COM5                 # plot for real
    python pcb_send.py --port COM5 --check         # validate only (no motion)
    python pcb_send.py --dry-run                    # parse the file, open no port

--check toggles GRBL/FluidNC Check Mode ($C): every line is parsed and
validated but no motors move -- a safe way to confirm the file is accepted by
the firmware before running it.
"""
import argparse
import sys
import time


def load_lines(path):
    """Return cleaned G-code lines (comments and blanks stripped)."""
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()   # drop ; comments
            if line:
                out.append(line)
    return out


def wait_for_reply(ser, timeout=30):
    """Read lines until the controller returns 'ok' or 'error:N'.

    Ignores banners, status reports (<...>) and messages ([...]).
    Returns the reply string, or None on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = ser.readline().decode(errors="replace").strip()
        if not raw:
            continue
        low = raw.lower()
        if low == "ok" or low.startswith("error"):
            return low
        # else: banner / [MSG:..] / <status> -- keep reading
    return None


def send_line(ser, line, verbose=False):
    """Send one line, wait for the ok/error handshake. Returns (ok, reply)."""
    ser.write((line + "\n").encode())
    reply = wait_for_reply(ser)
    if verbose:
        print(f"  > {line:<28} < {reply}")
    if reply is None:
        return False, "timeout"
    return reply == "ok", reply


def stream(lines, port, baud, check=False, verbose=False):
    import serial   # imported lazily so --dry-run needs no hardware/pyserial

    try:
        ser = serial.Serial(port, baud, timeout=2)
    except serial.SerialException as e:
        print(f"[FAILED] could not open {port}: {e}")
        return 2
    try:
        # Wake GRBL/FluidNC and discard the startup banner.
        ser.write(b"\r\n\r\n")
        time.sleep(2)
        ser.reset_input_buffer()

        if check:
            print("Entering Check Mode ($C) -- no motion will occur.")
            ok, reply = send_line(ser, "$C", verbose)
            if not ok:
                print(f"[FAILED] controller did not enter check mode: {reply}")
                return 1

        errors = []
        for i, line in enumerate(lines, 1):
            ok, reply = send_line(ser, line, verbose)
            if not ok:
                errors.append((i, line, reply))
                print(f"[error] line {i}: {line!r} -> {reply}")

        if check:
            send_line(ser, "$C", verbose)   # toggle check mode back off

        total = len(lines)
        print(f"\n{'Checked' if check else 'Sent'} {total} lines, "
              f"{len(errors)} error(s).")
        return 1 if errors else 0
    finally:
        ser.close()


def main():
    ap = argparse.ArgumentParser(description="Stream G-code to GRBL/FluidNC.")
    ap.add_argument("file", nargs="?", default="labExam.gcode",
                    help="G-code file to send (default: labExam.gcode)")
    ap.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200, help="baud rate")
    ap.add_argument("--check", action="store_true",
                    help="validate via Check Mode ($C); no motion")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse the file and report, open no serial port")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every line and its reply")
    args = ap.parse_args()

    try:
        lines = load_lines(args.file)
    except FileNotFoundError:
        print(f"[FAILED] file not found: {args.file}")
        return 1
    print(f"Loaded {len(lines)} G-code lines from {args.file}.")

    if args.dry_run:
        print("[dry-run] not opening a serial port. First / last lines:")
        for line in lines[:3]:
            print(f"  {line}")
        print("  ...")
        for line in lines[-3:]:
            print(f"  {line}")
        return 0

    if not args.port:
        print("[FAILED] --port is required (or use --dry-run). "
              "Example: --port COM5")
        return 2

    mode = "check" if args.check else "send"
    print(f"Opening {args.port} @ {args.baud} baud ({mode} mode)...")
    return stream(lines, args.port, args.baud,
                  check=args.check, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())

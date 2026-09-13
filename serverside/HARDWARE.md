# Hardware Setup — Arduino Pen Plotter (grbl_servo_z)

How to build and set up the machine that plots the G-code produced by this
project: an **Arduino Uno** running
[grbl_servo_z](https://github.com/moi-script/grbl_servo_z) — Grbl 1.1f with
28BYJ-48 steppers on X/Y and an SG90 servo lifting the pen on Z.

```
KiCad → pcb_gcode.py → G-code → USB serial → [Arduino + grbl_servo_z] → motors → pen
```

---

## 0. Parts list

| Part | Qty | Notes |
|------|-----|-------|
| Arduino Uno (CH340 clones are fine) | 1 | runs grbl_servo_z |
| 28BYJ-48 5 V stepper + ULN2003 driver board | 2 | X and Y |
| SG90 (or MG90S) servo | 1 | pen lift on Z |
| External 5 V supply, 2 A or more | 1 | servo and drivers; **not** the Uno's 5 V pin |
| 470 µF capacitor | 1 | across the servo's 5 V / GND, recommended |
| USB **data** cable | 1 | charge-only cables show no COM port |

Flash the firmware from the Arduino IDE: install the library into
`Documents\Arduino\libraries\grbl_servo_z` (remove any stock `grbl` library
first), open *File → Examples → grbl_servo_z → grblUpload*, and upload. Retry
if it reports `flash verification mismatch` — CH340 clones do that.

---

## 1. Wiring and firmware settings

`pcb_gcode.py`, `grbl/profile.py` and the `SIM` port all match this build.
Pins are read from the firmware source (`cpu_map.h`, `stepper.c`, `servo.c`),
not its README, which still says D11 for the servo.

| Part | Arduino pin | Notes |
|------|-------------|-------|
| X 28BYJ-48 via ULN2003: IN1 / IN2 / IN3 / IN4 | **D5 / D4 / D3 / D2** | half-step sequence written straight to `PORTD` |
| Y 28BYJ-48 via ULN2003: IN1 / IN2 / IN3 / IN4 | **A3 / A2 / A1 / A0** | same sequence on `PORTC` |
| SG90 signal (orange) | **D10** | Timer2 ISRs; D11 is not used |
| SG90 V+ (red) / GND (brown) | external 5 V + / − | GND also to Arduino GND |
| ULN2003 boards 5–12 V / GND | external supply | GND common with the Arduino |
| D8, D9, D12, D13 | — | set as outputs at boot, unused (were the Z stepper) |
| Limit switches, probe, cycle start/hold | — | none: the fork's limit and control pins are virtual |

The firmware's defaults, and what the software assumes from them:

| Setting | Firmware | Software |
|---------|----------|----------|
| Baud | 115200 | `profile.baud` 115200 |
| RX buffer | 128 bytes | `profile.rx_buffer` 128 |
| Pen | Z < 0 → down, Z ≥ 0 → up (`SERVO_Z_THRESHOLD_STEPS 0`) | pen down Z-0.5, up Z0.5 |
| Servo travel | planned Z move; 1 mm at F200 = 300 ms | every Z move is `G1 … F200` |
| `$100-$102` steps/mm | 250 | — |
| `$110-$112` max rate | 500 mm/min | draw, travel and jog feeds 500 |
| `$22` homing | 0 (no switches) | Home button disabled; zero X/Y by hand |
| G54 work offset | kept in EEPROM across resets | cleared on every connect; Z zero refused |
| `$21` hard limits | 0 — keep it off, or it alarms instantly | — |

If you change `$110`/`$111` on the board, raise `travel_feed`/`draw_feed` in
`pcb_gcode.py` and `grbl/profile.py` to match; Grbl clamps any F above them.

---

## 2. Connecting to TraceWorks

Plug the controller into the PC running the backend with a **data** USB cable.
That is the whole connection story: the backend owns the serial port, because
a browser tab cannot open one and `localhost:8000` can. Open `/connect`, pick
the port, press Connect.

There is no device ID, no pairing, and nothing on the network. If you want to
try the app without hardware, start the backend with `TRACEWORKS_SIM=1` and
connect to the port named `SIM`.

**Connecting resets the controller.** Opening the port toggles DTR and the
board reboots with machine position 0 wherever the pen is. Grbl would bring
back the last G54 work zero from EEPROM, which without homing points at an
arbitrary spot, so TraceWorks clears it (`G10 L2 P1 X0 Y0 Z0`, `G92.1`) the
moment the board announces itself. Work zero is therefore **where the pen
sits when you connect** — put it over the board's corner first, or jog there
and zero X + Y on `/dashboard/device`.

**Never zero Z.** The servo switches on *machine* Z (below 0 is down), and a
Z work offset shifts every G-code Z without moving that switch, so the pen
would stay down between traces. The app refuses it.

---

## 3. First-plot checklist (safe order)

Do these in order — each step catches problems before they can damage anything.

1. **Offline visual** — open the board in TraceWorks and check the toolpath
   preview (or `python pcb_gcode_preview.py`). No hardware needed.
2. **Pen test** — on `/dashboard/device`, jog Z down and up. The servo should
   drop below Z0 and lift at Z0 and above. If it never moves, check the
   signal wire is on **D10**.
3. **Set work zero** — jog the pen to the board's bottom-left corner and press
   *zero X + Y*. There is no homing on this firmware; Z is never zeroed.
4. **Dry check** — on the board page, run the check (Grbl check mode, `$C`):
   every line is parsed, **no motion**. Fix any `error:N` before continuing.
5. **Pen-up dry run** — take the pen out and plot. Watch that the motion stays
   within the bed and matches the preview.
6. **Real plot** — put the pen back and plot for real.

From the command line, `python pcb_send.py --port COM3 --check` and
`python pcb_send.py --port COM3` do steps 4 and 6. Replace `COM3` with your
board's port (Device Manager → Ports (COM & LPT) → "USB-SERIAL CH340").

---

## Reference links
- grbl_servo_z — https://github.com/moi-script/grbl_servo_z
- Grbl 1.1 settings (`$$`) — https://github.com/gnea/grbl/wiki/Grbl-v1.1-Configuration
- Grbl 1.1 error and alarm codes — https://github.com/gnea/grbl/wiki/Grbl-v1.1-Interface

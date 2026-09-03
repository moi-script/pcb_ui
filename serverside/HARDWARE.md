# Hardware Setup — ESP32 Pen Plotter (FluidNC)

How to build and set up the machine that plots the G-code produced by this
project. The controller runs **FluidNC** — free, open-source CNC firmware that
you flash onto an ESP32. You don't write or build it; you install it once.

```
KiCad → pcb_gcode.py → labExam.gcode → pcb_send.py → [ESP32 running FluidNC] → motors → pen
```

---

## 1. Parts list

### Recommended (easiest): all-in-one board
| Part | Notes |
|------|-------|
| **MKS DLC32** controller | ESP32 + stepper drivers + connectors on one board; FluidNC supports it out of the box |
| 2 × **NEMA 17** stepper motors | one for X, one for Y |
| 1 × **SG90 / MG90S** servo | pen up/down (lift) |
| 5–12 V power supply | match your motors / board rating |
| USB cable (data, not charge-only) | ESP32 ↔ PC for flashing and streaming |
| Belts, pulleys, rails/frame | the mechanical plotter (kit or 3D-printed) |

### Alternative (cheaper, more wiring): bare ESP32 + drivers
| Part | Notes |
|------|-------|
| **ESP32 DevKit** board | the microcontroller |
| CNC shield **or** 2 × stepper driver modules | **TMC2209** (quiet) or **A4988** (cheap) |
| 2 × NEMA 17 steppers + 1 servo | same as above |
| Power supply, USB cable, frame | same as above |

> The ESP32 by itself **cannot** drive motors — its pins output weak logic
> signals. The stepper **drivers** sit between the ESP32 and the motors. This is
> why the all-in-one board is simpler for a first build.

---

## 2. Flashing FluidNC onto the ESP32

FluidNC is separate, ready-made software. Flashing = writing that firmware into
the ESP32 over USB. Do it once (repeat only to update).

### Easiest method — browser web installer (nothing to install on your PC)
1. Plug the ESP32 / controller board into your PC with a **data** USB cable.
2. Open **https://install.fluidnc.com** in **Chrome** or **Edge**
   (uses the browser's Web Serial API — Firefox/Safari won't work).
3. Click **Connect**, and pick the serial port for your board.
   - On Windows the port looks like `COM5`. If none appears, install the USB
     driver for your board's USB chip (usually **CP2102** or **CH340**).
4. Choose the latest **FluidNC** release, then **Install / Flash**.
5. Wait for it to finish (~1–2 min) and reboot the board.
6. Still in the installer, open the **Terminal**/console and type:
   ```
   $I
   ```
   FluidNC should reply with its version — confirms the flash worked.

### Alternative methods (optional)
- **esptool** (command line): `esptool.py write_flash ...` with the release `.bin`.
- **PlatformIO**: build from source (github.com/bdring/FluidNC) and upload.

The web installer is by far the simplest — use it unless you have a reason not to.

---

## 3. Configure your machine (`config.yaml`)

After flashing, FluidNC needs a **config file** describing *your* machine —
which ESP32 pin drives which motor, travel limits, steps/mm, etc. This is
configuration, not programming. Upload it via the FluidNC web UI
(Files page) or the installer terminal.

> **Important:** the pin numbers below are a **starting point for a bare ESP32 +
> external drivers**. They MUST match how *you* wired it. If you use an MKS
> DLC32 (or another ready board), start from that board's official example at
> **github.com/bdring/FluidNC/tree/main/example_configs** instead — those boards
> use I2S/shift-register pins, not plain GPIO.

### Starter config — 2-axis pen plotter (X, Y steppers + servo pen)

```yaml
name: "PCB Pen Plotter"
board: "ESP32 DevKit"

stepping:
  engine: RMT          # standard GPIO stepping for a bare ESP32
  idle_ms: 255
  pulse_us: 4
  dir_delay_us: 1

# One pin disables all drivers (tie your drivers' EN pins together to it)
axes:
  shared_stepper_disable_pin: gpio.13:high

  x:
    steps_per_mm: 80          # 20T GT2 pulley + 1/16 microstep ≈ 80; TUNE THIS
    max_rate_mm_per_min: 5000
    acceleration_mm_per_sec2: 300
    max_travel_mm: 300
    homing:
      cycle: 1
      positive_direction: false
      mpos_mm: 0
      feed_mm_per_min: 300
      seek_mm_per_min: 1500
    motor0:
      limit_all_pin: gpio.17:low:pu   # optional endstop; remove if none
      hard_limits: false
      standard_stepper:
        step_pin: gpio.12
        direction_pin: gpio.14

  y:
    steps_per_mm: 80          # TUNE THIS to match your mechanics
    max_rate_mm_per_min: 5000
    acceleration_mm_per_sec2: 300
    max_travel_mm: 300
    homing:
      cycle: 1
      positive_direction: false
      mpos_mm: 0
      feed_mm_per_min: 300
      seek_mm_per_min: 1500
    motor0:
      limit_all_pin: gpio.16:low:pu   # optional endstop; remove if none
      hard_limits: false
      standard_stepper:
        step_pin: gpio.26
        direction_pin: gpio.15

  # Pen lift on "Z" via a hobby servo. The G-code uses Z moves:
  #   G0 Z5  = pen up,  G1 Z0 = pen down (see pcb_gcode.py CONFIG).
  # FluidNC maps the Z position range to the servo pulse range below.
  z:
    steps_per_mm: 100
    max_travel_mm: 5           # matches pen_up_z = 5 mm in pcb_gcode.py
    motor0:
      servo:
        pwm_hz: 50
        output_pin: gpio.27
        min_pulse_us: 1000     # pen DOWN position  (Z = 0)
        max_pulse_us: 2000     # pen UP position    (Z = max_travel)

# No spindle/laser on a pen plotter
start:
  must_home: false            # set true once endstops are wired & tested
```

### After uploading the config
- Send `$$` in the terminal to list settings and confirm it loaded.
- **Jog carefully** a few mm on X and Y and check direction; if an axis moves
  the wrong way, flip `direction_pin` polarity or swap motor wiring.
- Tune `steps_per_mm` until a commanded 100 mm move measures 100 mm.
- Adjust the servo `min_pulse_us` / `max_pulse_us` so the pen clearly lifts and
  touches. These must line up with `pen_up_z` / `pen_down_z` in `pcb_gcode.py`.

---

## 4. First-plot checklist (safe order)

Do these in order — each step catches problems before they can damage anything.

1. **Offline visual** — `python pcb_gcode_preview.py`
   Confirms the toolpath geometry looks right (no hardware).
2. **Firmware validation** — `python pcb_send.py --port COM5 --check`
   FluidNC Check Mode (`$C`): parses every line, **no motion**. Fix any
   `error:N` before continuing.
3. **Pen-up dry run** — raise/disconnect the pen, then
   `python pcb_send.py --port COM5`
   Watch that the motion stays within the bed and matches the preview.
4. **Real plot** — lower the pen and run it for real.
   `python pcb_send.py --port COM5`

Replace `COM5` with your board's port (Windows: Device Manager → Ports;
Linux/Mac: `/dev/ttyUSB0` or `/dev/tty.usbserial-*`).

---

## 5. WiFi option (no USB cable)

FluidNC also serves a **browser web UI over WiFi**. Once you set WiFi
credentials in the config (or via the terminal), you can open the ESP32's web
page to jog the machine, upload a `.gcode` file, and watch a built-in toolpath
visualizer — an alternative to `pcb_send.py` over USB.

---

## Reference links
- FluidNC web installer — https://install.fluidnc.com
- FluidNC source & docs — https://github.com/bdring/FluidNC
- FluidNC wiki (config, senders) — http://wiki.fluidnc.com
- Example board configs — https://github.com/bdring/FluidNC/tree/main/example_configs

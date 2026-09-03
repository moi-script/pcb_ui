# ESP32 G-code Bridge

`esp32_bridge/esp32_bridge.ino` turns an ESP32 into a WiFi-to-serial bridge: it
receives a G-code job over HTTP from the TraceWorks backend and streams it,
line by line, to an **Arduino running GRBL** over serial — using GRBL's standard
`ok` handshake.

```
web app  ->  FastAPI backend  ->  [ESP32 bridge]  --serial-->  Arduino (GRBL)  ->  motors/pen
```

This is an alternative to the all-in-one **FluidNC on ESP32** path in
[`../HARDWARE.md`](../HARDWARE.md). Use this bridge when your motion controller
is a separate Arduino (e.g. an Uno + CNC shield) flashed with stock GRBL.

## What you provide

- **An Arduino flashed with GRBL.** This repo does not generate GRBL — flash it
  yourself from <https://github.com/grbl/grbl> (Arduino Uno/Nano, ATmega328).
  Tune `$100/$101` (steps/mm) and the servo/pen setup for your machine.
- **WiFi credentials.** Edit the two `#define`s at the top of the `.ino`.

## Wiring

| ESP32            | Arduino (GRBL) | Note                                  |
|------------------|----------------|---------------------------------------|
| GPIO17 (TX2)     | RX (D0)        | ESP32 sends G-code to the Arduino     |
| GPIO16 (RX2)     | TX (D1)        | ESP32 reads GRBL's `ok`/`error`       |
| GND              | GND            | **Common ground is required**         |

Both boards here run at 3.3 V logic on their UART for the ESP32 side; a classic
5 V Arduino Uno's TX is 5 V. The ESP32 RX pin is **not** 5 V tolerant — put a
simple divider (e.g. 1kΩ/2kΩ) or a level shifter on the Arduino-TX → ESP32-RX16
line. The ESP32-TX17 → Arduino-RX direction is fine as-is.

Do not power the Arduino from the ESP32; give each its own supply and just share
ground. Flashing/serial-monitor USB can stay connected to the Arduino for GRBL
tuning.

## Flashing the ESP32

1. Arduino IDE → install the **esp32** boards package (Boards Manager).
2. Open `esp32_bridge/esp32_bridge.ino`, fill in `WIFI_SSID` / `WIFI_PASSWORD`.
3. Select your ESP32 board + port, **Upload**.
4. Open Serial Monitor @ 115200 — it prints the bridge IP once WiFi connects,
   e.g. `Bridge ready at http://192.168.1.42`.

## Point TraceWorks at it

The backend sends jobs to `http://<device-ip>/print`, where `<device-ip>` is the
paired device's `port` field (the machine IP). For a bench test without the
real board, set `ESP_BASE_URL` on the backend to override it (see
`esp_mock.py`).

## HTTP API (port 80)

| Method | Path      | Purpose                                             |
|--------|-----------|-----------------------------------------------------|
| POST   | `/print`  | Body = raw G-code. Header `X-Check: 1` runs GRBL `$C` (validate only) first. Returns `202`; streaming runs in the background. |
| GET    | `/status` | `{"state","line","total"}` — poll for progress.     |
| POST   | `/stop`   | Feed-hold + soft-reset, aborts the job.             |
| GET    | `/`       | Health/info.                                        |

`state` ∈ `idle | checking | printing | done | error | stopped`.

## Testing without hardware

`esp_mock.py` emulates this same HTTP API in Python and fakes the line-by-line
pacing, so you can exercise the whole web → backend → ESP chain from your
laptop:

```bash
python firmware/esp_mock.py                 # listens on :8770
# then run the backend pointed at it:
ESP_BASE_URL=http://localhost:8770 uvicorn server:app --reload --port 8000
```

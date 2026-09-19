# SurgeGuard alert hardware

An Arduino Uno with an RGB LED and a buzzer, driven over USB serial by the
backend. It shows the Operational Status on the Decision Engine's current
report: the Crowd Stability Index band, after hysteresis. The backend decides
what to show; the Arduino only shows it.

```
Crowd detection (YOLO + ByteTrack)
  -> Crowd Stability Index
  -> Operational Decision Engine (report issued on every status change)
  -> HardwareAlertService (backend/app/hardware)  -- "CRITICAL\n" over USB serial -->
  -> surgeguard_alert.ino  -- "OK CRITICAL"
  -> RGB LED + buzzer
```

## What it shows

| Command | When | RGB LED | Buzzer |
|---|---|---|---|
| `NORMAL` | Stable or Observe (CSI 60 and above) | Green | Off |
| `WARNING` | Attention Required or High Alert (CSI 20–59) | Yellow (full red, green dimmed to ~8%) | Quiet 70 ms chirp every 1.5 s (the original sketch's alert) |
| `CRITICAL` | Critical (CSI below 20) | Red | Continuous two-tone alarm |
| `NO_DATA` | No camera has a current report (none configured, all offline, or analysis stopped) | Blue | Off |
| *(link lost)* | No command from the backend for 10 s | Blinking blue | Off |

With several cameras, the most urgent camera decides. A camera that is offline,
disabled or whose analysis has stopped is left out, so it can neither hold the
site at its last alarm nor at its last all-clear.

The level follows the report's **status**, not its **priority**. The Decision
Engine can raise priority early on evidence (for example a sudden surge while
the index is still in High Alert); the Command Center shows that, and the
hardware waits until the index itself crosses the critical threshold.

## Wiring

Physically verified on 2026-09-17. Each pin was driven on its own, held for up
to a minute and confirmed by the board's own `STATE` reply, while the operator
reported the colour. The operator's original plan (R=9, G=10, B=11) is not what
is on the breadboard; this table is.

| Part | Uno pin | Verified |
|---|---|---|
| RGB LED blue (through a resistor) | 9 | Pin 9 alone → blue, steady when its jumper is wiggled |
| RGB LED red (through a resistor) | 10 | Pin 10 alone → red, steady when the jumper, its far end and the resistor are wiggled |
| RGB LED green (through a resistor) | 11 | Pin 11 alone → green, steady when wiggled |
| RGB LED common leg | GND | Common cathode: all three pins LOW → dark. For a common-anode LED, wire it to 5V and set `RGB_COMMON_ANODE true` |
| Buzzer | 8 | Driven with `tone()`, as the original sketch did |

**If a colour disappears, reseat its jumper before touching firmware.** Red
once showed nothing on pin 10. Swapping the pin 9 and 10 jumpers at the Uno
isolated it: pin 10 lit blue through the other wire, and the red wire lit red on
pin 9, so the pin, the LED and the resistor were all fine. Swapped back and
pressed fully home, pin 10 was steady red. The cause was a badly seated jumper,
which also explains why earlier tests contradicted each other. The resistor
leads on this breadboard are long, bare and cross one another; keep them apart,
or a nudge can short two colours together.

**Why green is dimmed in software.** Pin 11's PWM runs on Timer2, which `tone()`
owns, so `analogWrite()` on pin 11 would fight the buzzer. The sketch only uses
pin 11 as a digital output and time-slices it with `micros()` at 500 Hz. This
matters for WARNING: with green fully on, yellow looked the same as NORMAL's
green. Red and blue (pins 10 and 9, Timer1) use ordinary PWM. The yellow mix
(`YELLOW_RED 255`, `YELLOW_GREEN 20`) was tuned by eye on this LED with
`TUNE YELLOW`; a different LED or different resistors may need retuning.

## Firmware

`arduino/surgeguard_alert/surgeguard_alert.ino`. It keeps the behaviour of the
sketch that was on the board (`NMDC_FogGuard_FINAL_MANUAL_DEMO_v0_9__1_.ino`,
still in the Arduino sketchbook, unmodified): buzzer on pin 8, 80 ms 1500 Hz
startup beep, and the quiet chirp, now the WARNING pattern.

Build and upload with the Arduino IDE, or with the CLI it bundles:

```bash
arduino-cli compile --fqbn arduino:avr:uno hardware/arduino/surgeguard_alert
```

```bash
arduino-cli upload --fqbn arduino:avr:uno --port COM8 hardware/arduino/surgeguard_alert
```

Only one program can hold the serial port: close the Arduino IDE's Serial
Monitor before uploading or starting the backend.

### Serial protocol

115200 baud, one command per line, case-insensitive. Each accepted command gets
one reply line.

| Send | Reply |
|---|---|
| `NORMAL`, `WARNING`, `CRITICAL`, `NO_DATA` | `OK <command>` |
| `TEST RED`, `TEST GREEN`, `TEST BLUE`, `TEST YELLOW` | `OK TEST <colour>` (silent) |
| `TEST WARNING_TONE`, `TEST ALARM` | `OK TEST <pattern>` (LED off) |
| `TEST SEQUENCE` | Each colour, then the chirp, then the alarm, repeating |
| `TEST OFF` | LED off, silent |
| `TUNE YELLOW <red> <green>` (each 0–255) | `OK TUNE YELLOW <red> <green>`. Changes the yellow mix until the next reset, for tuning by eye; copy the result into `YELLOW_RED`/`YELLOW_GREEN`. The backend never sends it |
| `PING` | `PONG <mode>` |
| `STATUS` | `STATE <mode> <ms in mode>` |
| anything else | `ERR UNKNOWN_COMMAND <text>` |

On power-up it prints `READY SURGEGUARD-ALERT 1.1.0 R10 G11 B9 BUZZER8 CATHODE`.
Opening the port resets an Uno, so the backend waits for this banner, and
resends its level whenever it sees it again. `TEST` commands are exempt from the
10 s link timeout, so a test can be typed into the Serial Monitor with no
backend running.

## Backend

Settings (in `backend/.env`):

```
SURGEGUARD_HARDWARE_ENABLED=true
SURGEGUARD_HARDWARE_SERIAL_PORT=COM8     # or auto: the first connected Arduino
SURGEGUARD_HARDWARE_BAUD_RATE=115200
SURGEGUARD_HARDWARE_KEEPALIVE_SECONDS=3  # under the firmware's 10 s timeout
SURGEGUARD_HARDWARE_RECONNECT_SECONDS=5
```

The service reconciles immediately on every Decision Engine report and at least
once a second. It sends a command when the level changes, resends it as a
keepalive, reconnects after an unplug, and resends after a board reset. On
shutdown it sends `NO_DATA`.

API (operator sign-in required):

| Route | Does |
|---|---|
| `GET /api/v1/hardware` | Connection, firmware, live level and reason, last command and whether the board confirmed it, test state |
| `POST /api/v1/hardware/test` `{"command": "TEST_SEQUENCE", "duration_seconds": 15}` | Hardware test: overrides live monitoring for 1–120 s, then returns on its own. Accepts every command above, including `CRITICAL` |
| `DELETE /api/v1/hardware/test` | End a test now |

In the app: **System → Alert hardware** shows all of this and has the test
buttons.

## Verified (2026-09-17)

- **Firmware on the Uno (COM8):** every command and test answered correctly over serial; unknown commands rejected.
- **Full chain on the real board, production code end to end:** synthetic tracks for a crowd surge ran through crowd analysis, CSI and the Decision Engine to the serial link. The board confirmed `NORMAL` at Stable (CSI 82), `WARNING` 20 ms after the report reached Attention Required (CSI 50), and `CRITICAL` in the same millisecond the report reached Critical (CSI 17). The script is in the session scratchpad; the same chain is `backend/tests/integration/test_hardware_chain.py` against a scripted board.
- **Running backend:** with real YOLO and ByteTrack detection on the demo clip, the board showed `NO_DATA` while the model loaded, then confirmed `NORMAL` (Observe, CSI 62), and followed a brief live `WARNING` and back.
- **Test mode through the API:** a sequence, stop, and a `CRITICAL` test that expired on its own, all confirmed by the board.
- **Physical LED and buzzer, firmware 1.1.0** (the operator looking and listening; the board confirming each state first):
  - NO_DATA (live, no camera reachable): steady blue, silent.
  - NORMAL: green, silent.
  - WARNING: yellow, with the chirp every 1.5 s.
  - CRITICAL: red, with the two-tone alarm.
  - NORMAL → WARNING → CRITICAL → NORMAL: each change followed, and the alarm stopped cleanly.
  - Link lost: the board declared it 10 s after its last level command and blinked blue.
  - `TEST SEQUENCE`: red, green, blue and yellow are all distinct.
- **Backend restart:** after a forced kill, the restarted backend reconnected and sent `NO_DATA`, then the live Decision Engine level (`NORMAL`, Stable CSI 100) as soon as a camera reported. The LED went from blinking blue to steady green.
- **Not verified physically:** recovery from a USB unplug and replug. On both attempts the backend logged no disconnect and the board did not reboot, so the connection was never actually broken. The service's reconnect and resend-after-reset paths are covered by `test_hardware_service` and were exercised on the board earlier, but not while anyone watched the LED.

# DualShock 3 and Pressure-Sensitive Buttons

`dualshock-3-full`, new in v1.10.0, is a DualShock 3 in the form Sony's sixaxis.sys driver and DsHidMini's SXS mode present on Windows. That is the form PCSX2 and RPCS3 read button pressure from. It answers [PadForge discussion #476](https://github.com/hifihedgehog/PadForge/discussions/476).

Source: [`profiles/sony/dualshock-3-full.json`](https://github.com/hifihedgehog/HIDMaestro/blob/master/profiles/sony/dualshock-3-full.json), the `Ds3` functions in [`driver/driver.c`](https://github.com/hifihedgehog/HIDMaestro/blob/master/driver/driver.c), and the probe that verifies it, [`test/probes/ds3_sixaxis_check`](https://github.com/hifihedgehog/HIDMaestro/tree/master/test/probes/ds3_sixaxis_check).

---

## Which profile to pick

| Profile | What a host sees | Pressure and motion |
|---|---|---|
| `dualshock-3` | The pad's own 148-byte USB descriptor, filled through the standard descriptor path | Neither. Rumble and the player LEDs since v1.10.1 |
| `dualshock-3-full` | A 12-byte joystick report, and the whole native 49-byte report as feature report 0 | Both, plus battery, rumble and the player LEDs |

PS3 emulators want `dualshock-3-full`.

## Driving it

```csharp
var ds3 = ctx.GetProfile("dualshock-3-full")!;
using var pad = ctx.CreateController(ds3);

var state = new HMGamepadState
{
    Axes = HMGamepadStateHelpers.StandardAxes(ds3, leftTrigger: 0.5f),
    Buttons = HMButton.A,      // cross, pressed
    PressureA = 180,           // how hard cross is pressed
    PressureDpadUp = 90,       // pressure on a button not yet pressed
};
pad.SubmitState(in state);
```

Ten fields carry pressure from 0 to 255: `PressureA` (cross), `PressureB` (circle), `PressureX` (square), `PressureY` (triangle), `PressureLeftBumper`, `PressureRightBumper`, and `PressureDpadUp`, `PressureDpadRight`, `PressureDpadDown`, `PressureDpadLeft`. L2 and R2 take their pressure from the triggers.

A pressed button whose pressure is left at 0 is sent as 255, so code that only knows digital state presses every button fully. A nonzero pressure is sent as given, whether or not the button is pressed.

Motion comes from `AccelX`, `AccelY` and `AccelZ` at 8192 counts per g and `GyroYaw` at 16 counts per degree per second, the same units the DualShock 4 and DualSense profiles use. The persona converts them to the DualShock 3's 10-bit sensors, 113 counts per g and 123 per 90 degrees per second, the scales Linux's `hid-sony.c` and RPCS3 use. A DualShock 3 has one gyro axis, so `GyroPitch` and `GyroRoll` are not sent. `BatteryLevel` (0 to 10) maps to the pad's own 0 to 5 scale, and `BatteryCharging` and `BatteryFull` send its charging and charged codes.

## Output

On both profiles, rumble and LED writes arrive on `OutputDecoded` as report `0x01`, the native output report. `dualshock-3` decodes the report as a host writes it, since v1.10.1. `dualshock-3-full` also takes the sixaxis.sys form, described under How it works:

| Field | Meaning |
|---|---|
| `rightMotorOn` | The small motor, 0 off or 1 on |
| `rightMotorDuration` | How long the small motor runs, 0xFF forever |
| `leftMotorForce` | The large motor, 0 to 255 |
| `leftMotorDuration` | How long the large motor runs, 0xFF forever |
| `ledBitmap` | The player LEDs: LED 1 is 0x02, LED 2 0x04, LED 3 0x08, LED 4 0x10 |

A host reaches `dualshock-3`'s decode by writing the report itself, through `WriteFile` or `HidD_SetOutputReport`. Stock SDL's PS3 driver does not open `dualshock-3` on Windows: it reads feature reports 0xF2 and 0xF5 first, the native descriptor declares neither, and Windows' HID class driver refuses both.

## PCSX2

PCSX2 reads controllers through SDL. On Windows it turns on SDL's sixaxis driver (`SDL_HINT_JOYSTICK_HIDAPI_PS3_SIXAXIS_DRIVER`) and treats a pad as pressure-sensitive when SDL reports a PS3 controller with 16 axes and 11 buttons. Its automatic mapping then binds the ten pressure axes to Cross, Circle, Square, Triangle, L1, R1 and the d-pad. Stock SDL with those hints opens `dualshock-3-full` as exactly that controller.

## RPCS3

Pick the DualShock 3 handler in RPCS3's pad settings. On Windows it looks for 054C:0268, reads feature report 0xF2 with a 255-byte buffer, keeps the pad when the reply comes back under that id, and polls the same report for state: buttons, sticks, the twelve pressure bytes, the motion sensors and the battery. Its rumble and LED writes come back on `OutputDecoded`.

## How it works

The profile's `extendedReport` is the native report 0x01 with `alwaysArmed`, so the SDK fills it every frame and the driver keeps the latest copy. The driver derives the rest from it the way DsHidMini's SXS mode does. The 12-byte input report carries the buttons, the hat, the sticks, and four inverted pressure bytes. The feature reply sets the report's first two bytes to 0x00 and 0x3F, turns the motion words little-endian, and mirrors accelerometer X.

The descriptor declares no report ids, so the HID class hands every feature read to the driver as report 0, whatever id the reader asked for, and leaves the reader's id byte in place. A read of 0xF2 therefore returns the same report, as it does on DsHidMini.

Output arrives as report 0 with a sixaxis.sys command in its first byte. For command 2, which sets the motors, everything after the three-byte command header is the native output report's body. DsHidMini applies it that way, and RPCS3 lays out its Windows report to match. Command 1 sets the four player LEDs, which the driver writes into the native report's LED bitmap.

## What is verified

Battery scenario S64 checks, first offline and then on a live persona:

- The native report against the offsets SDL, Linux and RPCS3 read, every pressure byte included, and the motion values against the values RPCS3 computes from a DualShock 4 in the same state.
- The live joystick report and the feature reply against DsHidMini's conversions.
- RPCS3's read sequence: 0xF2 answers under its own id, and polling 0xF2 returns the same bytes as report 0.
- Rumble and LED writes in SDL's form and in RPCS3's form, decoded on `OutputDecoded`.
- Stock SDL with PCSX2's hints: a PS3 controller with 16 axes and 11 buttons, every pressure axis at the value submitted, the player LED SDL sets, and rumble.
- On `dualshock-3`, the native output report through `WriteFile` and `HidD_SetOutputReport`, every field decoded on `OutputDecoded`, a stop included.

Neither PCSX2 nor RPCS3 has been run against the persona.

SDL's sixaxis driver reads the feature reply's motion words big-endian. DsHidMini and RPCS3 read them little-endian, and the persona follows DsHidMini, so SDL reports wrong accelerometer values through that driver, as it does on DsHidMini. PCSX2 uses no motion.

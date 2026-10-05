# Switch 2 Pro Controller with Motion

`switch2-pro-controller-composite`, new in v1.11.0, is a Nintendo Switch 2 Pro Controller as the pad appears over USB on firmware 1.1.5. It has the second interface that SDL's Switch 2 driver and Steam start the pad through, and it carries the pad's motion. It answers [issue #66](https://github.com/hifihedgehog/HIDMaestro/issues/66).

Source: [`profiles/nintendo/switch2-pro-composite.json`](https://github.com/hifihedgehog/HIDMaestro/blob/master/profiles/nintendo/switch2-pro-composite.json), [`Switch2ProDevice.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/Internal/Usbip/Switch2ProDevice.cs) for the device side, [`Switch2ProPacker.cs`](https://github.com/hifihedgehog/HIDMaestro/blob/master/sdk/HIDMaestro.Core/Internal/Switch2ProPacker.cs) for the SDK side, and the probe that verifies it, [`test/probes/switch2_composite_check`](https://github.com/hifihedgehog/HIDMaestro/tree/master/test/probes/switch2_composite_check).

---

## Which profile to pick

| Profile | What a host sees | Who reads it |
|---|---|---|
| `switch2-pro-controller` | One HID interface streaming report `0x09`, through HIDMaestro's UMDF2 driver | DirectInput, RawInput, WGI, browsers, and SDL once a consumer registers the profile's `sdlMapping`. No motion |
| `switch2-pro-controller-composite` | The pad's two USB interfaces, HID and a vendor bulk pair, and report `0x05` with motion once a host starts the pad | Steam, and SDL built with libusb |

The two do not overlap. A host that does not speak the pad's command protocol never starts the composite persona, so DirectInput, RawInput, WGI and browsers see a gamepad that never reports, as they do with a real pad on Windows. Games that read the pad through Steam Input, or through SDL with libusb, want the composite persona.

## Driving it

```csharp
var pro2 = ctx.GetProfile("switch2-pro-controller-composite")!;
using var pad = ctx.CreateController(pro2);

var state = new HMGamepadState
{
    Axes = HMGamepadStateHelpers.StandardAxes(pro2, rightTrigger: 1f),
    Buttons = HMButton.A,
    AccelGY = 1.0f,    // at rest: gravity reads along +Y
    GyroDpsX = 100f,   // turning about X at 100 degrees per second
};
pad.SubmitState(in state);
```

Buttons follow the labels on the pad. `HMButton.A`, `B`, `X` and `Y` are the pad's A, B, X and Y, `Start` is Plus, `Back` is Minus, `Guide` is Home, `Share` is Capture, `LeftBumper` and `RightBumper` are L and R, `LeftPaddle` and `RightPaddle` are GL and GR, and `Misc1` is C. ZL and ZR are pressed while their trigger is above zero, and the d-pad comes from `Hat`. The sticks use the whole 12-bit range with the center at 0x800.

Motion is the calibrated channel in SDL's sensor frame: `AccelGX`, `AccelGY` and `AccelGZ` in g, and `GyroDpsX`, `GyroDpsY` and `GyroDpsZ` in degrees per second. The persona converts them to the pad's raw counts with the constants SDL's driver applies to this pad, 32767 counts per 8 g and per 34.8 radians per second. SDL reads each value back on the axis it was submitted on, with its sign: 1 g as 9.807 m/s², 100 deg/s as 1.745 rad/s. Report `0x05` carries motion while a host has the IMU feature enabled, which SDL and Steam do when they start the pad.

`SubmitState` is the only input path. `SubmitRawReport` and `SubmitRawExtendedReport` throw `NotSupportedException` on this persona, because the device decides which report goes out and stamps its counters. A submit replaces the state the next report is built from. The persona sends one report every 4 ms whatever rate the consumer submits at.

## Output

Rumble is output report `0x02`, one block for each actuator. `OutputDecoded` reports it as `leftMotor` and `rightMotor`, 0 to 255. `leftMotor` follows SDL's low-frequency rumble value and `rightMotor` its high-frequency value: `SDL_RumbleGamepad(0x8000, 0x4000)` decodes to 127 and 64, a stop to 0 and 0. `OutputReceived` carries the report whole.

## Steam and SDL

Steam adds the persona as a Nintendo Switch Pro Controller on its Switch 2 driver and gives it the Switch Pro configuration set. It starts the pad with the same commands SDL sends, sets the player LED, and reads 250 reports a second.

SDL's Switch 2 driver needs the vendor interface, which on Windows means SDL built with libusb. libusb can claim the interface because Windows binds WinUSB to it from the persona's own Microsoft OS 1.0 descriptors, with no INF and no driver install.

## How it works

The persona runs on the USB/IP backend, the same bundled usbip-win2 transport as the [composite USB personas](usb-audio-composite.md). Its device and configuration descriptors are a real pad's, byte for byte, from a link-layer capture of a console driving one: interface 0 is HID with the 97-byte report descriptor `switch2-pro-controller` also carries, and interface 1 is class 0xFF with a bulk OUT and a bulk IN endpoint.

A host sends commands on bulk OUT, an 8-byte header and data, and reads each reply on bulk IN. The persona answers every command as it arrives: the flash reads that carry its serial and stick calibration, the feature mask and the features it enables, the report selection, the player LEDs, the firmware version. Like the pad, it sends nothing on its interrupt endpoint until a host sends the start command. From then on it sends one report every 4 ms from a high-resolution timer, report `0x09` until a host selects report `0x05`. Each report is built when it goes out, from the consumer's newest state. Each report's motion timestamp advances 4000 microseconds, and SDL hands it on as the time of each sample, so the reports have to be 4 ms apart in real time. That is why the clock belongs to the device and not to the consumer's submit rate.

## Known issue

A bulk read that a host abandons comes back as success with stale bytes, and so do the reads after it. usbip-win2 0.9.8.1 completes a canceled transfer without resetting its length (`drivers/ude/request_list.cpp`), and WinUSB takes that length as bytes received. SDL and Steam read only after they send a command, so neither meets it.

Not emulated: headset audio, NFC, pairing, firmware update and the magnetometer.

## What is verified

Battery scenario S65 checks, first with the probe in the driver's place and then on a live persona:

- Both descriptors against the capture, the Microsoft OS 1.0 requests, silence until the start command, every command the table names, the flash image, the 4 ms clock, reports `0x09` and `0x05`, and the IMU feature gating motion.
- HidUsb on interface 0 and WinUSB on interface 1, bound from the persona's own descriptors, and the same serial in the USB string, the HID string and the flash.
- PadForge's SDL3 fork with libusb: the persona opens as a Nintendo Switch Pro Controller, receives SDL's whole start sequence, reads 1 g and 100 deg/s back within 1 percent on every axis with the sign, steps its sensor timestamps by 4 ms, reads every button, both sticks and both triggers, and rumbles.
- Two personas at once, each answering its own handle.
- The Steam client adding the persona, starting it, and reading it for eight seconds without abandoning a read.

Not run: a real wired Pro Controller 2 beside the persona, the gyro moving in Steam's own controller settings screen, and stock SDL3 from libsdl.org.

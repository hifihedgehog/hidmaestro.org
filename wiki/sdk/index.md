---
title: SDK
---

# SDK

The public C# surface a consumer talks to, in `HIDMaestro.Core.dll`.

Programs built on HIDMaestro 1.x must move to 2.0.0. [Moving from 1.x](../start/migration.md)
lists every change a 1.x program meets.

- **[SDK Reference](sdk-reference.md)**: `HMContext` (driver lifecycle,
  profile catalog, controller allocation), `HMController` (input submit,
  output events, PID FFB publish), `HMProfile` (immutable identity plus
  parsed descriptor layout), and `HMGamepadState` (the abstract input
  frame). Every method with thread-safety, throw conditions, and example
  usage.
- **[HID Descriptor Builder](hid-descriptor-builder.md)**: the
  `HidDescriptorBuilder` fluent API for authoring gamepad and joystick
  descriptors, and the rules it enforces.
- **[Force Feedback](force-feedback.md)**: the HID PID 1.0 round-trip,
  from descriptor authoring to the canonical packet ordering DirectInput
  games expect.
- **[Output Passthrough](output-passthrough.md)**: the output ring buffer,
  `OutputReceived` and `OutputDecoded` events, and encoding output in the
  other direction.
- **[Controller Audio (Composite USB)](usb-audio-composite.md)**: the
  four-interface Sony personas, the 4-channel stream whose channels 3 and
  4 are the DualSense's voice-coil actuators, `HMController.UsbAudio` for
  speaker and haptic PCM and the microphone, and the USB transport that
  ships inside the DLL and deploys itself.
- **[DualShock 3 and Pressure](dualshock-3.md)**: the `dualshock-3-full`
  persona, the ten `Pressure*` fields, and how PCSX2 and RPCS3 read it.
- **[Programs Side by Side](programs-side-by-side.md)**: two or more
  programs that embed HIDMaestro on one machine. Ownership claims,
  machine-wide transport indices, identity keys, sweeps of exited programs
  only, one driver deploy at a time that never downgrades, and the
  machine-wide locks.
- **[Wii U GameCube Adapter](gamecube-adapter.md)**: the
  `gamecube-adapter` persona, `HMController.Ports`, `BindWinUsb()` for
  Dolphin, Slippi and SDL, rumble, and the host poll interval.
- **[Switch 2 Pro with Motion](switch2-pro.md)**: the
  `switch2-pro-controller-composite` persona, its two USB interfaces,
  motion for Steam and SDL, and what each host needs.
- **[OEM Name Override](oem-name-override.md)**: make `joy.cpl` and
  DirectInput consumers show the label you want, transactionally and
  crash-safe.

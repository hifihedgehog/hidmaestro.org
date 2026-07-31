---
title: SDK
---

# SDK

The public C# surface a consumer talks to, in `HIDMaestro.Core.dll`.

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
- **[OEM Name Override](oem-name-override.md)**: make `joy.cpl` and
  DirectInput consumers show the label you want, transactionally and
  crash-safe.

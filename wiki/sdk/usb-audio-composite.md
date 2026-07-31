# Controller Audio (Composite USB Personas)

A real USB DualSense presents four interfaces: USB Audio Class speaker/haptics out, microphone in, and HID. The standard `dualsense` profile presents the HID interface only, because that is the one interface UMDF2 can create. Two profiles present the full composite:

| Profile | Audio out | Audio in | Haptics lane |
|--|--|--|--|
| `dualsense-composite` | 4 ch / 16-bit / 48 kHz (channels 1/2 speaker, 3/4 voice-coil actuators) | 2 ch / 48 kHz microphone | **Yes** |
| `dualshock-4-v2-composite` | 2 ch / 16-bit / 32 kHz headset | 1 ch / 16 kHz microphone | No (hardware has none) |

Every descriptor byte comes verbatim from a real pad's hardware dump, and the UAC volume/mute ranges are the real pad's wire values captured from live control transfers. Windows surfaces the same audio endpoints it would for the physical controller: **Speakers (Wireless Controller)** and **Headset Microphone (Wireless Controller)**.

The 4-channel OUT stream matters because channels 3/4 are the DualSense's voice-coil actuators. That stream is the only path on Windows by which a game hands a controller its authored haptic waveforms. Games that render audio to the controller endpoint reach the SDK, and the consumer routes the haptic lanes to real hardware.

---

## Opt-in backend: usbip-win2

The composite profiles declare `"backend": "usbip"` and require [usbip-win2](https://github.com/vadimgrn/usbip-win2) **0.9.7.7** installed. usbip-win2 is a third-party, BSD-2, WHLK-certified signed kernel driver providing a virtual USB host controller. A Windows audio endpoint requires a driver-backed USB device, and no user-mode API can create one, so this is the one capability that cannot ride UMDF2.

The rules:

- **HIDMaestro never installs or bundles usbip-win2.** Users opt in by installing it themselves.
- **Nothing changes without it.** Standard profiles keep working with zero dependencies. `CreateController` on a composite profile throws `NotSupportedException` with install guidance.
- **Gate your picker** on `HMContext.IsUsbipBackendAvailable` (a pure presence probe) plus `HMProfile.RequiresUsbipBackend`.
- **The version is pinned at 0.9.7.7.** 0.9.7.8 has two open kernel-pool-corruption reports ([#180](https://github.com/vadimgrn/usbip-win2/issues/180), [#181](https://github.com/vadimgrn/usbip-win2/issues/181)). Gate any bump on those closing.

The SDK runs an in-process USB/IP device server on loopback (fixed port range 18509-18524). Every device behavior stays in user space: descriptor service, HID reports through the same shared-memory contract as UMDF2 profiles, and a highest-priority pacing thread that completes isochronous URBs at the endpoint's 1 ms service interval. Installing usbip-win2 restarts the USB root hubs once (its extension INF re-enumerates them), so expect a brief input blink at install time and on its version updates. Measured idle cost with the driver installed and no device attached: indistinguishable from baseline (0.35% vs 0.24% CPU on an Atom Z8350).

`HMController.SubmitState`, `SubmitRawReport`, `OutputReceived`, `OutputDecoded`, and the Sony feature-report behavior are identical across backends. The HID interface of each composite is byte-identical to its UMDF2 sibling.

---

## The audio surfaces

Composite controllers expose `HMController.UsbAudio` (null on every UMDF2 profile):

```csharp
var controller = ctx.CreateController(ctx.GetProfile("dualsense-composite"));
var audio = controller.UsbAudio!;

// Host → consumer: the game's speaker + haptic PCM, paced at the wire rate.
audio.Output.FramesReceived += (output, pcm) =>
{
    // Interleaved 16-bit little-endian PCM. output.ChannelRoles maps the
    // channels: ["speakerLeft", "speakerRight", "hapticLeft", "hapticRight"].
    // The memory is only valid during the callback; copy to retain.
};
audio.Output.StreamingChanged += (_, open) => { /* audio session opened/parked */ };

// Consumer → host: feed the microphone. Silence when the buffer runs dry.
audio.Microphone.Submit(pcmBytes);   // interleaved 16-bit LE at the declared format

// Volume/mute writes from Windows (volume mixer, control panel):
audio.ControlChanged += (_, e) =>
    Console.WriteLine($"{e.Function}: {(e.IsMute ? $"mute={e.MuteValue}" : $"{e.VolumeDb:F1} dB")}");
```

`FramesReceived` fires on the backend's pacing thread with a few milliseconds of PCM per window, at the cadence the host renders. Handlers must be quick and thread-safe, the same contract as `OutputReceived`.

One fidelity note worth knowing: Windows persists per-endpoint enable/disable state by device identity. Because the composite presents the real pad's exact identity, it inherits whatever state the machine last had for the real controller's endpoints. If the real pad's speaker endpoint was ever disabled in the Sound control panel, the virtual one arrives disabled too. Re-enable it there once.

---

## Profile schema

Composite personas add two fields to the profile JSON:

- `"backend": "usbip"` marks the instantiation path. It is a property of the device, never a mode toggle on an existing profile: a profile that presented four interfaces with the backend and one without would name a device plus a machine state.
- `"usbConfiguration"` carries the full USB identity: the structured interface/endpoint model the backend routes with, plus the verbatim wire blobs (`deviceDescriptor`, `configurationDescriptor`, `otherSpeedConfigurationDescriptor`), the `busSpeed`, and `audioControls` with the real pad's UAC volume ranges. The blobs are served byte-for-byte and cross-checked against the structured model at create time.

See [Profile System](../profiles/profile-system.md) for the rest of the schema.

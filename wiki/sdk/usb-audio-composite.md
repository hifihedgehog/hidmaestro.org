# Controller Audio (Composite USB Personas)

A real USB DualSense presents four interfaces: USB Audio Class speaker/haptics out, microphone in, and HID. The standard `dualsense` profile presents the HID interface only, because that is the one interface UMDF2 can create. Three profiles present the full composite:

| Profile | Audio out | Audio in | Haptics lane |
|--|--|--|--|
| `dualsense-composite` | 4 ch / 16-bit / 48 kHz (channels 1/2 speaker, 3/4 voice-coil actuators) | 2 ch / 48 kHz microphone | **Yes** |
| `dualsense-edge-composite` | Same 4-ch stream as the base pad, with the Edge's 1 ms USB input polling | 2 ch / 48 kHz microphone | **Yes** |
| `dualshock-4-v2-composite` | 2 ch / 16-bit / 32 kHz headset | 1 ch / 16 kHz microphone | No (hardware has none) |

In a profile picker these are the entries marked **Full**, which is how the catalog flags the most capable profile for a given device. A device never has more than one.

Every descriptor byte comes verbatim from a real pad's hardware dump, and the UAC volume/mute ranges are real wire values captured from live control transfers. Windows surfaces the same audio endpoints it would for the physical controller: **Speakers (Wireless Controller)** and **Headset Microphone (Wireless Controller)**.

The 4-channel OUT stream matters because channels 3/4 are the DualSense's voice-coil actuators. That stream is the only path on Windows by which a game hands a controller its authored haptic waveforms. Games that render audio to the controller endpoint reach the SDK, and the consumer routes the haptic lanes to real hardware.

The original DS4 v1 (054C:05C4) has no composite variant deliberately: real hardware probes show a single HID interface over USB and no audio class. USB audio arrived with the v2.

---

## Nothing to install

```csharp
using var ctx = new HMContext();
ctx.LoadDefaultProfiles();
ctx.InstallDriver();

using var ctrl = ctx.CreateController(ctx.GetProfile("dualsense-composite")!);
```

That is the entire setup. A composite persona is created the same way as any other profile.

Composite personas need a driver-backed USB device for their audio endpoints, since no user-mode API can create a Windows audio endpoint. HIDMaestro ships that transport, [usbip-win2](https://github.com/vadimgrn/usbip-win2) 0.9.7.7, **inside `HIDMaestro.Core.dll`** and deploys it on the first composite create, exactly the way it already ships and deploys its own UMDF2 driver. There is no second package, no separate download, and nothing for a user to go find.

What that means in practice:

- **The install is one-time and automatic.** It needs the same elevation `InstallDriver` needs. On every later create it is a no-op.
- **USB blinks once.** usbip-win2's extension INF matches the generic USB 3.0 root-hub hardware ID, so PnP re-enumerates the root hubs during install. That happens once per machine, on the very first composite controller it ever creates, and again only if the pinned version changes.
- **The binary is verified twice.** Its SHA256 is checked against the upstream release's published digest when the SDK is built, and again on the extracted copy before it is executed. A mismatch fails rather than running an unverified installer.
- **The license notice ships with it.** usbip-win2 is BSD-2-Clause and redistributed unmodified. The required notice is embedded in the assembly and written to disk beside the binary at deploy time.
- **The version pin is deliberate.** 0.9.7.8 has two open kernel-pool-corruption reports ([#180](https://github.com/vadimgrn/usbip-win2/issues/180), [#181](https://github.com/vadimgrn/usbip-win2/issues/181)). Any bump waits on those closing.

Two optional APIs exist for consumers that want control over *when* the one-time install happens:

```csharp
// Informational: has this machine already got the transport?
bool ready = HMContext.IsUsbipBackendAvailable;

// Do the one-time install now (onboarding step, settings toggle) instead
// of on the first composite create. Idempotent.
HMContext.InstallUsbipBackend(status => Console.WriteLine(status));
```

Neither is a gate. `CreateController` works either way. `HMProfile.RequiresUsbipBackend` marks which profiles are composites, useful for labeling picker entries that bring controller audio.

Everything else stays in HIDMaestro's own user-mode code. The SDK runs an in-process USB/IP device server on loopback (fixed port range 18509-18524): descriptor service, HID reports through the same shared-memory contract every other profile uses, and a highest-priority pacing thread completing isochronous URBs at the endpoint's 1 ms service interval. Measured idle cost with the transport installed and no device attached: indistinguishable from baseline (0.35% vs 0.24% CPU on an Atom Z8350).

`HMController.SubmitState`, `SubmitRawReport`, `OutputReceived`, `OutputDecoded`, and the Sony feature-report behavior are identical across backends. The HID interface of each composite is byte-identical to its UMDF2 sibling.

---

## The audio surfaces

Composite controllers expose `HMController.UsbAudio` (null on every UMDF2 profile):

```csharp
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
int accepted = audio.Microphone.Submit(pcmBytes);  // interleaved 16-bit LE at the declared format
if (accepted < pcmBytes.Length) { /* buffer full: the rest was dropped */ }

// Volume/mute writes from Windows (volume mixer, control panel):
audio.ControlChanged += (_, e) =>
    Console.WriteLine($"{e.Function}: {(e.IsMute ? $"mute={e.MuteValue}" : $"{e.VolumeDb:F1} dB")}");
```

`FramesReceived` fires on the backend's pacing thread with a few milliseconds of PCM per window, at the cadence the host renders. Handlers must be quick and thread-safe, the same contract as `OutputReceived`.

`Submit` returns the bytes it accepted. The microphone buffer holds roughly a quarter second, and a producer that outruns the 1 ms service interval will eventually fill it, at which point the excess is dropped rather than allowed to grow capture latency without bound. Feeding one continuous stream is what the buffer expects, so chunk sizes need not be frame-aligned and a sample may span two calls. What a short return means is that audio was lost, and a consumer that wants to know should compare it against the length submitted. Bytes are only ever dropped on a sample-frame boundary, so a full buffer costs you a click, never a permanently misaligned stream.

One fidelity note worth knowing: Windows persists per-endpoint enable/disable state by device identity. Because the composite presents the real pad's exact identity, it inherits whatever state the machine last had for the real controller's endpoints. If the real pad's speaker endpoint was ever disabled in the Sound control panel, the virtual one arrives disabled too. Re-enable it there once.

---

## Profile schema

Composite personas add two fields to the profile JSON:

- `"backend": "usbip"` selects the create path. It is a property of the device, never a mode toggle on an existing profile: a profile that presented four interfaces on some machines and one on others would name a device plus a machine state.
- `"usbConfiguration"` carries the full USB identity: the structured interface/endpoint model the backend routes with, plus the verbatim wire blobs (`deviceDescriptor`, `configurationDescriptor`, `otherSpeedConfigurationDescriptor`), the `busSpeed`, and `audioControls` with the pad's real UAC volume ranges. The blobs are served byte-for-byte and cross-checked against the structured model at create time.

See [Profile System](../profiles/profile-system.md) for the rest of the schema.

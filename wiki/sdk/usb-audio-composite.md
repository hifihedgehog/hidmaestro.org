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

## Recognising your own persona

A composite persona is byte-for-byte a real Sony pad at every level a filter can inspect. That is what the USB Audio Class driver binds against, so it cannot carry a HIDMaestro marker of its own. An application that enumerates HID devices will therefore see the persona as an ordinary controller, which for a host that created it means seeing itself: SDL, for one, will treat it as a second gamepad and drive the lightbar and player pips from its index.

The token lives on the one node HIDMaestro owns, the emulated host controller the persona sits behind:

```
ROOT\USB\0000   HardwareIds = ROOT\USBIP_WIN2\UDE
                              ROOT\HIDMAESTRO_UDE
```

It is added alongside the upstream id, never in place of it, so driver binding is unchanged. A consumer that already filters its own virtual pads by testing hardware IDs for `HIDMAESTRO` needs only to walk far enough up the device tree: from the persona's HID interface, that node is four parents away, so a depth limit of five or more finds it. Filtering on the transport's `usbip2_ude` service instead would also catch an unrelated usbip install, and would break outright if the backend is ever replaced.

The same absence of a marker changes how a persona is cleaned up. The device sweep behind `RemoveAllVirtualControllers` walks the ROOT and SWD enumerators looking for exactly that `HIDMAESTRO` token, so it can never see a composite, and before v1.4.5 a consumer that created one and exited left a USB DualSense enumerated on the machine with nothing left running to feed it. The sweep now detaches every persona this SDK owns from the emulated host controller before it walks the enumerators. Personas owned by another live process are detached too, which is the point of asking for a clean machine.

The order matters and is not an implementation detail a consumer can ignore. A persona's input pump maps the shared input section directly and reads it in a loop, taking no part in the stop-event drain the UMDF2 controllers use, so the pump has to be joined before the sweep destroys those sections. Detaching without stopping it first is not a leak, it is an access violation on a background thread that takes the process down. If you build your own teardown path over the internals rather than calling the SDK's, stop the pumps first.

One fidelity note worth knowing: Windows persists per-endpoint enable/disable state by device identity. Because the composite presents the real pad's exact identity, it inherits whatever state the machine last had for the real controller's endpoints. If the real pad's speaker endpoint was ever disabled in the Sound control panel, the virtual one arrives disabled too. Re-enable it there once.

---

## Profile schema

Composite personas add these fields to the profile JSON:

- `"backend": "usbip"` selects the create path. It is a property of the device, never a mode toggle on an existing profile: a profile that presented four interfaces on some machines and one on others would name a device plus a machine state.
- `"usbConfiguration"` carries the full USB identity: the structured interface/endpoint model the backend routes with, plus the verbatim wire blobs (`deviceDescriptor`, `configurationDescriptor`, `otherSpeedConfigurationDescriptor`), the `busSpeed`, and `audioControls` with the pad's real UAC volume ranges. The blobs are served byte-for-byte and cross-checked against the structured model at create time.
- An interface's alt setting may carry its own `"reportDescriptor"`, for a persona presenting more than one HID interface. The primary interface (the one whose `function` is `"hid"`) serves the profile's own `descriptor` as always; the others serve theirs from here.
- `"featureStubs"` declares the answers the persona gives to `GET_REPORT(Feature)`, for a device whose claiming software interrogates it before it will use it. `messageByte` says where the message id sits in a write's payload, and a report may declare the `param` it answers for, when one message carries several.

See [Profile System](../profiles/profile-system.md) for the rest of the schema.

---

## A second kind of persona: the Valve devices

The audio personas above exist because UMDF2 can present exactly one HID interface and a DualSense has four. The three Valve personas use the same backend for a different reason: what a device *is* to Steam.

### The Steam Deck

The plain `steam-deck` profile carries Valve's real ids over a standard gamepad descriptor. Steam files it under Generic DirectInput, and none of Steam Input's Valve-device treatment applies: no gyro lane, no trackpads, no HD haptics, no Valve button prompts. The ids alone are not what earns that treatment; the device behind them is.

So the persona presents the device, reproduced from a real unit's `lsusb` dump rather than assembled, because the identity Steam inspects is the whole configuration and not just the controller interface: `bcdDevice` 3.00, product string `Steam Controller`, a serial string at index 3, `bmAttributes` 0x80, `wTotalLength` 150 and five interfaces. Mouse on 0 (endpoint 0x81), keyboard on 1 (0x82, boot protocol), the vendor-page controller on 2 (`06 FF FF`, 0x83, 64-byte input and feature reports), then an Interface Association Descriptor and the CDC ACM pair on 3 and 4. An earlier revision of this page described a three-interface device with `bcdDevice` 2.00 and the product string `Steam Deck Controller`, taken from a different unit's dump with the CDC pair dropped. Steam claimed that device, read its attributes and named it, and then decoded every input as zero.

#### The interrogation

Steam does not simply read input from a Deck. It asks the device what it is, over the feature-report channel, and the Deck's protocol declares no report ids at all: the host writes a message with `SET_REPORT(Feature)` and reads its answer with `GET_REPORT(Feature)`. `ID_GET_ATTRIBUTES_VALUES` (`0x83`) returns a block of `(tag, u32)` records: the product id, the firmware build time, the board revision, and the connection interval Steam uses to pace its own reads.

That is what `featureStubs` answers, keyed `match: "lastMessage"` so a lookup follows the message the preceding write carried. The shipped values come from a capture of a real Deck answering a real Steam client, with the connection interval matching the persona's own 4 ms endpoint rather than being copied blindly.

#### Driving it

The persona's input report is the 64-byte Neptune frame (`ID_CONTROLLER_DECK_STATE`, type `0x09`), and `extendedReport` packs it from `SteamDeckStatePacket_t`, so an ordinary `SubmitState` call drives it. That matters more than it sounds: a profile whose descriptor is an opaque vendor blob declares no axes, and every layer that keys off declared axes will quietly emit nothing rather than fail. The profile must also set `alwaysArmed`, or the encoder is built and never armed and `SubmitState` falls through to the descriptor-driven builder, which has nothing to fill. Consumers can still submit the frame whole through `SubmitRawReport`. Steam's rumble (`0xEB`), haptic (`0xEA`) and pulse (`0x8F`) writes arrive as HID feature output on `OutputReceived`.

The real device also exposes a CDC ACM debug serial pair, which the persona omits: it carries no controller data and nothing in the input stack reads it.

### The 2015 Steam Controller

`steam-controller-composite` is the wired D0G at `28DE:1102`, and it presents three interfaces for a blunter reason than the Deck's: SDL's driver refuses the pad on any interface but number 2. A single-interface profile carrying the same descriptor and the same ids is skipped outright. So the persona reproduces the real unit's whole configuration from its `lsusb` dump, `wTotalLength` 0x54 and all: keyboard on interface 0 (endpoint 0x81, 8 bytes, `bInterval` 10), mouse on interface 1 (0x82, 4 bytes, interval 6), and the controller on interface 2 (0x83, 64 bytes, interval 6), which is where the driver looks.

Every descriptor is verbatim from a real unit: the device and configuration blobs, the 63-byte keyboard and 56-byte mouse report descriptors its lizard mode drives, and the 33-byte vendor-page controller descriptor. Its input frame is `ValveControllerStatePacket_t`. The pad has one stick and the wire carries no separate stick field: with `STEAM_LEFTPAD_FINGERDOWN` clear, SDL's `FormatStatePacketUntilGyro` reads `sLeftPadX/Y` as the joystick, so that is where the stick is written. Its analog triggers come from the 8-bit values inside the `ButtonTriggerData` union, which SDL remaps against 26000 rather than full scale, not from the redundant 16-bit copy further down the packet.

Its `featureStubs` answer the same `0x83` interrogation the Deck's do, since both speak the same Valve protocol with no report ids, keyed off the message the preceding `SET_REPORT` carried. The attribute block carries three records in the order two real Valve captures use: the product id, a zero capabilities word (zero on both of those real devices too), and the 9000 µs connection interval, which is SDL's documented fallback for this family and what it turns into the gyro and accelerometer sample rate.

Three records, not six. A real block also carries a firmware build timestamp, a bootloader build timestamp and a board revision, and no public capture of a 2015 unit's exists. Those are absent rather than invented: SDL ignores all three, and a wrong firmware timestamp is what makes Steam re-ask forever.

### The 2026 Steam Controller

`steam-controller-2` is the wired unit at `28DE:1302`, the one SDL calls Triton. It is built differently from both of the above: one HID interface carries everything, addressed by report id rather than split across interfaces. The mouse (`0x40`) and keyboard (`0x41`) reports its lizard mode drives live in the same descriptor as the 53-byte controller state (`0x42`), the BLE state (`0x45`), battery (`0x43`), wireless status (`0x79`), the `0x80`–`0x89` haptic and rumble output reports, and a 63-byte command channel on feature reports 1 and 2. The command channel is why this persona's `featureStubs` set `"messageByte": 1`: the message id sits after the feature report id rather than at byte 0.

The 372-byte descriptor is verbatim from [OpenPuck](https://github.com/safijari/openpuck)'s `ReversePuckFirmware`, an emulation of this controller that a live Steam client already accepts, and every report id in it matches SDL's own `ID_TRITON_*` constants.

The feature answers are grounded on two independent reads of real hardware that agree record for record: OpenPuck's `identity.cpp`, and [sc2-research](https://github.com/CouchTurtle/sc2-research), which logs the same five attribute tags in the same order off a live controller and matches Steam's own firmware-update JSON on two of the values. The `0x83` block is those 25 bytes: product id `0x1302`, a zero capabilities word, the bootloader and firmware build timestamps, and the board revision. Steam validates them byte for byte, so none of them is a guess. The build timestamp shipped is the newer of the two real ones, so Steam sees a current unit rather than offering it an update.

`0xAE` reads a string by index, and the persona declares one answer per index the real device provisions: the board serial, the unit serial, and the constant at index 3 that Steam checks. Every other index reads back `0xFF` where the index would be, which is how a real unit says a string is not provisioned, and the byte Steam's own updater tests.

Its input frame is the 54-byte `TritonMTUFull_t` on report `0x42`, packed by `extendedReport` so an ordinary `SubmitState` drives it; consumers can still submit it whole through `SubmitRawReport`. Steam's haptic writes arrive on `OutputReceived` as output reports `0x80` and up.

SDL binds Triton on any interface of a wired unit, so nothing here depends on interface numbering the way the 2015 controller does.

### Using them without Steam

These pads speak only Valve's vendor protocol. Nothing generic reads it: not DirectInput, not XInput, not `joy.cpl`. That is equally true of real hardware, which is what lizard mode exists to cover. What makes a real Steam Controller work with Steam closed is SDL, which implements the protocol directly and turns lizard mode off itself.

The personas never emit keyboard or mouse reports at all, so they sit permanently in the gamepad state and nothing needs disabling. An SDL application reads them with Steam not running.

Battery scenario S52 proves this without a client: it creates each persona, drives it through `SubmitState`, reads the frame back off the real HID stack, and decodes it with SDL's own per-device arithmetic, asserting both stick extremes and a trigger pulled and released. `ValveWireCheck.exe --monitor <persona>` runs the same path interactively and prints what an SDL application would read.

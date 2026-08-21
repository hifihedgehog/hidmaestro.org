# Custom Profiles

Three patterns for building controllers that aren't in the 234-profile catalog: clone-and-modify, build-from-scratch, and spoof. All three use `HMProfileBuilder` plus optionally `HidDescriptorBuilder`. Resulting profiles deploy through the same `HMContext.CreateController` path as catalog entries with no special-casing.

For the underlying APIs, see [SDK Reference](../sdk/sdk-reference.md) and [HID Descriptor Builder](../sdk/hid-descriptor-builder.md). This page is the cookbook.

---

## Pattern 1: Clone and modify

Take an existing profile, change a few fields, deploy. Best when you want most of an existing controller's behavior with one or two adjustments.

### Use case A: same controller, custom product string

```csharp
var modded = new HMProfileBuilder()
    .FromProfile(ctx.GetProfile("dualsense")!)
    .Id("dualsense-custom-label")
    .ProductString("My Custom Controller")
    .Build();

using var ctrl = ctx.CreateController(modded);
```

Windows still sees DualSense (VID/PID unchanged), Steam's controller database still matches, but `joy.cpl` and DirectInput show "My Custom Controller". For a `joy.cpl` label change without modifying the profile, see [OEM Name Override](../sdk/oem-name-override.md) &mdash; that's the right tool when the VID/PID can't change.

### Use case B: extra button on an existing controller

```csharp
var existing = ctx.GetProfile("dualsense")!;

var custom = new HMProfileBuilder()
    .FromProfile(existing)
    .Id("dualsense-16btn")
    .Descriptor(new HidDescriptorBuilder()
        .Gamepad()
        .AddStick("Left", 8).AddStick("Right", 8)
        .AddTrigger("Left", 8).AddTrigger("Right", 8)
        .AddButtons(16).AddHat()
        .Build())
    .InputReportSize(8)
    .Build();

using var ctrl = ctx.CreateController(custom);
```

VID/PID and product string are preserved (Windows / Steam / games still see "DualSense"), but the descriptor declares 16 buttons instead of 15. The extra bit is real wire data &mdash; submit `HMButton.Touchpad` (bit 11) or any custom bit and the consumer reads it via DirectInput / SDL3 / Browser like any other button.

This pattern works for axis count, trigger resolution, hat positions, and FFB declarations. Whatever the descriptor says, that's what consumers see.

### Use case C: change the PID

```csharp
var modded = new HMProfileBuilder()
    .FromProfile(ctx.GetProfile("dualsense")!)
    .Id("dualsense-clone")
    .Pid(0x1234)
    .Build();
```

Less useful in practice. Most consumers (Windows, Steam, games) match by VID:PID, so changing the PID makes the device unrecognizable. Either change PID **and** the product string for a clean spoof, or use [OEM Name Override](../sdk/oem-name-override.md) to relabel without changing VID/PID.

---

## Pattern 2: Build from scratch

Define a controller that doesn't exist anywhere &mdash; arbitrary VID/PID, custom descriptor, custom product string. Best when emulating a niche device or constructing a custom-shaped controller (16-axis flight panel, DJ deck with 8 sliders + 4 jog wheels).

### Custom flight stick with 16-position hat

```csharp
var stick = new HMProfileBuilder()
    .Id("custom-hotas").Name("My HOTAS")
    .Vendor("MyCo")
    .Vid(0x0483).Pid(0x0001)
    .ProductString("Custom HOTAS")
    .Type("hotas")
    .Connection("usb")
    .FromDescriptorBuilder(new HidDescriptorBuilder()
        .Joystick()
        .AddStick("Left", 16)            // X/Y, 16-bit each
        .AddTrigger("Left", 8)           // throttle
        .AddTrigger("Right", 8)          // brake
        .AddButtons(12)
        .AddHat(positions: 16))          // 22.5° hat
    .Build();

using var ctx = new HMContext();
ctx.LoadDefaultProfiles();   // optional — gives us catalog access too
ctx.InstallDriver();
using var ctrl = ctx.CreateController(stick);

// Drive the hat at full descriptor resolution
ctrl.SubmitState(new HMGamepadState { HatDegrees = 22.5f });    // ENE
ctrl.SubmitState(new HMGamepadState { HatHundredths = 11250 }); // 112.5° = ESE
```

`FromDescriptorBuilder` derives `InputReportSize` correctly &mdash; including the +1 byte for the Report ID prefix that `AddPidFfbBlock` would inject if you called it. See [HID Descriptor Builder](../sdk/hid-descriptor-builder.md).

### More than 4 sticks + 2 triggers

Profiles whose descriptor declares analog axes beyond the standard 4 sticks + 2 triggers &mdash; throttle quadrants, racing wheels with separate brake/throttle/clutch pedals, HOTAS systems with rudder pedals &mdash; declare each by HID usage with `AddAxis` and consumers drive them through the same `state.Axes` dict as everything else.

```csharp
var quadrant = new HMProfileBuilder()
    .Id("custom-throttle-quadrant")
    .Vid(0x0483).Pid(0x0010)
    .ProductString("Throttle Quadrant")
    .Type("hotas")
    .FromDescriptorBuilder(new HidDescriptorBuilder()
        .Joystick()
        .AddStick("Left", 16)                  // primary X/Y
        .AddAxis(HMAxis.Slider,   bits: 8)     // throttle slider 1
        .AddAxis(HMAxis.Throttle, bits: 8)     // throttle 2
        .AddAxis(HMAxis.Rudder,   bits: 8)     // rudder pedal
        .AddAxis(HMAxis.Brake,    bits: 8)     // toe brake
        .AddButtons(20).AddHat())
    .Build();

using var ctrl = ctx.CreateController(quadrant);

// Discovery: list every axis the descriptor exposes
foreach (var a in quadrant.AvailableAxes) Console.WriteLine($"  {a}");

// Drive every axis in one frame. Allocate the dictionary once and reuse —
// null on the hot path is free (encoder skips the dict walk).
var axes = new Dictionary<HMAxis, float>
{
    [HMAxis.X]        = 0.55f,   // stick X, slightly right of center
    [HMAxis.Y]        = 0.35f,   // stick Y, slightly below center
    [HMAxis.Slider]   = 0.75f,
    [HMAxis.Throttle] = 1.00f,
    [HMAxis.Rudder]   = 0.25f,
    [HMAxis.Brake]    = 0.00f,
};
ctrl.SubmitState(new HMGamepadState { Axes = axes });
```

Every analog input lives in `state.Axes` keyed by `HMAxis` &mdash; sticks, triggers, sliders, pedals, simulation usages all share the same surface. Setting an entry whose usage isn't declared is a no-op, so consumer UIs can populate every axis they track without checking which ones the active profile actually exposes. See [SDK Reference](../sdk/sdk-reference.md) for the `HMAxis` enum and the full `Layout` schema for kind-aware discovery.

### Adding force feedback

```csharp
var ffbStick = new HMProfileBuilder()
    .Id("custom-ffb-stick")
    .Vid(0x0483).Pid(0x5740)
    .ProductString("Custom FFB Stick")
    .Type("hotas")
    .FromDescriptorBuilder(new HidDescriptorBuilder()
        .Joystick()                        // REQUIRED for FFB — Gamepad TLC AVs pid.dll
        .AddStick("Left", 16)
        .AddTrigger("Left", 8).AddTrigger("Right", 8)
        .AddButtons(12).AddHat()
        .AddPidFfbBlock())                 // canonical PID 1.0 block
    .Build();

using var ctrl = ctx.CreateController(ffbStick);

// Required to enable FFB
ctrl.PublishPidPool(
    ramPoolSize: 0x0400,
    simultaneousEffectsMax: 16,
    deviceManagedPool: false,
    sharedParameterBlocks: false);

ctrl.OutputReceived += (_, packet) => RouteFfbToPhysicalHardware(packet);
```

DirectInput games will see this as a fully PID-FFB-capable HOTAS. See [Force Feedback](../sdk/force-feedback.md) for the publish/read protocol and the canonical `pid.dll` packet flow.

### Custom Xbox-shape gamepad (no descriptor work)

```csharp
var gamepad = new HMProfileBuilder()
    .Id("custom-pad")
    .Vid(0x1234).Pid(0x5678)
    .ProductString("Custom Pad")
    .Type("gamepad")
    .Connection("usb")
    .FromDescriptorBuilder(new HidDescriptorBuilder()
        .Gamepad()
        .AddStick("Left", 16).AddStick("Right", 16)
        .AddTrigger("Left", 8).AddTrigger("Right", 8)
        .AddButtons(10).AddHat())
    .Build();
```

This produces a generic 10-button Xbox-shape gamepad with separate triggers. SDL3 will recognize it as a gamepad (TopLevelUsage = 0x05); browsers will surface it as a STANDARD_GAMEPAD if the layout matches Chromium's expectations.

For full XInput support (XUSB companion + WGI vibration via Chromium `put_Vibration`), the VID **must** be `0x045E` (Microsoft) so the runtime allocates an XUSB companion. Custom-VID gamepads can still XInput-rumble via SetState wired through the consumer's own physical-hardware path, but won't receive `IOCTL_XUSB_SET_STATE` from Chromium directly.

---

## Pattern 3: Spoof a known controller

You know a real device's VID, PID, and product string but you don't own one. HIDMaestro can present as that device without owning it.

### Manual spoof (when you have the descriptor bytes)

```csharp
// "Mad Catz Pro Race FFB Wheel" — VID 0x0738, PID 0xCB29, descriptor known
var spoof = new HMProfileBuilder()
    .Id("madcatz-pro-race")
    .Vendor("Mad Catz")
    .Vid(0x0738).Pid(0xCB29)
    .ProductString("Pro Race FFB Wheel")
    .Type("wheel")
    .Connection("usb")
    .Descriptor(File.ReadAllBytes(@"C:\descriptors\madcatz-pro-race.bin"))
    .InputReportSize(28)
    .Build();
```

Windows pre-populates a clone label for many VID:PIDs, which can show up in `joy.cpl` even with the spoof active &mdash; combine with `HMOemNameOverride.Set` if you need the joy.cpl label to match. See [OEM Name Override](../sdk/oem-name-override.md).

### Automatic spoof from a connected device

If the device you want to spoof is currently plugged into the same machine, `HMDeviceExtractor` reads it back and produces a ready-to-deploy profile:

```csharp
var device = HMDeviceExtractor.ListDevices()
    .First(d => d.VendorId == 0x046D && d.ProductId == 0xC216);

HMProfile extracted = HMDeviceExtractor.Extract(device);

using var ctrl = ctx.CreateController(extracted);
// Virtual now presents with the real device's descriptor, VID/PID,
// product string — identical to what the physical device reports.
```

The descriptor is reconstructed from `HidD_GetPreparsedData` via the libusb/hidapi C# port. Output is logically equivalent to the original (same report IDs, field layouts, logical ranges, usage pages) but not byte-for-byte identical. For HIDMaestro's purpose (creating a virtual that behaves the same as the physical), logical equivalence is the right fidelity bar.

For a UI-driven extract flow, use the standalone `HIDMaestroProfileExtractor.exe` &mdash; see [Profile Extractor](profile-extractor.md).

### Why spoof?

- **Game compatibility databases.** Some games match controllers by VID:PID (Final Fantasy XIV recognizes a specific list of FFB wheels; Forza Motorsport whitelists pro racing rigs). Spoof to gain access.
- **Steam controller mappings.** Steam's controller database maps VID:PIDs to button layouts; spoof a known controller to inherit its mapping without needing manual configuration.
- **SDL3 controller mappings.** SDL3's `gamecontrollerdb` keys by GUID derived from VID:PID. Spoof to get auto-mappings.
- **Browser STANDARD_GAMEPAD.** Chromium maps known VID:PIDs to its STANDARD_GAMEPAD layout; spoof an Xbox 360 to inherit that mapping.

### Caveats

- **Cryptographic auth chips.** PS4 / PS5 online play, Switch Online, some racing wheels for console use hardware authentication. Spoof presents the descriptor and identity but cannot replicate the auth chip. Offline use works; online use of these protected devices typically does not.
- **Vendor private protocols.** Logitech G HUB, Thrustmaster TARGET, Fanatec ControlPanel use proprietary feature reports for calibration / firmware / config. The spoof carries the standard descriptor; vendor extensions need per-controller decoder work in the consumer.
- **Anti-cheat detection.** Virtual devices are detectable by kernel-level anti-cheat (the device path and bus type differ from real USB). HIDMaestro doesn't try to evade detection. A spoofed identity is for app/game **compatibility**, not for evading anti-cheat.

---

## Per-archetype custom profile patterns

### Custom plain-HID gamepad (most common)

```csharp
new HMProfileBuilder()
    .Id("my-pad").Vid(0x1234).Pid(0x5678)
    .ProductString("My Pad")
    .Type("gamepad").Connection("usb")
    .FromDescriptorBuilder(new HidDescriptorBuilder()
        .Gamepad()
        .AddStick("Left", 16).AddStick("Right", 16)
        .AddTrigger("Left", 8).AddTrigger("Right", 8)
        .AddButtons(N).AddHat())
    .Build();
```

Lands in architecture group 1 (plain HID). DirectInput, SDL3 / HIDAPI, browser RawInput-fallback all see it. **No XInput** (custom VID, no XUSB companion). **No xinputhid** (no `driverMode`).

### Custom Xbox-VID gamepad (gets XUSB companion)

```csharp
new HMProfileBuilder()
    .Id("my-xbox-clone")
    .Vid(0x045E).Pid(0x0291)               // Microsoft VID, Xbox 360 family PID
    .ProductString("My Xbox Clone")
    .Type("gamepad").Connection("usb")
    .TriggerMode("combined")                // matches real xusb22 DI behavior
    .FromDescriptorBuilder(/* ... */)
    .Build();
```

Lands in architecture group 2 (non-xinputhid Xbox + XUSB companion). XInput, WGI vibration via XUSB companion, separate triggers in browser via Vx/Vy + GameInput registry mapping. Note: only specific PIDs in the `[Standard.NTamd64]` section of `hidmaestro_xusb.inf` get the dedicated PID-aliased install &mdash; new PIDs fall through to the generic `root\HIDMaestroXUSB` alias which still works but isn't bound to a specific VID:PID.

### Custom xinputhid-bound profile

This requires hardware IDs that match `xinputhid.inf [GIP_Hid]`. Not portable to arbitrary VID:PIDs &mdash; xinputhid binds by hardware ID, and adding new IDs to `xinputhid.inf` requires modifying a Microsoft inbox driver (which we can't ship). Custom xinputhid profiles aren't supported in v1.3.4.

If you need 16-button + native XInput + WGI vibration over Bluetooth, use one of the catalog Xbox Series / One / Elite v2 BT profiles directly.

### Custom HOTAS / wheel / pedals

```csharp
new HMProfileBuilder()
    .Id("my-hotas").Vid(0x0483).Pid(0xABCD)
    .ProductString("My HOTAS")
    .Type("hotas").Connection("usb")
    .FromDescriptorBuilder(new HidDescriptorBuilder()
        .Joystick()                          // REQUIRED for FFB
        .AddStick("Left", 16)                // X / Y
        .AddTrigger("Left", 8).AddTrigger("Right", 8)   // throttles or pedals
        .AddButtons(20).AddHat(positions: 16)
        .AddPidFfbBlock())
    .Build();
```

Lands in architecture group 1. DirectInput PID FFB enabled; consumer must call `PublishPidPool` once to enable FFB.

---

## Submitting input to a custom profile

`HMGamepadState` works the same regardless of profile shape:

```csharp
ctrl.SubmitState(new HMGamepadState
{
    Axes = HMGamepadStateHelpers.StandardAxes(ctrl.Profile,
        leftStickX: 0.75f,           // [0..1] uniform; 0.5 = center
        leftStickY: 0.15f,
        leftTrigger: 0.3f),
    Buttons = HMButton.A | HMButton.LeftBumper,
    HatDegrees = 90f,                // East
});
```

For features the abstract struct doesn't model (DualSense touchpad coordinates, Switch Pro motion, vendor-specific report extensions), assemble bytes per the descriptor and use `SubmitRawReport`:

```csharp
byte[] dualsenseRawReport = AssembleDualSenseInputReport(state, touchpad, gyro, accel);
ctrl.SubmitRawReport(dualsenseRawReport);
```

Pass **data bytes only** &mdash; the SDK prepends the Report ID automatically based on what the descriptor declared.

For a custom descriptor where you need bit-exact axis encoding:

```csharp
// Query the descriptor's hat field bounds
ushort? min = ctrl.Profile.HatLogicalMin.HasValue ? (ushort)ctrl.Profile.HatLogicalMin : null;
ushort? max = ctrl.Profile.HatLogicalMax.HasValue ? (ushort)ctrl.Profile.HatLogicalMax : null;

// Bit-exact value
ctrl.SubmitState(new HMGamepadState
{
    HatRaw = (ushort)((min ?? 0) + 7)    // 7 positions in
});
```

The encoder picks the first non-null in the priority chain `HatDegrees > HatHundredths > HatRaw > Hat`.

---

## Validation

A custom profile fails `HMContext.CreateController` if:

- **VID is 0.** `HMProfileBuilder.Build()` throws `InvalidOperationException`.
- **PID is 0.** Same.
- **`IsDeployable` is false** (descriptor missing). `CreateController` throws `ArgumentException`.
- **Descriptor is malformed.** The driver fails to bind; `CreateController` throws `InvalidOperationException` after the PnP wait times out.

Test custom profiles against `scripts/verify.py` before shipping:

```cmd
HIDMaestroTest.exe make-custom-profile C:\my-profiles
HIDMaestroTest.exe emulate --profile-dir C:\my-profiles my-pad
:: in another terminal:
python scripts\verify.py --controllers 1
```

The regression battery's S21-S23 scenarios cover runtime-built custom profiles end-to-end &mdash; create + idle, swap-cycle through Xbox / DualSense / Custom, and a real PadForge-shape consumer config. See [Testing and Verification](../reference/testing-and-verification.md).

---

## See also

- [SDK Reference](../sdk/sdk-reference.md) &mdash; `HMProfileBuilder` API and `FromDescriptorBuilder` mechanics.
- [HID Descriptor Builder](../sdk/hid-descriptor-builder.md) &mdash; the fluent descriptor authoring API.
- [Profile System](profile-system.md) &mdash; the JSON schema your custom profile maps to.
- [Profile Extractor](profile-extractor.md) &mdash; the GUI tool for capturing profiles from real connected devices.
- [Force Feedback](../sdk/force-feedback.md) &mdash; the FFB descriptor + publish/read protocol.
- [OEM Name Override](../sdk/oem-name-override.md) &mdash; relabel `joy.cpl` without changing VID:PID.
- [Contributing Profiles](contributing-profiles.md) &mdash; submit a custom profile back to the catalog.

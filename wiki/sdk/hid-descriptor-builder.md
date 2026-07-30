# HID Descriptor Builder

`HidDescriptorBuilder` is the fluent API for constructing valid HID report descriptors from semantic building blocks. The user describes what they want (sticks, buttons, hat, triggers, FFB) and the builder emits the correct HID descriptor bytes. No hex authoring, no byte counting, no aligning report sizes by hand.

The builder is paired with [HMProfileBuilder](sdk-reference.md#hmprofilebuilder) via `FromDescriptorBuilder` so that the wire input report size (and the +1 byte for Report ID prefixes) is derived automatically:

```csharp
var desc = new HidDescriptorBuilder()
    .Gamepad()
    .AddStick("Left", 16).AddStick("Right", 16)
    .AddTrigger("Left", 8).AddTrigger("Right", 8)
    .AddButtons(10).AddHat();

var profile = new HMProfileBuilder()
    .Id("my-pad").Vid(0x1234).Pid(0x5678)
    .ProductString("My Pad")
    .FromDescriptorBuilder(desc)
    .Build();
```

This page documents every method, the validation rules, and the empirical reasons behind each rule.

---

## Application collections

```csharp
.Gamepad()    // Usage Page Generic Desktop, Usage Game Pad (0x05)
.Joystick()   // Usage Page Generic Desktop, Usage Joystick (0x04)
```

Both open an Application Collection (`A1 01`). The choice of TLC matters for two downstream behaviors:

- **DirectInput / WGI classification.** Joystick TLC surfaces in DirectInput as a "Joystick" device with the full 6-axis layout; Gamepad TLC surfaces with the 5-axis Xbox 360 convention. Browser Gamepad's `STANDARD_GAMEPAD` mapping resolves only for Gamepad TLC devices that match its expected layout.
- **`pid.dll` PID FFB enumeration.** `AddPidFfbBlock` rejects a Gamepad TLC because DirectInput's `pid.dll` (DirectX 8-era code) AVs inside `PID_EffectOperation+0x52` when `CreateEffect` is called against a Gamepad TLC. **Always use `Joystick()` for FFB-capable virtuals.** This is not OS-build-gated; it has been baked into `pid.dll` since FFB enumeration shipped. Verified empirically on Windows 11 26100.

For an XInput / WGI rumble path that doesn't go through DirectInput PID FFB, `Gamepad()` is fine.

`Build()` auto-closes the Application Collection if you forgot to.

---

## `AddStick(name, bits)`

Adds a 2-axis stick (X+Y or Rx+Ry) inside a Physical collection.

```csharp
.AddStick("Left", 16)    // X (0x30) + Y (0x31), 16-bit each
.AddStick("Right", 16)   // Rx (0x33) + Ry (0x34), 16-bit each
.AddStick("Left", 8)     // 8-bit version
```

| `name` | Axes | Usages |
|--------|------|--------|
| `"Left"` or `"L"` | X, Y | 0x30, 0x31 |
| (anything else)   | Rx, Ry | 0x33, 0x34 |

`bits` is the axis resolution. 8 produces `[0..255]` ranges; 16 produces `[0..65535]`. Other values work but should match the descriptor's wire alignment &mdash; the builder doesn't enforce byte-alignment on stick bits because two sticks together always sum to a byte multiple.

The Physical collection wraps the two axes per HID spec convention. Logical Min is 0; Logical Max is `(1 << bits) - 1` (encoded as 1-byte for 8-bit, 4-byte for 16-bit per HID Item rules).

---

## `AddTrigger(name, bits)`

Adds a single trigger axis.

```csharp
.AddTrigger("Left", 8)    // Z (0x32), 8-bit
.AddTrigger("Right", 8)   // Rz (0x35), 8-bit
```

| `name` | Usage |
|--------|-------|
| `"Left"` or `"L"` | Z (0x32) |
| (anything else)   | Rz (0x35) |

`bits` **must be a multiple of 8**. Non-aligned sizes (10, 12, 14) introduce phantom axes in Chromium's Gamepad API:

> "Non-aligned sizes introduce phantom axes in Chromium's Gamepad API. Throws ArgumentException if bits is not a multiple of 8."

The reason is Chromium's RawInput parser. When the report has unaligned trigger bits, HIDMaestro emits a Const padding item to byte-align the report; that Const item surfaces as `axes[N] = 1227133568` (a literal phantom value tied to the const-pad bit pattern). See issue #6.

For separate triggers on Xbox profiles, the catalog uses 8-bit Vx/Vy velocity usages instead of declaring Z + Rz directly &mdash; that's the velocity-usage trick documented in [Cross-API Coverage](../reference/cross-api-coverage.md). Vx and Vy are usages 0x40 and 0x41 on the Generic Desktop Page (HID Usage Tables 1.5 §4 &mdash; download from [usb.org/document-library](https://www.usb.org/document-library)). Custom profiles wanting the same behavior bypass `AddTrigger` and emit Vx/Vy via `AddRaw`. See [Custom Profiles](../profiles/custom-profiles.md).

---

## `AddAxis(axis, bits, logicalMin, logicalMax)` (v1.3.8)

Adds an analog axis identified by HID usage. Covers everything outside the standard sticks-and-triggers layout: throttle sliders, rudders, separate brake/throttle/clutch pedals, steering wheels, flight-stick rudder pedals, and the rest of the `HMAxis` enum.

```csharp
// HOTAS-shape with throttle slider, rudder pedal, secondary throttle
.Joystick()
.AddStick("Left", 16)
.AddAxis(HMAxis.Slider,   bits: 8)              // throttle slider on stick base
.AddAxis(HMAxis.Rudder,   bits: 8)              // separate rudder pedal
.AddAxis(HMAxis.Throttle, bits: 8)              // secondary autopilot throttle
.AddButtons(12).AddHat()

// Racing wheel with three pedals + 16-bit centered steering
.Joystick()
.AddAxis(HMAxis.Wheel, bits: 16,
         logicalMin: -32768, logicalMax: 32767) // signed centered steering
.AddAxis(HMAxis.Accelerator, bits: 8)
.AddAxis(HMAxis.Brake,       bits: 8)
.AddAxis(HMAxis.Clutch,      bits: 8)
.AddButtons(20)
```

`bits` must be a multiple of 8 &mdash; same Chromium-phantom-axis constraint `AddTrigger` enforces. `logicalMin` defaults to `0` and `logicalMax` defaults to `(2^bits) - 1` (the typical convention for unidirectional axes). Pass an explicit signed range when the axis is centered (e.g. a 16-bit steering wheel as `[-32768, 32767]`).

Whatever `HMAxis` value you declare becomes addressable at runtime via `state.Axes[axis] = value`. `HMProfile.AvailableAxes` enumerates every `HMAxis` declared in the profile so consumer UIs can render the right axis-mapping widget per profile without hardcoding which usages a given device exposes. See [SDK Reference](sdk-reference.md) for the consumer-side surface.

For the canonical 4-stick + 2-trigger gamepad shape, `HMGamepadStateHelpers.StandardAxes(profile, leftStickX, ..., rightTrigger)` resolves the 6-slot convention into the right `HMAxis` keys for the active profile (Sony's Z=right-stick, Rx=left-trigger axis map is honored automatically). For HOTAS / wheel / pedal devices, drive any descriptor-declared usage directly through `state.Axes`.

---

## `AddButtons(count)`

Adds N buttons (Button Page, Usages 1..N, 1 bit each).

```csharp
.AddButtons(10)    // 10 declared, rounded up to 16 to byte-align
.AddButtons(15)    // 15 declared, rounded up to 16
.AddButtons(16)    // 16 declared, no rounding
```

The declared Report Count is **rounded up to the next multiple of 8** with extra "dummy" buttons that the caller never sets. This eliminates the Const-pad-as-phantom-axis problem `AddTrigger` warns about &mdash; absorbing the pad as additional buttons keeps the report byte-aligned without introducing a Const Input item.

The historical "AXIS 9 = 1227133568" symptom in the W3C Gamepad API (surfaced in Chromium's RawInput backend per issue #6) was a trailing Const Input item the descriptor needed for byte alignment; rounded-up button counts make the Const item unnecessary.

`HMButton.Touchpad` (bit 11, mask 0x800) and `HMButton.Share` (bit 12, mask 0x1000) only fit if the descriptor declared at least 12 or 13 buttons; the abstract bits are silently dropped if the descriptor doesn't include them.

---

## `AddHat(positions = 8)`

Adds a hat switch (D-pad / POV) with the given number of distinct positions.

```csharp
.AddHat()              // 8 positions (octant), default
.AddHat(positions: 8)  // explicit 8
.AddHat(positions: 16) // 22.5° HOTAS hat
.AddHat(positions: 360) // continuous degree hat
```

Useful values:

| Positions | Resolution | Use case |
|-----------|-----------|----------|
| 8 | octants (45°) | Standard gamepad d-pad |
| 16 | 22.5° | HOTAS programmable hats |
| 360 | 1° | Pro flight-stick continuous hats |
| 36000 | 0.01° | Theoretical max with `HatHundredths` (Report Size 16, LogicalMax 35999) |

The wire format uses Report Size 8 for byte-aligned encoding when positions ≤ 256, auto-extending to Report Size 16 above. LogicalMin is 0; LogicalMax is `positions - 1`. PhysicalMin is 0; PhysicalMax follows the conventional `(positions - 1) * 360 / positions` formula (e.g. 8 &rarr; 315°, 16 &rarr; 337°, 360 &rarr; 359°).

The Input item is `0x81 0x42` (Data, Var, Abs, **Null**) so values outside `LogicalMin..LogicalMax` encode "no direction" via the Null state flag.

After the hat, the builder resets Physical Maximum (0) and Unit (None) so they don't bleed into subsequent items.

> **v1.3.4 fix.** Pre-v1.3.4, `AddHat()` declared `LogicalMax = positions` (one too many; wasted one wire value). v1.3.4 corrects to `LogicalMax = positions - 1` matching Xbox 360 / standard HID convention. The on-wire byte values for the eight `HMHat` directions are unchanged (encoder writes 0..7 either way), but consumers that inspect the descriptor's LogicalMax now see the correct 7 instead of 8. Throws `ArgumentOutOfRangeException` for `positions < 4`.

---

## `AddPidFfbBlock()`

Appends the HID PID 1.0 force-feedback report block to the descriptor (specification at [usb.org/document-library](https://www.usb.org/document-library)). Emits the full Output-report set the DirectInput PID mapper drives, plus the single Feature report Create New Effect (0x11) used for effect allocation.

```csharp
var desc = new HidDescriptorBuilder()
    .Joystick()                         // REQUIRED — Gamepad throws
    .AddStick("Left", 16).AddStick("Right", 16)
    .AddTrigger("Left", 8).AddTrigger("Right", 8)
    .AddButtons(10).AddHat()
    .AddPidFfbBlock();                  // appended at the end
```

### Reports emitted

| Report ID | Direction | Purpose |
|-----------|-----------|---------|
| 0x11 | Output | Set Effect (effect type + selector) |
| 0x12 | Output | Set Envelope |
| 0x13 | Output | Set Condition |
| 0x14 | Output | Set Periodic |
| 0x15 | Output | Set Constant Force |
| 0x16 | Output | Set Ramp Force |
| 0x17 | Output | Custom Force Data |
| 0x18 | Output | Download Force Sample |
| 0x1A | Output | Effect Operation (Start / Stop / Solo) |
| 0x1B | Output | PID Block Free |
| 0x1C | Output | PID Device Control (Reset, Pause, Continue) |
| 0x1D | Output | Device Gain |
| 0x1E | Output | Set Custom Force |
| **0x11** | **Feature** | Create New Effect (the ONLY Feature report in the block) |

### Why only one Feature report

The [vJoy reference descriptor](https://github.com/njz3/vJoy/blob/master/driver/sys/hidReportDescFfb.h) (`hidReportDescFfb.h`) declares **four** sibling Feature reports: Create New Effect (0x11), Block Load (0x12), PID Pool (0x13), PID State (0x14). With HIDMaestro's UMDF2 shared-section transport, the four-feature variant causes `pid.dll` to AV inside `PID_EffectOperation+0x52` the first time the consumer calls `CreateEffect` via DirectInput8 / SharpDX ([issue #16](https://github.com/hifihedgehog/HIDMaestro/issues/16)). The crash reproduces with the exact bytes vJoy ships.

The block emitted here drops 0x12, 0x13, 0x14 from the Feature side and serves them via shared-section `HidD_GetFeature` handling in the driver instead &mdash; the only configuration that does not AV. See [Force Feedback](force-feedback.md) for the architecture.

**Don't add additional Feature reports inside the same Application Collection.** If you need extra metadata reachable via `HidD_GetFeature`, expose it through `HMController.PublishPidPool` / `PublishPidBlockLoad` / `PublishPidState` &mdash; those are served by the driver from a separate shared-section path that doesn't touch `pid.dll`'s preparsed-data parser.

### Auto-injected Report ID 0x01

HID validation rejects a descriptor that mixes untagged input items with the FFB block's tagged Output reports. If no Report ID has been emitted before `AddPidFfbBlock` is called, the method auto-injects `85 01` (Report ID 0x01) **immediately after the Application Collection open** so every preceding input item picks up the tag. The total wire input report size is then `InputReportByteSize + 1` &mdash; `HMProfileBuilder.FromDescriptorBuilder` derives this automatically.

If you already emitted a Report ID via `AddRaw` or by manually composing items, the injection is skipped and your existing tag wins.

### Throws

`InvalidOperationException` if the current Application Collection is a Gamepad TLC. The message:

> "AddPidFfbBlock() requires a Joystick (Usage 0x04) Application Collection. DirectInput's pid.dll PID FFB enumerator AVs inside PID_EffectOperation+0x52 when CreateEffect is called against a Gamepad (Usage 0x05) TLC. The behavior is pid.dll-architectural (DirectX 8-era code, not OS-build-gated). Use HidDescriptorBuilder.Joystick() instead, or use Gamepad() for an XInput/WGI rumble path that doesn't go through DirectInput PID FFB."

### `MinimumViablePidFfbBlock`

```csharp
public static byte[] MinimumViablePidFfbBlock { get; }
```

The exact bytes `AddPidFfbBlock` appends, exposed as a static byte array for probe and test code that needs to verify the canonical block byte-for-byte. Consumers should call the fluent `AddPidFfbBlock` method instead.

---

## `AddRaw(bytes)`

```csharp
.AddRaw(new byte[] { 0x05, 0x01, 0x09, 0x40, 0x15, 0x00, ... })
```

Signature is `AddRaw(byte[] bytes)` &mdash; not `params byte[]` &mdash; so callers pass an explicit array. Appends arbitrary HID descriptor bytes without validation. For advanced cases not covered by the semantic methods:

- **Vx / Vy velocity usages** for separate-trigger Xbox profiles. Append the bytes for Vx (Generic Desktop Page 0x01, Usage 0x40) and Vy (Usage 0x41) in the order the descriptor needs them.
- **Vendor-page items** for proprietary input/output/feature reports.
- **Specific descriptor bytes copied from a real device** when you want bit-identical wire shape rather than logically equivalent.

The builder doesn't track what `AddRaw` adds for purposes of `TotalInputBits` &mdash; if you append input items via raw bytes, `InputReportByteSize` and `FromDescriptorBuilder`'s wire-size derivation may be off. Use either fully-fluent or fully-raw construction; mixing requires manual `InputReportSize`.

---

## `Build()`, `TotalInputBits`, `InputReportByteSize`, `DescriptorContainsReportId`

```csharp
public byte[] Build();
public int    TotalInputBits { get; }
public int    InputReportByteSize { get; }
public bool   DescriptorContainsReportId();
```

`Build()` returns the descriptor bytes. Closes the Application Collection if open (appends `0xC0`).

`TotalInputBits` is the running total of input bits declared so far via the semantic methods. Useful for sizing checks; `AddRaw` doesn't update it.

`InputReportByteSize` is `TotalInputBits` rounded up to a byte multiple. **Does not include the +1 byte for a Report ID prefix.**

`DescriptorContainsReportId()` walks the emitted bytes and returns true if at least one HID Report ID Global item (`0x85 NN`) is present. Used internally by `HMProfileBuilder.FromDescriptorBuilder` to decide whether the wire input report size needs the +1.

---

## Example: a complete custom HOTAS

```csharp
var desc = new HidDescriptorBuilder()
    .Joystick()                       // Joystick TLC for FFB compatibility
    .AddStick("Left", 16)             // primary X/Y
    .AddTrigger("Left", 8)             // throttle
    .AddTrigger("Right", 8)            // brake
    .AddButtons(20)                    // 20 buttons (rounded up to 24)
    .AddHat(positions: 16)             // 22.5° hat
    .AddPidFfbBlock();                 // full PID FFB

var profile = new HMProfileBuilder()
    .Id("custom-hotas-stick")
    .Name("Custom HOTAS Stick")
    .Vendor("MyCo")
    .Vid(0x0483).Pid(0x5740)
    .ProductString("Custom HOTAS")
    .Type("hotas")
    .Connection("usb")
    .FromDescriptorBuilder(desc)       // descriptor bytes + correct InputReportSize
    .Build();

using var ctx = new HMContext();
ctx.LoadDefaultProfiles();
ctx.InstallDriver();
using var ctrl = ctx.CreateController(profile);

// FFB now works: declare pool, drive any DirectInput game with this virtual
ctrl.PublishPidPool(ramPoolSize: 0x0400,
                    simultaneousEffectsMax: 16,
                    deviceManagedPool: false,
                    sharedParameterBlocks: false);

// Wire output to your physical HOTAS
ctrl.OutputReceived += (sender, packet) => RouteFFBToHardware(packet);

// 16-position hat at full descriptor resolution
ctrl.SubmitState(new HMGamepadState { HatDegrees = 22.5f });
```

---

## Validation summary

| Method | Checks | Throws |
|--------|--------|--------|
| `Gamepad()` | None | &mdash; |
| `Joystick()` | None | &mdash; |
| `AddStick(name, bits)` | None &mdash; bits not enforced byte-aligned (two-stick always rounds) | &mdash; |
| `AddTrigger(name, bits)` | `bits % 8 == 0` | `ArgumentException` |
| `AddButtons(count)` | None &mdash; rounds up internally | &mdash; |
| `AddHat(positions)` | `positions >= 4` | `ArgumentOutOfRangeException` |
| `AddPidFfbBlock()` | Current TLC must not be Gamepad | `InvalidOperationException` |
| `AddRaw(bytes)` | None &mdash; no validation by design | &mdash; |
| `Build()` | None &mdash; auto-closes Application Collection | &mdash; |

---

## See also

- [SDK Reference](sdk-reference.md) &mdash; `HMProfileBuilder.FromDescriptorBuilder` automatic `+1` wire-size derivation.
- [Custom Profiles](../profiles/custom-profiles.md) &mdash; full clone / build / spoof patterns using this builder.
- [Force Feedback](force-feedback.md) &mdash; what the FFB block does at runtime, descriptor authoring requirements, and the full publish/read loop.
- [Profile System](../profiles/profile-system.md) &mdash; how the JSON `descriptor` field maps to the bytes this builder produces.

## References

USB-IF specs are at [usb.org/document-library](https://www.usb.org/document-library); search by the exact title.

- USB HID 1.11 specification &mdash; Item Format encoding, report descriptor structure.
- HID Usage Tables (HUT) 1.5 &mdash; Generic Desktop usages (X/Y/Z/Rx/Ry/Rz/Vx/Vy/Hat) and the Joystick (0x04) / Gamepad (0x05) application TLCs.
- HID PID 1.0 specification &mdash; the descriptor block `AddPidFfbBlock` emits.
- vJoy reference descriptor &mdash; in [github.com/njz3/vJoy](https://github.com/njz3/vJoy) under `driver/sys/hidReportDescFfb.h`. The four-feature variant that triggers the `pid.dll` AV.
- [HIDMaestro issue #16](https://github.com/hifihedgehog/HIDMaestro/issues/16) &mdash; the empirical pid.dll AV report.
- [HIDMaestro issue #6](https://github.com/hifihedgehog/HIDMaestro/issues/6) &mdash; the Chromium phantom-axis trap that motivates `AddButtons` round-up and `AddTrigger` byte-alignment validation.
- [References](../reference/references.md) &mdash; full source bibliography.

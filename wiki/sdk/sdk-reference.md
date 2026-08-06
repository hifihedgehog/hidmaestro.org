# SDK Reference

The full public surface of `HIDMaestro.Core.dll`. Five primary types: `HMContext` (process-wide entry point), `HMController` (live virtual device), `HMProfile` (immutable profile handle), `HMProfileBuilder` (custom-profile builder), and `HMGamepadState` (abstract input frame). Plus `HidDescriptorBuilder`, `HMDeviceExtractor`, `HMOemNameOverride`, and the PID FFB output types.

This page documents every method's contract, thread safety, throw conditions, and the underlying mechanics that affect when you'd call which.

The deep-dive subjects each get their own page:

- [HID Descriptor Builder](hid-descriptor-builder.md) &mdash; `HidDescriptorBuilder` API.
- [Force Feedback](force-feedback.md) &mdash; `PublishPidPool` / `PublishPidBlockLoad` / `PublishPidState` / `GetCurrentPidBlockLoad`.
- [Output Passthrough](output-passthrough.md) &mdash; `OutputReceived` event, `HMOutputPacket`, `HMOutputSource`.
- [OEM Name Override](oem-name-override.md) &mdash; `HMOemNameOverride.Set` / `Clear` / `RecoverOrphans` / `ListActive`.
- [Custom Profiles](../profiles/custom-profiles.md) &mdash; the `HMProfileBuilder` patterns.
- [Profile Extractor](../profiles/profile-extractor.md) &mdash; `HMDeviceExtractor` API used by the GUI tool.

---

## HMContext

The SDK's process-wide entry point. One per consuming application. Owns the loaded profile catalog, the per-controller index allocator, and the lifecycle of every `HMController` it creates.

```csharp
public sealed class HMContext : IDisposable
{
    public HMContext();
}
```

### Lifecycle

- Construct one at app startup. Disposing the context disposes every controller it owns.
- The constructor is non-blocking. It kicks off three background prewarm tasks (driver-payload extraction, profile catalog parse, GameInput service warm-up) so the first `InstallDriver` / `LoadDefaultProfiles` / `CreateController` call hides 200-500 ms of cold-start cost in the consumer's think-time budget. Failures are silently swallowed; the foreground call retries.
- Multiple contexts in one process work but share the controller-index pool. There is no good reason to create more than one.

### Driver lifecycle

```csharp
public bool IsDriverInstalled { get; }
public void InstallDriver();
public static void RemoveAllVirtualControllers();
```

`IsDriverInstalled` returns true if a HIDMaestro driver package matching the embedded payload's manifest hash is currently in the DriverStore. Does not require admin.

`InstallDriver` extracts the embedded driver files to `%TEMP%`, generates / installs a self-signed code-signing certificate, signs the binaries, and registers them with `pnputil`. Idempotent &mdash; if the same hash is already installed, returns immediately. The temp extraction is deleted on success. **Requires admin** (`UnauthorizedAccessException` if not elevated). Throws `InvalidOperationException` if any signing or `pnputil` step fails. Always runs `RemoveAllVirtualControllers` first as a self-heal so a stale INF can't pin the install. See [Driver Install and Signing](../reference/driver-install-and-signing.md) for the full sequence.

`RemoveAllVirtualControllers` is static and instance-free. Removes every HIDMaestro virtual device on the system, including orphans from previous runs that crashed before disposing. **Requires admin.** Use this from a "cleanup" command-line subcommand or as a defensive call after a force-kill. The proven pattern: `HIDMaestroTest cleanup` invokes it.

### Profile catalog

```csharp
public IReadOnlyList<HMProfile> AllProfiles { get; }
public HMProfile? GetProfile(string id);
public int LoadDefaultProfiles();
public int LoadProfilesFromDirectory(string profilesDir);
```

`AllProfiles` returns every profile loaded into this context, sorted by stable ID. Empty until you call one of the `LoadProfiles*` methods.

`GetProfile(id)` looks up by stable ID slug (e.g. `"xbox-360-wired"`, `"dualsense"`, `"thrustmaster-t300rs"`). Returns null if no such profile is loaded. Case-insensitive.

`LoadDefaultProfiles` loads the embedded catalog (228 entries shipping inside `HIDMaestro.Core.dll`) and returns the count added. Skips IDs already loaded.

`LoadProfilesFromDirectory(path)` loads `*.json` from a directory matching the [Profile System](../profiles/profile-system.md) schema. Useful for shipping a curated subset, or for hot-loading runtime-modified profiles. Schema validation files (`schema.json`) are skipped. Does not auto-load the embedded catalog &mdash; call both if you want catalog + custom.

### Controller lifecycle

```csharp
public HMController CreateController(HMProfile profile);
public HMController CreateControllerAt(int index, HMProfile profile);
public IReadOnlyCollection<HMController> ActiveControllers { get; }

public void DisposeControllersInParallel(
    IEnumerable<HMController> controllers,
    Action<HMController, long>? perControllerCallback = null);

public void FinalizeNames();
```

`CreateController(profile)` allocates the next free controller index (linear scan from 0), runs the per-archetype `SetupController` orchestration (registry write &rarr; `pnputil /add-driver` if needed &rarr; SwDevice or SetupAPI device creation &rarr; PnP wait &rarr; XInput slot-claim wait), and returns once the device is fully bound and ready to receive input. **Requires admin.**

Throws:

- `ArgumentNullException` if `profile` is null.
- `ArgumentException` if the profile has no descriptor (not deployable).
- `InvalidOperationException` if device-node creation fails or the driver install fails.

The returned `HMController` is live. Dispose it to remove the device, or dispose the entire context to remove all controllers it owns.

`CreateControllerAt(index, profile)` is the same except it pins to a specific index. Used by live profile-switch workflows where you want to dispose the controller at index N and replace it with a different profile while keeping N stable. Throws `InvalidOperationException` if index is in use.

`ActiveControllers` returns a snapshot of every live controller this context owns. Order is creation order.

`DisposeControllersInParallel(controllers, perCallback)` disposes a set of controllers concurrently with the per-controller HID orphan sweep suppressed and run once at the end. Use from any caller that already has a list to dispose together (e.g. a test harness's end-of-run cleanup, a consumer's app exit). The per-controller wall-clock for each `Dispose` call is reported via the optional callback. Single-element or empty inputs degrade to plain serial dispose. Internal context disposal uses an equivalent path.

`FinalizeNames` re-applies friendly names to every live controller. Call **once after creating ALL controllers** &mdash; there is a Windows PnP race where the first controller's friendly name gets overwritten by the second controller's driver-bind activity. Re-applying after PnP has settled makes the writes stick. Polls each HID child for `DN_STARTED` (driver fully bound) before re-applying; on fast machines exits in <100 ms, on slow machines adapts up to 5 s.

### Disposal

```csharp
public void Dispose();
```

Disposes every live `HMController`, runs a final orphan sweep, and tears down the prewarm threads. Idempotent.

---

## HMController

A live virtual controller. Created by `HMContext.CreateController`; dispose to remove the device. Two channels: input (consumer pushes state) and output (SDK raises rumble/haptics/FFB events).

```csharp
public sealed class HMController : IDisposable
{
    public HMProfile Profile { get; }
}
```

### Input

```csharp
public void SubmitState(in HMGamepadState state);
public void SubmitRawReport(ReadOnlySpan<byte> report);
```

`SubmitState` translates the abstract `HMGamepadState` into the active profile's HID report layout and writes it to shared memory. Cadence is set by the consumer &mdash; there is no internal pump thread. Typical rates: 1000 Hz for high-fidelity input passthrough (PadForge), 250 Hz for bench testing, 8 Hz for a profile that's only sending the occasional button event.

For Xbox-VID profiles (`vid == 0x045E`), the same call also packs a 14-byte GIP-format buffer for the XUSB companion to read on `IOCTL_XUSB_GET_STATE`. Non-Xbox profiles skip this packing entirely (~60-80 instructions per frame saved).

`SubmitRawReport(report)` pushes a raw HID input report for features `HMGamepadState` doesn't model: DualSense touchpad coordinates, gyroscope, sensor packets, vendor extensions. Pass **data bytes only** &mdash; do NOT include a Report ID prefix. The driver prepends the Report ID automatically. For profiles with no Report ID, pass the full report as-is.

Throws `ArgumentException` if `report` is empty or exceeds the 256-byte shared-section payload capacity.

The output of either method becomes visible through every downstream API simultaneously: `XInputGetState`, `joy.cpl`, browser Gamepad, SDL3, WGI. See [Cross-API Coverage](../reference/cross-api-coverage.md) for the per-API translation.

### Output (rumble / haptics / FFB / LEDs)

```csharp
public event Action<HMController, HMOutputPacket>? OutputReceived;
```

Raised on the SDK's output-polling thread (~125 Hz, ~8 ms cadence) whenever a host application sends a rumble, haptic, FFB, feature, or LED command to this virtual. Multiple invocations per poll iteration are normal (DirectInput PID FFB writes Set Effect &rarr; Set Constant Force &rarr; Effect Operation Start within 1-3 ms; the ring buffer drains all three on the next poll).

Handlers run on the polling thread, **not the consumer's UI thread**. Marshal back to UI thread if needed. Keep handlers cheap &mdash; the ring buffer holds 64 slots × 256-byte payload; if a reader stalls past ~512 ms while the producer is bursting, the oldest packets get overwritten.

`HMOutputPacket` carries `Source` (HidOutput / HidFeature / XInput), `ReportId`, `Data` (a `ReadOnlyMemory<byte>` over the SDK's reusable buffer &mdash; copy if you need it past the handler return), and a monotonic `SeqNo`.

See [Output Passthrough](output-passthrough.md) for the wire format and consumer-side decoding patterns.

### Output (parsed-field, v1.3.5+)

```csharp
public event EventHandler<HMOutputDecodedEventArgs>? OutputDecoded;

public sealed class HMOutputDecodedEventArgs : EventArgs
{
    public byte ReportId { get; init; }
    public IReadOnlyDictionary<string, object> Fields { get; init; }
    public ReadOnlyMemory<byte> RawBytes { get; init; }
    public bool CrcValid { get; init; }
}
```

Fires alongside `OutputReceived` whenever an inbound output report matches the profile's `extendedOutputReport.reportId`. `Fields` is keyed by the JSON spec's `semantic` names; values map to runtime types per the field type (see [Profile System](../profiles/profile-system.md) / [Output Passthrough](output-passthrough.md) for the type table).

Use `OutputDecoded` when the profile JSON describes the byte layout (Sony BT 0x31 in v1.3.5; future profiles by JSON addition only). Fall back to `OutputReceived` for raw bytes or for profiles without an `extendedOutputReport` block.

```csharp
ctrl.OutputDecoded += (_, e) =>
{
    if (e.Fields.TryGetValue("rightMotor", out var rm)) ApplyMotor((byte)rm);
    if (e.Fields.TryGetValue("lightbar",   out var rgb)
        && rgb is byte[] c) ApplyLightbar(c[0], c[1], c[2]);
};
```

The inverse direction — synthesize parsed fields, encode wire bytes — uses `HMOutputEncoder.Encode`:

```csharp
public static class HMOutputEncoder
{
    public static byte[] Encode(HMProfile profile, IReadOnlyDictionary<string, object> fields);
}
```

Returns the full on-wire report buffer including report ID at byte 0 and (if the spec declares a `crc32-le` field) the CRC32 footer. Throws `InvalidOperationException` if `profile.ExtendedOutputReport` is null.

### HID PID 1.0 force feedback

```csharp
public void PublishPidPool(ushort ramPoolSize, byte simultaneousEffectsMax,
                           bool deviceManagedPool, bool sharedParameterBlocks);
public void PublishPidBlockLoad(byte effectBlockIndex, PidLoadStatus loadStatus,
                                ushort ramPoolAvailable);
public void PublishPidState(byte effectBlockIndex, PidStateFlags flags);
public HMPidBlockLoad GetCurrentPidBlockLoad();
```

The four shared-section publish/read methods. The driver answers `HidD_GetFeature` for the canonical PID Report IDs (Pool 0x13, Block Load 0x12, State 0x14) directly from a per-controller shared state section the consumer fills via these methods.

`PublishPidPool` is the gate &mdash; until called at least once, the driver returns `STATUS_NO_SUCH_DEVICE` for the Pool Report so DirectInput cleanly concludes "device exists but no FFB" rather than retrying. First call enables FFB on this controller; subsequent calls update pool state.

`PublishPidBlockLoad` is now optional (v1.1.37+). The driver allocates EBIs synchronously inside its `SetFeature(0x11 Create New Effect)` IOCTL handler &mdash; the consumer reads the assigned EBI via `GetCurrentPidBlockLoad` rather than writes its own. Manual writes are still supported (overwrite the driver's allocation) but no longer needed for the canonical handshake.

`PublishPidState` reflects current device state for the most-recently-referenced effect: paused, actuators enabled, safety switch, effect playing, etc. Update on Effect Operation Start/Stop, Device Reset, Device Pause, or Actuators Enable/Disable.

The descriptor must declare the PID FFB block. Use `HidDescriptorBuilder.AddPidFfbBlock` &mdash; that method emits the canonical "minimum viable" block with exactly the right report-ID / collection / usage shape. Do **not** add additional Feature reports inside the same Application Collection; the four-feature variant from vJoy's reference descriptor causes `pid.dll` to AV. See [Force Feedback](force-feedback.md) for the full architecture.

### Disposal

```csharp
public void Dispose();
```

Removes the virtual device from PnP, frees the per-controller shared memory section, signals the output-polling thread to stop, and releases handles. Idempotent &mdash; safe to call multiple times. Called automatically when the owning `HMContext` is disposed.

---

## HMGamepadState

The abstract input frame.

```csharp
public struct HMGamepadState
{
    public Dictionary<HMAxis, float>? Axes;   // every analog input, keyed by HID usage

    public HMButton Buttons;                  // bitmask
    public HMHat Hat;                         // 8-direction enum

    public float?  HatDegrees;                // 0 = North, clockwise. [0, 360)
    public int?    HatHundredths;             // hundredths of a degree, 0..35999
    public ushort? HatRaw;                    // raw descriptor field value (LogicalMin..LogicalMax)

    // Sony-specific surface (touchpad, IMU, battery) keeps native representation.
    // See HMGamepadState.cs for the full set of fields.
}
```

`Axes` is the single drive surface for every analog input (v1.3.9). Values are uniformly `[0.0, 1.0]`: 0.5 is centered for signed axes (sticks, twist rudders), 0.0 is released for unsigned axes (triggers, throttles, sliders, pedals). The SDK iterates each declared analog field in the active profile's descriptor, reads the dict by HID usage, and writes the report. Axes the consumer doesn't write default to centered (signed) or released (unsigned); axes the descriptor doesn't declare are silently ignored.

```csharp
// HOTAS with stick + slider + rudder + throttle, all in one dict
state.Axes = new Dictionary<HMAxis, float>
{
    [HMAxis.X]        = 0.55f,   // stick X, slightly right of center
    [HMAxis.Y]        = 0.35f,   // stick Y, slightly below center
    [HMAxis.Slider]   = 0.75f,   // throttle slider
    [HMAxis.Rudder]   = 0.25f,   // rudder pedal
    [HMAxis.Throttle] = 1.00f,   // secondary throttle full
};
```

Null `Axes` is the hot-path-cost-free idle case: the encoder's dict walk is gated on `axes != null && Count > 0`. Allocate the dict once in your input pump and reuse.

For features `HMGamepadState` does not model (Sony touchpad finger coordinates, gyro/accel for non-IMU profiles, vendor extensions), use `SubmitRawReport` with bytes you assembled per the profile's descriptor.

### `HMGamepadStateHelpers.StandardAxes` &mdash; ergonomic 6-slot shortcut

Most consumers want the canonical `(LX, LY, RX, RY, LT, RT)` convention. The static helper resolves those into the active profile's actual axis keys (Sony's Z=right-stick, Rx=left-trigger axis map is honored automatically) and returns a fresh dict ready to assign to `state.Axes`.

```csharp
ctrl.SubmitState(new HMGamepadState
{
    Axes = HMGamepadStateHelpers.StandardAxes(ctrl.Profile,
        leftStickX: 0.5f, leftStickY: 0.5f,
        rightStickX: 0.5f, rightStickY: 0.5f,
        leftTrigger: 0.0f, rightTrigger: 0.0f),
    Buttons = HMButton.A,
    Hat = HMHat.North,
});
```

Use the helper for tests and demos. For 1000 Hz hot paths, allocate one `Dictionary<HMAxis, float>` and update entries directly by HMAxis key &mdash; same code path, no per-frame dict allocation. Discover which axes a profile exposes via `HMProfile.Sticks` / `HMProfile.Triggers` (variable-length lists derived from the layout's role tags) or `HMProfile.AvailableAxes` (every `HMAxis` the descriptor declares).

### `HMAxis` enum

```csharp
public enum HMAxis : ushort
{
    None = 0,

    // Generic Desktop (page 0x01) &mdash; (page << 8 | usage)
    X = 0x0130, Y = 0x0131, Z = 0x0132, Rx = 0x0133, Ry = 0x0134, Rz = 0x0135,
    Slider = 0x0136, Dial = 0x0137, Wheel = 0x0138,
    Vx = 0x0140, Vy = 0x0141, Vz = 0x0142,
    Vbrx = 0x0143, Vbry = 0x0144, Vbrz = 0x0145, Vno = 0x0146,

    // Simulation Controls (page 0x02)
    Aileron = 0x02B0, AileronTrim = 0x02B1, AntiTorque = 0x02B2,
    CollectiveControl = 0x02B5, DiveBrake = 0x02B6,
    Elevator = 0x02B8, ElevatorTrim = 0x02B9,
    Rudder = 0x02BA, Throttle = 0x02BB,
    LandingGear = 0x02BE, ToeBrake = 0x02BF,
    WingFlaps = 0x02C3, Accelerator = 0x02C4, Brake = 0x02C5,
    Clutch = 0x02C6, Shifter = 0x02C7, Steering = 0x02C8,
    TurretDirection = 0x02C9, BarrelElevation = 0x02CA,
    DivePlane = 0x02CB, Ballast = 0x02CC,
    BicycleCrank = 0x02CD, HandleBars = 0x02CE,
    FrontBrake = 0x02CF, RearBrake = 0x02D0,
}
```

The enum value encodes `(UsagePage << 8) | Usage` so it's a stable identifier consumers can switch on. Generic Desktop covers stick, trigger, slider, dial, wheel, and the velocity (Vx/Vy/Vz/Vbrx/Vbry/Vbrz/Vno) usages. Simulation Controls covers the analog flight, automotive, marine, and cycling control set.

### Hat priority chain (v1.3.4)

The encoder picks the first non-null in the order: `HatDegrees` &rarr; `HatHundredths` &rarr; `HatRaw` &rarr; `Hat`. Use:

- `Hat` for XInput-style 8-way d-pads.
- `HatDegrees` when your source produces a continuous angle (e.g. analog hat from a stick).
- `HatHundredths` for vJoy-migration paths or when keeping float off the hot path matters.
- `HatRaw` when you have queried `HMProfile.HatLogicalMin` / `HatLogicalMax` and want bit-exact descriptor values.

For a 16-position HOTAS hat, `HatDegrees = 22.5f` snaps to ENE. For a 360-position pro flight stick, `HatDegrees = 47.3f` lands at the closest declared position.

### HMButton

```csharp
[Flags] public enum HMButton : uint
{
    None         = 0,
    A            = 1u << 0,
    B            = 1u << 1,
    X            = 1u << 2,
    Y            = 1u << 3,
    LeftBumper   = 1u << 4,
    RightBumper  = 1u << 5,
    Back         = 1u << 6,    // Select / Share / View
    Start        = 1u << 7,    // Options / Menu
    LeftStick    = 1u << 8,    // L3
    RightStick   = 1u << 9,    // R3
    Guide        = 1u << 10,   // Xbox / PS / Home
    Touchpad     = 1u << 11,   // PS touchpad click
    Share        = 1u << 12,   // Xbox Series Share button

    RightPaddle  = 1u << 13,   // rear paddle, right side
    LeftPaddle   = 1u << 14,   // rear paddle, left side
    Misc1        = 1u << 15,   // vendor button with no cross-vendor role


    Cross    = A,    // Sony alias
    Circle   = B,
    Square   = X,
    Triangle = Y,
}
```

`RightPaddle` and `LeftPaddle` are named by side rather than by number, because the pads that have them disagree on numbering and agree on side. SDL splits them the same way with `SDL_GAMEPAD_BUTTON_RIGHT_PADDLE1` and `LEFT_PADDLE1`. The Switch 2 Pro's GR and GL map here.

`Misc1` is a vendor button with no cross-vendor meaning, currently the Switch 2 family's C button, which opens GameChat on real hardware. SDL models it the same way rather than forcing it into one of the standard roles.

All three were added in v1.5.0 as bits 13 to 15. They are additive, so a consumer only needs to care if it switches exhaustively over the enum.

The SDK applies the active profile's `buttonMap` (where present) to translate from the abstract `HMButton` bit position to the descriptor button index. Sony profiles remap so `HMButton.A &rarr; Cross`, `HMButton.X &rarr; Square`, etc. Xbox profiles use identity mapping.

`HMButton.Guide` reaches XInput consumers via `XInputGetStateEx` as the undocumented `XINPUT_GAMEPAD_GUIDE` (0x0400) bit. Reaches WGI / browser via the System Main Menu HID usage on xinputhid profiles, or via the GIP buffer's `btnHigh` bit 6 (0x40) on XUSB-companion profiles &mdash; the companion translates 0x40 to `XINPUT_GAMEPAD_GUIDE` in `IOCTL_XUSB_GET_STATE`.

### HMHat

```csharp
public enum HMHat : byte
{
    None      = 0,
    North     = 1, NorthEast = 2, East = 3, SouthEast = 4,
    South     = 5, SouthWest = 6, West = 7, NorthWest = 8,
}
```

The SDK encodes into whatever the profile's descriptor declares. For an 8-position hat the wire values are 0..7 (with the encoder writing N=0, NE=1, etc.). For a 16-position hat the SDK fills the right value at the right resolution; consumers not using `HMHat`'s 8-way step should switch to `HatDegrees` / `HatRaw`.

---

## HMProfile

An immutable handle to a profile.

```csharp
public sealed class HMProfile
{
    // Identity
    public string Id { get; }
    public string Name { get; }
    public string Vendor { get; }
    public ushort VendorId { get; }
    public ushort ProductId { get; }
    public string ProductString { get; }
    public string ManufacturerString { get; }
    public string DisplayName { get; }
    public string Type { get; }     // "gamepad", "wheel", "joystick", "hotas", ...

    // Connection / driver
    public string  Connection { get; }    // "usb", "bluetooth", "wireless-adapter"
    public string? DriverMode { get; }    // "xinputhid" or null
    public string? TriggerMode { get; }   // "combined", "separate", or null

    // Descriptor
    public bool   IsDeployable { get; }
    public int    InputReportSize { get; }
    public byte[]? GetDescriptorBytes();  // returns a defensive copy
    public string? DescriptorHex { get; }

    // Parsed layout
    public int   ButtonCount { get; }
    public int   AxisCount { get; }
    public IReadOnlyList<HMAxis> AvailableAxes { get; }
    public bool  HasHat { get; }
    public int?  HatLogicalMin { get; }
    public int?  HatLogicalMax { get; }
    public int   StickBits { get; }
    public int   TriggerBits { get; }

    // v1.3.9 — authored physical layout (discriminated union, 16 kinds)
    public HMLayout? Layout { get; }
    public IReadOnlyList<HMSimpleStick>   Sticks { get; }    // derived from Layout role tags
    public IReadOnlyList<HMSimpleTrigger> Triggers { get; }
    public int StickCount { get; }
    public int TriggerCount { get; }
    // Per-kind accessors: AsGamepad(), AsWheel(), AsHotas(), ... return the
    // concrete HMLayout subtype when Layout matches that kind, else null.

    // Customization tables
    public int[]?                       ButtonMap { get; }
    public Dictionary<string,string>?   AxisMap { get; }
    public string?                      SdlMapping { get; }
    public string?                      Notes { get; }

    // Vendor-blob layout (null when the profile JSON has none)
    public ExtendedReportSpec? ExtendedReport { get; }        // input direction
    public ExtendedReportSpec? ExtendedOutputReport { get; }  // output direction
    public bool HasExtendedInput { get; }
    public bool HasExtendedOutput { get; }
}
```

Profiles are immutable. Mutation goes through `HMProfileBuilder.FromProfile(existing)` &mdash; build a new profile with the changes you want.

`IsDeployable` is false for placeholder catalog entries that have no descriptor yet. `CreateController` will throw `ArgumentException` for those. The catalog ships only deployable profiles by default; placeholders are an internal concept that survived from the catalog generator.

`HatLogicalMin` / `HatLogicalMax` are the HID-spec values declared in the descriptor. For an octant hat, `Min=0 Max=7` (or equivalents); for a 16-position hat `Min=0 Max=15`; for a 360-position continuous hat `Min=0 Max=359`. The count of distinct positions is `Max - Min + 1`.

`ButtonMap` is the optional remapping table from `HMButton` bit position (index into the array) to descriptor button index (the value). Null = identity (Xbox layout). Sony's table reorders so Cross/Circle/Square/Triangle land at the right bit.

`AxisMap` is the optional axis semantic override. Keys are hex HID usage codes (e.g. `"0x32"` for Z), values are semantic names (`"leftStickX"`, `"rightTrigger"`, etc.). Sony profiles override `Z/Rz &rarr; rightStick` and `Rx/Ry &rarr; triggers` because Sony's descriptor uses Generic Desktop usages differently from Xbox's.

`SdlMapping` is the profile's SDL gamepad mapping, or null when SDL already knows the device. It matters for one specific case. SDL only exposes a joystick through its gamepad API when a mapping exists for that device's GUID, and it synthesizes one only for devices its HIDAPI, RawInput, WGI or XInput backends claim. A pad that reaches SDL through DirectInput gets a mapping from SDL's built-in database or from nowhere. So a controller newer than the SDL build in use, or one whose vendor protocol SDL drives over a transport a HID profile cannot present, arrives with axes and buttons but no roles: no A/B/X/Y, no triggers, no dpad. The Switch 2 Pro is the shipped example.

The string is everything after the GUID and the name, trailing comma included, because the GUID is per-device and only exists once SDL has enumerated the pad. A consumer prepends the two device-specific fields:

```csharp
// once per joystick SDL reports, before opening it as a gamepad
var guid = FormatSdlGuid(SDL_GetJoystickGUIDForID(id));   // 32 lowercase hex chars
if (profile.SdlMapping != null)
    SDL_AddGamepadMapping($"{guid},{profile.Name},{profile.SdlMapping}");
```

Registering it is idempotent and safe even when SDL already has a mapping for that GUID, since SDL replaces the entry. Consumers that never touch SDL can ignore the property.

`AxisCount` is the count of every analog input axis the descriptor declares. For SideWinder Force Feedback 2 that's `4` (X, Y, Rz, Slider); for a Logitech G29 with three pedals, `4` (X plus three 8-bit pedals); for an Xbox 360 Wired with the Vx/Vy hidden-trigger pair, `7`.

`AvailableAxes` returns every `HMAxis` the descriptor declares as an analog input, in descriptor order. Combined with `state.Axes`, this is the discovery + drive pair for descriptor-aware binding UIs ("Map physical input to virtual axis: \[dropdown of AvailableAxes\]") without hard-coding which axes a given profile exposes. Empty array when the profile has no descriptor.

### `Layout` and the simple-slot framework (v1.3.9)

`HMProfile.Layout` is a discriminated union with 16 concrete kinds: `gamepad`, `joystick`, `flight_stick`, `hotas`, `wheel`, `pedals`, `shifter`, `handbrake`, `single_axis_accessory`, `arcade_stick`, `dance_pad`, `guitar`, `motion_wand`, `remote`, `controller_adapter`, `unspecified`. Each kind carries the structured fields that make sense for it (sticks, triggers, pedals, wheel rotation range, hat location, paddle count, rumble kind, IMU presence). Consumers render the right widget per profile by matching the layout's kind:

```csharp
switch (pad.Layout)
{
    case HMWheelLayout w:
        RenderWheelGauge(w.RotationRangeDegrees, w.Pedals);
        break;
    case HMHotasLayout h:
        RenderHotasView(h.Stick, h.ThrottlePrimary, h.StickRudder);
        break;
    case HMGamepadLayout g:
    default:
        RenderStandardGamepad();
        break;
}
```

For consumers that just want "give me sticks and triggers for the simple framework," `Profile.Sticks` and `Profile.Triggers` are variable-length lists derived deterministically from the layout's role tags:

- Gamepad &rarr; 2 sticks + 2 triggers.
- Wheel + 3 pedals &rarr; 1 stick (steering on `XAxis`, clutch on `YAxis`) + 2 triggers (accelerator, brake).
- Pedals-only box &rarr; 0 sticks + 2 or 3 triggers.
- Stick-only joystick &rarr; 1 stick + 0 triggers (or 1 throttle if the layout declares one).

Each entry surfaces the `HMAxis` key the consumer writes through. `HMGamepadStateHelpers.StandardAxes(profile, leftStickX, leftStickY, ..., leftTrigger, rightTrigger)` maps the canonical 6-slot convention into the right axis keys for the active profile (so a Sony pad's Z=right-stick mapping is honored automatically).

Profiles whose physical layout is unknown or undocumented declare `kind: "unspecified"` (`HMUnspecifiedLayout`); 30 of the 126 shipped profiles fall into this bucket rather than fabricate a layout. The classifier still resolves their descriptor's standard usages into the simple slots.

---

## HMProfileBuilder

Fluent builder for runtime-built profiles. Three patterns: clone-and-modify, build-from-scratch, spoof. See [Custom Profiles](../profiles/custom-profiles.md) for the full walkthrough; this section is the API reference.

```csharp
public sealed class HMProfileBuilder
{
    public HMProfileBuilder Id(string id);
    public HMProfileBuilder Name(string name);
    public HMProfileBuilder Vendor(string vendor);
    public HMProfileBuilder Vid(ushort vid);
    public HMProfileBuilder Pid(ushort pid);
    public HMProfileBuilder ProductString(string s);
    public HMProfileBuilder ManufacturerString(string s);
    public HMProfileBuilder DeviceDescription(string? desc);
    public HMProfileBuilder Type(string type);            // "gamepad", "wheel", "hotas", ...
    public HMProfileBuilder Connection(string conn);      // "usb", "bluetooth", ...
    public HMProfileBuilder DriverMode(string? mode);     // "xinputhid" or null
    public HMProfileBuilder TriggerMode(string? mode);    // "combined", "separate", or null
    public HMProfileBuilder Notes(string? notes);

    public HMProfileBuilder Descriptor(byte[] bytes);
    public HMProfileBuilder DescriptorHex(string hex);
    public HMProfileBuilder InputReportSize(int size);
    public HMProfileBuilder FromDescriptorBuilder(HidDescriptorBuilder builder);

    public HMProfileBuilder ButtonMap(int[]? map);
    public HMProfileBuilder TriggerButtons(int[]? map);
    public HMProfileBuilder AxisMap(Dictionary<string,string>? map);

    public HMProfileBuilder FromProfile(HMProfile source);

    public HMProfile Build();
}
```

`Build()` validates that VID and PID are non-zero and returns an `HMProfile`. The result can be passed directly to `HMContext.CreateController`.

### `FromDescriptorBuilder` (preferred)

`FromDescriptorBuilder(builder)` takes both the descriptor bytes and the input report wire size from a `HidDescriptorBuilder`. The wire size is derived as `InputReportByteSize + 1` when the descriptor carries a Report ID, and `InputReportByteSize` otherwise. This replaces the easy-to-get-wrong:

```csharp
// Wrong way (works without Report ID, breaks with it)
.Descriptor(b.Build()).InputReportSize(b.InputReportByteSize + 1)
```

with:

```csharp
// Right way: the +1 byte for Report ID is decided automatically
.FromDescriptorBuilder(b)
```

If you forget the `+1`, the kernel sizes the input buffer wrong, HidClass preparsed data is misaligned, and `pid.dll` resolves Feature reports to Report ID 0 instead of the declared values. PadForge tracked this bug across several iterations of issue #16; `FromDescriptorBuilder` makes it impossible to hit.

### `FromProfile` clone

```csharp
var custom = new HMProfileBuilder()
    .FromProfile(ctx.GetProfile("dualsense")!)
    .Id("dualsense-custom")
    .Pid(0x1234)
    .Build();
```

Initializes every field from an existing profile, then individual setters override. Good for "DualSense but with a different PID" or "Xbox 360 Wired with a custom product string for joy.cpl labeling".

### `ButtonMap` and `AxisMap`

For full control over button/axis routing through your custom descriptor. See [Custom Profiles](../profiles/custom-profiles.md).

---

## HidDescriptorBuilder

Fluent HID-descriptor authoring without touching hex. Full reference on its own page: [HID Descriptor Builder](hid-descriptor-builder.md).

```csharp
public sealed class HidDescriptorBuilder
{
    public HidDescriptorBuilder Gamepad();
    public HidDescriptorBuilder Joystick();

    public HidDescriptorBuilder AddStick(string name, int bits = 16);
    public HidDescriptorBuilder AddTrigger(string name, int bits = 8);
    public HidDescriptorBuilder AddButtons(int count);
    public HidDescriptorBuilder AddHat(int positions = 8);
    public HidDescriptorBuilder AddPidFfbBlock();
    public HidDescriptorBuilder AddRaw(byte[] bytes);

    public byte[] Build();
    public int InputReportByteSize { get; }
    public bool DescriptorContainsReportId();
}
```

---

## HMDeviceExtractor

Read HID descriptors back out of currently-connected physical devices. The same API powers `HIDMaestroProfileExtractor.exe` and the `HIDMaestroTest extract-profile` CLI command. See [Profile Extractor](../profiles/profile-extractor.md) for the user-facing tool.

```csharp
public static class HMDeviceExtractor
{
    public static IReadOnlyList<HMHidDeviceInfo> ListDevices();
    public static HMProfile Extract(HMHidDeviceInfo device);
    public static HMProfile ExtractByVidPid(ushort vid, ushort pid);
    public static string ToJson(HMProfile profile);
}
```

`ListDevices` enumerates every HID-class device. Returns one entry per HID interface (a single physical device with multiple top-level collections appears multiple times &mdash; pick by `TopLevelUsage`). Non-elevated.

`Extract(device)` reconstructs the descriptor from `HidD_GetPreparsedData` using the libusb/hidapi algorithm (Chromium WebHID team's reverse engineering of Microsoft's preparsed-data layout). Output is logically equivalent to the device's real descriptor &mdash; same report IDs, field layouts, logical ranges, usage pages, sizes &mdash; but not byte-for-byte identical. For HIDMaestro's purpose (creating a virtual that behaves the same as the physical), logical equivalence is the correct fidelity bar; filter drivers can mutate the descriptor before it reaches user mode anyway. Non-elevated.

Throws `InvalidOperationException` if the device disconnected between enumeration and extraction, or if preparsed data can't be reconstructed.

`ExtractByVidPid(vid, pid)` is a convenience wrapper that finds the first matching device and extracts. Throws if no match.

`ToJson(profile)` serializes to the JSON format used by the shipped catalog. Output can be saved to `profiles/<vendor>/<slug>.json` and picked up by `LoadProfilesFromDirectory`.

---

## HMHidDeviceInfo

```csharp
public sealed class HMHidDeviceInfo
{
    public ushort  VendorId { get; }
    public ushort  ProductId { get; }
    public ushort  VersionNumber { get; }
    public string? ProductString { get; }
    public string? ManufacturerString { get; }
    public string? SerialNumberString { get; }
    public ushort  TopLevelUsagePage { get; }
    public ushort  TopLevelUsage { get; }      // 0x04 = Joystick, 0x05 = Gamepad
    public ushort  InputReportByteLength { get; }
    public string  DevicePath { get; }
}
```

Lightweight description of one currently-connected HID interface. Returned by `HMDeviceExtractor.ListDevices`.

---

## HMOemNameOverride

Static API for overriding the joy.cpl / DirectInput OEM-name label per VID:PID. Crash-safe via the pending-override hive at `HKLM\SOFTWARE\HIDMaestroOemOverrides`. Full reference: [OEM Name Override](oem-name-override.md).

```csharp
public static class HMOemNameOverride
{
    public static void Set(ushort vid, ushort pid, string label);
    public static void Clear(ushort vid, ushort pid);
    public static int  RecoverOrphans();
    public static IReadOnlyList<HMOemNameOverrideEntry> ListActive();
}
```

---

## Output / FFB types

```csharp
public readonly struct HMOutputPacket
{
    public readonly HMOutputSource Source;
    public readonly byte ReportId;
    public readonly ReadOnlyMemory<byte> Data;
    public readonly uint SeqNo;
}

public enum HMOutputSource : byte
{
    HidOutput  = 0,    // HidD_SetOutputReport / dinput8 PID effects / HIDAPI write
    HidFeature = 1,    // HidD_SetFeature
    XInput     = 2,    // XInputSetState (XUSB-wire 5-byte vibration)
}

public enum PidLoadStatus : byte { Success = 1, Full = 2, Error = 3 }

[Flags] public enum PidStateFlags : byte
{
    None                   = 0,
    DeviceIsPaused         = 1 << 0,
    ActuatorsEnabled       = 1 << 1,
    SafetySwitch           = 1 << 2,
    ActuatorOverrideSwitch = 1 << 3,
    ActuatorPower          = 1 << 4,
    EffectPlaying          = 1 << 5,
}

public readonly struct HMPidBlockLoad
{
    public byte EffectBlockIndex { get; }
    public PidLoadStatus LoadStatus { get; }
    public ushort RAMPoolAvailable { get; }
}
```

See [Output Passthrough](output-passthrough.md) and [Force Feedback](force-feedback.md) for the full decoding patterns and consumer-side templates.

---

## Thread safety summary

| Method / event | Caller thread | SDK behavior |
|----------------|---------------|--------------|
| `HMContext.InstallDriver` | Any (admin) | Blocks. Single-threaded internally. Don't call concurrently from two threads. |
| `HMContext.CreateController` | Any (admin) | Blocks until device fully bound. Lock-protected against concurrent index allocation. |
| `HMController.SubmitState` / `SubmitRawReport` | Any | Lock-free seqlock write. ~250 ns per call. Can be called from any thread but typically the consumer's input-poll thread. |
| `HMController.OutputReceived` | SDK poll thread | NOT the consumer's thread. Marshal back if needed. Keep handlers cheap (<512 ms total). |
| `HMController.PublishPid*` | Any | Lock-protected per-controller (so pool/state writes don't tear). Cheap. |
| `HMOemNameOverride.Set` / `Clear` | Any (admin) | Global mutex around all three registry writes. |
| `HMDeviceExtractor.ListDevices` / `Extract` | Any | Read-only. Re-enumerates on every call. |

Avoid disposing an `HMController` from inside its own `OutputReceived` handler &mdash; the dispose path joins the polling thread, which would deadlock on the handler-return wait. If you need event-driven dispose, capture the controller and call `Dispose` from a different thread.

---

## See also

- [Quickstart](../start/quickstart.md) &mdash; the SDK methods in their canonical order.
- [HID Descriptor Builder](hid-descriptor-builder.md) &mdash; full `HidDescriptorBuilder` reference.
- [Force Feedback](force-feedback.md) &mdash; PID FFB descriptor authoring + publish/read patterns.
- [Output Passthrough](output-passthrough.md) &mdash; output ring buffer mechanics and decoding.
- [Custom Profiles](../profiles/custom-profiles.md) &mdash; `HMProfileBuilder` patterns end-to-end.
- [Profile System](../profiles/profile-system.md) &mdash; the JSON schema `HMProfile` corresponds to.

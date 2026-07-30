# Quickstart

The shortest possible path from "I just cloned this repo" to "I have a virtual Xbox 360 controller and a virtual DualSense both visible in `joy.cpl`, both responding to input, and rumble events being captured".

The walkthrough mirrors `example/SdkDemo/Program.cs` &mdash; a minimal SDK consumer that exercises every public surface.

## Prerequisites

- HIDMaestro built (`scripts\build_all.cmd` &mdash; see [Installation](installation.md)).
- An elevated terminal. `CreateController` and `InstallDriver` require admin.

```cmd
dotnet run --project example\SdkDemo
```

That's it. Five seconds later you have two virtual controllers, the demo pulses inputs through them for a few seconds, captures any rumble the OS sends back, and disposes everything cleanly. Open `joy.cpl` while the demo runs to see them.

The rest of this page walks through what just happened.

---

## Step 0: orphan recovery

```csharp
int recovered = HMOemNameOverride.RecoverOrphans();
```

If the previous run of any HIDMaestro consumer crashed mid-execution and had set OEM-name overrides for `joy.cpl` labels, those would persist as registry entries pointing at labels for VID:PIDs that no longer have a virtual. `RecoverOrphans` reads the pending-override hive at `HKLM\SOFTWARE\HIDMaestroOemOverrides` and restores every captured pre-override value.

Safe to call on every startup. Returns the number restored. See [OEM Name Override](../sdk/oem-name-override.md) for the crash-safe write protocol.

---

## Step 1: context + profiles

```csharp
using var ctx = new HMContext();
int loaded = ctx.LoadDefaultProfiles();   // returns 225
```

`HMContext` is the SDK's process-wide entry point. The constructor is cheap &mdash; it kicks off three background prewarm tasks (driver-payload extraction to `%TEMP%`, profile catalog parse, GameInput service warm-up) but doesn't block.

`LoadDefaultProfiles` reads the embedded JSON catalog out of `HIDMaestro.Core.dll`. Consumers don't need to ship profile files alongside their app. To load profiles from disk instead (custom directory, modded profiles), use `LoadProfilesFromDirectory(path)`.

After this call, `ctx.AllProfiles` is populated and `ctx.GetProfile("xbox-360-wired")` resolves.

---

## Step 2: install the driver

```csharp
ctx.InstallDriver();
```

Idempotent. On a fresh machine this:

1. Sweeps any orphan virtuals from a prior crashed run.
2. Generates a per-machine self-signed certificate if needed.
3. Extracts the embedded driver payload to `%TEMP%\HIDMaestro\<hash>\`.
4. Signs `HIDMaestro.dll`, `HMXInput.dll`, and the catalog files.
5. Calls `pnputil /add-driver` for both INFs.

Total: ~1.7s on a clean machine, ~50 ms on a machine where the same hash is already installed.

Throws `UnauthorizedAccessException` if the calling process isn't elevated; throws `InvalidOperationException` if any signing or `pnputil` step fails.

---

## Step 3: create two virtual controllers

```csharp
var ds = ctx.GetProfile("dualsense") ?? throw new InvalidOperationException();
var x360 = ctx.GetProfile("xbox-360-wired") ?? throw new InvalidOperationException();

using var ctrl0 = ctx.CreateController(ds);
using var ctrl1 = ctx.CreateController(x360);
```

`CreateController` allocates the next free controller index (linear scan from 0), runs the per-archetype `SetupController` orchestration, and returns once the device's HID child has reached `DN_STARTED` and any required XInput slot has been claimed (capped at 500ms post-v1.3.2).

Single-controller wall time: ~200 ms warm. Two mixed: ~1 s. The second create overlaps `pnputil` work with the first's PnP-binding wait so it's not strictly serial.

`ctrl0` is the DualSense at controller index 0. `ctrl1` is the Xbox 360 Wired at index 1. The XInput slot allocator hands the Xbox 360 user-index 0 (DualSense doesn't claim an XInput slot &mdash; it's a non-Xbox-VID profile).

`using var` matters: `Dispose` removes the device and frees the kernel slot. Forgetting it leaks the virtual until `HMContext.Dispose()` runs.

---

## Step 3a: override the joy.cpl label

```csharp
HMOemNameOverride.Set(x360.VendorId, x360.ProductId, "My Custom 360");
```

`joy.cpl` and DirectInput consumers will now show "My Custom 360" instead of "Controller (XBOX 360 For Windows)" for any VID_045E:PID_028E device until you `Clear`. The label sources from three registry locations and Windows pre-populates at least one for many clone PIDs &mdash; `Set` writes all three in a single transaction under a global mutex, capturing the prior values to the pending hive first so a crash doesn't leave the override stuck. See [OEM Name Override](../sdk/oem-name-override.md) for the full mechanism.

---

## Step 4: subscribe to output events

```csharp
ctrl0.OutputReceived += (sender, packet) =>
{
    Console.WriteLine($"DS rumble  src={packet.Source}  rid=0x{packet.ReportId:X2}  bytes={packet.Data.Length}");
};

ctrl1.OutputReceived += (sender, packet) =>
{
    if (packet.Source == HMOutputSource.XInput)
    {
        // 5-byte XInput rumble: cmd, size, lo, hi, reserved
        var bytes = packet.Data.Span;
        if (bytes.Length >= 4)
            Console.WriteLine($"X360 rumble  lo={bytes[2]:X2}  hi={bytes[3]:X2}");
    }
};
```

The output channel is a 64-slot ring drained on every SDK poll (~125 Hz). Multiple `OutputReceived` invocations per poll iteration are normal &mdash; DirectInput PID FFB writes Set Effect &rarr; Set Constant Force &rarr; Effect Operation Start within 1-3 ms and all three surface here. See [Output Passthrough](../sdk/output-passthrough.md) for the wire format and decoding.

Handlers run on the SDK's poll thread, **not** your UI thread. Marshal back if needed. Keep handlers cheap &mdash; the ring will overwrite the oldest packets if a reader stalls past ~512 ms.

---

## Step 5: submit input

```csharp
var sw = System.Diagnostics.Stopwatch.StartNew();
while (sw.Elapsed < TimeSpan.FromSeconds(5))
{
    float t = (float)(sw.Elapsed.TotalSeconds % 2.0 / 2.0);
    float angle = t * 2 * MathF.PI;

    ctrl0.SubmitState(new HMGamepadState
    {
        Axes = HMGamepadStateHelpers.StandardAxes(ctrl0.Profile,
            leftStickX: (MathF.Cos(angle) + 1) / 2,    // [0..1] uniform; 0.5 = center
            leftStickY: (MathF.Sin(angle) + 1) / 2),
        Buttons = HMButton.Cross,                       // Sony alias for HMButton.A
        Hat = HMHat.North,
    });

    ctrl1.SubmitState(new HMGamepadState
    {
        Axes = HMGamepadStateHelpers.StandardAxes(ctrl1.Profile,
            leftTrigger: t,
            rightTrigger: 1 - t),
        Buttons = HMButton.A | HMButton.Start,
    });

    Thread.Sleep(8);   // 125 Hz; consumers typically run at the rate of their input source
}
```

`HMGamepadState` is the abstract input frame. Analog inputs live in a single `Dictionary<HMAxis, float> Axes` keyed by HID usage; values normalize to `[0..1]` (0.5 = centered for signed axes, 0.0 = released for unsigned). Buttons stay as a flags bitmask, hat as a cardinal/diagonal enum. The SDK encodes into the active profile's HID descriptor &mdash; you don't need to know whether the target is a DualSense, Xbox 360, or arcade stick.

For the common 4-stick + 2-trigger gamepad shape, `HMGamepadStateHelpers.StandardAxes(profile, ...)` resolves the canonical `(LX, LY, RX, RY, LT, RT)` slots into the right axis keys per profile (Sony's Z=right-stick, Rx=left-trigger axis map is honored). For HOTAS / wheel / pedal devices, drive any descriptor-declared usage directly: `state.Axes[HMAxis.Slider] = 0.7f`.

For features the abstract struct doesn't model (DualSense touchpad coordinates, gyro/accel, vendor extensions), use `SubmitRawReport` with bytes you assembled yourself.

There is no SDK-managed pump thread. The consumer drives the cadence. PadForge runs at 1000 Hz; the demo runs at 125 Hz; a profile-switch utility might submit zero frames. The driver's worker thread reads from shared memory event-driven, so submit rate and idle CPU cost are independent.

---

## Step 6: cleanup

```csharp
HMOemNameOverride.Clear(x360.VendorId, x360.ProductId);
// `using` disposes ctrl0, ctrl1, and ctx as the scope ends.
```

Each `HMController.Dispose()` removes its device via `DIF_REMOVE` and (for SwD-enumerated profiles) closes the `HSWDEVICE` handle so the kernel cascade fires. `HMContext.Dispose()` disposes any controllers it still owns plus the prewarm threads.

For batch teardown of N controllers without N orphan-sweeps, use `DisposeControllersInParallel`:

```csharp
ctx.DisposeControllersInParallel(
    new[] { ctrl0, ctrl1 },
    perControllerCallback: (c, ms) => Console.WriteLine($"  {c.Profile.Id} disposed in {ms} ms"));
```

The system-wide HID orphan sweep runs once at the end instead of per-controller.

---

## Verifying it worked

While the demo is running, in another terminal:

```cmd
:: Cross-API validation: DInput axes, XInput slots, HIDAPI bus, browser, WGI
python scripts\verify.py --controllers 2

:: Pretty PnP tree
powershell -c "Get-PnpDevice -Status OK | Where-Object FriendlyName -like '*Game*'"

:: GUI verification
joy.cpl
```

`scripts\verify.py` is the tool every README screenshot was produced with. Returns exit 0 if every API agrees the controllers exist and report sane state. See [Testing and Verification](../reference/testing-and-verification.md) for what it actually checks per-API.

---

## Where to go from here

| You want to... | Read |
|----------------|------|
| Understand every method on `HMContext` / `HMController` | [SDK Reference](../sdk/sdk-reference.md) |
| Build a custom controller (not in the catalog) | [Custom Profiles](../profiles/custom-profiles.md) + [HID Descriptor Builder](../sdk/hid-descriptor-builder.md) |
| Capture a real device's descriptor and ship it as a profile | [Profile Extractor](../profiles/profile-extractor.md) |
| Submit a profile back to the catalog | [Contributing Profiles](../profiles/contributing-profiles.md) |
| Implement DirectInput PID FFB | [Force Feedback](../sdk/force-feedback.md) |
| Understand how the driver actually works | [Architecture Overview](../reference/architecture-overview.md) &rarr; [UMDF2 Driver Internals](../reference/umdf2-driver-internals.md) |
| Diagnose a missing virtual or a stuck install | [Troubleshooting](../troubleshooting.md) |
